"""FastAPI app: JSON API + file downloads + React SPA (built to app/static)."""
from __future__ import annotations

import io
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from . import api, auth, storage
from .db import SessionLocal, get_db, init_db
from .models import Batch, JobUrl, ProfileAccess, STATUS_DONE, User

PACIFIC = ZoneInfo("America/Los_Angeles")
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Resume Builder")


@app.on_event("startup")
def _startup() -> None:
    init_db()
    db = SessionLocal()
    try:
        auth.ensure_admin_seeded(db)
    finally:
        db.close()


app.include_router(api.router)


# ── file downloads (kept as raw routes because they stream binary) ─────────

def _check_download_access(user: User, ju: JobUrl, db: Session) -> None:
    if user.role == "admin":
        return
    has = (db.query(ProfileAccess)
           .filter(ProfileAccess.profile_id == ju.batch.profile_id,
                   ProfileAccess.user_id == user.id).first())
    if has is None:
        raise HTTPException(403)


def _check_batch_access(user: User, batch: Batch, db: Session) -> None:
    if user.role == "admin":
        return
    has = (db.query(ProfileAccess)
           .filter(ProfileAccess.profile_id == batch.profile_id,
                   ProfileAccess.user_id == user.id).first())
    if has is None:
        raise HTTPException(403)


def _to_pacific(value: Optional[datetime]) -> Optional[datetime]:
    if not value:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(PACIFIC)


def _safe_slug(s: str, limit: int = 80) -> str:
    s = (s or "Resume").strip()
    s = re.sub(r"[^A-Za-z0-9._ -]+", "", s)
    s = re.sub(r"\s+", "_", s)
    return s[:limit] or "Resume"


@app.get("/download/batch/{bid}/zip")
def download_batch_zip(
    bid: int,
    user: User = Depends(auth.require_user),
    db: Session = Depends(get_db),
):
    batch = db.get(Batch, bid)
    if batch is None:
        raise HTTPException(404)
    _check_batch_access(user, batch, db)

    jobs = (db.query(JobUrl)
            .filter(JobUrl.batch_id == bid, JobUrl.status == STATUS_DONE)
            .order_by(JobUrl.id.asc()).all())
    if not jobs:
        raise HTTPException(404, "No tailored resumes in this batch yet.")

    buf = io.BytesIO()
    used: set = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for idx, ju in enumerate(jobs, start=1):
            path = storage.generated_docx_path(ju.batch_id, ju.id)
            if not path.exists():
                continue
            base = _safe_slug(f"{idx:02d}_{ju.company or 'Company'}_{ju.title or 'Role'}")
            name = f"{base}.docx"
            n = 2
            while name in used:
                name = f"{base}_{n}.docx"; n += 1
            used.add(name)
            zf.write(str(path), arcname=name)
    buf.seek(0)
    date_tag = _to_pacific(batch.created_at).strftime("%Y-%m-%d")
    zip_name = _safe_slug(f"{batch.profile.name}_{batch.label or date_tag}") + ".zip"
    return StreamingResponse(
        buf, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
    )


@app.get("/download/{jid}/{kind}")
def download(
    jid: int, kind: str,
    user: User = Depends(auth.require_user),
    db: Session = Depends(get_db),
):
    if kind not in {"docx", "pdf"}:
        raise HTTPException(400)
    ju = db.get(JobUrl, jid)
    if ju is None:
        raise HTTPException(404)
    _check_download_access(user, ju, db)

    if kind == "docx":
        path = storage.generated_docx_path(ju.batch_id, ju.id)
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        path = storage.generated_pdf_path(ju.batch_id, ju.id)
        media = "application/pdf"

    if not path.exists():
        raise HTTPException(404, "File not generated yet.")

    friendly = _safe_slug(f"{ju.company or 'Company'}_{ju.title or 'Role'}") + (
        ".docx" if kind == "docx" else ".pdf"
    )
    return FileResponse(str(path), media_type=media, filename=friendly)


@app.get("/healthz")
def healthz():
    return {"ok": True}


# ── SPA (built React app) at /static + client-side routing fallback ────────

STATIC_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/{path:path}")
def spa(path: str):
    """Serve the built React app for every non-API route.

    In dev, Vite runs on :5173 and proxies /api + /download to :8000.
    In prod, `npm run build` emits into app/static/ and FastAPI serves it here.
    """
    index = STATIC_DIR / "index.html"
    if not index.exists():
        return {
            "error": "Frontend not built yet.",
            "hint": "Run `npm --prefix frontend run dev` for development, "
                    "or `npm --prefix frontend run build` to produce app/static/.",
        }
    candidate = STATIC_DIR / path
    if path and candidate.is_file():
        return FileResponse(str(candidate))
    return FileResponse(str(index))

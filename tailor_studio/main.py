"""tailor-studio FastAPI entry. Run from repo root:

    .venv/Scripts/python -m uvicorn tailor_studio.main:app --reload --port 8001
"""
from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import api, auth, config
from .db import Batch, JobUrl, Profile, get_session, init_db


app = FastAPI(title="resume-tailor-studio", version="0.1.0")
app.include_router(api.public_router)
app.include_router(api.router)


@app.on_event("startup")
def _startup() -> None:
    init_db()


def _slug(text: str) -> str:
    """Filesystem-safe slug: keep alphanumerics + hyphen + underscore, collapse runs."""
    import re
    s = re.sub(r"[^A-Za-z0-9_-]+", "_", (text or "").strip())
    return s.strip("_")


def _filename_bits(j) -> list[str]:
    """Return the candidate / company / title slug bits, used for both .docx
    and .pdf download names."""
    bits = []
    try:
        if j.batch and j.batch.profile and j.batch.profile.name:
            bits.append(_slug(j.batch.profile.name))
    except Exception:
        pass
    if j.company: bits.append(_slug(j.company))
    if j.title:   bits.append(_slug(j.title))
    return bits


def _job_for_user(jid: int, user) -> JobUrl:
    """Resolve a JobUrl that belongs to `user`. Used by /download/* routes
    so users can't download each other's resumes via direct URL guessing."""
    db = get_session()
    try:
        j = db.get(JobUrl, jid)
        if j is None or not j.docx_filename:
            raise HTTPException(404, "No tailored output.")
        b = db.get(Batch, j.batch_id)
        if b is None:
            raise HTTPException(404, "No tailored output.")
        p = db.get(Profile, b.profile_id)
        if p is None or p.user_id != user.id:
            raise HTTPException(404, "No tailored output.")
        # Detach so the caller can use j after the session closes.
        db.expunge(j); db.expunge(b); db.expunge(p)
        # Reattach via plain attribute access so _filename_bits works.
        j.batch = b; b.profile = p
        return j
    finally:
        db.close()


@app.get("/download/{jid}/pdf")
def download_pdf(jid: int, me=Depends(auth.require_user)):
    """Serve a PDF rendition of the tailored resume. Generated lazily on
    first request, cached to disk + JobUrl.pdf_filename for re-downloads."""
    from .pdf_export import make_pdf
    j = _job_for_user(jid, me)
    db = get_session()
    try:
        # Re-fetch with a fresh session for the commit.
        j = db.get(JobUrl, jid)
        pdf_path, err = make_pdf(j.docx_filename)
        if pdf_path is None or not pdf_path.exists():
            raise HTTPException(500, f"PDF generation failed: {err or 'unknown error'}")
        # Stash the filename so the row exposes its existence to the UI.
        if j.pdf_filename != pdf_path.name:
            j.pdf_filename = pdf_path.name
            db.commit()
        bits = _filename_bits(j) or [f"job{jid}"]
        return FileResponse(
            str(pdf_path),
            media_type="application/pdf",
            filename="__".join(bits) + ".pdf",
        )
    finally:
        db.close()


@app.get("/download/{jid}/docx")
@app.get("/download/{jid}")
def download_tailored(jid: int, me=Depends(auth.require_user)):
    # Ownership check first.
    _job_for_user(jid, me)
    db = get_session()
    try:
        j = db.get(JobUrl, jid)
        if j is None or not j.docx_filename:
            raise HTTPException(404, "No tailored output.")
        path = config.OUTPUTS_DIR / j.docx_filename
        if not path.exists():
            raise HTTPException(404, "Tailored file missing on disk.")
        # Bump the download counter so the dashboard tracks engagement.
        j.download_count += 1
        db.commit()

        bits = _filename_bits(j) or [f"job{jid}"]
        return FileResponse(
            str(path),
            media_type=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            filename="__".join(bits) + ".docx",
        )
    finally:
        db.close()


# Static frontend (built React app). Served from /assets/* and root /.
_STATIC_DIR = Path(__file__).parent / "static"
if (_STATIC_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(_STATIC_DIR / "assets")),
              name="assets")


_INDEX = _STATIC_DIR / "index.html"


@app.get("/")
def index_root():
    if not _INDEX.exists():
        raise HTTPException(500, "Frontend not built. Run: cd tailor_studio/web && npm run build")
    return FileResponse(str(_INDEX), media_type="text/html")


# SPA fallback — anything that doesn't match an /api or /download route
# returns index.html so React Router can take over. If a real file with that
# name exists in static/, serve it (so the upload-test.html debug page works).
@app.get("/{path:path}")
def spa_fallback(path: str):
    if path.startswith("api/") or path.startswith("download/") or path.startswith("assets/"):
        raise HTTPException(404, "Not found.")
    sibling = _STATIC_DIR / path
    if sibling.is_file():
        return FileResponse(str(sibling))
    if not _INDEX.exists():
        raise HTTPException(500, "Frontend not built. Run: cd tailor_studio/web && npm run build")
    return FileResponse(str(_INDEX), media_type="text/html")

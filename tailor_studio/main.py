"""tailor-studio FastAPI entry. Run from repo root:

    .venv/Scripts/python -m uvicorn tailor_studio.main:app --reload --port 8001
"""
from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import api, auth, chat, config
from .db import Batch, ChatMessage, JobUrl, Profile, User, get_session, init_db


app = FastAPI(title="resume-tailor-studio", version="0.1.0")

# Allow the Chrome extension popup (origin = chrome-extension://<id>) to call
# the API with the session cookie. allow_origin_regex covers any extension ID
# since the user side-loads the extension and Chrome assigns a fresh ID each
# install.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"chrome-extension://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api.public_router)
app.include_router(api.router)


@app.websocket("/ws/chat")
async def chat_ws(websocket: WebSocket):
    """Team group chat. Authenticates off the session cookie sent on the
    upgrade handshake, then streams messages to/from all connected members."""
    uid = auth.user_id_from_token(websocket.cookies.get(config.SESSION_COOKIE))
    if uid is None:
        await websocket.close(code=1008)
        return
    db = get_session()
    try:
        user = db.get(User, uid)
        if user is None or not user.approved:
            await websocket.close(code=1008)
            return
        name = chat.display_name(user.email, user.display_name)
    finally:
        db.close()

    await chat.manager.connect(websocket, {"id": uid, "name": name})
    await chat.manager.broadcast(chat.manager.presence_payload())
    try:
        while True:
            data = await websocket.receive_json()
            if not isinstance(data, dict):
                continue
            action = data.get("action")
            mid = data.get("id")
            mid = int(mid) if isinstance(mid, int) else None

            # ── edit (author only) ──────────────────────────────────────
            if action == "edit" and mid is not None:
                body = (data.get("body") or "").strip()
                if not body:
                    continue
                db = get_session()
                try:
                    m = chat.edit_message(db, mid, uid, body[:4000])
                    out = {"type": "edit", "id": mid, "body": m.body,
                           "edited_at": chat._iso(m.edited_at)} if m else None
                finally:
                    db.close()
                if out:
                    await chat.manager.broadcast(out)
                continue

            # ── delete (author or admin) ────────────────────────────────
            if action == "delete" and mid is not None:
                db = get_session()
                try:
                    u = db.get(User, uid)
                    ok = chat.delete_message(db, mid, uid, bool(u and u.is_admin))
                finally:
                    db.close()
                if ok:
                    await chat.manager.broadcast({"type": "delete", "id": mid})
                continue

            # ── typing indicator (ephemeral, relayed) ───────────────────
            if action == "typing":
                await chat.manager.broadcast({"type": "typing", "user_id": uid, "name": name})
                continue

            # ── bulk delete (admin only) ────────────────────────────────
            if action == "delete_many":
                ids = [int(i) for i in (data.get("ids") or []) if isinstance(i, int)][:500]
                db = get_session()
                try:
                    u = db.get(User, uid)
                    removed = chat.delete_many(db, ids) if (u and u.is_admin and ids) else []
                finally:
                    db.close()
                if removed:
                    await chat.manager.broadcast({"type": "delete_many", "ids": removed})
                continue

            # ── clear all (admin only) ──────────────────────────────────
            if action == "clear":
                db = get_session()
                try:
                    u = db.get(User, uid)
                    ok = chat.clear_all(db) if (u and u.is_admin) else False
                finally:
                    db.close()
                if ok:
                    await chat.manager.broadcast({"type": "clear"})
                continue

            # ── pin / unpin (admin only) ────────────────────────────────
            if action == "pin" and mid is not None:
                want = bool(data.get("pinned"))
                db = get_session()
                try:
                    u = db.get(User, uid)
                    m = chat.set_pin(db, mid, want) if (u and u.is_admin) else None
                    out = {"type": "pin", "id": mid, "pinned": want,
                           "msg": chat.pin_view(m)} if m else None
                finally:
                    db.close()
                if out:
                    await chat.manager.broadcast(out)
                continue

            # ── new message ─────────────────────────────────────────────
            body = (data.get("body") or "").strip()
            if not body:
                continue
            reply_to_id = data.get("reply_to_id")
            reply_to_id = int(reply_to_id) if isinstance(reply_to_id, int) else None
            db = get_session()
            try:
                u = db.get(User, uid)
                nm = chat.display_name(u.email, u.display_name) if u else name
                m = chat.save_message(db, uid, nm, body[:4000], reply_to_id=reply_to_id)
                payload = chat.message_payload(m, chat.reply_snippet(db, m.reply_to_id))
            finally:
                db.close()
            await chat.manager.broadcast(payload)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await chat.manager.disconnect(websocket)
        await chat.manager.broadcast(chat.manager.presence_payload())


@app.on_event("startup")
def _startup() -> None:
    init_db()
    # Promote the configured admin account (STUDIO_ADMIN_EMAIL) to admin+approved.
    db = get_session()
    try:
        auth.ensure_admin(db)
    finally:
        db.close()
    _start_auto_prune()
    # Re-enqueue jobs left in pending / in-flight states by a previous
    # process. Without this, server restarts strand the entire in-memory
    # ThreadPoolExecutor queue.
    try:
        from . import pipeline
        n = pipeline.requeue_orphans()
        if n:
            import logging
            logging.getLogger("tailor_studio.startup").info(
                "Re-queued %d orphaned tailoring jobs from previous process", n,
            )
    except Exception:
        import logging, traceback
        logging.getLogger("tailor_studio.startup").warning(
            "Orphan-requeue failed:\n%s", traceback.format_exc(),
        )


def _start_auto_prune() -> None:
    """Spawn a daemon thread that runs the prune script once per day.

    Keeps generated .docx/.pdf and Claude caches under control without
    requiring an external cron. Threshold: 7 days. First sweep happens
    60 seconds after server start; then every 24 hours."""
    import threading
    import time as _time
    import logging

    log = logging.getLogger("tailor_studio.prune")

    def _runner() -> None:
        # Brief grace period after boot so the first sweep doesn't fight
        # with init_db() / table migrations.
        _time.sleep(60)
        while True:
            try:
                from scripts.prune_old_outputs import main as prune_main
                prune_main(["--days", "7"])
            except Exception as e:  # pragma: no cover — daemon must not die
                log.warning("auto-prune failed: %s", e)
            # 24h between sweeps. Use small wakeups so process shutdown is
            # responsive rather than blocking for a full day.
            for _ in range(24 * 60):
                _time.sleep(60)

    t = threading.Thread(target=_runner, name="auto-prune", daemon=True)
    t.start()


def _slug(text: str) -> str:
    """Filesystem-safe slug: keep alphanumerics + hyphen + underscore, collapse runs."""
    import re
    s = re.sub(r"[^A-Za-z0-9_-]+", "_", (text or "").strip())
    return s.strip("_")


def _filename_bits(j) -> list[str]:
    """Return the stable download stem '<profile>-resume' (no company/role) so
    re-downloads overwrite instead of accumulating copies. Returned as a list so
    the .docx / .pdf routes can join it and append the extension."""
    name = ""
    try:
        if j.batch and j.batch.profile and j.batch.profile.name:
            name = _slug(j.batch.profile.name)
    except Exception:
        pass
    return [f"{name}-resume" if name else "candidate-resume"]


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
        # Access = the profile's owner, an admin, OR a bidder the profile was
        # assigned to (ProfileAccess grant) — same model the rest of the app
        # uses. Owner-only would 404 every bidder download.
        from .api import _can_access_profile
        if p is None or not (getattr(user, "is_admin", False) or _can_access_profile(db, user, p)):
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
        # Stash the filename + content hash so the upload-observer can verify a
        # PDF upload (not just the .docx). Always re-hash the served file: a
        # re-tailored job regenerates the PDF under the SAME filename, so a
        # name-only check would leave a stale hash. Hashing a ~100KB PDF is
        # ~1ms. The bidder downloads before uploading, so this is populated in
        # time to classify the upload.
        from .api import _file_sha256
        pdf_sha = _file_sha256(pdf_path)
        if j.pdf_filename != pdf_path.name or j.pdf_sha256 != pdf_sha:
            j.pdf_filename = pdf_path.name
            j.pdf_sha256 = pdf_sha
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


def _zip_entry_name(profile_name: str, j: JobUrl, ext: str) -> str:
    """Readable path inside the zip: 'Joshua/Company__Role.docx' so resumes are
    easy to find per-candidate when prepping for interviews."""
    prof = _slug(profile_name) or "candidate"
    company = _slug(j.company or "") or "company"
    title = _slug(j.title or "") or "role"
    return f"{prof}/{company}__{title}__job{j.id}.{ext}"


def _build_resume_zip(jobs, *, generate_missing_pdf=False):
    """Zip every tailored .docx for `jobs`, plus PDFs. Each job must carry a
    `._zip_profile` attribute (the profile name). Returns (BytesIO, count).

    generate_missing_pdf=False (default, for bulk archives): include only PDFs
    already on disk — never drive Word for a big batch (slow/unreliable). True
    (small per-batch zips): generate any missing PDFs on the fly.
    """
    import io, zipfile
    from .pdf_export import make_pdf, _pdf_path_for
    buf = io.BytesIO()
    added = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for j in jobs:
            if not j.docx_filename:
                continue
            docx_path = config.OUTPUTS_DIR / j.docx_filename
            if not docx_path.exists():
                continue
            pname = getattr(j, "_zip_profile", None) or "candidate"
            z.write(docx_path, _zip_entry_name(pname, j, "docx"))
            added += 1
            try:
                pdf_path = _pdf_path_for(j.docx_filename)
                if not pdf_path.exists() and generate_missing_pdf:
                    pdf_path, _ = make_pdf(j.docx_filename)
                if pdf_path and pdf_path.exists():
                    z.write(pdf_path, _zip_entry_name(pname, j, "pdf"))
            except Exception:
                pass  # PDF is best-effort; the .docx is always included
    buf.seek(0)
    return buf, added


@app.get("/download/batch/{bid}/zip")
def download_batch_zip(bid: int, me=Depends(auth.require_user)):
    """Zip all tailored resumes (.docx + .pdf) in one batch."""
    from .api import _can_access_profile
    from fastapi.responses import StreamingResponse
    db = get_session()
    try:
        b = db.get(Batch, bid)
        if b is None:
            raise HTTPException(404, "Batch not found.")
        p = db.get(Profile, b.profile_id)
        if p is None or not (getattr(me, "is_admin", False) or _can_access_profile(db, me, p)):
            raise HTTPException(404, "Batch not found.")
        jobs = db.query(JobUrl).filter(JobUrl.batch_id == bid).all()
        for j in jobs:
            j._zip_profile = p.name
        buf, n = _build_resume_zip(jobs, generate_missing_pdf=True)
        if n == 0:
            raise HTTPException(404, "No tailored resumes in this batch yet.")
        fname = f"{_slug(p.name)}__batch{bid}__{n}_resumes.zip"
        return StreamingResponse(
            buf, media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )
    finally:
        db.close()


@app.get("/download/resumes/zip")
def download_all_resumes_zip(date: str | None = None, me=Depends(auth.require_user)):
    """Zip EVERY tailored resume the user can access — the daily archive for
    future interviews. Optional ?date=YYYY-MM-DD (US Pacific) limits to batches
    created that day; omit it to archive everything."""
    from .api import _accessible_pids
    from fastapi.responses import StreamingResponse
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    db = get_session()
    try:
        pids = _accessible_pids(db, me)
        if not pids:
            raise HTTPException(404, "No accessible profiles.")
        profiles = {p.id: p.name for p in db.query(Profile).filter(Profile.id.in_(pids)).all()}
        q = (db.query(JobUrl, Batch.profile_id)
             .join(Batch, JobUrl.batch_id == Batch.id)
             .filter(Batch.profile_id.in_(pids)))
        if date:
            try:
                pt = ZoneInfo("America/Los_Angeles")
                day = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=pt)
            except ValueError:
                raise HTTPException(400, "Bad date — use YYYY-MM-DD.")
            start = day.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
            end = (day + timedelta(days=1)).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
            q = q.filter(Batch.created_at >= start, Batch.created_at < end)
        rows = q.all()
        jobs = []
        for j, profile_id in rows:
            j._zip_profile = profiles.get(profile_id, "candidate")
            jobs.append(j)
        buf, n = _build_resume_zip(jobs)
        if n == 0:
            raise HTTPException(404, "No tailored resumes found for that selection.")
        label = date or "all"
        fname = f"resumes__{label}__{n}_files.zip"
        return StreamingResponse(
            buf, media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
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

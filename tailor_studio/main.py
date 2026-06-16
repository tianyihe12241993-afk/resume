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
        name = chat.display_name(user.email)
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
                m = chat.save_message(db, uid, name, body[:4000], reply_to_id=reply_to_id)
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

"""JSON API mirroring the HTML routes — feeds the React frontend."""
from __future__ import annotations

import calendar as _calendar
import io
import re
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, Response, StreamingResponse, FileResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from . import auth, config, pipeline, storage
from .db import get_db
from .models import (
    APP_STATUSES, STATUS_DONE, STATUS_PENDING,
    Batch, JobUrl, Profile, ProfileAccess, User,
)

PACIFIC = ZoneInfo("America/Los_Angeles")

router = APIRouter(prefix="/api")


# ── serializers ────────────────────────────────────────────────────────────

def _iso(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()

def _to_pacific(dt: Optional[datetime]) -> Optional[datetime]:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(PACIFIC)


def user_out(u: User) -> dict:
    return {
        "id": u.id, "email": u.email, "name": u.name, "role": u.role,
        "password_set": bool(u.password_hash),
        "created_at": _iso(u.created_at),
    }

def profile_out(p: Profile, *, has_base: bool | None = None) -> dict:
    return {
        "id": p.id, "name": p.name,
        "base_resume_filename": p.base_resume_filename,
        "has_base_resume": storage.base_resume_path(p.id).exists() if has_base is None else has_base,
        "batch_count": len(p.batches),
        "tailor_prompt": p.tailor_prompt or "",
        "uses_default_prompt": not (p.tailor_prompt or "").strip(),
        "created_at": _iso(p.created_at),
    }

def job_out(j: JobUrl) -> dict:
    return {
        "id": j.id, "url": j.url, "status": j.status,
        "company": j.company, "title": j.title, "location": j.location,
        "description": j.description,
        "error_message": j.error_message,
        "application_status": j.application_status or "new",
        "applied_at": _iso(j.applied_at),
        "application_note": j.application_note,
        "application_source": j.application_source,
        "has_docx": storage.generated_docx_path(j.batch_id, j.id).exists(),
    }

def batch_summary(jobs: list[JobUrl]) -> dict:
    counts = defaultdict(int)
    app_counts = defaultdict(int)
    for j in jobs:
        counts[j.status] += 1
        app_counts[j.application_status or "new"] += 1
    total = len(jobs)
    done = counts.get("done", 0)
    in_flight = counts.get("pending", 0) + counts.get("fetching", 0) + counts.get("tailoring", 0)
    applied = sum(app_counts.get(s, 0) for s in ("applied", "interview", "rejected", "offer"))
    return {
        "total": total, "done": done, "in_flight": in_flight,
        "needs_jd": counts.get("needs_manual_jd", 0),
        "errors": counts.get("error", 0),
        "percent": int(round(100 * done / total)) if total else 0,
        "applied": applied,
        "applied_percent": int(round(100 * applied / done)) if done else 0,
    }


# ── auth ───────────────────────────────────────────────────────────────────

class LoginIn(BaseModel):
    email: EmailStr
    password: str


# Sliding-window rate limit for /login.
# Two independent buckets: per-IP and per-email — whichever fills up first triggers 429.
import time
import threading
_LOGIN_WINDOW_SEC = 60
_LOGIN_MAX_PER_IP = 10
_LOGIN_MAX_PER_EMAIL = 5
_login_attempts: dict[str, list] = {}
_login_lock = threading.Lock()


def _check_login_rate_limit(ip: str, email: str) -> None:
    now = time.monotonic()
    cutoff = now - _LOGIN_WINDOW_SEC
    keys = (f"ip:{ip}", f"em:{email}")
    limits = (_LOGIN_MAX_PER_IP, _LOGIN_MAX_PER_EMAIL)
    with _login_lock:
        for k, limit in zip(keys, limits):
            bucket = [t for t in _login_attempts.get(k, []) if t > cutoff]
            _login_attempts[k] = bucket
            if len(bucket) >= limit:
                raise HTTPException(
                    429,
                    "Too many login attempts. Please wait a minute and try again.",
                )
        for k in keys:
            _login_attempts.setdefault(k, []).append(now)


@router.post("/login")
def api_login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    ip = (request.client.host if request.client else "unknown")
    _check_login_rate_limit(ip, email)
    user = db.query(User).filter(User.email == email).first()
    if user is None or not auth.verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    resp = JSONResponse({"user": user_out(user)})
    auth.set_session(resp, user.id)
    return resp


@router.post("/logout")
def api_logout():
    resp = JSONResponse({"ok": True})
    auth.clear_session(resp)
    return resp


@router.get("/me")
def api_me(request: Request, db: Session = Depends(get_db)):
    u = auth.current_user(request, db)
    if u is None:
        return {"user": None}
    return {"user": user_out(u)}


@router.get("/setup/peek")
def api_setup_peek(token: str, db: Session = Depends(get_db)):
    u = auth.peek_invite_token(db, token) if token else None
    if u is None:
        raise HTTPException(404, "Invite link is invalid or expired.")
    return {"email": u.email}


class SetupIn(BaseModel):
    token: str
    password: str
    confirm: str

@router.post("/setup")
def api_setup(body: SetupIn, db: Session = Depends(get_db)):
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    if body.password != body.confirm:
        raise HTTPException(400, "Passwords do not match")
    u = auth.consume_invite_token(db, body.token)
    if u is None:
        raise HTTPException(400, "Invite link invalid or expired")
    u.password_hash = auth.hash_password(body.password)
    db.commit()
    resp = JSONResponse({"user": user_out(u)})
    auth.set_session(resp, u.id)
    return resp


class ChangePasswordIn(BaseModel):
    current: str
    password: str
    confirm: str

@router.post("/change-password")
def api_change_password(
    body: ChangePasswordIn,
    user: User = Depends(auth.require_user),
    db: Session = Depends(get_db),
):
    if not auth.verify_password(body.current, user.password_hash):
        raise HTTPException(400, "Current password is wrong")
    if len(body.password) < 8:
        raise HTTPException(400, "New password must be at least 8 characters")
    if body.password != body.confirm:
        raise HTTPException(400, "Passwords do not match")
    user.password_hash = auth.hash_password(body.password)
    db.commit()
    return {"ok": True}


# ── admin: dashboard ────────────────────────────────────────────────────────

@router.get("/admin/dashboard")
def api_admin_dashboard(
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    from datetime import timedelta
    now_pst = datetime.now(PACIFIC)
    today = now_pst.date()
    start_utc = datetime.combine(today, datetime.min.time(), tzinfo=PACIFIC).astimezone(timezone.utc).replace(tzinfo=None)
    end_utc   = datetime.combine(today, datetime.max.time(), tzinfo=PACIFIC).astimezone(timezone.utc).replace(tzinfo=None)

    # 7-day trend window (including today) — load once, bucket by profile+date
    trend_days = 7
    trend_start = today - timedelta(days=trend_days - 1)
    trend_start_utc = (
        datetime.combine(trend_start, datetime.min.time(), tzinfo=PACIFIC)
        .astimezone(timezone.utc).replace(tzinfo=None)
    )
    history_batches = (
        db.query(Batch).filter(Batch.created_at >= trend_start_utc).all()
    )
    # { profile_id: [applied per day for trend_days days, oldest → newest] }
    trend_map: dict[int, list[int]] = {}
    for b in history_batches:
        d = _to_pacific(b.created_at).date()
        idx = (d - trend_start).days
        if idx < 0 or idx >= trend_days:
            continue
        applied_count = sum(
            1 for j in b.urls
            if (j.application_status or "new") in ("applied", "interview", "rejected", "offer")
        )
        arr = trend_map.setdefault(b.profile_id, [0] * trend_days)
        arr[idx] += applied_count

    # Find today's batch (if any) per profile — we merged multiple batches/day.
    todays_batch_by_profile: dict[int, Batch] = {}
    for b in history_batches:
        if start_utc <= b.created_at <= end_utc:
            # If multiple exist (shouldn't after the merge logic), pick newest
            cur = todays_batch_by_profile.get(b.profile_id)
            if cur is None or b.created_at > cur.created_at:
                todays_batch_by_profile[b.profile_id] = b

    profiles = db.query(Profile).order_by(Profile.name.asc()).all()

    profile_statuses = []
    agg = {"total": 0, "done": 0, "applied": 0, "in_flight": 0, "needs_jd": 0, "errors": 0}

    for p in profiles:
        tb = todays_batch_by_profile.get(p.id)
        if tb is not None:
            s = batch_summary(tb.urls)
        else:
            s = {
                "total": 0, "done": 0, "in_flight": 0, "needs_jd": 0, "errors": 0,
                "percent": 0, "applied": 0, "applied_percent": 0,
            }

        profile_statuses.append({
            "profile": {
                "id": p.id,
                "name": p.name,
                "has_base_resume": storage.base_resume_path(p.id).exists(),
            },
            "today_batch": (
                {"id": tb.id, "created_at": _iso(tb.created_at)} if tb else None
            ),
            "summary": s,
            "trend": trend_map.get(p.id, [0] * trend_days),
        })
        for k in agg:
            agg[k] += s.get(k, 0)

    # Aggregate trend across all profiles
    agg_trend = [0] * trend_days
    for arr in trend_map.values():
        for i, v in enumerate(arr):
            agg_trend[i] += v

    agg["percent"] = int(round(100 * agg["done"] / agg["total"])) if agg["total"] else 0
    agg["applied_percent"] = int(round(100 * agg["applied"] / agg["done"])) if agg["done"] else 0

    ready = [profile_out(p) for p in profiles if storage.base_resume_path(p.id).exists()]

    trend_dates = [
        (trend_start + timedelta(days=i)).isoformat() for i in range(trend_days)
    ]
    return {
        "now_pst": _iso(now_pst),
        "today": today.isoformat(),
        "profile_statuses": profile_statuses,
        "agg": agg,
        "agg_trend": agg_trend,
        "trend_dates": trend_dates,
        "ready_profiles": ready,
        "has_any_profile": len(profiles) > 0,
    }


# ── admin: profiles ────────────────────────────────────────────────────────

@router.get("/admin/tailor-prompt-default")
def api_admin_tailor_prompt_default(
    admin: User = Depends(auth.require_admin),
):
    """The built-in tailoring prompt — shown to admins as the fallback."""
    from . import tailoring
    return {"prompt": tailoring.TAILOR_SYSTEM}


@router.get("/admin/profiles")
def api_admin_profiles(
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    profiles = db.query(Profile).order_by(Profile.created_at.desc()).all()
    return {"profiles": [profile_out(p) for p in profiles]}


class ProfileCreateIn(BaseModel):
    name: str

@router.post("/admin/profiles")
def api_admin_profiles_create(
    body: ProfileCreateIn,
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    p = Profile(owner_user_id=admin.id, name=body.name.strip() or "Untitled")
    db.add(p); db.commit()
    return {"profile": profile_out(p)}


class ProfileUpdateIn(BaseModel):
    name: Optional[str] = None
    # Pass an empty string to fall back to the global default prompt.
    tailor_prompt: Optional[str] = None

@router.post("/admin/profiles/{pid}/delete")
def api_admin_profile_delete(
    pid: int,
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    import shutil
    p = db.get(Profile, pid)
    if p is None: raise HTTPException(404)
    # Cascade deletes batches/jobs/access via ORM relationships.
    db.delete(p); db.commit()
    # Remove the base resume and any generated docx/pdf for this profile's batches.
    base = storage.base_resume_path(pid)
    if base.exists():
        try: base.unlink()
        except OSError: pass
    # Outputs are organized per-batch; a best-effort cleanup of orphaned batch
    # folders happens naturally as they won't be referenced. No harm leaving them.
    _ = shutil  # (kept for future bulk cleanup if we want it)
    return {"ok": True}


@router.post("/admin/profiles/{pid}/update")
def api_admin_profile_update(
    pid: int, body: ProfileUpdateIn,
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    p = db.get(Profile, pid)
    if p is None: raise HTTPException(404)
    if body.name is not None and body.name.strip():
        p.name = body.name.strip()
    if body.tailor_prompt is not None:
        # Empty string clears the override and falls back to the default.
        cleaned = body.tailor_prompt.strip()
        p.tailor_prompt = cleaned or None
    db.commit()
    return {"profile": profile_out(p)}


@router.get("/admin/profiles/{pid}")
def api_admin_profile_detail(
    pid: int,
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    p = db.get(Profile, pid)
    if p is None: raise HTTPException(404)
    accesses = db.query(ProfileAccess).filter(ProfileAccess.profile_id == pid).all()
    invite_urls = {a.user_id: auth.pending_invite_url(db, a.user) for a in accesses}
    batches = (db.query(Batch).filter(Batch.profile_id == pid)
               .order_by(Batch.created_at.desc()).all())
    return {
        "profile": profile_out(p),
        "accesses": [{
            "id": a.id,
            "user": user_out(a.user),
            "invite_url": invite_urls.get(a.user_id),
        } for a in accesses],
        "batches": [{
            "id": b.id,
            "created_at": _iso(b.created_at),
            "url_count": len(b.urls),
        } for b in batches],
    }


@router.post("/admin/profiles/{pid}/resume")
async def api_admin_upload_resume(
    pid: int,
    file: UploadFile = File(...),
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    p = db.get(Profile, pid)
    if p is None: raise HTTPException(404)
    if not file.filename or not file.filename.lower().endswith(".docx"):
        raise HTTPException(400, "Please upload a .docx file.")
    dst = storage.base_resume_path(pid)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(await file.read())
    p.base_resume_filename = file.filename
    db.commit()
    return {"profile": profile_out(p)}


class GrantAccessIn(BaseModel):
    email: EmailStr
    name: Optional[str] = None

@router.post("/admin/profiles/{pid}/access")
def api_admin_grant_access(
    pid: int, body: GrantAccessIn,
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    p = db.get(Profile, pid)
    if p is None: raise HTTPException(404)
    u = auth.get_or_create_user(db, body.email.strip().lower(), role="bidder",
                                name=(body.name.strip() if body.name else None))
    exists = (db.query(ProfileAccess)
              .filter(ProfileAccess.profile_id == pid, ProfileAccess.user_id == u.id).first())
    if exists is None:
        db.add(ProfileAccess(profile_id=pid, user_id=u.id))
    if not u.password_hash:
        auth.pending_invite_url(db, u)
    db.commit()
    return {"ok": True}


@router.post("/admin/profiles/{pid}/access/{aid}/revoke")
def api_admin_revoke_access(
    pid: int, aid: int,
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    row = db.get(ProfileAccess, aid)
    if row is None or row.profile_id != pid: raise HTTPException(404)
    db.delete(row); db.commit()
    return {"ok": True}


# ── admin: bidders ─────────────────────────────────────────────────────────

@router.get("/admin/bidders")
def api_admin_bidders(
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    bidders = (db.query(User).filter(User.role == "bidder")
               .order_by(User.created_at.desc()).all())
    return {
        "bidders": [{**user_out(b), "profile_count": len(b.profile_accesses)}
                    for b in bidders]
    }


@router.get("/admin/bidders/{uid}")
def api_admin_bidder_detail(
    uid: int,
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    b = db.get(User, uid)
    if b is None or b.role != "bidder": raise HTTPException(404)
    return {
        "bidder": user_out(b),
        "profiles": [profile_out(a.profile) for a in b.profile_accesses],
        "invite_url": auth.pending_invite_url(db, b),
    }


class RenameIn(BaseModel):
    name: str

@router.post("/admin/bidders/{uid}/rename")
def api_admin_rename_bidder(
    uid: int, body: RenameIn,
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    b = db.get(User, uid)
    if b is None: raise HTTPException(404)
    b.name = body.name.strip() or None
    db.commit()
    return {"bidder": user_out(b)}


@router.post("/admin/users/{uid}/reset-invite")
def api_admin_reset_invite(
    uid: int,
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    target = db.get(User, uid)
    if target is None: raise HTTPException(404)
    auth.issue_invite_token(db, target)
    target.password_hash = None
    db.commit()
    return {"invite_url": auth.pending_invite_url(db, target)}


# ── admin: batches ─────────────────────────────────────────────────────────

class BatchCreateIn(BaseModel):
    profile_id: int
    urls: str

@router.post("/admin/batches")
def api_admin_batch_create(
    body: BatchCreateIn,
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    p = db.get(Profile, body.profile_id)
    if p is None: raise HTTPException(404)
    if not storage.base_resume_path(body.profile_id).exists():
        raise HTTPException(400, "Upload a base resume for this profile first.")

    raw_lines = [ln.strip() for ln in body.urls.splitlines()
                 if ln.strip() and not ln.strip().startswith("#")]
    seen: set = set(); lines: list = []
    for u in raw_lines:
        if u not in seen:
            seen.add(u); lines.append(u)
    if not lines:
        raise HTTPException(400, "Paste at least one URL.")
    if len(lines) > config.MAX_URLS_PER_BATCH:
        raise HTTPException(
            400,
            f"That's {len(lines)} URLs — capped at {config.MAX_URLS_PER_BATCH} per submit "
            "to keep API costs in check. Submit in chunks.",
        )

    done_urls = {u for (u,) in (
        db.query(JobUrl.url).join(Batch, Batch.id == JobUrl.batch_id)
        .filter(Batch.profile_id == body.profile_id, JobUrl.status == STATUS_DONE).all()
    )}
    new_lines = [u for u in lines if u not in done_urls]
    skipped = len(lines) - len(new_lines)

    today = datetime.now(PACIFIC).date()
    start_utc = datetime.combine(today, datetime.min.time(), tzinfo=PACIFIC).astimezone(timezone.utc).replace(tzinfo=None)
    end_utc   = datetime.combine(today, datetime.max.time(), tzinfo=PACIFIC).astimezone(timezone.utc).replace(tzinfo=None)

    if not new_lines:
        existing = (db.query(Batch).filter(
            Batch.profile_id == body.profile_id,
            Batch.created_at >= start_utc, Batch.created_at <= end_utc,
        ).order_by(Batch.created_at.desc()).first())
        return {
            "batch_id": existing.id if existing else None,
            "added": 0, "skipped_done": skipped, "skipped_dupe": 0,
            "message": f"All {skipped} URLs were already tailored for this profile.",
        }

    batch = (db.query(Batch).filter(
        Batch.profile_id == body.profile_id,
        Batch.created_at >= start_utc, Batch.created_at <= end_utc,
    ).order_by(Batch.created_at.desc()).first())
    if batch is None:
        batch = Batch(profile_id=body.profile_id, label=None)
        db.add(batch); db.flush()

    existing_in_batch = {u for (u,) in db.query(JobUrl.url).filter(JobUrl.batch_id == batch.id).all()}
    to_add = [u for u in new_lines if u not in existing_in_batch]
    in_batch_dupes = len(new_lines) - len(to_add)

    jus = [JobUrl(batch_id=batch.id, url=u, status=STATUS_PENDING) for u in to_add]
    for j in jus: db.add(j)
    db.commit()
    for j in jus: pipeline.enqueue(j.id)

    return {
        "batch_id": batch.id,
        "added": len(jus),
        "skipped_done": skipped,
        "skipped_dupe": in_batch_dupes,
    }


@router.get("/admin/batches/{bid}")
def api_admin_batch_detail(
    bid: int,
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    b = db.get(Batch, bid)
    if b is None: raise HTTPException(404)
    jobs = db.query(JobUrl).filter(JobUrl.batch_id == bid).order_by(JobUrl.id.asc()).all()
    return {
        "batch": {"id": b.id, "created_at": _iso(b.created_at)},
        "profile": {
            "id": b.profile.id,
            "name": b.profile.name,
        },
        "jobs": [job_out(j) for j in jobs],
        "summary": batch_summary(jobs),
    }


class ManualJDIn(BaseModel):
    company: Optional[str] = ""
    title: Optional[str] = ""
    location: Optional[str] = ""
    description: str

@router.post("/admin/batches/{bid}/jobs/{jid}/manual")
def api_admin_manual_jd(
    bid: int, jid: int, body: ManualJDIn,
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    ju = db.get(JobUrl, jid)
    if ju is None or ju.batch_id != bid: raise HTTPException(404)
    if not body.description.strip() or len(body.description.strip()) < 100:
        raise HTTPException(400, "Paste at least 100 characters of job description.")
    ju.company = (body.company or "").strip() or ju.company
    ju.title = (body.title or "").strip() or ju.title
    ju.location = (body.location or "").strip() or ju.location
    ju.description = body.description.strip()
    ju.status = STATUS_PENDING
    ju.error_message = None
    db.commit()
    pipeline.enqueue(ju.id)
    return {"job": job_out(ju)}


@router.post("/batches/{bid}/jobs/{jid}/manual-jd")
def api_manual_jd(
    bid: int, jid: int, body: ManualJDIn,
    user: User = Depends(auth.require_user),
    db: Session = Depends(get_db),
):
    """Anyone with access to the batch (admin or granted bidder) can paste the
    job description to unblock a `needs_manual_jd` row and re-run the pipeline."""
    ju = db.get(JobUrl, jid)
    if ju is None or ju.batch_id != bid: raise HTTPException(404)
    _check_batch_access(user, ju.batch, db)
    if not body.description.strip() or len(body.description.strip()) < 100:
        raise HTTPException(400, "Paste at least 100 characters of job description.")
    ju.company = (body.company or "").strip() or ju.company
    ju.title = (body.title or "").strip() or ju.title
    ju.location = (body.location or "").strip() or ju.location
    ju.description = body.description.strip()
    ju.status = STATUS_PENDING
    ju.error_message = None
    db.commit()
    pipeline.enqueue(ju.id)
    return {"job": job_out(ju)}


@router.post("/admin/batches/{bid}/jobs/{jid}/retry")
def api_admin_retry_job(
    bid: int, jid: int,
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    ju = db.get(JobUrl, jid)
    if ju is None or ju.batch_id != bid: raise HTTPException(404)
    ju.status = STATUS_PENDING
    ju.error_message = None
    db.commit()
    pipeline.enqueue(ju.id)
    return {"job": job_out(ju)}


@router.post("/admin/batches/{bid}/retry-errors")
def api_admin_retry_errors(
    bid: int,
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    b = db.get(Batch, bid)
    if b is None: raise HTTPException(404)
    errored = db.query(JobUrl).filter(JobUrl.batch_id == bid, JobUrl.status == "error").all()
    for ju in errored:
        ju.status = STATUS_PENDING
        ju.error_message = None
    db.commit()
    for ju in errored: pipeline.enqueue(ju.id)
    return {"requeued": len(errored)}


# ── admin: calendar ────────────────────────────────────────────────────────

@router.get("/admin/calendar")
def api_admin_calendar(
    year: Optional[int] = None, month: Optional[int] = None,
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    today_pst = datetime.now(PACIFIC).date()
    y = year or today_pst.year
    m = month or today_pst.month

    batches = db.query(Batch).order_by(Batch.created_at.asc()).all()
    by_day: dict = defaultdict(list)
    for b in batches:
        d = _to_pacific(b.created_at).date()
        if d.year == y and d.month == m:
            s = batch_summary(b.urls)
            by_day[d].append({
                "id": b.id,
                "profile_name": b.profile.name,
                "profile_id": b.profile.id,
                "url_count": len(b.urls),
                "done": s["done"],
                "applied": s["applied"],
            })

    cal = _calendar.Calendar(firstweekday=6)

    def day_totals(entries: list[dict]) -> dict:
        tailored = sum(e["done"] for e in entries)
        applied = sum(e["applied"] for e in entries)
        return {
            "applied": applied, "tailored": tailored,
            "percent": int(round(100 * applied / tailored)) if tailored else 0,
        }

    weeks = [[{
        "date": d.isoformat(),
        "day": d.day,
        "in_month": d.month == m,
        "is_today": d == today_pst,
        "batches": by_day.get(d, []),
        "totals": day_totals(by_day.get(d, [])),
    } for d in week] for week in cal.monthdatescalendar(y, m)]

    prev_y, prev_m = (y - 1, 12) if m == 1 else (y, m - 1)
    next_y, next_m = (y + 1, 1) if m == 12 else (y, m + 1)
    return {
        "year": y, "month": m, "month_name": _calendar.month_name[m],
        "weeks": weeks, "today": today_pst.isoformat(),
        "prev": {"year": prev_y, "month": prev_m},
        "next": {"year": next_y, "month": next_m},
    }


# ── bidder: "my" ────────────────────────────────────────────────────────────

@router.get("/my/profiles")
def api_my_profiles(
    user: User = Depends(auth.require_user),
    db: Session = Depends(get_db),
):
    if user.role == "admin":
        profiles = db.query(Profile).all()
    else:
        profiles = [a.profile for a in user.profile_accesses]
    return {"profiles": [profile_out(p) for p in profiles]}


@router.get("/my/profiles/{pid}")
def api_my_profile(
    pid: int,
    user: User = Depends(auth.require_user),
    db: Session = Depends(get_db),
):
    p = db.get(Profile, pid)
    if p is None: raise HTTPException(404)
    if user.role != "admin":
        if not (db.query(ProfileAccess)
                .filter(ProfileAccess.profile_id == pid, ProfileAccess.user_id == user.id).first()):
            raise HTTPException(403)
    batches = (db.query(Batch).filter(Batch.profile_id == pid)
               .order_by(Batch.created_at.desc()).all())
    return {
        "profile": profile_out(p),
        "batches": [{
            "id": b.id,
            "created_at": _iso(b.created_at),
            "total": len(b.urls),
            "done": sum(1 for j in b.urls if j.status == STATUS_DONE),
            "needs_jd": sum(1 for j in b.urls if j.status == "needs_manual_jd"),
            "in_flight": sum(
                1 for j in b.urls
                if j.status in ("pending", "fetching", "tailoring")
            ),
            "errors": sum(1 for j in b.urls if j.status == "error"),
        } for b in batches],
    }


def _check_batch_access(user: User, batch: Batch, db: Session) -> None:
    if user.role == "admin":
        return
    if not (db.query(ProfileAccess)
            .filter(ProfileAccess.profile_id == batch.profile_id,
                    ProfileAccess.user_id == user.id).first()):
        raise HTTPException(403)


@router.get("/my/batches/{bid}")
def api_my_batch(
    bid: int,
    user: User = Depends(auth.require_user),
    db: Session = Depends(get_db),
):
    b = db.get(Batch, bid)
    if b is None: raise HTTPException(404)
    _check_batch_access(user, b, db)
    # Bidders see every URL in the batch so they know why a number is missing
    # (still scraping, needs JD, errored, etc.). Done URLs appear first so the
    # usable resumes are always on top.
    jobs_all = (db.query(JobUrl).filter(JobUrl.batch_id == bid)
                .order_by(JobUrl.id.asc()).all())
    done_jobs = [j for j in jobs_all if j.status == STATUS_DONE]
    pending_jobs = [j for j in jobs_all if j.status != STATUS_DONE]
    applied = sum(1 for j in done_jobs if j.application_status == "applied")
    return {
        "batch": {"id": b.id, "created_at": _iso(b.created_at)},
        "profile": {
            "id": b.profile.id,
            "name": b.profile.name,
        },
        "jobs": [job_out(j) for j in done_jobs],
        "pending_jobs": [job_out(j) for j in pending_jobs],
        "applied": applied,
    }


class AppStatusIn(BaseModel):
    status: str
    note: Optional[str] = ""

@router.post("/batches/{bid}/jobs/{jid}/app-status")
def api_app_status(
    bid: int, jid: int, body: AppStatusIn,
    user: User = Depends(auth.require_user),
    db: Session = Depends(get_db),
):
    ju = db.get(JobUrl, jid)
    if ju is None or ju.batch_id != bid: raise HTTPException(404)
    _check_batch_access(user, ju.batch, db)
    if body.status not in APP_STATUSES:
        raise HTTPException(400, f"Unknown status: {body.status}")
    ju.application_status = body.status
    if body.status == "new":
        ju.applied_at = None
    elif body.status == "applied" and ju.applied_at is None:
        ju.applied_at = datetime.now(timezone.utc)
    if body.note:
        ju.application_note = body.note.strip() or None
    db.commit()
    return {"job": job_out(ju)}

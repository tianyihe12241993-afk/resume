"""tailor-studio REST API. JSON shapes match the admin app's where possible
so the React frontend (forked from `frontend/`) reuses the same components.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urlsplit, urlunsplit, parse_qsl, urlencode

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from . import auth, config, pipeline, storage
from .db import (
    Batch, CalendarEvent, ChatMessage, JobUrl, Profile, ProfileAccess, User, get_db,
    APP_STATUSES, STATUS_DONE, STATUS_ERROR, STATUS_NEEDS_JD, STATUS_PENDING,
)


# Public router: /api/login, /api/signup, /api/logout, /api/me — no auth dep.
public_router = APIRouter(prefix="/api")
# Protected router: every other endpoint requires a valid session.
# We DON'T put auth.require_user in `dependencies=` because each handler
# wants the User object (via Depends(auth.require_user)) and adding it as a
# router-level dep too would invoke it twice.
router = APIRouter(prefix="/api")


def _accessible_pids(db: Session, user) -> set[int]:
    """Profile ids `user` can act on: ones they own + ones an admin assigned
    them. Admins have oversight of EVERY profile (incl. bidder-created ones).
    Uses filter_by(...) deliberately so the project-wide owner-filter rewrite
    doesn't touch this definition."""
    if getattr(user, "is_admin", False):
        return {pid for (pid,) in db.query(Profile.id).all()}
    owned = {pid for (pid,) in db.query(Profile.id).filter_by(user_id=user.id).all()}
    granted = {pid for (pid,) in db.query(ProfileAccess.profile_id).filter_by(user_id=user.id).all()}
    return owned | granted


def _can_access_profile(db: Session, user, p: Profile) -> bool:
    if getattr(user, "is_admin", False) or p.user_id == user.id:
        return True
    return db.query(ProfileAccess.id).filter_by(profile_id=p.id, user_id=user.id).first() is not None


def _user_profile(db: Session, user, pid: int) -> Profile:
    """Look up a profile `user` can access (owns or was assigned). 404 otherwise."""
    p = db.get(Profile, pid)
    if p is None or not _can_access_profile(db, user, p):
        raise HTTPException(404, "Not found.")
    return p


def _user_batch(db: Session, user, bid: int) -> Batch:
    """Look up a batch on a profile `user` can access."""
    b = db.get(Batch, bid)
    if b is None:
        raise HTTPException(404, "Not found.")
    profile = db.get(Profile, b.profile_id)
    if profile is None or not _can_access_profile(db, user, profile):
        raise HTTPException(404, "Not found.")
    return b


def _user_job(db: Session, user, bid: int, jid: int) -> JobUrl:
    """Verify ownership chain and return the JobUrl."""
    _user_batch(db, user, bid)  # raises 404 if not owner
    j = db.get(JobUrl, jid)
    if j is None or j.batch_id != bid:
        raise HTTPException(404, "Not found.")
    return j


# ───────────────── auth ─────────────────

class LoginIn(BaseModel):
    email: str
    password: str


class SignupIn(BaseModel):
    email: str
    password: str


@public_router.post("/signup")
def api_signup(body: SignupIn, response: Response, db: Session = Depends(get_db)):
    err = auth.validate_signup(body.email, body.password)
    if err:
        raise HTTPException(400, err)
    if auth.get_user_by_email(db, body.email) is not None:
        raise HTTPException(409, "An account with that email already exists.")
    # Admin if the email is in the configured allow-list, OR (bootstrap) this is
    # the first account on a fresh instance with no admin yet — so a freshly
    # cloned deployment can just register its first user as the admin.
    is_admin = auth.is_configured_admin(body.email) or (
        config.BOOTSTRAP_FIRST_ADMIN and not auth.admin_exists(db)
    )
    user = auth.create_user(db, body.email, body.password,
                            approved=is_admin, is_admin=is_admin)
    auth.issue_session(response, user.id)
    return {"ok": True, "email": user.email, "id": user.id, "approved": user.approved}


@public_router.post("/login")
def api_login(body: LoginIn, response: Response, db: Session = Depends(get_db)):
    user = auth.get_user_by_email(db, body.email or "")
    if user is None or not auth.verify_password(body.password or "", user.password_hash):
        raise HTTPException(401, "Invalid email or password.")
    auth.issue_session(response, user.id)
    return {"ok": True, "email": user.email, "id": user.id}


@public_router.post("/logout")
def api_logout(response: Response):
    auth.clear_session(response)
    return {"ok": True}


class NameIn(BaseModel):
    name: str


@router.post("/me/name")
def api_set_name(body: NameIn, db: Session = Depends(get_db), me=Depends(auth.require_user)):
    """Member sets their own username (chat display + @mention). Restricted to
    mention-friendly characters so @name keeps working."""
    import re as _re
    name = (body.name or "").strip()
    if not (2 <= len(name) <= 32) or not _re.fullmatch(r"[A-Za-z0-9._-]+", name):
        raise HTTPException(400, "Use 2–32 chars: letters, numbers, . _ - (no spaces).")
    u = db.get(User, me.id)
    u.display_name = name
    # Reflect the new name on this member's existing chat messages too.
    db.query(ChatMessage).filter(ChatMessage.user_id == u.id).update(
        {ChatMessage.sender_name: name}, synchronize_session=False)
    db.commit()
    return {"name": _uname(u)}


@public_router.get("/me")
def api_me(request: Request):
    user = auth.current_user(request)
    if user is None:
        raise HTTPException(401, "Not authenticated.")
    return {
        "id": user.id,
        "email": user.email,
        "name": _uname(user),
        "role": "user",
        "is_admin": bool(getattr(user, "is_admin", False)),
        "approved": bool(getattr(user, "approved", False)),
        "password_set": True,
        "created_at": _iso(user.created_at),
    }


# ───────────────── helpers ─────────────────

def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _uname(u: User) -> str:
    """A member's display name: chosen username, else the email local-part."""
    return (u.display_name or "").strip() or u.email.split("@")[0]


def _profile_out(p: Profile) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "base_resume_filename": p.base_resume_filename,
        "has_base_resume": bool(p.base_resume_filename)
                            and storage.base_resume_path(p.id).exists(),
        "batch_count": len(p.batches),
        "tailor_prompt": p.tailor_prompt or "",
        "uses_default_prompt": not (p.tailor_prompt and p.tailor_prompt.strip()),
        "daily_target": p.daily_target,
        "created_at": _iso(p.created_at),
    }


def _job_out(j: JobUrl, *, with_coverage: bool = False) -> dict:
    out = {
        "id": j.id,
        "url": j.url,
        "status": j.status,
        "company": j.company,
        "title": j.title,
        "location": j.location,
        "work_type": j.work_type,
        "description": j.description,
        "error_message": j.error_message,
        "fail_reason": j.fail_reason,
        "application_status": j.application_status,
        "applied_at": _iso(j.applied_at),
        "application_note": j.application_note,
        "application_source": j.application_source,
        "apply_count": j.apply_count or 0,
        "has_docx": bool(j.docx_filename),
        "download_count": j.download_count,
        "upload_filename": j.upload_filename,
        "upload_match": j.upload_match,
        "upload_observed_at": _iso(j.upload_observed_at),
        "note": j.note,
        "note_updated_at": _iso(j.note_updated_at),
        "note_seen_at": _iso(j.note_seen_at),
        "note_by": j.note_by,
        "note_confirmed_at": _iso(j.note_confirmed_at),
        "note_confirmed_by": j.note_confirmed_by,
        "has_unread_note": bool(
            j.note and j.note.strip() and
            (j.note_seen_at is None or (j.note_updated_at and j.note_updated_at > j.note_seen_at))
        ),
        "created_at": _iso(j.created_at),
    }
    if with_coverage:
        try:
            out["coverage_initial"] = json.loads(j.coverage_initial) if j.coverage_initial else None
        except (TypeError, ValueError):
            out["coverage_initial"] = None
        try:
            out["coverage_final"] = json.loads(j.coverage_final) if j.coverage_final else None
        except (TypeError, ValueError):
            out["coverage_final"] = None
        try:
            out["claimed_terms"] = json.loads(j.claimed_terms) if j.claimed_terms else []
        except (TypeError, ValueError):
            out["claimed_terms"] = []
    return out


def _batch_summary(jobs: list[JobUrl]) -> dict:
    total = len(jobs)
    done = sum(1 for j in jobs if j.status == STATUS_DONE)
    needs_jd = sum(1 for j in jobs if j.status == STATUS_NEEDS_JD)
    errors = sum(1 for j in jobs if j.status == STATUS_ERROR)
    in_flight = sum(
        1 for j in jobs
        if j.status not in (STATUS_DONE, STATUS_NEEDS_JD, STATUS_ERROR)
    )
    applied = sum(1 for j in jobs if j.application_status == "applied")
    pct = round(100 * done / total) if total else 0
    applied_pct = round(100 * applied / total) if total else 0
    return {
        "total": total, "done": done, "in_flight": in_flight,
        "needs_jd": needs_jd, "errors": errors,
        "percent": pct, "applied": applied, "applied_percent": applied_pct,
    }


# ───────────────── dashboard ─────────────────

def _today_pst() -> date:
    # Pacific Time, but without zoneinfo dependency: PT is UTC-8 (no DST adjust
    # for simplicity; off by 1h half the year — fine for "today's batch").
    return (datetime.now(timezone.utc) - timedelta(hours=8)).date()


@router.get("/admin/dashboard")
def api_dashboard(
    db: Session = Depends(get_db),
    user=Depends(auth.require_user),
):
    # Show every profile (team-wide work overview); `can_access` controls whether
    # the viewer can open/act on each one.
    profiles = db.query(Profile).order_by(Profile.created_at.asc()).all()
    accessible = _accessible_pids(db, user)
    today = _today_pst()
    today_start = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=8)
    today_end = today_start + timedelta(days=1)

    profile_statuses = []
    agg_jobs: list[JobUrl] = []
    today_job_rows: list[tuple[JobUrl, Profile, Batch]] = []
    trend_dates = [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    agg_trend = [0] * 7

    week_start = today_start - timedelta(days=6)
    for p in profiles:
        today_batch = (
            db.query(Batch)
            .filter(
                Batch.profile_id == p.id,
                Batch.created_at >= today_start,
                Batch.created_at < today_end,
            )
            .order_by(Batch.created_at.desc())
            .first()
        )
        today_jobs: list[JobUrl] = list(today_batch.urls) if today_batch else []
        agg_jobs.extend(today_jobs)
        if today_batch:
            for j in today_jobs:
                today_job_rows.append((j, p, today_batch))
        summary = _batch_summary(today_jobs)

        # 7-day applied trend (per-profile)
        trend = [0] * 7
        rows = (
            db.query(JobUrl)
            .join(Batch, JobUrl.batch_id == Batch.id)
            .filter(
                Batch.profile_id == p.id,
                JobUrl.applied_at != None,  # noqa: E711
                JobUrl.applied_at >= week_start,
                JobUrl.applied_at < today_end,
            )
            .all()
        )
        for r in rows:
            d = (r.applied_at - timedelta(hours=8)).date()
            try:
                idx = trend_dates.index(d.isoformat())
                trend[idx] += 1
                agg_trend[idx] += 1
            except ValueError:
                pass

        # This-week aggregate: every JobUrl on any batch created in the
        # past 7 PT days for this profile, bucketed by status.
        week_jobs: list[JobUrl] = (
            db.query(JobUrl)
            .join(Batch, JobUrl.batch_id == Batch.id)
            .filter(
                Batch.profile_id == p.id,
                Batch.created_at >= week_start,
                Batch.created_at < today_end,
            )
            .all()
        )
        week_summary = _batch_summary(week_jobs)

        profile_statuses.append({
            "profile": {
                "id": p.id,
                "name": p.name,
                "has_base_resume": bool(p.base_resume_filename)
                                    and storage.base_resume_path(p.id).exists(),
                "can_access": p.id in accessible,
            },
            "today_batch": {"id": today_batch.id, "created_at": _iso(today_batch.created_at)}
                            if today_batch else None,
            "summary": summary,
            "week": week_summary,
            "trend": trend,
        })

    # Flat list of today's individual jobs across every profile — drives the
    # "Today's jobs" detail table on the dashboard. Sorted newest-first.
    today_job_rows.sort(key=lambda r: (r[0].updated_at or r[0].created_at), reverse=True)
    today_jobs_out = [
        {
            "job_id": j.id,
            "batch_id": b.id,
            "profile_id": p.id,
            "profile_name": p.name,
            "company": j.company,
            "title": j.title,
            "location": j.location,
            "work_type": j.work_type,
            "url": j.url,
            "status": j.status,
            "fail_reason": j.fail_reason,
            "error_message": j.error_message,
            "application_status": j.application_status,
            "upload_match": j.upload_match,
            "apply_count": j.apply_count or 0,
            "applied_at": _iso(j.applied_at),
            "created_at": _iso(j.created_at),
            "has_unread_note": bool(
                j.note and j.note.strip() and
                (j.note_seen_at is None or (j.note_updated_at and j.note_updated_at > j.note_seen_at))
            ),
        }
        for (j, p, b) in today_job_rows
    ]

    return {
        "now_pst": _iso(datetime.now(timezone.utc)),
        "today": today.isoformat(),
        "profile_statuses": profile_statuses,
        "agg": _batch_summary(agg_jobs),
        "agg_trend": agg_trend,
        "trend_dates": trend_dates,
        "today_jobs": today_jobs_out,
        "ready_profiles": [_profile_out(p) for p in profiles
                            if storage.base_resume_path(p.id).exists()],
        "has_any_profile": len(profiles) > 0,
    }


# ───────────────── profiles ─────────────────

@router.get("/admin/tailor-prompt-default")
def api_default_prompt():
    from app.tailoring import TAILOR_SYSTEM
    return {"prompt": TAILOR_SYSTEM}


@router.get("/admin/profiles")
def api_list_profiles(
    db: Session = Depends(get_db),
    user=Depends(auth.require_user),
):
    # Everyone sees every profile card (so bidders can see the whole team's work),
    # but `can_access` controls whether they can open / act on it.
    rows = db.query(Profile).order_by(Profile.created_at.desc()).all()
    accessible = _accessible_pids(db, user)
    out = []
    for p in rows:
        counts = dict(
            db.query(JobUrl.status, func.count(JobUrl.id))
            .join(Batch, JobUrl.batch_id == Batch.id)
            .filter(Batch.profile_id == p.id)
            .group_by(JobUrl.status).all()
        )
        applied = (
            db.query(func.count(JobUrl.id))
            .join(Batch, JobUrl.batch_id == Batch.id)
            .filter(Batch.profile_id == p.id, JobUrl.application_status == "applied")
            .scalar()
        )
        out.append({
            **_profile_out(p),
            "can_access": p.id in accessible,
            "total": sum(counts.values()),
            "done": counts.get(STATUS_DONE, 0),
            "applied": applied or 0,
        })
    return {"profiles": out}


class ProfileCreateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


@router.post("/admin/profiles")
def api_create_profile(
    body: ProfileCreateIn,
    db: Session = Depends(get_db),
    user=Depends(auth.require_user),
):
    # Any approved user can create a profile; they own it (and can fully manage
    # it). Admins additionally have oversight of every profile via _accessible.
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "Profile name is required.")
    p = Profile(name=name, user_id=user.id)
    db.add(p)
    db.commit()
    db.refresh(p)
    return {"profile": _profile_out(p)}


class ProfileUpdateIn(BaseModel):
    name: Optional[str] = None
    tailor_prompt: Optional[str] = None
    daily_target: Optional[int] = None


@router.post("/admin/profiles/{pid}/update")
def api_update_profile(
    pid: int, body: ProfileUpdateIn,
    db: Session = Depends(get_db),
    user=Depends(auth.require_user),
):
    if not user.is_admin:
        raise HTTPException(403, "Only the admin can edit profiles.")
    p = _user_profile(db, user, pid)
    if body.name is not None and body.name.strip():
        p.name = body.name.strip()
    if body.tailor_prompt is not None:
        p.tailor_prompt = body.tailor_prompt.strip() or None
    if body.daily_target is not None:
        p.daily_target = max(0, int(body.daily_target))
    db.commit()
    db.refresh(p)
    return {"profile": _profile_out(p)}


@router.post("/admin/profiles/{pid}/delete")
def api_delete_profile(
    pid: int,
    db: Session = Depends(get_db),
    user=Depends(auth.require_user),
):
    if not user.is_admin:
        raise HTTPException(403, "Only the admin can delete profiles.")
    p = _user_profile(db, user, pid)
    p_path = storage.base_resume_path(pid)
    if p_path.exists():
        try: p_path.unlink()
        except OSError: pass
    for b in p.batches:
        for j in b.urls:
            if j.docx_filename:
                fp = config.OUTPUTS_DIR / j.docx_filename
                if fp.exists():
                    try: fp.unlink()
                    except OSError: pass
    db.delete(p)
    db.commit()
    return {"ok": True}


@router.get("/admin/profiles/{pid}")
def api_profile_detail(
    pid: int,
    db: Session = Depends(get_db),
    user=Depends(auth.require_user),
):
    p = _user_profile(db, user, pid)
    batches = sorted(p.batches, key=lambda b: b.created_at, reverse=True)
    return {
        "profile": _profile_out(p),
        "accesses": [],  # no bidders in studio — kept for FE compat
        "batches": [
            {"id": b.id, "created_at": _iso(b.created_at), "url_count": len(b.urls)}
            for b in batches
        ],
    }


@router.get("/admin/profiles/{pid}/resume")
def api_download_base_resume(
    pid: int,
    db: Session = Depends(get_db),
    user=Depends(auth.require_user),
):
    """Serve the base resume .docx for a profile. Used by the extension's
    Resume Ready widget when no tailored resume exists yet."""
    from fastapi.responses import FileResponse
    p = _user_profile(db, user, pid)
    path = storage.base_resume_path(pid)
    if not path.exists():
        raise HTTPException(404, "No base resume uploaded for this profile.")
    fname = f"{_slugify(p.name)}__base_resume.docx"
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=fname,
    )


@router.post("/admin/profiles/{pid}/resume")
async def api_upload_resume(
    pid: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user=Depends(auth.require_user),
):
    # Owner, admin, or an assigned bidder may set the base resume — _user_profile
    # enforces access (404 for anyone without owner/grant access to this profile).
    p = _user_profile(db, user, pid)
    if not file.filename or not file.filename.lower().endswith(".docx"):
        raise HTTPException(400, "Upload a .docx file.")
    contents = await file.read()
    if not contents:
        raise HTTPException(400, "Empty file.")
    if len(contents) > config.MAX_RESUME_BYTES:
        raise HTTPException(
            400, f"File too large (>{config.MAX_RESUME_BYTES // (1024*1024)} MB)."
        )
    safe = Path(file.filename).name
    storage.base_resume_path(pid).write_bytes(contents)
    p.base_resume_filename = safe
    db.commit()
    db.refresh(p)
    return {"profile": _profile_out(p)}


# ───────────────── profile ↔ bidder assignment (admin) ─────────────────

@router.get("/admin/profiles/{pid}/access")
def api_profile_access_list(
    pid: int, db: Session = Depends(get_db), me=Depends(auth.require_admin),
):
    """List every bidder and whether they're assigned to this profile."""
    p = db.get(Profile, pid)
    if p is None or p.user_id != me.id:
        raise HTTPException(404, "Not found.")
    granted = {
        uid for (uid,) in db.query(ProfileAccess.user_id).filter_by(profile_id=pid).all()
    }
    bidders = (
        db.query(User)
        .filter(User.is_admin == False, User.approved == True)  # noqa: E712
        .order_by(User.email).all()
    )
    return {"bidders": [
        {"id": u.id, "name": _uname(u), "email": u.email, "has_access": u.id in granted}
        for u in bidders
    ]}


class AccessIn(BaseModel):
    granted: bool


@router.post("/admin/profiles/{pid}/access/{uid}")
def api_profile_access_set(
    pid: int, uid: int, body: AccessIn,
    db: Session = Depends(get_db), me=Depends(auth.require_admin),
):
    p = db.get(Profile, pid)
    if p is None or p.user_id != me.id:
        raise HTTPException(404, "Not found.")
    u = db.get(User, uid)
    if u is None or u.is_admin:
        raise HTTPException(400, "Not a bidder account.")
    row = db.query(ProfileAccess).filter_by(profile_id=pid, user_id=uid).first()
    if body.granted and row is None:
        db.add(ProfileAccess(profile_id=pid, user_id=uid))
    elif not body.granted and row is not None:
        db.delete(row)
    db.commit()
    return {"ok": True, "granted": body.granted}


# ───────────────── batches ─────────────────

class BatchCreateIn(BaseModel):
    profile_id: int
    urls: str  # newline-separated; admin-style


@router.post("/admin/batches")
def api_create_batch(
    body: BatchCreateIn,
    db: Session = Depends(get_db),
    user=Depends(auth.require_user),
):
    return _queue_urls_for_profile(db, user, body.profile_id, body.urls or "")


def _queue_urls_for_profile(
    db: Session, user, profile_id: int, raw_url_input: str | list[str],
) -> dict:
    """Shared core for batch creation. Accepts either the legacy newline-
    delimited string (BatchCreateIn.urls) or a list of URLs (extension
    endpoint). Returns the same response shape as api_create_batch."""
    p = _user_profile(db, user, profile_id)
    if not storage.base_resume_path(p.id).exists():
        raise HTTPException(400, "Upload a base resume for this profile first.")

    if isinstance(raw_url_input, list):
        candidates = raw_url_input
    else:
        candidates = (raw_url_input or "").splitlines()
    raw_urls = [
        u.strip() for u in candidates
        if u and u.strip() and (u.strip().startswith("http://") or u.strip().startswith("https://"))
    ]
    if not raw_urls:
        raise HTTPException(400, "No valid URLs provided.")
    seen: set[str] = set()
    cleaned = []
    skipped_linkedin: list[str] = []
    for u in raw_urls:
        if u in seen:
            continue
        seen.add(u)
        host = urlparse(u).netloc.lower()
        if host == "linkedin.com" or host.endswith(".linkedin.com"):
            skipped_linkedin.append(u)
            continue
        cleaned.append(u)
    if len(cleaned) > config.MAX_URLS_PER_BATCH:
        raise HTTPException(
            400, f"Too many URLs ({len(cleaned)}). Max {config.MAX_URLS_PER_BATCH}."
        )
    if not cleaned:
        return {
            "batch_id": None, "added": 0,
            "skipped_done": 0, "skipped_existing": 0, "skipped_dupe": 0,
            "skipped_linkedin": len(skipped_linkedin),
            "duplicates": [],
            "message": f"All {len(skipped_linkedin)} URLs were LinkedIn — skipped (LinkedIn blocks scrapers). Paste the JD text manually for these.",
        }
    result = _queue_cleaned_urls(db, p, raw_urls, cleaned)
    result["skipped_linkedin"] = len(skipped_linkedin)
    return result


# Query params that identify *how the user arrived* at a posting, not *which*
# posting it is. Stripped before dedup so the same job pasted from different
# aggregators / with different tracking tags is recognized as one. Identity
# params (greenhouse `token`/`gh_jid`, ADP `jobId`, Lever ids, etc.) are kept.
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_name", "gclid", "fbclid", "msclkid", "yclid", "mc_cid",
    "mc_eid", "igshid", "ref", "ref_src", "referrer", "source", "src", "spm",
    "trk", "trkcampaign", "gh_src", "lever-source", "lever-origin", "_hsenc",
    "_hsmi", "vero_id", "cid",
}


def _normalize_url(url: str) -> str:
    """Canonical form of a job URL for DEDUP COMPARISON ONLY (the original URL
    is what gets stored/fetched). Lowercases scheme+host, drops `www.`, a
    trailing slash, the fragment, and tracking query params, and sorts the
    remaining (identity-bearing) params so order doesn't matter."""
    try:
        s = urlsplit(url.strip())
        scheme = (s.scheme or "https").lower()
        netloc = s.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        kept = [
            (k, v) for (k, v) in parse_qsl(s.query, keep_blank_values=True)
            if k.lower() not in _TRACKING_PARAMS and not k.lower().startswith("utm_")
        ]
        kept.sort()
        path = s.path.rstrip("/") or "/"
        return urlunsplit((scheme, netloc, path, urlencode(kept), ""))
    except Exception:
        return (url or "").strip()


def _queue_cleaned_urls(db: Session, p, raw_urls, cleaned) -> dict:

    # Skip any URL that already exists for this profile in ANY status — compared
    # on the NORMALIZED form, so the same job pasted with different tracking tags
    # is caught. We keep the original URL on each row (extension URL-matching is
    # unaffected); normalization is comparison-only. Reposted jobs they may want
    # to re-apply to are surfaced with their last-applied info.
    rows = (
        db.query(JobUrl, Batch)
        .join(Batch, JobUrl.batch_id == Batch.id)
        .filter(Batch.profile_id == p.id)
        .all()
    )
    existing_norm: dict[str, tuple] = {}
    for (j, b) in rows:
        existing_norm.setdefault(_normalize_url(j.url), (j, b))

    existing_urls: set[str] = set()          # normalized hits (for counts)
    existing_by_status: dict[str, set[str]] = {}
    duplicates: list[dict] = []
    todo_urls: list[str] = []
    batch_seen: set[str] = set()
    now_utc = datetime.now(timezone.utc)
    for u in cleaned:
        nu = _normalize_url(u)
        hit = existing_norm.get(nu)
        if hit is not None:
            j, b = hit
            existing_by_status.setdefault(j.status, set()).add(nu)
            if nu not in existing_urls:
                existing_urls.add(nu)
                days_since_applied = None
                if j.applied_at:
                    applied = j.applied_at
                    if applied.tzinfo is None:
                        applied = applied.replace(tzinfo=timezone.utc)
                    days_since_applied = int((now_utc - applied).total_seconds() // 86400)
                duplicates.append({
                    "url": j.url,
                    "job_id": j.id,
                    "batch_id": b.id,
                    "status": j.status,
                    "application_status": j.application_status,
                    "applied_at": _iso(j.applied_at),
                    "days_since_applied": days_since_applied,
                    "apply_count": j.apply_count or 0,
                    "company": j.company,
                    "title": j.title,
                })
            continue
        if nu in batch_seen:
            continue  # same job twice in this paste (e.g. different utm tags)
        batch_seen.add(nu)
        todo_urls.append(u)
    if not todo_urls:
        n_done    = len(existing_by_status.get(STATUS_DONE, set()))
        n_other   = len(existing_urls) - n_done
        bits = []
        if n_done:  bits.append(f"{n_done} already tailored")
        if n_other: bits.append(f"{n_other} already in queue / errored")
        return {
            "batch_id": None, "added": 0,
            "skipped_done": n_done,
            "skipped_existing": len(existing_urls),
            "skipped_dupe": 0,
            "duplicates": duplicates,
            "message": "All URLs already submitted for this profile (" + ", ".join(bits) + ").",
        }

    # Auto-merge with today's batch (Pacific time) if one exists.
    today = _today_pst()
    today_start = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=8)
    today_end = today_start + timedelta(days=1)
    batch = (
        db.query(Batch).filter(
            Batch.profile_id == p.id,
            Batch.created_at >= today_start,
            Batch.created_at < today_end,
        ).order_by(Batch.created_at.desc()).first()
    )
    if batch is None:
        batch = Batch(profile_id=p.id)
        db.add(batch)
        db.flush()
    new_jobs = []
    for u in todo_urls:
        ju = JobUrl(batch_id=batch.id, url=u)
        db.add(ju)
        new_jobs.append(ju)
    db.commit()
    for j in new_jobs:
        db.refresh(j)
        pipeline.enqueue(j.id)

    return {
        "batch_id": batch.id,
        "added": len(new_jobs),
        "skipped_done": len(existing_by_status.get(STATUS_DONE, set())),
        "skipped_existing": len(existing_urls),
        "skipped_dupe": len(raw_urls) - len(cleaned),
        "duplicates": duplicates,
    }


def _user_stuck_jobs_for_url(db: Session, user, url: str) -> list[JobUrl]:
    """Return JobUrl rows owned by ``user`` that match ``url`` and are stuck
    in a state Rescue Mode can recover: needs_manual_jd or scrape-error."""
    return (
        db.query(JobUrl)
        .join(Batch, JobUrl.batch_id == Batch.id)
        .join(Profile, Batch.profile_id == Profile.id)
        .filter(Profile.id.in_(_accessible_pids(db, user)))
        .filter(JobUrl.url == url)
        .filter(JobUrl.status.in_([STATUS_NEEDS_JD, STATUS_ERROR]))
        .all()
    )


class ExtensionCheckIn(BaseModel):
    url: str


@router.post("/extension/check_url")
def api_extension_check_url(
    body: ExtensionCheckIn,
    db: Session = Depends(get_db),
    user=Depends(auth.require_user),
):
    """Cheap probe used by the content script: 'is this URL stuck?'.
    Content script only sends the rendered DOM when the answer is yes."""
    stuck = _user_stuck_jobs_for_url(db, user, body.url)
    return {"stuck": len(stuck) > 0, "count": len(stuck)}


class ExtensionRescueIn(BaseModel):
    url: str
    html: str


@router.post("/extension/rescue")
def api_extension_rescue(
    body: ExtensionRescueIn,
    db: Session = Depends(get_db),
    user=Depends(auth.require_user),
):
    """Receive the rendered DOM from the content script for a URL the user
    has stuck. Runs Haiku extraction on the *rendered* HTML (which the
    server-side scrape could not see), populates company/title/location/
    work_type/description on every matching stuck JobUrl, sets status back
    to pending, and re-enqueues the tailoring pipeline.
    """
    from app.scraping import _haiku_extract_from_html, _finalize
    from app import scrape_cache

    if not body.url or not body.html:
        raise HTTPException(400, "Missing url or html.")
    # Defensive cap. _haiku_extract_from_html truncates to 30K internally;
    # the network cap protects us from runaway request bodies.
    html = body.html
    if len(html) > 2_000_000:
        html = html[:2_000_000]

    stuck = _user_stuck_jobs_for_url(db, user, body.url)
    if not stuck:
        return {"rescued": 0, "message": "No stuck job for this URL."}

    info = _haiku_extract_from_html(html, body.url)
    if not info or not info.get("description"):
        return {
            "rescued": 0,
            "error": "Could not extract a job description from the rendered DOM.",
        }
    info = _finalize(info)
    # Cache it so future fetches of the same URL (e.g. re-tailor) get the
    # rescued content for free.
    try:
        scrape_cache.put(body.url, info)
    except Exception:
        pass

    rescued_ids = []
    for ju in stuck:
        if not ju.company and info.get("company"): ju.company = info["company"]
        if not ju.title   and info.get("title"):   ju.title   = info["title"]
        if not ju.location and info.get("location"): ju.location = info["location"]
        if not ju.work_type and info.get("work_type"): ju.work_type = info["work_type"]
        ju.description = info["description"]
        ju.status = STATUS_PENDING
        ju.error_message = None
        rescued_ids.append(ju.id)
    db.commit()

    # Re-enqueue after commit so the worker sees the populated row.
    for jid in rescued_ids:
        pipeline.enqueue(jid)

    return {
        "rescued": len(rescued_ids),
        "company": info.get("company"),
        "title": info.get("title"),
    }


@router.get("/extension/resume_for")
def api_extension_resume_for(
    url: str,
    profile_id: Optional[int] = None,
    db: Session = Depends(get_db),
    user=Depends(auth.require_user),
):
    """Tell the in-page widget what resume to surface for ``url``.

    If ``profile_id`` is provided (the extension's saved 'main profile'),
    only matching JobUrl rows for that profile are returned. Otherwise
    falls back to the most recently created match across all the user's
    profiles. Includes the base-resume path so the widget can offer it as
    a fallback when no tailored .docx is ready yet.
    """
    if not url:
        raise HTTPException(400, "Missing url.")

    # ALL accessible matches for this URL (do NOT pre-filter by profile — we need
    # to know about other profiles to detect a wrong/ambiguous pin).
    all_matches = (
        db.query(JobUrl, Batch, Profile)
        .join(Batch, JobUrl.batch_id == Batch.id)
        .join(Profile, Batch.profile_id == Profile.id)
        .filter(Profile.id.in_(_accessible_pids(db, user)))
        .filter(JobUrl.url == url)
        .order_by(JobUrl.created_at.desc())
        .all()
    )
    distinct_pids = {p.id for (_, _, p) in all_matches}
    if profile_id is not None:
        pinned = [(j, b, p) for (j, b, p) in all_matches if p.id == profile_id]
    else:
        pinned = all_matches

    # SAFETY: the same JD is commonly tracked for several profiles (5-6 people
    # applying to the same jobs). Two cases where we must NOT serve a resume —
    # guessing/pinning-wrong served the wrong person's file:
    #   (a) no profile pinned and the URL matches >1 profile, or
    #   (b) a profile IS pinned but the URL belongs to OTHER profile(s), not it.
    # In both, return the candidates so the widget makes the bidder pick.
    wrong_pin = profile_id is not None and not pinned and bool(distinct_pids)
    no_pin_ambiguous = profile_id is None and len(distinct_pids) > 1
    if wrong_pin or no_pin_ambiguous:
        seen: set[int] = set()
        candidates = []
        for (j, b, p) in all_matches:
            if p.id in seen:
                continue
            seen.add(p.id)
            candidates.append({
                "profile_id": p.id,
                "profile_name": p.name,
                "job_id": j.id,
                "status": j.status,
                "has_tailored": j.status == STATUS_DONE and bool(j.docx_filename),
            })
        return {"matched": True, "ambiguous": True, "wrong_pin": wrong_pin, "candidates": candidates, "base": None}

    matches = pinned
    row = matches[0] if matches else None

    # Always include the main-profile base-resume info so the widget can
    # fall back when no tailored resume exists yet.
    main_profile = None
    if profile_id is not None:
        p = db.get(Profile, profile_id)
        if p and p.user_id == user.id:
            main_profile = p
    elif row:
        main_profile = row[2]

    base = None
    if main_profile:
        has_base = storage.base_resume_path(main_profile.id).exists()
        base = {
            "profile_id": main_profile.id,
            "profile_name": main_profile.name,
            "has_base": has_base,
            "base_url": f"/api/admin/profiles/{main_profile.id}/resume" if has_base else None,
            "base_filename": f"{_slugify(main_profile.name)}__base_resume.docx",
        }

    if not row:
        return {"matched": False, "base": base}

    j, b, p = row
    tailored = None
    if j.status == STATUS_DONE and j.docx_filename:
        # Stable per-profile name (no company/role) so the auto-download
        # overwrites the previous file instead of piling up copies. Matches
        # the /download route's name.
        fname = f"{_slugify(p.name) if p.name else 'candidate'}-resume.docx"
        # Lazy-compute and persist the docx hash so the extension can
        # verify the uploaded file later. Cheap: ~10ms for a 50KB docx.
        had_hash = bool(j.resume_sha256)
        size, sha = _docx_hash_and_size(j)
        if sha and not had_hash:
            db.commit()
        tailored = {
            "job_id": j.id,
            "docx_url": f"/download/{j.id}/docx",
            "pdf_url": f"/download/{j.id}/pdf",
            "filename": fname,
            "size": size,
            "sha256": sha,
            # Null until the PDF is first generated; the extension matches the
            # upload against either hash so a PDF upload still verifies.
            "pdf_sha256": j.pdf_sha256,
        }

    return {
        "matched": True,
        "job_id": j.id,
        "profile_id": p.id,
        "profile_name": p.name,
        "company": j.company,
        "title": j.title,
        "status": j.status,
        "application_status": j.application_status,
        "has_tailored": bool(tailored),
        "tailored": tailored,
        "base": base,
    }


def _slugify(s: str) -> str:
    import re as _re
    return _re.sub(r"[^A-Za-z0-9_-]+", "_", (s or "").strip()).strip("_") or "x"


def _file_sha256(path) -> Optional[str]:
    """Stream-hash a file. Returns None if the file is missing or unreadable."""
    import hashlib
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _docx_hash_and_size(j: JobUrl) -> tuple[Optional[int], Optional[str]]:
    """Return (size, sha256) for the tailored .docx. Computes lazily and
    persists on the JobUrl row so subsequent calls are free. Returns
    (None, None) if the file is missing (pruned or never generated)."""
    if not j.docx_filename:
        return None, None
    path = config.OUTPUTS_DIR / j.docx_filename
    if not path.exists():
        return None, None
    try:
        size = path.stat().st_size
    except OSError:
        size = None
    sha = j.resume_sha256
    if not sha:
        sha = _file_sha256(path)
        if sha:
            j.resume_sha256 = sha
            # Caller is inside a Session — flushing later on commit.
    return size, sha


class UploadObservedIn(BaseModel):
    url: str
    filename: str
    size: int
    sha256: str


@router.post("/extension/upload_observed")
def api_extension_upload_observed(
    body: UploadObservedIn,
    db: Session = Depends(get_db),
    user=Depends(auth.require_user),
):
    """Receive a file-input observation from the extension content script.

    For each JobUrl owned by ``user`` matching ``body.url``, record what
    the co-worker selected on the upload form and classify the match as
    'tailored' / 'base' / 'other' so the studio UI can audit which jobs
    actually got the right resume uploaded.
    """
    rows = (
        db.query(JobUrl, Batch, Profile)
        .join(Batch, JobUrl.batch_id == Batch.id)
        .join(Profile, Batch.profile_id == Profile.id)
        .filter(Profile.id.in_(_accessible_pids(db, user)))
        .filter(JobUrl.url == body.url)
        .all()
    )
    if not rows:
        return {"observed": 0}

    # We may need each profile's base-resume hash for the "uploaded base
    # instead of tailored" case. Cache by profile_id.
    base_hashes: dict[int, Optional[str]] = {}
    def base_sha(profile_id: int) -> Optional[str]:
        if profile_id in base_hashes:
            return base_hashes[profile_id]
        p_path = storage.base_resume_path(profile_id)
        sha = _file_sha256(p_path) if p_path.exists() else None
        base_hashes[profile_id] = sha
        return sha

    observed = 0
    for j, b, p in rows:
        # Decide match category.
        match = "other"
        # Refresh resume_sha256 if missing.
        if not j.resume_sha256 and j.docx_filename:
            path = config.OUTPUTS_DIR / j.docx_filename
            if path.exists():
                j.resume_sha256 = _file_sha256(path)
        if j.resume_sha256 and body.sha256 == j.resume_sha256:
            match = "tailored"
        elif j.pdf_sha256 and body.sha256 == j.pdf_sha256:
            # Uploaded the PDF rendition of the tailored resume — most portals
            # want PDF, so this is the common success case.
            match = "tailored"
        elif base_sha(p.id) and body.sha256 == base_sha(p.id):
            match = "base"
        j.upload_filename = body.filename[:255]
        j.upload_size = body.size
        j.upload_sha256 = body.sha256
        j.upload_match = match
        j.upload_observed_at = datetime.now(timezone.utc)
        observed += 1
    db.commit()
    return {"observed": observed, "match": rows[0][0].upload_match}


def _default_answer_library() -> dict:
    """Empty scaffold returned for users who haven't set any answers yet.
    Keeps the frontend simple — every field is always present."""
    return {
        "personal": {
            "first_name": "", "last_name": "", "email": "", "phone": "",
            "linkedin_url": "", "github_url": "", "portfolio_url": "",
            "address_city": "", "address_state": "", "address_country": "",
            "address_zip": "",
        },
        "professional": {
            "current_company": "", "current_title": "",
            "years_of_experience": "",
        },
        "eligibility": {
            "us_authorized": None,         # True / False / None (unknown)
            "need_sponsorship": None,
            "willing_to_relocate": None,
            "willing_remote": None,
            "salary_expectation": "",
            "preferred_start": "",
        },
        # Optional EEO / voluntary self-identification.
        # String values match the dropdown options on Lever / Greenhouse /
        # Ashby (case-insensitive partial-match in formfill).
        "demographics": {
            "gender": "",                  # "Male" / "Female" / "Non-binary" / "Decline to self-identify"
            "race": "",
            "veteran": "",                 # "I am not a protected veteran" / "I am a protected veteran" / "Decline…"
            "disability": "",              # "No, I do not have a disability" / "Yes…" / "Decline…"
        },
    }


def _merge_answers(stored: dict, incoming: dict) -> dict:
    """Deep-merge incoming over stored, preserving the scaffold shape."""
    out = _default_answer_library()
    for section in out.keys():
        s = (stored or {}).get(section) or {}
        i = (incoming or {}).get(section) or {}
        for k in out[section].keys():
            if k in i:
                out[section][k] = i[k]
            elif k in s:
                out[section][k] = s[k]
    return out


def _load_profile_answers(p: Profile) -> dict:
    raw = (p.answer_library_json or "").strip()
    stored: dict = {}
    if raw:
        try:
            stored = json.loads(raw)
        except (TypeError, ValueError):
            stored = {}
    return _merge_answers(stored, {})


@router.get("/admin/answers")
def api_get_answers(
    profile_id: int,
    db: Session = Depends(get_db),
    me=Depends(auth.require_user),
):
    """Return one profile's standard form-fill answers."""
    p = _user_profile(db, me, profile_id)
    return {"profile_id": p.id, "answers": _load_profile_answers(p)}


class AnswersIn(BaseModel):
    profile_id: int
    answers: dict


@router.post("/admin/answers")
def api_save_answers(
    body: AnswersIn,
    db: Session = Depends(get_db),
    me=Depends(auth.require_user),
):
    """Persist a profile's answer library."""
    p = _user_profile(db, me, body.profile_id)
    raw = (p.answer_library_json or "").strip()
    stored: dict = {}
    if raw:
        try:
            stored = json.loads(raw)
        except (TypeError, ValueError):
            stored = {}
    merged = _merge_answers(stored, body.answers or {})
    p.answer_library_json = json.dumps(merged, ensure_ascii=False)
    db.commit()
    return {"profile_id": p.id, "answers": merged}


@router.get("/extension/answers")
def api_extension_answers(
    profile_id: int,
    db: Session = Depends(get_db),
    me=Depends(auth.require_user),
):
    """Same payload as /admin/answers — namespace alias for the extension."""
    return api_get_answers(profile_id, db, me)


class DraftQuestion(BaseModel):
    id: str
    text: str            # the question text the candidate is being asked
    kind: str = "text"   # "text" | "textarea" | "radio" | "select"
    options: Optional[list[str]] = None  # for radio/select


class DraftAnswersIn(BaseModel):
    url: str
    profile_id: Optional[int] = None
    questions: list[DraftQuestion]


_ANSWER_CACHE_VERSION = "3"   # bumped: post-process strips em/en-dashes


def _answer_cache_path(profile_id: Optional[int], question_text: str, context_hash: str) -> Path:
    import hashlib
    from app import config as app_config
    norm = " ".join((question_text or "").lower().split())
    h = hashlib.sha256()
    h.update(_ANSWER_CACHE_VERSION.encode()); h.update(b"\x00")
    h.update(str(profile_id or 0).encode()); h.update(b"\x00")
    h.update(norm.encode("utf-8")); h.update(b"\x00")
    h.update(context_hash.encode("utf-8"))
    cache_dir = app_config.DATA_DIR / "answer_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{h.hexdigest()}.txt"


def _load_cached_answer(profile_id: Optional[int], question_text: str, context_hash: str) -> Optional[str]:
    p = _answer_cache_path(profile_id, question_text, context_hash)
    if not p.exists():
        return None
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return None


def _save_cached_answer(profile_id: Optional[int], question_text: str, context_hash: str, answer: str) -> None:
    try:
        _answer_cache_path(profile_id, question_text, context_hash).write_text(answer, encoding="utf-8")
    except OSError:
        pass


def _draft_one(client, question: DraftQuestion, context_block: str,
               *, profile_id: Optional[int] = None,
               context_hash: str = "") -> str:
    """Single Claude (Haiku) call for one application question. Disk-cached
    by (profile_id, normalized question text, candidate context hash) so
    repeat questions across applications return instantly."""
    from app import config as app_config

    # Cache check first — many questions repeat verbatim across applications.
    cached = _load_cached_answer(profile_id, question.text, context_hash)
    if cached is not None:
        return cached
    if question.kind in ("radio", "select") and question.options:
        opts_block = "\n".join(f"- {o}" for o in question.options)
        instruction = (
            f"Pick the single most-likely option for this candidate. You MUST pick one — "
            f"never refuse, never say you can't decide. If the candidate context is silent "
            f"on this, pick the most reasonable default (e.g. 'Prefer not to say' for "
            f"demographic questions; the most inclusive option for eligibility questions). "
            f"Output JUST the option text verbatim — no quotes, no explanation."
            f"\n\nOPTIONS:\n{opts_block}"
        )
    else:
        instruction = (
            "Generate the candidate's answer in their first-person voice. "
            "1-3 sentences for short questions, max one short paragraph for "
            "essay questions. Be concrete and specific, drawing on the candidate's "
            "experience profile. You MUST produce an answer - never say 'I can't "
            "answer', 'insufficient information', or anything similar. If a specific "
            "fact isn't in the context, give a reasonable, plausible answer grounded "
            "in the candidate's general experience and motivation. Use plain hyphens "
            "(-) only - never em-dashes or en-dashes. The ONLY hard rule: don't "
            "invent specific metrics, employer names, or product names that aren't "
            "in the context. Output just the answer text - no preamble, no quotes."
        )

    prompt = (
        f"CANDIDATE CONTEXT:\n{context_block}\n\n"
        f"QUESTION:\n{question.text.strip()}\n\n"
        f"{instruction}"
    )
    resp = client.messages.create(
        model=app_config.EXTRACT_MODEL,   # Haiku — fast + cheap
        max_tokens=600,
        temperature=0.3,
        system=[{"type": "text",
                 "text": "You are filling out a job application as the candidate. Always "
                         "produce a usable answer — never refuse, never say 'I can't answer' "
                         "or 'insufficient information'. Be honest, specific, and concise. "
                         "Match the question's register: a Yes/No gets one word, a 'tell us "
                         "about a time' gets a short STAR-style story grounded in the "
                         "candidate's real work. For generic motivation/why-this-role "
                         "questions, infer reasonable framing from the candidate's "
                         "experience profile rather than refusing."}],
        messages=[{"role": "user", "content": prompt}],
    )
    def _extract(resp_obj) -> str:
        return "".join(b.text for b in resp_obj.content if getattr(b, "type", None) == "text").strip()

    out = _extract(resp)
    # One retry if Haiku refused. Cheap and rare.
    refusal_phrases = (
        "i can't answer", "i cannot answer", "i'm unable to",
        "insufficient information", "not enough information",
        "i don't have", "without more information",
    )
    if any(p in out.lower() for p in refusal_phrases):
        retry = client.messages.create(
            model=app_config.EXTRACT_MODEL,
            max_tokens=600,
            temperature=0.5,
            system=[{"type": "text",
                     "text": "You are the candidate, filling in a job application. You "
                             "MUST give a usable answer — never refuse. Use the candidate's "
                             "experience profile as a basis; if a specific fact is missing, "
                             "give a reasonable plausible answer in their voice."}],
            messages=[{"role": "user", "content": prompt + "\n\nNote: your previous reply refused. Try again and produce an actual answer."}],
        )
        retry_out = _extract(retry)
        if retry_out and not any(p in retry_out.lower() for p in refusal_phrases):
            out = retry_out

    # Strip surrounding quote marks if Claude added them
    if len(out) >= 2 and out[0] in ('"', '"', '"', "'") and out[-1] in ('"', '"', '"', "'"):
        out = out[1:-1].strip()
    # Normalize stylized dashes to plain hyphens. Haiku occasionally inserts
    # em-dashes (— U+2014) or en-dashes (– U+2013); the candidate's voice is
    # a plain hyphen.
    out = out.replace("—", "-").replace("–", "-")
    _save_cached_answer(profile_id, question.text, context_hash, out)
    return out


def _build_candidate_context_block(
    db: Session, user, url: str, profile_id_hint: Optional[int],
) -> tuple[str, Optional[int], str]:
    """Pull together every grounding signal we have for the LLM:
       - JD text (if a JobUrl row exists for the URL + profile)
       - Candidate deep profile (from app.profile_extractor cache)
       - Standard answer library (personal + professional + eligibility)

    Returns (context_text, matched_profile_id, identity_hash) where
    identity_hash is a sha of ONLY the candidate-identity parts (deep
    profile + standard answers). Used as the cache key so the same
    question on a different application's JD still hits cache — JD text
    is in the prompt but NOT in the cache key.
    """
    from app.profile_extractor import extract_candidate_profile, profile_summary_text
    from app.similarity import docx_text

    # Find the best-matching JobUrl: prefer the profile_id hint, fall back to
    # most-recent match.
    q = (
        db.query(JobUrl, Batch, Profile)
        .join(Batch, JobUrl.batch_id == Batch.id)
        .join(Profile, Batch.profile_id == Profile.id)
        .filter(Profile.id.in_(_accessible_pids(db, user)))
        .filter(JobUrl.url == url)
    )
    if profile_id_hint is not None:
        q = q.filter(Profile.id == profile_id_hint)
    row = q.order_by(JobUrl.created_at.desc()).first()

    profile: Optional[Profile] = None
    jd_text: str = ""
    job_company: str = ""
    job_title: str = ""
    if row:
        j, _b, p = row
        profile = p
        jd_text = (j.description or "")[:8000]
        job_company = j.company or ""
        job_title = j.title or ""
    elif profile_id_hint is not None:
        profile = db.get(Profile, profile_id_hint)
        if profile and profile.user_id != user.id:
            profile = None

    # Identity parts (stable per profile) go into both the prompt AND the
    # cache-key hash. JD parts go only into the prompt.
    identity_bits: list[str] = []
    jd_bits: list[str] = []

    if job_company or job_title:
        jd_bits.append(f"TARGET ROLE: {job_title} @ {job_company}")
    if jd_text:
        jd_bits.append(f"JOB DESCRIPTION:\n{jd_text}")

    if profile:
        try:
            base = storage.base_resume_path(profile.id)
            if base.exists():
                resume_text = docx_text(base)
                deep = extract_candidate_profile(resume_text)
                summary = profile_summary_text(deep, max_chars=4000)
                if summary:
                    identity_bits.append("CANDIDATE EXPERIENCE PROFILE:\n" + summary)
        except Exception:
            pass

        try:
            ans = _load_profile_answers(profile)
            lines = []
            for section_key, section_label in (
                ("personal", "Personal"),
                ("professional", "Professional"),
                ("eligibility", "Eligibility"),
            ):
                section = ans.get(section_key) or {}
                for k, v in section.items():
                    if v in (None, ""):
                        continue
                    if v is True:
                        v = "Yes"
                    elif v is False:
                        v = "No"
                    pretty = k.replace("_", " ")
                    lines.append(f"  • {pretty}: {v}")
            if lines:
                identity_bits.append("STANDARD ANSWERS:\n" + "\n".join(lines))
        except Exception:
            pass

    # Identity hash: only the parts that are stable per (profile, resume,
    # answer library). Repeat questions across different JDs hit cache.
    import hashlib
    identity_blob = "\n\n".join(identity_bits) or "(no identity context)"
    identity_hash = hashlib.sha256(identity_blob.encode("utf-8")).hexdigest()[:16]

    bits = jd_bits + identity_bits
    return (
        "\n\n".join(bits) or "(no context available)",
        (profile.id if profile else None),
        identity_hash,
    )


@router.post("/extension/draft_answers")
def api_extension_draft_answers(
    body: DraftAnswersIn,
    db: Session = Depends(get_db),
    user=Depends(auth.require_user),
):
    """Draft answers for a list of application-form questions using the
    candidate's deep profile + JD + standard answer library. One Claude
    call per question. Used by the co-worker extension's '✨ Draft' button."""
    from anthropic import Anthropic
    from app import config as app_config
    if not app_config.ANTHROPIC_API_KEY:
        raise HTTPException(500, "ANTHROPIC_API_KEY not configured")
    if not body.questions:
        return {"drafts": [], "profile_id": None}

    context_text, matched_pid, identity_hash = _build_candidate_context_block(
        db, user, body.url, body.profile_id,
    )
    client = Anthropic(api_key=app_config.ANTHROPIC_API_KEY)

    drafts: list[dict] = []
    for q in body.questions:
        try:
            answer = _draft_one(client, q, context_text,
                                profile_id=matched_pid, context_hash=identity_hash)
        except Exception as e:
            drafts.append({"id": q.id, "answer": "", "error": str(e)[:200]})
            continue
        drafts.append({"id": q.id, "answer": answer})

    return {"drafts": drafts, "profile_id": matched_pid}


class ExtensionQueueIn(BaseModel):
    urls: list[str]
    profile_ids: list[int]


@router.post("/extension/queue")
def api_extension_queue(
    body: ExtensionQueueIn,
    db: Session = Depends(get_db),
    user=Depends(auth.require_user),
):
    """One-click batch entry for the browser extension. Accepts a list of
    URLs scraped from the user's open tabs and fans them out to one or more
    profiles. Per-profile result mirrors ``api_create_batch``'s shape."""
    if not body.urls:
        raise HTTPException(400, "No URLs provided.")
    if not body.profile_ids:
        raise HTTPException(400, "Pick at least one profile.")

    results = []
    for pid in body.profile_ids:
        try:
            r = _queue_urls_for_profile(db, user, pid, body.urls)
            # Look up the profile name so the popup can show a useful summary.
            prof = db.get(Profile, pid)
            r["profile_id"] = pid
            r["profile_name"] = prof.name if prof else f"#{pid}"
            results.append(r)
        except HTTPException as e:
            results.append({
                "profile_id": pid,
                "profile_name": "",
                "error": e.detail,
                "added": 0,
            })
    return {"results": results}


@router.get("/admin/batches/{bid}")
def api_batch_detail(
    bid: int,
    db: Session = Depends(get_db),
    me=Depends(auth.require_user),
):
    b = _user_batch(db, me, bid)
    jobs = sorted(b.urls, key=lambda j: j.id)
    return {
        "batch": {"id": b.id, "created_at": _iso(b.created_at)},
        "profile": {"id": b.profile.id, "name": b.profile.name},
        "jobs": [_job_out(j, with_coverage=True) for j in jobs],
        "summary": _batch_summary(jobs),
    }


# ───────────────── team chat ─────────────────

@router.get("/chat/messages")
def api_chat_history(
    limit: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_db),
    me=Depends(auth.require_user),
):
    """Most recent messages (oldest-first) for the shared team group chat.
    Live updates arrive over the /ws/chat WebSocket."""
    rows = (
        db.query(ChatMessage)
        .order_by(ChatMessage.id.desc())
        .limit(limit)
        .all()
    )
    rows.reverse()
    loaded = {m.id: m for m in rows}

    def _reply(rid):
        if not rid:
            return None
        r = loaded.get(rid) or db.get(ChatMessage, rid)
        if r is None:
            return None
        return {"id": r.id, "name": r.sender_name or "member", "body": (r.body or "")[:160]}

    pinned_rows = (
        db.query(ChatMessage).filter(ChatMessage.pinned == True)  # noqa: E712
        .order_by(ChatMessage.id.desc()).all()
    )
    return {
        "me": {"id": me.id, "name": _uname(me), "is_admin": bool(me.is_admin)},
        "gif_enabled": bool(config.GIPHY_API_KEY),
        "messages": [
            {
                "id": m.id, "user_id": m.user_id, "name": m.sender_name or "member",
                "body": m.body, "reply_to": _reply(m.reply_to_id),
                "pinned": bool(m.pinned), "edited_at": _iso(m.edited_at),
                "created_at": _iso(m.created_at),
            }
            for m in rows
        ],
        "pinned": [
            {"id": m.id, "name": m.sender_name or "member", "body": m.body,
             "created_at": _iso(m.created_at)}
            for m in pinned_rows
        ],
    }


@router.get("/chat/gif")
def api_chat_gif(q: str = Query("", max_length=120), me=Depends(auth.require_user)):
    """Proxy Giphy search/trending so the API key stays server-side."""
    if not config.GIPHY_API_KEY:
        raise HTTPException(503, "GIF search is not configured.")
    import requests
    q = q.strip()
    base = "https://api.giphy.com/v1/gifs/" + ("search" if q else "trending")
    params = {"api_key": config.GIPHY_API_KEY, "limit": 24, "rating": "pg-13"}
    if q:
        params["q"] = q
    try:
        r = requests.get(base, params=params, timeout=10)
        data = r.json().get("data", [])
    except Exception as e:
        raise HTTPException(502, f"GIF provider error: {e}")
    out = []
    for g in data:
        imgs = g.get("images", {})
        preview = (imgs.get("fixed_width_small") or imgs.get("fixed_height_small") or {}).get("url")
        full = (imgs.get("downsized_medium") or imgs.get("downsized") or imgs.get("original") or {}).get("url")
        if preview and full:
            out.append({"id": g.get("id"), "preview": preview, "url": full})
    return {"gifs": out}


@router.get("/chat/members")
def api_chat_members(db: Session = Depends(get_db), me=Depends(auth.require_user)):
    """Approved members, for the @mention autocomplete. Includes a synthetic
    'all' entry for mentioning everyone."""
    users = db.query(User).filter(User.approved == True).order_by(User.email).all()  # noqa: E712
    return {"members": [{"id": u.id, "name": _uname(u)} for u in users]}


# ───────────────── members (admin approval) ─────────────────

def _member_out(u: User) -> dict:
    return {
        "id": u.id, "email": u.email, "name": _uname(u),
        "approved": bool(u.approved), "is_admin": bool(u.is_admin),
        "created_at": _iso(u.created_at),
    }


@router.get("/admin/members")
def api_members(db: Session = Depends(get_db), me=Depends(auth.require_admin)):
    users = db.query(User).order_by(User.approved.asc(), User.created_at.desc()).all()
    grant_counts = dict(
        db.query(ProfileAccess.user_id, func.count(ProfileAccess.id))
        .group_by(ProfileAccess.user_id).all()
    )
    owned_counts = dict(
        db.query(Profile.user_id, func.count(Profile.id))
        .group_by(Profile.user_id).all()
    )

    def _pc(u):
        return owned_counts.get(u.id, 0) if u.is_admin else grant_counts.get(u.id, 0)

    return {
        "members": [{**_member_out(u), "profile_count": _pc(u)} for u in users],
        "pending": sum(1 for u in users if not u.approved),
    }


@router.post("/admin/members/{uid}/approve")
def api_member_approve(uid: int, db: Session = Depends(get_db), me=Depends(auth.require_admin)):
    u = db.get(User, uid)
    if u is None:
        raise HTTPException(404, "No such member.")
    u.approved = True
    db.commit()
    return {"member": _member_out(u)}


@router.post("/admin/members/{uid}/reject")
def api_member_reject(uid: int, db: Session = Depends(get_db), me=Depends(auth.require_admin)):
    """Reject (delete) a member account. Can't remove yourself or another admin."""
    u = db.get(User, uid)
    if u is None:
        raise HTTPException(404, "No such member.")
    if u.id == me.id:
        raise HTTPException(400, "You can't remove your own account.")
    if u.is_admin:
        raise HTTPException(400, "Can't remove an admin account.")
    db.delete(u)
    db.commit()
    return {"ok": True}


@router.get("/admin/members/{uid}/profiles")
def api_member_profiles(uid: int, db: Session = Depends(get_db), me=Depends(auth.require_admin)):
    """List the admin's profiles with whether this bidder is assigned to each.
    Toggle via POST /admin/profiles/{pid}/access/{uid}."""
    u = db.get(User, uid)
    if u is None or u.is_admin:
        raise HTTPException(404, "Not a bidder account.")
    granted = {pid for (pid,) in db.query(ProfileAccess.profile_id).filter_by(user_id=uid).all()}
    profs = db.query(Profile).filter_by(user_id=me.id).order_by(Profile.created_at.desc()).all()
    return {"profiles": [
        {"id": p.id, "name": p.name, "has_access": p.id in granted} for p in profs
    ]}


# ───────────────── job actions ─────────────────

class ManualJDIn(BaseModel):
    description: str = Field(..., min_length=10)
    company: Optional[str] = None
    title: Optional[str] = None
    location: Optional[str] = None


@router.post("/admin/batches/{bid}/jobs/{jid}/manual")
def api_manual_jd(
    bid: int, jid: int, body: ManualJDIn,
    db: Session = Depends(get_db),
    me=Depends(auth.require_user),
):
    """Accept a manually-pasted JD. If the user didn't fill company/title/
    location, ask Haiku to extract them from the text — same UX as a scraped
    job so the row in the table is never blank metadata.
    """
    j = _user_job(db, me, bid, jid)
    j.description = body.description

    user_company  = (body.company  or "").strip()
    user_title    = (body.title    or "").strip()
    user_location = (body.location or "").strip()

    needs_extract = not (user_company and user_title)
    if needs_extract:
        from app.tailoring import extract_job_info_from_text
        extracted = extract_job_info_from_text(body.description)
    else:
        extracted = {"company": "", "title": "", "location": ""}

    # User-provided values win over Haiku-extracted ones.
    j.company  = user_company  or extracted["company"]  or j.company
    j.title    = user_title    or extracted["title"]    or j.title
    j.location = user_location or extracted["location"] or j.location

    j.status = "pending"
    j.error_message = None
    db.commit()
    pipeline.enqueue(j.id)
    return {"job": _job_out(j)}


@router.post("/admin/batches/{bid}/jobs/{jid}/retry")
def api_retry_job(
    bid: int, jid: int,
    db: Session = Depends(get_db),
    me=Depends(auth.require_user),
):
    j = _user_job(db, me, bid, jid)
    j.status = "pending"
    j.error_message = None
    db.commit()
    pipeline.enqueue(j.id)
    return {"job": _job_out(j)}


class ClaimIn(BaseModel):
    terms: list[str]


@router.post("/admin/batches/{bid}/jobs/{jid}/claim")
def api_claim_terms(
    bid: int, jid: int, body: ClaimIn,
    db: Session = Depends(get_db),
    me=Depends(auth.require_user),
):
    j = _user_job(db, me, bid, jid)
    if j.status not in (STATUS_DONE, STATUS_ERROR):
        raise HTTPException(400, f"Cannot edit job in status '{j.status}'.")
    cleaned = sorted({t.strip() for t in (body.terms or []) if t and t.strip()})
    j.claimed_terms = json.dumps(cleaned) if cleaned else None
    j.status = "pending"
    j.error_message = None
    db.commit()
    pipeline.enqueue(j.id)
    return {"job": _job_out(j)}


class AppStatusIn(BaseModel):
    # Frontend posts `status` (admin codebase shape) — keep `application_status`
    # as an alias so manual API users can use either name.
    status: Optional[str] = None
    application_status: Optional[str] = None
    note: Optional[str] = None


@router.post("/batches/{bid}/jobs/{jid}/app-status")
def api_app_status(
    bid: int, jid: int, body: AppStatusIn,
    db: Session = Depends(get_db),
    me=Depends(auth.require_user),
):
    new_status = body.status or body.application_status
    if not new_status:
        raise HTTPException(400, "Missing 'status' field.")
    if new_status not in APP_STATUSES:
        raise HTTPException(400, f"Invalid status '{new_status}'.")
    j = _user_job(db, me, bid, jid)
    prev_status = j.application_status
    j.application_status = new_status
    if new_status == "applied":
        # Count this as a new application attempt every time the user
        # transitions into "applied" — even from another non-yet state.
        # (Within-applied bumps go through /reapply.)
        if prev_status != "applied":
            j.apply_count = (j.apply_count or 0) + 1
            j.applied_at = datetime.now(timezone.utc)
            j.application_source = "manual"
    if new_status in ("not_yet", "error", "not_remote", "unavailable"):
        j.applied_at = None
        j.application_source = None
    if body.note is not None:
        j.application_note = body.note.strip() or None
    db.commit()
    return {"job": _job_out(j)}


@router.post("/admin/batches/{bid}/jobs/{jid}/reapply")
def api_reapply(
    bid: int, jid: int,
    db: Session = Depends(get_db),
    me=Depends(auth.require_user),
):
    """Record an additional application attempt for a job. Use this when a
    job has been reposted and the co-worker is applying again. Always bumps
    apply_count and resets applied_at to now()."""
    j = _user_job(db, me, bid, jid)
    j.application_status = "applied"
    j.apply_count = (j.apply_count or 0) + 1
    j.applied_at = datetime.now(timezone.utc)
    j.application_source = "manual"
    db.commit()
    return {"job": _job_out(j)}


class NoteIn(BaseModel):
    text: str


@router.post("/admin/batches/{bid}/jobs/{jid}/note")
def api_save_note(
    bid: int, jid: int, body: NoteIn,
    db: Session = Depends(get_db),
    me=Depends(auth.require_user),
):
    """Save the collaboration note for a job. Touches note_updated_at so
    the unread badge fires for the other viewer until they open the note."""
    j = _user_job(db, me, bid, jid)
    text = (body.text or "").strip()
    j.note = text or None
    j.note_updated_at = datetime.now(timezone.utc) if text else None
    if text:
        # A new/edited note records its author and re-opens it (unconfirmed).
        j.note_by = _uname(me)
        j.note_confirmed_at = None
        j.note_confirmed_by = None
    else:
        # Clearing the note resets all its metadata.
        j.note_seen_at = None
        j.note_by = None
        j.note_confirmed_at = None
        j.note_confirmed_by = None
    db.commit()
    return {"job": _job_out(j)}


@router.post("/admin/batches/{bid}/jobs/{jid}/note/confirm")
def api_confirm_note(
    bid: int, jid: int,
    db: Session = Depends(get_db),
    me=Depends(auth.require_user),
):
    """Mark a note as confirmed (acknowledged/resolved) — it leaves the open
    feedback queue. Set confirmed=false in the body to re-open it."""
    j = _user_job(db, me, bid, jid)
    if j.note_confirmed_at is None:
        j.note_confirmed_at = datetime.now(timezone.utc)
        j.note_confirmed_by = _uname(me)
    else:
        j.note_confirmed_at = None
        j.note_confirmed_by = None
    db.commit()
    return {"job": _job_out(j)}


@router.post("/admin/batches/{bid}/jobs/{jid}/note/seen")
def api_mark_note_seen(
    bid: int, jid: int,
    db: Session = Depends(get_db),
    me=Depends(auth.require_user),
):
    """Mark the collaboration note as read by stamping note_seen_at = now()."""
    j = _user_job(db, me, bid, jid)
    j.note_seen_at = datetime.now(timezone.utc)
    db.commit()
    return {"job": _job_out(j)}


@router.get("/admin/notes/unread")
def api_unread_notes(
    db: Session = Depends(get_db),
    me=Depends(auth.require_user),
):
    """Open feedback notes across the user's profiles — notes that exist and
    haven't been confirmed yet. Powers the sidebar feedback queue (each item is
    clickable to the job, shows its author, and can be confirmed)."""
    rows = (
        db.query(JobUrl, Batch, Profile)
        .join(Batch, JobUrl.batch_id == Batch.id)
        .join(Profile, Batch.profile_id == Profile.id)
        .filter(Profile.id.in_(_accessible_pids(db, me)))
        .filter(JobUrl.note.isnot(None))
        .filter(JobUrl.note_confirmed_at.is_(None))
        .order_by(JobUrl.note_updated_at.desc())
        .all()
    )
    samples = []
    for (j, b, p) in rows:
        if not j.note or not j.note.strip():
            continue
        unread = j.note_seen_at is None or (j.note_updated_at and j.note_updated_at > j.note_seen_at)
        samples.append({
            "job_id": j.id, "batch_id": b.id,
            "profile_id": p.id, "profile_name": p.name,
            "company": j.company, "title": j.title,
            "note": j.note[:300],
            "note_by": j.note_by,
            "updated_at": _iso(j.note_updated_at),
            "unread": bool(unread),
        })
    return {"count": len(samples), "samples": samples}


@router.post("/admin/batches/{bid}/retry-errors")
def api_retry_errors(
    bid: int,
    db: Session = Depends(get_db),
    me=Depends(auth.require_user),
):
    """Re-queue every job in this batch whose status is 'error' or
    'needs_manual_jd'. Frontend's "Retry N errors" button hits this."""
    b = _user_batch(db, me, bid)
    requeued = 0
    for j in b.urls:
        if j.status in ("error", "needs_manual_jd"):
            j.status = "pending"
            j.error_message = None
            requeued += 1
    db.commit()
    for j in b.urls:
        if j.status == "pending":
            pipeline.enqueue(j.id)
    return {"requeued": requeued}


# ───────────────── personal calendar (interview panels) ─────────────────

class CalendarEventIn(BaseModel):
    title: str
    start_at: str       # ISO 8601
    end_at: str
    color: Optional[str] = "indigo"
    notes: Optional[str] = None
    job_url_id: Optional[int] = None
    profile_ids: Optional[list[int]] = None
    status: Optional[str] = None   # pending / passed / failed


_PALETTE = {"indigo", "emerald", "amber", "rose", "violet", "sky", "fuchsia"}
_EV_STATUSES = {"pending", "passed", "failed"}


def _ev_out(e: CalendarEvent) -> dict:
    try:
        profile_ids = json.loads(e.profile_ids_json) if e.profile_ids_json else []
        if not isinstance(profile_ids, list):
            profile_ids = []
    except (TypeError, ValueError):
        profile_ids = []
    return {
        "id": e.id, "title": e.title,
        "start_at": _iso(e.start_at), "end_at": _iso(e.end_at),
        "color": e.color, "notes": e.notes,
        "job_url_id": e.job_url_id,
        "profile_ids": [int(p) for p in profile_ids if isinstance(p, int)],
        "status": e.status or "pending",
    }


def _validate_profile_ids(db: Session, user, ids: Optional[list[int]]) -> list[int]:
    """Filter incoming profile_ids to ones the user actually owns. Silently
    drops invalid ids rather than 400ing — the frontend shouldn't be sending
    them in the first place."""
    if not ids:
        return []
    rows = (
        db.query(Profile.id)
        .filter(Profile.id.in_(_accessible_pids(db, user)))
        .filter(Profile.id.in_(ids))
        .all()
    )
    valid = {pid for (pid,) in rows}
    return [pid for pid in ids if pid in valid]


def _parse_iso(s: str) -> datetime:
    s = (s or "").strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


@router.get("/admin/calendar-events")
def api_list_events(
    from_at: str = Query(..., alias="from"),
    to_at:   str = Query(..., alias="to"),
    db: Session = Depends(get_db),
    me=Depends(auth.require_user),
):
    """Return events whose [start_at, end_at) overlap the [from, to) range."""
    try:
        f = _parse_iso(from_at)
        t = _parse_iso(to_at)
    except (TypeError, ValueError):
        raise HTTPException(400, "Invalid from/to (must be ISO 8601).")
    rows = (
        db.query(CalendarEvent)
        .filter(CalendarEvent.user_id == me.id)
        .filter(CalendarEvent.start_at < t)
        .filter(CalendarEvent.end_at > f)
        .order_by(CalendarEvent.start_at.asc())
        .all()
    )
    return {"events": [_ev_out(e) for e in rows]}


@router.post("/admin/calendar-events")
def api_create_event(
    body: CalendarEventIn,
    db: Session = Depends(get_db),
    me=Depends(auth.require_user),
):
    title = (body.title or "").strip()
    if not title:
        raise HTTPException(400, "Title is required.")
    try:
        s = _parse_iso(body.start_at)
        e = _parse_iso(body.end_at)
    except (TypeError, ValueError):
        raise HTTPException(400, "Invalid start_at / end_at (must be ISO 8601).")
    if e <= s:
        raise HTTPException(400, "end_at must be after start_at.")
    color = body.color if body.color in _PALETTE else "indigo"
    profile_ids = _validate_profile_ids(db, me, body.profile_ids)
    status = body.status if body.status in _EV_STATUSES else "pending"
    ev = CalendarEvent(
        user_id=me.id, title=title[:255],
        start_at=s, end_at=e, color=color,
        notes=(body.notes.strip() if body.notes and body.notes.strip() else None),
        job_url_id=body.job_url_id,
        profile_ids_json=json.dumps(profile_ids) if profile_ids else None,
        status=status,
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return {"event": _ev_out(ev)}


@router.post("/admin/calendar-events/{eid}/update")
def api_update_event(
    eid: int, body: CalendarEventIn,
    db: Session = Depends(get_db),
    me=Depends(auth.require_user),
):
    ev = db.get(CalendarEvent, eid)
    if not ev or ev.user_id != me.id:
        raise HTTPException(404, "Event not found.")
    title = (body.title or "").strip()
    if not title:
        raise HTTPException(400, "Title is required.")
    try:
        s = _parse_iso(body.start_at)
        e = _parse_iso(body.end_at)
    except (TypeError, ValueError):
        raise HTTPException(400, "Invalid start_at / end_at.")
    if e <= s:
        raise HTTPException(400, "end_at must be after start_at.")
    ev.title = title[:255]
    ev.start_at = s
    ev.end_at = e
    ev.color = body.color if body.color in _PALETTE else ev.color
    ev.notes = (body.notes.strip() if body.notes and body.notes.strip() else None)
    ev.job_url_id = body.job_url_id
    profile_ids = _validate_profile_ids(db, me, body.profile_ids)
    ev.profile_ids_json = json.dumps(profile_ids) if profile_ids else None
    if body.status in _EV_STATUSES:
        ev.status = body.status
    db.commit()
    return {"event": _ev_out(ev)}


@router.post("/admin/calendar-events/{eid}/delete")
def api_delete_event(
    eid: int,
    db: Session = Depends(get_db),
    me=Depends(auth.require_user),
):
    ev = db.get(CalendarEvent, eid)
    if not ev or ev.user_id != me.id:
        raise HTTPException(404, "Event not found.")
    db.delete(ev)
    db.commit()
    return {"ok": True}


# ───────────────── search (existing) ─────────────────

@router.get("/admin/search")
def api_search(
    q: str = Query(..., min_length=1, max_length=200),
    status: Optional[str] = Query(None),
    work_type: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    me=Depends(auth.require_user),
):
    """Substring search across every job in every batch. Matches against
    company, title, URL, location, and description (case-insensitive).
    Results include the parent batch + profile so the UI can link out.
    Scoped to the current user's profiles only.
    """
    like = f"%{q.strip().lower()}%"
    query = (
        db.query(JobUrl, Batch, Profile)
        .join(Batch, JobUrl.batch_id == Batch.id)
        .join(Profile, Batch.profile_id == Profile.id)
        .filter(Profile.id.in_(_accessible_pids(db, me)))
        .filter(or_(
            func.lower(func.coalesce(JobUrl.company, "")).like(like),
            func.lower(func.coalesce(JobUrl.title, "")).like(like),
            func.lower(JobUrl.url).like(like),
            func.lower(func.coalesce(JobUrl.location, "")).like(like),
            func.lower(func.coalesce(JobUrl.description, "")).like(like),
        ))
    )
    if status:
        query = query.filter(JobUrl.status == status)
    if work_type:
        if work_type == "unknown":
            query = query.filter(JobUrl.work_type.is_(None))
        elif work_type in ("remote", "hybrid", "onsite"):
            query = query.filter(JobUrl.work_type == work_type)
    rows = query.order_by(JobUrl.created_at.desc()).limit(limit).all()
    return {
        "query": q,
        "count": len(rows),
        "results": [
            {
                "job": _job_out(j),
                "batch": {"id": b.id, "created_at": _iso(b.created_at)},
                "profile": {"id": p.id, "name": p.name},
            }
            for (j, b, p) in rows
        ],
    }


@router.get("/admin/calendar")
def api_calendar(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    me=Depends(auth.require_user),
):
    today = _today_pst()
    y = year or today.year
    m = month or today.month

    first = date(y, m, 1)
    next_m = date(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 1)
    days_in_month = (next_m - first).days

    # Pad to start on Sunday (US convention).
    pad_before = (first.weekday() + 1) % 7  # Mon=0 -> Sunday=6
    grid_start = first - timedelta(days=pad_before)
    cells = []
    d = grid_start
    while d < grid_start + timedelta(days=42):
        cells.append(d)
        d += timedelta(days=1)

    # Pull all batches for the month range in one query — current user only.
    range_start = datetime.combine(grid_start, datetime.min.time(), tzinfo=timezone.utc)
    range_end = datetime.combine(grid_start + timedelta(days=42), datetime.min.time(), tzinfo=timezone.utc)
    batches = (
        db.query(Batch)
        .join(Profile, Batch.profile_id == Profile.id)
        .filter(
            Profile.id.in_(_accessible_pids(db, me)),
            Batch.created_at >= range_start,
            Batch.created_at < range_end,
        ).all()
    )
    by_day: dict[date, list[Batch]] = {}
    for b in batches:
        d = (b.created_at - timedelta(hours=8)).date()
        by_day.setdefault(d, []).append(b)

    weeks = []
    for w in range(6):
        row = []
        for i in range(7):
            d = cells[w * 7 + i]
            day_batches = by_day.get(d, [])
            cell_batches = []
            day_applied = day_tailored = day_total = 0
            for b in day_batches:
                jobs = list(b.urls)
                done = sum(1 for j in jobs if j.status == STATUS_DONE)
                applied = sum(1 for j in jobs if j.application_status == "applied")
                cell_batches.append({
                    "id": b.id,
                    "profile_id": b.profile_id,
                    "profile_name": b.profile.name,
                    "url_count": len(jobs),
                    "done": done,
                    "applied": applied,
                })
                day_total += len(jobs); day_tailored += done; day_applied += applied
            row.append({
                "date": d.isoformat(),
                "day": d.day,
                "in_month": d.month == m,
                "is_today": d == today,
                "batches": cell_batches,
                "totals": {
                    "applied": day_applied, "tailored": day_tailored,
                    "percent": round(100 * day_applied / day_tailored)
                                if day_tailored else 0,
                },
            })
        weeks.append(row)

    return {
        "year": y, "month": m,
        "month_name": first.strftime("%B"),
        "weeks": weeks,
        "today": today.isoformat(),
        "prev": {"year": y - 1 if m == 1 else y, "month": 12 if m == 1 else m - 1},
        "next": {"year": y + 1 if m == 12 else y, "month": 1 if m == 12 else m + 1},
    }


# ── Super-admin endpoints ─────────────────────────────────────────────────
# Platform-wide visibility for users marked User.is_admin=1. The regular
# /api/admin/* endpoints scope to the logged-in user's own data; these
# /api/superadmin/* endpoints cross that boundary.

@router.get("/superadmin/users")
def api_superadmin_users(
    db: Session = Depends(get_db),
    me=Depends(auth.require_admin),
):
    """Return every user on the platform with quick activity counts."""
    users = db.query(User).order_by(User.created_at.desc()).all()
    out: list[dict] = []
    for u in users:
        prof_count = db.query(Profile).filter(Profile.user_id == u.id).count()
        # Total jobs across all profiles this user owns.
        job_count = (
            db.query(JobUrl)
            .join(Batch, JobUrl.batch_id == Batch.id)
            .join(Profile, Batch.profile_id == Profile.id)
            .filter(Profile.user_id == u.id)
            .count()
        )
        applied_count = (
            db.query(JobUrl)
            .join(Batch, JobUrl.batch_id == Batch.id)
            .join(Profile, Batch.profile_id == Profile.id)
            .filter(Profile.user_id == u.id)
            .filter(JobUrl.application_status == "applied")
            .count()
        )
        out.append({
            "id": u.id,
            "email": u.email,
            "is_admin": bool(u.is_admin),
            "created_at": _iso(u.created_at),
            "profile_count": prof_count,
            "job_count": job_count,
            "applied_count": applied_count,
        })
    return {"users": out}


@router.get("/superadmin/users/{uid}")
def api_superadmin_user_detail(
    uid: int,
    db: Session = Depends(get_db),
    me=Depends(auth.require_admin),
):
    """All profiles + batches + status breakdown for one user."""
    u = db.get(User, uid)
    if u is None:
        raise HTTPException(404, "No such user.")
    profiles = db.query(Profile).filter(Profile.user_id == u.id).order_by(Profile.created_at.desc()).all()
    profile_blocks: list[dict] = []
    for p in profiles:
        batches = (
            db.query(Batch)
            .filter(Batch.profile_id == p.id)
            .order_by(Batch.created_at.desc())
            .limit(50)
            .all()
        )
        batch_blocks: list[dict] = []
        for b in batches:
            total = db.query(JobUrl).filter(JobUrl.batch_id == b.id).count()
            done = db.query(JobUrl).filter(JobUrl.batch_id == b.id, JobUrl.status == STATUS_DONE).count()
            applied = db.query(JobUrl).filter(
                JobUrl.batch_id == b.id, JobUrl.application_status == "applied"
            ).count()
            batch_blocks.append({
                "id": b.id, "created_at": _iso(b.created_at),
                "total": total, "done": done, "applied": applied,
            })
        profile_blocks.append({
            "id": p.id, "name": p.name, "has_base_resume": bool(p.base_resume_filename),
            "created_at": _iso(p.created_at),
            "batches": batch_blocks,
        })
    return {
        "user": {
            "id": u.id, "email": u.email, "is_admin": bool(u.is_admin),
            "created_at": _iso(u.created_at),
        },
        "profiles": profile_blocks,
    }

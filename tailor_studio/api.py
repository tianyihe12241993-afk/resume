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

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from . import auth, config, pipeline, storage
from .db import (
    Batch, JobUrl, Profile, get_db,
    APP_STATUSES, STATUS_DONE, STATUS_ERROR, STATUS_NEEDS_JD,
)


# Public router: /api/login, /api/signup, /api/logout, /api/me — no auth dep.
public_router = APIRouter(prefix="/api")
# Protected router: every other endpoint requires a valid session.
# We DON'T put auth.require_user in `dependencies=` because each handler
# wants the User object (via Depends(auth.require_user)) and adding it as a
# router-level dep too would invoke it twice.
router = APIRouter(prefix="/api")


def _user_profile(db: Session, user, pid: int) -> Profile:
    """Look up a profile and verify it belongs to `user`. 404 otherwise."""
    p = db.get(Profile, pid)
    if p is None or p.user_id != user.id:
        raise HTTPException(404, "Not found.")
    return p


def _user_batch(db: Session, user, bid: int) -> Batch:
    """Look up a batch and verify it belongs to one of `user`'s profiles."""
    b = db.get(Batch, bid)
    if b is None:
        raise HTTPException(404, "Not found.")
    profile = db.get(Profile, b.profile_id)
    if profile is None or profile.user_id != user.id:
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
    user = auth.create_user(db, body.email, body.password)
    auth.issue_session(response, user.id)
    return {"ok": True, "email": user.email, "id": user.id}


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


@public_router.get("/me")
def api_me(request: Request):
    user = auth.current_user(request)
    if user is None:
        raise HTTPException(401, "Not authenticated.")
    return {
        "id": user.id,
        "email": user.email,
        "name": user.email.split("@")[0],
        "role": "user",
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
        "description": j.description,
        "error_message": j.error_message,
        "application_status": j.application_status,
        "applied_at": _iso(j.applied_at),
        "application_note": j.application_note,
        "application_source": j.application_source,
        "has_docx": bool(j.docx_filename),
        "download_count": j.download_count,
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
    profiles = (
        db.query(Profile)
        .filter(Profile.user_id == user.id)
        .order_by(Profile.created_at.asc())
        .all()
    )
    today = _today_pst()
    today_start = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=8)
    today_end = today_start + timedelta(days=1)

    profile_statuses = []
    agg_jobs: list[JobUrl] = []
    trend_dates = [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    agg_trend = [0] * 7

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
        summary = _batch_summary(today_jobs)

        # 7-day applied trend (per-profile)
        trend = [0] * 7
        rows = (
            db.query(JobUrl)
            .join(Batch, JobUrl.batch_id == Batch.id)
            .filter(
                Batch.profile_id == p.id,
                JobUrl.applied_at != None,  # noqa: E711
                JobUrl.applied_at >= today_start - timedelta(days=6),
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

        profile_statuses.append({
            "profile": {
                "id": p.id,
                "name": p.name,
                "has_base_resume": bool(p.base_resume_filename)
                                    and storage.base_resume_path(p.id).exists(),
            },
            "today_batch": {"id": today_batch.id, "created_at": _iso(today_batch.created_at)}
                            if today_batch else None,
            "summary": summary,
            "trend": trend,
        })

    return {
        "now_pst": _iso(datetime.now(timezone.utc)),
        "today": today.isoformat(),
        "profile_statuses": profile_statuses,
        "agg": _batch_summary(agg_jobs),
        "agg_trend": agg_trend,
        "trend_dates": trend_dates,
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
    rows = (
        db.query(Profile)
        .filter(Profile.user_id == user.id)
        .order_by(Profile.created_at.desc())
        .all()
    )
    return {"profiles": [_profile_out(p) for p in rows]}


class ProfileCreateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


@router.post("/admin/profiles")
def api_create_profile(
    body: ProfileCreateIn,
    db: Session = Depends(get_db),
    user=Depends(auth.require_user),
):
    p = Profile(name=body.name.strip(), user_id=user.id)
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


@router.post("/admin/profiles/{pid}/resume")
async def api_upload_resume(
    pid: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user=Depends(auth.require_user),
):
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
    p = _user_profile(db, user, body.profile_id)
    if not storage.base_resume_path(p.id).exists():
        raise HTTPException(400, "Upload a base resume for this profile first.")

    raw_urls = [
        u.strip() for u in (body.urls or "").splitlines()
        if u.strip() and (u.startswith("http://") or u.startswith("https://"))
    ]
    if not raw_urls:
        raise HTTPException(400, "No valid URLs provided.")
    seen: set[str] = set()
    cleaned = []
    for u in raw_urls:
        if u in seen:
            continue
        seen.add(u); cleaned.append(u)
    if len(cleaned) > config.MAX_URLS_PER_BATCH:
        raise HTTPException(
            400, f"Too many URLs ({len(cleaned)}). Max {config.MAX_URLS_PER_BATCH}."
        )

    # Skip any URL that already exists for this profile in ANY status —
    # pending, in-flight, done, error, needs_manual_jd. The user can use the
    # row-level Retry / Fix-JD buttons to act on existing rows; submitting
    # the same URL again should not create a duplicate JobUrl.
    existing_by_status: dict[str, set[str]] = {}
    rows = (
        db.query(JobUrl.url, JobUrl.status)
        .join(Batch, JobUrl.batch_id == Batch.id)
        .filter(
            Batch.profile_id == p.id,
            JobUrl.url.in_(cleaned),
        )
        .all()
    )
    existing_urls: set[str] = set()
    for url_value, status_value in rows:
        existing_urls.add(url_value)
        existing_by_status.setdefault(status_value, set()).add(url_value)
    todo_urls = [u for u in cleaned if u not in existing_urls]
    if not todo_urls:
        # Build a small message that distinguishes "already tailored" from
        # other states so the user understands why nothing was queued.
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
    }


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
    j.application_status = new_status
    if new_status == "applied" and not j.applied_at:
        j.applied_at = datetime.now(timezone.utc)
        j.application_source = "manual"
    if new_status in ("not_yet", "error", "not_remote"):
        j.applied_at = None
        j.application_source = None
    if body.note is not None:
        j.application_note = body.note.strip() or None
    db.commit()
    return {"job": _job_out(j)}


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


# ───────────────── calendar (light) ─────────────────

@router.get("/admin/search")
def api_search(
    q: str = Query(..., min_length=1, max_length=200),
    status: Optional[str] = Query(None),
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
        .filter(Profile.user_id == me.id)
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
            Profile.user_id == me.id,
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

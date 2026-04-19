"""FastAPI application: auth + admin + bidder routes."""
from __future__ import annotations

import calendar as _calendar
import io
import sys
import zipfile
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import (
    Depends, FastAPI, File, Form, HTTPException, Request, UploadFile,
)
from fastapi.responses import (
    FileResponse, HTMLResponse, RedirectResponse, StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

PACIFIC = ZoneInfo("America/Los_Angeles")

from . import auth, config, pipeline, storage
from .db import SessionLocal, get_db, init_db
from .models import (
    APP_STATUSES,
    STATUS_DONE,
    STATUS_NEEDS_JD,
    STATUS_PENDING,
    Batch,
    JobUrl,
    Profile,
    ProfileAccess,
    User,
)

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _to_pacific(value: Optional[datetime]) -> Optional[datetime]:
    if not value:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(PACIFIC)


def _format_dt(value: Optional[datetime]) -> str:
    pst = _to_pacific(value)
    if not pst:
        return ""
    return pst.strftime("%Y-%m-%d %H:%M %Z")


def _format_date(value: Optional[datetime]) -> str:
    pst = _to_pacific(value)
    return pst.strftime("%Y-%m-%d") if pst else ""


def _format_time(value: Optional[datetime]) -> str:
    pst = _to_pacific(value)
    return pst.strftime("%H:%M") if pst else ""


TEMPLATES.env.filters["dt"] = _format_dt
TEMPLATES.env.filters["d"] = _format_date
TEMPLATES.env.filters["hm"] = _format_time


app = FastAPI(title="resume-maker")
app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).parent / "static")),
    name="static",
)


@app.on_event("startup")
def _startup() -> None:
    init_db()
    db = SessionLocal()
    try:
        auth.ensure_admin_seeded(db)
    finally:
        db.close()


# --------------------------------------------------------------------------
# Template helpers
# --------------------------------------------------------------------------

def render(request: Request, name: str, **ctx) -> HTMLResponse:
    ctx.setdefault("user", None)
    return TEMPLATES.TemplateResponse(request, name, ctx)


def user_or_none(request: Request) -> Optional[User]:
    db = SessionLocal()
    try:
        return auth.current_user(request, db)
    finally:
        db.close()


# --------------------------------------------------------------------------
# Landing + login
# --------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    u = user_or_none(request)
    if u is None:
        return RedirectResponse("/login", status_code=302)
    return RedirectResponse("/admin" if u.role == "admin" else "/my", status_code=302)


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = "/", error: str = ""):
    return render(request, "login.html", next_url=next, error=error)


@app.post("/login")
def login_submit(
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
    db: Session = Depends(get_db),
):
    email = email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if user is None or not auth.verify_password(password, user.password_hash):
        return RedirectResponse(
            f"/login?error=Invalid+email+or+password&next={next}", status_code=303
        )
    dest = next if next and next.startswith("/") else (
        "/admin" if user.role == "admin" else "/my"
    )
    resp = RedirectResponse(dest, status_code=303)
    auth.set_session(resp, user.id)
    return resp


@app.get("/setup", response_class=HTMLResponse)
def setup_form(
    request: Request,
    token: str = "",
    error: str = "",
    db: Session = Depends(get_db),
):
    user = auth.peek_invite_token(db, token) if token else None
    if user is None:
        return render(
            request, "setup.html",
            token="", user_email="", error="Invite link is invalid or expired.",
        )
    return render(
        request, "setup.html",
        token=token, user_email=user.email, error=error,
    )


@app.post("/setup")
def setup_submit(
    token: str = Form(...),
    password: str = Form(...),
    confirm: str = Form(...),
    db: Session = Depends(get_db),
):
    if len(password) < 8:
        return RedirectResponse(
            f"/setup?token={token}&error=Password+must+be+at+least+8+characters",
            status_code=303,
        )
    if password != confirm:
        return RedirectResponse(
            f"/setup?token={token}&error=Passwords+do+not+match",
            status_code=303,
        )
    user = auth.consume_invite_token(db, token)
    if user is None:
        return RedirectResponse("/login?error=Invite+link+invalid+or+expired", status_code=303)
    user.password_hash = auth.hash_password(password)
    db.commit()
    dest = "/admin" if user.role == "admin" else "/my"
    resp = RedirectResponse(dest, status_code=303)
    auth.set_session(resp, user.id)
    return resp


@app.get("/change-password", response_class=HTMLResponse)
def change_password_form(
    request: Request,
    error: str = "",
    ok: str = "",
    user: User = Depends(auth.require_user),
):
    return render(
        request, "change_password.html",
        user=user, error=error, ok=ok,
    )


@app.post("/change-password")
def change_password_submit(
    current: str = Form(...),
    password: str = Form(...),
    confirm: str = Form(...),
    user: User = Depends(auth.require_user),
    db: Session = Depends(get_db),
):
    if not auth.verify_password(current, user.password_hash):
        return RedirectResponse(
            "/change-password?error=Current+password+is+wrong", status_code=303
        )
    if len(password) < 8:
        return RedirectResponse(
            "/change-password?error=New+password+must+be+at+least+8+characters",
            status_code=303,
        )
    if password != confirm:
        return RedirectResponse(
            "/change-password?error=Passwords+do+not+match", status_code=303
        )
    user.password_hash = auth.hash_password(password)
    db.commit()
    return RedirectResponse("/change-password?ok=1", status_code=303)


@app.post("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    auth.clear_session(resp)
    return resp


# --------------------------------------------------------------------------
# Admin: profiles
# --------------------------------------------------------------------------

@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(
    request: Request,
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    """Today-focused dashboard: what happened today + where to act."""
    now_pst = datetime.now(PACIFIC)
    today = now_pst.date()
    start_of_day_utc = (
        datetime.combine(today, datetime.min.time(), tzinfo=PACIFIC)
        .astimezone(timezone.utc).replace(tzinfo=None)
    )
    end_of_day_utc = (
        datetime.combine(today, datetime.max.time(), tzinfo=PACIFIC)
        .astimezone(timezone.utc).replace(tzinfo=None)
    )
    todays_batches = (
        db.query(Batch)
        .filter(
            Batch.created_at >= start_of_day_utc,
            Batch.created_at <= end_of_day_utc,
        )
        .order_by(Batch.created_at.desc())
        .all()
    )
    # Per-batch summaries
    batch_infos = []
    agg_total = agg_done = agg_applied = agg_in_flight = agg_needs = agg_err = 0
    for b in todays_batches:
        jobs = b.urls
        s = _batch_summary(jobs)
        batch_infos.append({"batch": b, "summary": s})
        agg_total += s["total"]
        agg_done += s["done"]
        agg_applied += s["applied"]
        agg_in_flight += s["in_flight"]
        agg_needs += s["needs_jd"]
        agg_err += s["errors"]
    agg = {
        "total": agg_total,
        "done": agg_done,
        "applied": agg_applied,
        "in_flight": agg_in_flight,
        "needs_jd": agg_needs,
        "errors": agg_err,
        "percent": int(round(100 * agg_done / agg_total)) if agg_total else 0,
        "applied_percent": (
            int(round(100 * agg_applied / agg_done)) if agg_done else 0
        ),
    }
    profiles = db.query(Profile).order_by(Profile.name.asc()).all()
    ready_profiles = [
        p for p in profiles if storage.base_resume_path(p.id).exists()
    ]
    return render(
        request, "admin_dashboard.html",
        user=admin,
        today=today, now_pst=now_pst,
        batch_infos=batch_infos, agg=agg,
        ready_profiles=ready_profiles, all_profiles=profiles,
        nav_active="dashboard",
    )


@app.get("/admin/profiles", response_class=HTMLResponse)
def admin_profiles_list(
    request: Request,
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    profiles = db.query(Profile).order_by(Profile.created_at.desc()).all()
    return render(
        request, "admin_profiles.html",
        user=admin, profiles=profiles,
        nav_active="profiles",
    )


@app.post("/admin/profiles")
def admin_profiles_create(
    name: str = Form(...),
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    p = Profile(owner_user_id=admin.id, name=name.strip() or "Untitled")
    db.add(p)
    db.commit()
    return RedirectResponse(f"/admin/profiles/{p.id}", status_code=303)


@app.get("/admin/profiles/{pid}", response_class=HTMLResponse)
def admin_profile_detail(
    pid: int,
    request: Request,
    msg: str = "",
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    profile = db.get(Profile, pid)
    if profile is None:
        raise HTTPException(404)
    accesses = (
        db.query(ProfileAccess).filter(ProfileAccess.profile_id == pid).all()
    )
    # Resolve a live invite URL for each access whose user has no password.
    invite_urls = {
        a.user_id: auth.pending_invite_url(db, a.user) for a in accesses
    }
    batches = (
        db.query(Batch)
        .filter(Batch.profile_id == pid)
        .order_by(Batch.created_at.desc())
        .all()
    )
    base_path = storage.base_resume_path(pid)
    return render(
        request, "admin_profile_detail.html",
        user=admin, profile=profile, accesses=accesses, batches=batches,
        invite_urls=invite_urls,
        has_base_resume=base_path.exists(),
        msg=msg,
        nav_active="profiles",
    )


@app.post("/admin/profiles/{pid}/resume")
async def admin_upload_resume(
    pid: int,
    file: UploadFile = File(...),
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    profile = db.get(Profile, pid)
    if profile is None:
        raise HTTPException(404)
    if not file.filename or not file.filename.lower().endswith(".docx"):
        raise HTTPException(400, "Please upload a .docx file.")
    dst = storage.base_resume_path(pid)
    dst.parent.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    dst.write_bytes(content)
    profile.base_resume_filename = file.filename
    db.commit()
    return RedirectResponse(f"/admin/profiles/{pid}", status_code=303)


@app.post("/admin/profiles/{pid}/access")
def admin_grant_access(
    pid: int,
    email: str = Form(...),
    name: str = Form(""),
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    profile = db.get(Profile, pid)
    if profile is None:
        raise HTTPException(404)
    email = email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(400, "Invalid email.")
    user = auth.get_or_create_user(
        db, email, role="bidder", name=(name.strip() or None)
    )
    exists = (
        db.query(ProfileAccess)
        .filter(
            ProfileAccess.profile_id == pid,
            ProfileAccess.user_id == user.id,
        )
        .first()
    )
    if exists is None:
        db.add(ProfileAccess(profile_id=pid, user_id=user.id))
    if not user.password_hash:
        auth.pending_invite_url(db, user)
    db.commit()
    return RedirectResponse(f"/admin/profiles/{pid}", status_code=303)


# --------------------------------------------------------------------------
# Admin: bidders
# --------------------------------------------------------------------------

@app.get("/admin/bidders", response_class=HTMLResponse)
def admin_bidders(
    request: Request,
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    bidders = (
        db.query(User)
        .filter(User.role == "bidder")
        .order_by(User.created_at.desc())
        .all()
    )
    # Count accessible profiles per bidder for the list view.
    counts = {b.id: len(b.profile_accesses) for b in bidders}
    return render(
        request, "admin_bidders.html",
        user=admin, bidders=bidders, counts=counts,
        nav_active="bidders",
    )


@app.get("/admin/bidders/{uid}", response_class=HTMLResponse)
def admin_bidder_detail(
    uid: int,
    request: Request,
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    bidder = db.get(User, uid)
    if bidder is None or bidder.role != "bidder":
        raise HTTPException(404)
    profiles = [a.profile for a in bidder.profile_accesses]
    invite_url = auth.pending_invite_url(db, bidder)
    return render(
        request, "admin_bidder_detail.html",
        user=admin, bidder=bidder, profiles=profiles, invite_url=invite_url,
        nav_active="bidders",
    )


@app.post("/admin/bidders/{uid}/rename")
def admin_rename_bidder(
    uid: int,
    name: str = Form(""),
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    bidder = db.get(User, uid)
    if bidder is None:
        raise HTTPException(404)
    bidder.name = name.strip() or None
    db.commit()
    return RedirectResponse(f"/admin/bidders/{uid}", status_code=303)


@app.post("/admin/users/{uid}/reset-invite")
def admin_reset_invite(
    uid: int,
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    """Generate a fresh invite URL for a user (used to share a new link)."""
    target = db.get(User, uid)
    if target is None:
        raise HTTPException(404)
    # This invalidates any prior unused tokens for the user and creates a new one.
    auth.issue_invite_token(db, target)
    # Also clear the password so the invite flow makes sense.
    # (Admin is explicitly resetting access.)
    target.password_hash = None
    db.commit()
    referer = "/admin"
    return RedirectResponse(referer, status_code=303)


@app.post("/admin/profiles/{pid}/access/{access_id}/revoke")
def admin_revoke_access(
    pid: int,
    access_id: int,
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    row = db.get(ProfileAccess, access_id)
    if row is None or row.profile_id != pid:
        raise HTTPException(404)
    db.delete(row)
    db.commit()
    return RedirectResponse(f"/admin/profiles/{pid}", status_code=303)


# --------------------------------------------------------------------------
# Admin: batches
# --------------------------------------------------------------------------

@app.post("/admin/batches")
def admin_batches_create(
    profile_id: int = Form(...),
    urls: str = Form(...),
    label: str = Form(""),
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    profile = db.get(Profile, profile_id)
    if profile is None:
        raise HTTPException(404)
    if not storage.base_resume_path(profile_id).exists():
        raise HTTPException(
            400,
            "Upload a base resume for this profile before running a batch.",
        )
    raw_lines = [
        ln.strip() for ln in urls.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    # Dedupe within the paste itself
    seen: set = set()
    lines: list = []
    for u in raw_lines:
        if u not in seen:
            seen.add(u)
            lines.append(u)
    if not lines:
        raise HTTPException(400, "Paste at least one URL.")

    # Dedupe against already-done URLs for this profile.
    done_urls = {
        u for (u,) in (
            db.query(JobUrl.url)
            .join(Batch, Batch.id == JobUrl.batch_id)
            .filter(Batch.profile_id == profile_id, JobUrl.status == STATUS_DONE)
            .all()
        )
    }
    new_lines = [u for u in lines if u not in done_urls]
    skipped = len(lines) - len(new_lines)
    if not new_lines:
        return RedirectResponse(
            f"/admin/profiles/{profile_id}?msg=All+{skipped}+URLs+were+already+tailored+for+this+profile.",
            status_code=303,
        )

    # One batch per profile per US-Pacific day: reuse today's batch if it exists.
    today = datetime.now(PACIFIC).date()
    start_of_day_utc = (
        datetime.combine(today, datetime.min.time(), tzinfo=PACIFIC)
        .astimezone(timezone.utc).replace(tzinfo=None)
    )
    end_of_day_utc = (
        datetime.combine(today, datetime.max.time(), tzinfo=PACIFIC)
        .astimezone(timezone.utc).replace(tzinfo=None)
    )
    batch = (
        db.query(Batch)
        .filter(
            Batch.profile_id == profile_id,
            Batch.created_at >= start_of_day_utc,
            Batch.created_at <= end_of_day_utc,
        )
        .order_by(Batch.created_at.desc())
        .first()
    )
    if batch is None:
        batch = Batch(profile_id=profile_id, label=None)
        db.add(batch)
        db.flush()

    # Also dedupe against URLs that are already part of this day's batch
    # (pending/fetching/tailoring/error/needs_jd) so re-pasting doesn't duplicate rows.
    existing_in_batch = {
        u for (u,) in db.query(JobUrl.url).filter(JobUrl.batch_id == batch.id).all()
    }
    to_add = [u for u in new_lines if u not in existing_in_batch]
    in_batch_dupes = len(new_lines) - len(to_add)

    jus = [JobUrl(batch_id=batch.id, url=u, status=STATUS_PENDING) for u in to_add]
    for j in jus:
        db.add(j)
    db.commit()
    for j in jus:
        pipeline.enqueue(j.id)

    # Compose a friendly message
    parts = []
    if jus:
        parts.append(f"Added {len(jus)} URL{'s' if len(jus) != 1 else ''} to today's batch.")
    if skipped:
        parts.append(f"Skipped {skipped} already tailored.")
    if in_batch_dupes:
        parts.append(f"Skipped {in_batch_dupes} already in today's batch.")
    msg = " ".join(parts).replace(" ", "+")
    return RedirectResponse(f"/admin/batches/{batch.id}?msg={msg}", status_code=303)


def _batch_summary(jobs: list) -> dict:
    counts = defaultdict(int)
    app_counts = defaultdict(int)
    for j in jobs:
        counts[j.status] += 1
        app_counts[j.application_status or "new"] += 1
    total = len(jobs)
    done = counts.get("done", 0)
    in_flight = (
        counts.get("pending", 0)
        + counts.get("fetching", 0)
        + counts.get("tailoring", 0)
    )
    applied_or_later = sum(
        app_counts.get(s, 0) for s in ("applied", "interview", "rejected", "offer")
    )
    return {
        "total": total,
        "done": done,
        "in_flight": in_flight,
        "needs_jd": counts.get("needs_manual_jd", 0),
        "errors": counts.get("error", 0),
        "percent": int(round(100 * done / total)) if total else 0,
        "applied": applied_or_later,
        "applied_percent": (
            int(round(100 * applied_or_later / done)) if done else 0
        ),
        "app_counts": dict(app_counts),
    }


@app.get("/admin/batches/{bid}", response_class=HTMLResponse)
def admin_batch_detail(
    bid: int,
    request: Request,
    msg: str = "",
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    batch = db.get(Batch, bid)
    if batch is None:
        raise HTTPException(404)
    jobs = (
        db.query(JobUrl)
        .filter(JobUrl.batch_id == bid)
        .order_by(JobUrl.id.asc())
        .all()
    )
    return render(
        request, "admin_batch_detail.html",
        user=admin, batch=batch, profile=batch.profile, jobs=jobs,
        summary=_batch_summary(jobs),
        msg=msg,
        nav_active="profiles",
    )


@app.post("/admin/batches/{bid}/jobs/{jid}/manual")
def admin_job_manual_jd(
    bid: int,
    jid: int,
    company: str = Form(""),
    title: str = Form(""),
    location: str = Form(""),
    description: str = Form(...),
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    ju = db.get(JobUrl, jid)
    if ju is None or ju.batch_id != bid:
        raise HTTPException(404)
    if not description.strip() or len(description.strip()) < 100:
        raise HTTPException(400, "Paste at least 100 characters of job description.")
    ju.company = company.strip() or ju.company
    ju.title = title.strip() or ju.title
    ju.location = location.strip() or ju.location
    ju.description = description.strip()
    ju.status = STATUS_PENDING
    ju.error_message = None
    db.commit()
    pipeline.enqueue(ju.id)
    return RedirectResponse(f"/admin/batches/{bid}", status_code=303)


@app.post("/admin/batches/{bid}/jobs/{jid}/retry")
def admin_job_retry(
    bid: int,
    jid: int,
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    ju = db.get(JobUrl, jid)
    if ju is None or ju.batch_id != bid:
        raise HTTPException(404)
    ju.status = STATUS_PENDING
    ju.error_message = None
    db.commit()
    pipeline.enqueue(ju.id)
    return RedirectResponse(f"/admin/batches/{bid}", status_code=303)


@app.post("/admin/batches/{bid}/retry-errors")
def admin_batch_retry_errors(
    bid: int,
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    batch = db.get(Batch, bid)
    if batch is None:
        raise HTTPException(404)
    errored = (
        db.query(JobUrl)
        .filter(JobUrl.batch_id == bid, JobUrl.status == "error")
        .all()
    )
    for ju in errored:
        ju.status = STATUS_PENDING
        ju.error_message = None
    db.commit()
    for ju in errored:
        pipeline.enqueue(ju.id)
    return RedirectResponse(
        f"/admin/batches/{bid}?msg=Requeued+{len(errored)}+errored+URLs.",
        status_code=303,
    )


@app.get("/admin/batches/{bid}/rows", response_class=HTMLResponse)
def admin_batch_rows(
    bid: int,
    request: Request,
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    """HTMX partial: rerendered rows + progress for auto-refresh."""
    batch = db.get(Batch, bid)
    if batch is None:
        raise HTTPException(404)
    jobs = (
        db.query(JobUrl)
        .filter(JobUrl.batch_id == bid)
        .order_by(JobUrl.id.asc())
        .all()
    )
    return render(
        request, "partials/batch_body.html",
        jobs=jobs, batch=batch, summary=_batch_summary(jobs),
    )


# --------------------------------------------------------------------------
# Calendar (by US Pacific date)
# --------------------------------------------------------------------------

@app.get("/admin/calendar", response_class=HTMLResponse)
def admin_calendar(
    request: Request,
    year: Optional[int] = None,
    month: Optional[int] = None,
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    today_pst = datetime.now(PACIFIC).date()
    y = year or today_pst.year
    m = month or today_pst.month

    batches = (
        db.query(Batch).order_by(Batch.created_at.asc()).all()
    )
    by_day: dict = defaultdict(list)
    for b in batches:
        d = _to_pacific(b.created_at).date()
        if d.year == y and d.month == m:
            by_day[d].append(b)

    cal = _calendar.Calendar(firstweekday=6)  # Sunday first (US convention)
    weeks = cal.monthdatescalendar(y, m)

    prev_y, prev_m = (y - 1, 12) if m == 1 else (y, m - 1)
    next_y, next_m = (y + 1, 1) if m == 12 else (y, m + 1)

    return render(
        request, "admin_calendar.html",
        user=admin,
        weeks=weeks, by_day=by_day, today=today_pst,
        cur_y=y, cur_m=m,
        month_name=_calendar.month_name[m],
        prev_y=prev_y, prev_m=prev_m,
        next_y=next_y, next_m=next_m,
        nav_active="calendar",
    )


# --------------------------------------------------------------------------
# Bidder pages
# --------------------------------------------------------------------------

@app.get("/my", response_class=HTMLResponse)
def my_home(
    request: Request,
    user: User = Depends(auth.require_user),
    db: Session = Depends(get_db),
):
    if user.role == "admin":
        profiles = db.query(Profile).all()
    else:
        profiles = [a.profile for a in user.profile_accesses]
    return render(request, "my_home.html", user=user, profiles=profiles, nav_active="my")


@app.get("/my/profiles/{pid}", response_class=HTMLResponse)
def my_profile(
    pid: int,
    request: Request,
    user: User = Depends(auth.require_user),
    db: Session = Depends(get_db),
):
    profile = db.get(Profile, pid)
    if profile is None:
        raise HTTPException(404)
    if user.role != "admin":
        has_access = (
            db.query(ProfileAccess)
            .filter(
                ProfileAccess.profile_id == pid,
                ProfileAccess.user_id == user.id,
            )
            .first()
        )
        if has_access is None:
            raise HTTPException(403)
    batches = (
        db.query(Batch)
        .filter(Batch.profile_id == pid)
        .order_by(Batch.created_at.desc())
        .all()
    )
    return render(
        request, "my_profile.html",
        user=user, profile=profile, batches=batches,
        nav_active="my",
    )


def _check_batch_access(user: User, batch: Batch, db: Session) -> None:
    if user.role == "admin":
        return
    has_access = (
        db.query(ProfileAccess)
        .filter(
            ProfileAccess.profile_id == batch.profile_id,
            ProfileAccess.user_id == user.id,
        )
        .first()
    )
    if has_access is None:
        raise HTTPException(403)


@app.post("/batches/{bid}/jobs/{jid}/app-status")
def set_application_status(
    bid: int,
    jid: int,
    request: Request,
    status: str = Form(...),
    note: str = Form(""),
    user: User = Depends(auth.require_user),
    db: Session = Depends(get_db),
):
    ju = db.get(JobUrl, jid)
    if ju is None or ju.batch_id != bid:
        raise HTTPException(404)
    _check_batch_access(user, ju.batch, db)
    if status not in APP_STATUSES:
        raise HTTPException(400, f"Unknown status: {status}")
    ju.application_status = status
    if status == "new":
        ju.applied_at = None
    elif status == "applied" and ju.applied_at is None:
        ju.applied_at = datetime.now(timezone.utc)
    if note:
        ju.application_note = note.strip() or None
    db.commit()

    # If HTMX invoked us, return just the updated control so the page doesn't reload.
    if request.headers.get("HX-Request"):
        return render(request, "partials/app_status.html", j=ju, batch=ju.batch)

    dest = "/admin/batches" if user.role == "admin" else "/my/batches"
    return RedirectResponse(f"{dest}/{bid}", status_code=303)


@app.get("/my/batches/{bid}", response_class=HTMLResponse)
def my_batch(
    bid: int,
    request: Request,
    user: User = Depends(auth.require_user),
    db: Session = Depends(get_db),
):
    batch = db.get(Batch, bid)
    if batch is None:
        raise HTTPException(404)
    _check_batch_access(user, batch, db)
    jobs = (
        db.query(JobUrl)
        .filter(JobUrl.batch_id == bid, JobUrl.status == STATUS_DONE)
        .order_by(JobUrl.id.asc())
        .all()
    )
    return render(
        request, "my_batch.html",
        user=user, batch=batch, profile=batch.profile, jobs=jobs,
        nav_active="my",
    )


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

    jobs = (
        db.query(JobUrl)
        .filter(JobUrl.batch_id == bid, JobUrl.status == STATUS_DONE)
        .order_by(JobUrl.id.asc())
        .all()
    )
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
            # Ensure uniqueness in case of collisions
            n = 2
            while name in used:
                name = f"{base}_{n}.docx"
                n += 1
            used.add(name)
            zf.write(str(path), arcname=name)
    buf.seek(0)
    date_tag = _to_pacific(batch.created_at).strftime("%Y-%m-%d")
    zip_name = _safe_slug(f"{batch.profile.name}_{batch.label or date_tag}") + ".zip"
    return StreamingResponse(
        buf, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
    )


# --------------------------------------------------------------------------
# Downloads
# --------------------------------------------------------------------------

def _check_download_access(user: User, ju: JobUrl, db: Session) -> None:
    if user.role == "admin":
        return
    has_access = (
        db.query(ProfileAccess)
        .filter(
            ProfileAccess.profile_id == ju.batch.profile_id,
            ProfileAccess.user_id == user.id,
        )
        .first()
    )
    if has_access is None:
        raise HTTPException(403)


@app.get("/download/{jid}/{kind}")
def download(
    jid: int,
    kind: str,
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
        fname = ju.docx_filename
        path = storage.generated_docx_path(ju.batch_id, ju.id)
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        fname = ju.pdf_filename
        path = storage.generated_pdf_path(ju.batch_id, ju.id)
        media = "application/pdf"

    if not fname or not path.exists():
        raise HTTPException(404, "File not generated yet.")

    # Friendly filename on disk
    friendly = _safe_slug(f"{ju.company or 'Company'}_{ju.title or 'Role'}") + (
        ".docx" if kind == "docx" else ".pdf"
    )
    return FileResponse(str(path), media_type=media, filename=friendly)


def _safe_slug(s: str, limit: int = 80) -> str:
    import re
    s = (s or "Resume").strip()
    s = re.sub(r"[^A-Za-z0-9._ -]+", "", s)
    s = re.sub(r"\s+", "_", s)
    return s[:limit] or "Resume"


# --------------------------------------------------------------------------
# Health
# --------------------------------------------------------------------------

@app.get("/healthz")
def healthz():
    return {"ok": True}

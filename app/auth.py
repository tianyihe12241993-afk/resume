"""Password auth + one-time invite tokens + signed session cookie."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from . import config
from .db import get_db
from .models import InviteToken, User

SESSION_COOKIE = "rm_session"
SESSION_MAX_AGE = 30 * 24 * 3600  # 30 days

_serializer = URLSafeTimedSerializer(config.SESSION_SECRET, salt="session")


# -------- password hashing --------

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: Optional[str]) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


# -------- session cookies --------

def set_session(response, user_id: int) -> None:
    token = _serializer.dumps({"uid": user_id})
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=False,  # flip to True behind HTTPS
    )


def clear_session(response) -> None:
    response.delete_cookie(SESSION_COOKIE)


def _read_session(request: Request) -> Optional[int]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        data = _serializer.loads(token, max_age=SESSION_MAX_AGE)
        return int(data.get("uid"))
    except (BadSignature, Exception):
        return None


def current_user(
    request: Request, db: Session = Depends(get_db)
) -> Optional[User]:
    uid = _read_session(request)
    if uid is None:
        return None
    return db.get(User, uid)


def require_user(
    request: Request, db: Session = Depends(get_db)
) -> User:
    user = current_user(request, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": f"/login?next={request.url.path}"},
        )
    return user


def require_admin(
    request: Request, db: Session = Depends(get_db)
) -> User:
    user = require_user(request, db)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only.")
    return user


# -------- invite / reset tokens --------

INVITE_TTL_HOURS = 72


def issue_invite_token(db: Session, user: User) -> str:
    """Create a one-time URL for the user to set their password."""
    # Invalidate any previous unused tokens for cleanliness.
    for t in user.invite_tokens:
        if t.used_at is None:
            t.used_at = datetime.now(timezone.utc)
    token = secrets.token_urlsafe(32)
    row = InviteToken(
        user_id=user.id,
        token=token,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=INVITE_TTL_HOURS),
    )
    db.add(row)
    db.commit()
    return token


def invite_url_for(token: str) -> str:
    return f"{config.FRONTEND_URL}/setup?token={token}"


def consume_invite_token(db: Session, token: str) -> Optional[User]:
    row = db.query(InviteToken).filter(InviteToken.token == token).first()
    if row is None or row.used_at is not None:
        return None
    if row.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        return None
    row.used_at = datetime.now(timezone.utc)
    db.commit()
    return db.get(User, row.user_id)


def peek_invite_token(db: Session, token: str) -> Optional[User]:
    """Look at a token without consuming it (for displaying the setup form)."""
    row = db.query(InviteToken).filter(InviteToken.token == token).first()
    if row is None or row.used_at is not None:
        return None
    if row.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        return None
    return db.get(User, row.user_id)


def get_or_create_user(
    db: Session, email: str, role: str = "bidder", name: Optional[str] = None
) -> User:
    email = email.strip().lower()
    u = db.query(User).filter(User.email == email).first()
    if u is None:
        u = User(email=email, role=role, name=(name.strip() if name else None))
        db.add(u)
        db.flush()
    elif name and not u.name:
        u.name = name.strip()
    return u


def pending_invite_url(db: Session, user: User) -> Optional[str]:
    """Return the live invite URL for a user who hasn't set a password yet."""
    if user.password_hash:
        return None
    token = (
        db.query(InviteToken)
        .filter(InviteToken.user_id == user.id, InviteToken.used_at.is_(None))
        .order_by(InviteToken.created_at.desc())
        .first()
    )
    if token is None or token.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        fresh = issue_invite_token(db, user)
        return invite_url_for(fresh)
    return invite_url_for(token.token)


def ensure_admin_seeded(db: Session) -> None:
    """On boot, ensure the env ADMIN_EMAIL exists as an admin.

    If they have no password yet, mint an invite URL and print it to the
    server console so the first admin can set their own password.
    """
    admin_email = config.ADMIN_EMAIL
    if not admin_email:
        return
    u = db.query(User).filter(User.email == admin_email).first()
    if u is None:
        u = User(email=admin_email, role="admin")
        db.add(u)
        db.flush()
    elif u.role != "admin":
        u.role = "admin"
    db.commit()

    if not u.password_hash:
        url = pending_invite_url(db, u)
        print(
            f"\n[bootstrap] Admin {u.email} has no password yet.\n"
            f"[bootstrap] Open this URL to set one (valid {INVITE_TTL_HOURS}h):\n"
            f"[bootstrap]   {url}\n",
            flush=True,
        )

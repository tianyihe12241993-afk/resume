"""Multi-user auth for tailor-studio.

Users sign up with email + password. Passwords stored as bcrypt hashes in
the `user` table. Login issues a signed cookie with `{u: user_id}`; every
protected endpoint resolves that to a User row.

If the legacy STUDIO_AUTH_EMAIL / STUDIO_AUTH_PASSWORD_HASH env vars are
set, init_db() materializes that as the first user so existing data isn't
orphaned. After the first multi-user signup the env vars are no longer
consulted.
"""
from __future__ import annotations

import re
import time
from typing import Optional

import bcrypt
from fastapi import HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from . import config
from .db import SessionLocal, User


_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def _serializer() -> URLSafeTimedSerializer:
    if not config.SESSION_SECRET:
        raise RuntimeError(
            "STUDIO_SESSION_SECRET not configured. Set it in .env."
        )
    return URLSafeTimedSerializer(config.SESSION_SECRET, salt="studio-session")


# ── password hashing / verification ────────────────────────────────────────

def hash_password(plaintext: str) -> str:
    if not plaintext:
        raise ValueError("Empty password.")
    return bcrypt.hashpw(
        plaintext.encode("utf-8"),
        bcrypt.gensalt(rounds=12),
    ).decode("ascii")


def verify_password(plaintext: str, hashed: str) -> bool:
    if not (plaintext and hashed):
        return False
    try:
        return bcrypt.checkpw(plaintext.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ── email + password validation helpers (used by signup) ───────────────────

def normalize_email(raw: str) -> str:
    return (raw or "").strip().lower()


def validate_signup(email: str, password: str) -> Optional[str]:
    """Return None on valid, or an error string."""
    e = normalize_email(email)
    if not e or not _EMAIL_RE.match(e):
        return "Enter a valid email address."
    if not password or len(password) < 8:
        return "Password must be at least 8 characters."
    return None


# ── session cookie issuance / verification ─────────────────────────────────

def issue_session(response: Response, user_id: int) -> None:
    token = _serializer().dumps({"u": user_id, "iat": int(time.time())})
    response.set_cookie(
        key=config.SESSION_COOKIE,
        value=token,
        max_age=config.SESSION_TTL_SECONDS,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(
        key=config.SESSION_COOKIE,
        path="/",
        secure=config.COOKIE_SECURE,
        samesite="lax",
    )


def _read_user_id(request: Request) -> Optional[int]:
    raw = request.cookies.get(config.SESSION_COOKIE)
    if not raw:
        return None
    try:
        data = _serializer().loads(raw, max_age=config.SESSION_TTL_SECONDS)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(data, dict):
        return None
    uid = data.get("u")
    return int(uid) if isinstance(uid, int) else None


# ── DB-backed user lookup helpers ──────────────────────────────────────────

def get_user_by_id(db: Session, uid: int) -> Optional[User]:
    return db.get(User, uid)


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    e = normalize_email(email)
    if not e:
        return None
    return db.query(User).filter(User.email == e).first()


def create_user(db: Session, email: str, password: str) -> User:
    user = User(email=normalize_email(email), password_hash=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ── FastAPI dependencies ───────────────────────────────────────────────────

def current_user(request: Request) -> Optional[User]:
    uid = _read_user_id(request)
    if uid is None:
        return None
    db = SessionLocal()
    try:
        return get_user_by_id(db, uid)
    finally:
        db.close()


def require_user(request: Request) -> User:
    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return user

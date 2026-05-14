"""SQLite + SQLAlchemy models for tailor-studio.

Single-user, no auth. Mirrors the admin app's data model minus User /
InviteToken / ProfileAccess. Field names are kept compatible with the admin
frontend's API shapes so most of the React UI works untouched.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Column, Date, DateTime, ForeignKey, Integer, String, Text, Boolean,
    create_engine, text,
)
from sqlalchemy.orm import (
    DeclarativeBase, Mapped, Session, mapped_column, relationship,
    sessionmaker,
)

from . import config


def now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    """One row per signed-up user. Email is the login identifier."""
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    profiles = relationship("Profile", back_populates="owner", cascade="all, delete-orphan")


class Profile(Base):
    """A base-resume profile. One per role type the owner is targeting."""
    __tablename__ = "profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # NULL allowed in schema for forward-compat with rows from before multi-user;
    # API layer enforces non-null on create and on every read.
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=True, index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_resume_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    tailor_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    daily_target: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

    owner = relationship("User", back_populates="profiles")
    batches = relationship("Batch", back_populates="profile", cascade="all, delete-orphan")


class Batch(Base):
    """A collection of JD URLs submitted together."""
    __tablename__ = "batch"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("profile.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    profile = relationship("Profile", back_populates="batches")
    urls = relationship("JobUrl", back_populates="batch", cascade="all, delete-orphan")


# Pipeline statuses.
STATUS_PENDING = "pending"
STATUS_FETCHING = "fetching"
STATUS_ANALYZING = "analyzing"
STATUS_TAILORING = "tailoring"
STATUS_DONE = "done"
STATUS_NEEDS_JD = "needs_manual_jd"
STATUS_ERROR = "error"

# Application-funnel statuses (orthogonal to pipeline status).
#   not_yet    — default for newly tailored jobs (haven't submitted yet)
#   applied    — successfully submitted an application
#   error      — couldn't apply (link broken, posting closed, blocked, etc.)
#   not_remote — posting turned out to require on-site work, skipping
APP_STATUSES = ("not_yet", "applied", "error", "not_remote")


class JobUrl(Base):
    __tablename__ = "job_url"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("batch.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default=STATUS_PENDING)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    company: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    docx_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    pdf_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    download_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Coverage report (constrained-rewrite pipeline)
    coverage_initial: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    coverage_final: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    spec_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    claimed_terms: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Application funnel
    application_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="not_yet"
    )
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    application_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    application_source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

    batch = relationship("Batch", back_populates="urls")


_engine = create_engine(
    f"sqlite:///{config.DB_PATH}",
    connect_args={"check_same_thread": False},
    future=True,
)
SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)


def init_db() -> None:
    Base.metadata.create_all(_engine)
    # Idempotent migrations for older dev DBs.
    with _engine.connect() as conn:
        # job_url.pdf_filename
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(job_url)"))}
        if "pdf_filename" not in cols:
            conn.execute(text("ALTER TABLE job_url ADD COLUMN pdf_filename VARCHAR(255)"))
        # profile.user_id
        prof_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(profile)"))}
        if "user_id" not in prof_cols:
            conn.execute(text("ALTER TABLE profile ADD COLUMN user_id INTEGER REFERENCES user(id) ON DELETE CASCADE"))
        # Remap legacy application_status values to the new 4-status set.
        # Idempotent: only rows still on legacy values are touched.
        conn.execute(text("UPDATE job_url SET application_status = 'not_yet' WHERE application_status = 'new'"))
        conn.execute(text(
            "UPDATE job_url SET application_status = 'applied' "
            "WHERE application_status IN ('interview', 'rejected', 'offer')"
        ))
        conn.commit()

        # Backfill: if there's a single-credential env config and existing
        # profiles without an owner, materialize that user and assign all
        # orphan profiles to them. Safe to run repeatedly.
        from . import config
        legacy_email = (config.AUTH_EMAIL or "").strip().lower()
        legacy_hash = (config.AUTH_PASSWORD_HASH or "").strip()
        if legacy_email and legacy_hash:
            existing = conn.execute(
                text("SELECT id FROM user WHERE email = :e"),
                {"e": legacy_email},
            ).fetchone()
            if existing:
                user_id = existing[0]
            else:
                # Use raw SQL for the insert so we don't depend on the
                # SQLAlchemy session being primed before tables exist.
                res = conn.execute(
                    text(
                        "INSERT INTO user (email, password_hash, created_at) "
                        "VALUES (:e, :h, :t)"
                    ),
                    {"e": legacy_email, "h": legacy_hash, "t": now()},
                )
                user_id = res.lastrowid
            conn.execute(
                text("UPDATE profile SET user_id = :u WHERE user_id IS NULL"),
                {"u": user_id},
            )
        conn.commit()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_session() -> Session:
    return SessionLocal()

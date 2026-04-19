"""ORM models."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="bidder")  # admin|bidder
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    profiles_owned = relationship("Profile", back_populates="owner", cascade="all, delete-orphan")
    profile_accesses = relationship("ProfileAccess", back_populates="user", cascade="all, delete-orphan")
    invite_tokens = relationship("InviteToken", back_populates="user", cascade="all, delete-orphan")


class InviteToken(Base):
    """One-time URL token for setting a password (invite or reset)."""
    __tablename__ = "invite_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    user = relationship("User", back_populates="invite_tokens")


class Profile(Base):
    """A candidate profile. Owned by an admin; bidders gain access via ProfileAccess."""
    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_resume_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    daily_target: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

    owner = relationship("User", back_populates="profiles_owned")
    accesses = relationship("ProfileAccess", back_populates="profile", cascade="all, delete-orphan")
    batches = relationship("Batch", back_populates="profile", cascade="all, delete-orphan")


class ProfileAccess(Base):
    __tablename__ = "profile_access"
    __table_args__ = (UniqueConstraint("profile_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    profile = relationship("Profile", back_populates="accesses")
    user = relationship("User", back_populates="profile_accesses")


class Batch(Base):
    """A group of job URLs submitted together, typically one per morning."""
    __tablename__ = "batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    profile = relationship("Profile", back_populates="batches")
    urls = relationship("JobUrl", back_populates="batch", cascade="all, delete-orphan")


# Status values for JobUrl
STATUS_PENDING = "pending"              # queued, worker hasn't picked up
STATUS_FETCHING = "fetching"            # scraping JD
STATUS_NEEDS_JD = "needs_manual_jd"     # scrape failed, admin should paste JD
STATUS_TAILORING = "tailoring"          # Claude call in flight
STATUS_DONE = "done"                    # tailored docx (and maybe pdf) ready
STATUS_ERROR = "error"                  # unrecoverable error

# Applied / not applied — simple checkbox.
APP_STATUSES = ("new", "applied")


class JobUrl(Base):
    __tablename__ = "job_urls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default=STATUS_PENDING)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    company: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    docx_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    pdf_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Application-funnel status (orthogonal to pipeline status above).
    # Values: new | applied | interview | rejected | offer
    application_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="new"
    )
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    application_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Source tag: "manual" (checkbox), "gmail_auto" (detected from inbox), etc.
    application_source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # When auto-detected: the Gmail message id that evidence came from.
    application_evidence: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

    batch = relationship("Batch", back_populates="urls")

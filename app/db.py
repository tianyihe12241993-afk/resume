"""SQLAlchemy setup + session helpers."""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from . import config

engine = create_engine(
    f"sqlite:///{config.DB_PATH}",
    connect_args={"check_same_thread": False, "timeout": 30},
    pool_size=20,
    max_overflow=20,
    pool_timeout=60,
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _run_lightweight_migrations()


def _run_lightweight_migrations() -> None:
    """Hand-rolled ALTER TABLE migrations for new columns.

    SQLite's CREATE IF NOT EXISTS won't add columns to existing tables,
    so we add them idempotently here.
    """
    from sqlalchemy import text

    migrations = [
        ("job_urls", "application_status", "VARCHAR(16) NOT NULL DEFAULT 'new'"),
        ("job_urls", "applied_at", "DATETIME"),
        ("job_urls", "application_note", "TEXT"),
        ("users", "password_hash", "VARCHAR(255)"),
        ("users", "name", "VARCHAR(255)"),
    ]
    with engine.begin() as conn:
        for table, col, decl in migrations:
            rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
            have = {r[1] for r in rows}
            if col not in have:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {decl}"))
        # legacy magic-link table is no longer used; drop if present
        conn.execute(text("DROP TABLE IF EXISTS login_tokens"))

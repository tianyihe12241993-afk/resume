"""App configuration."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data"))
BASE_RESUMES_DIR = DATA_DIR / "base_resumes"
OUTPUTS_DIR = DATA_DIR / "outputs"
DB_PATH = Path(os.getenv("DB_PATH", DATA_DIR / "app.db"))

DATA_DIR.mkdir(parents=True, exist_ok=True)
BASE_RESUMES_DIR.mkdir(parents=True, exist_ok=True)
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-secret-change-me")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "").strip().lower()
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
# Whether the session cookie should be flagged "Secure" (only sent over HTTPS).
# Auto-detect from APP_BASE_URL but allow override.
COOKIE_SECURE = os.getenv(
    "COOKIE_SECURE", "true" if APP_BASE_URL.startswith("https://") else "false"
).lower() in ("1", "true", "yes")
# Max URLs accepted per batch submission (prevents accidental API blow-ups).
MAX_URLS_PER_BATCH = int(os.getenv("MAX_URLS_PER_BATCH", "200"))
# Where the user-facing React app lives. In dev this is the Vite dev server on
# :5173; in prod it's the same origin as the API.
FRONTEND_URL = os.getenv("FRONTEND_URL", APP_BASE_URL).rstrip("/")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
# Per-request timeout (seconds) + retry cap for ALL Claude calls. The SDK
# default is 600s, so a hung connection under heavy concurrency can jam a worker
# for ~30 min. A tight timeout makes a stalled call fail fast and the job moves
# on (degraded) instead of blocking the whole queue.
ANTHROPIC_TIMEOUT = float(os.getenv("ANTHROPIC_TIMEOUT", "90"))
ANTHROPIC_MAX_RETRIES = int(os.getenv("ANTHROPIC_MAX_RETRIES", "2"))
# Global cap on simultaneous in-flight Claude calls across the WHOLE process
# (all jobs, all fan-out). Decouples API load from STUDIO_WORKERS so a big batch
# can't overwhelm your Anthropic rate limit (which causes 429 backoff + stalls).
ANTHROPIC_MAX_CONCURRENCY = int(os.getenv("ANTHROPIC_MAX_CONCURRENCY", "12"))
TAILOR_MODEL = os.getenv("TAILOR_MODEL", "claude-sonnet-4-6")
EXTRACT_MODEL = os.getenv("EXTRACT_MODEL", "claude-haiku-4-5-20251001")
# Defensibility / judgment calls (adjacency bridges, truthful skills-rewrite).
# These decide whether a JD skill is a real match, an adjacent bridge, or an
# over-reach — the highest-leverage judgment in the pipeline — so they default
# to the stronger model rather than the cheap extraction one.
JUDGE_MODEL = os.getenv("JUDGE_MODEL", "claude-sonnet-4-6")

# Email (magic link)
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER or "noreply@localhost")
# If SMTP_HOST is empty, magic links are printed to the server console
# (useful for local development / first-time admin login).

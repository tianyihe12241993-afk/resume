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
TAILOR_MODEL = os.getenv("TAILOR_MODEL", "claude-sonnet-4-6")
EXTRACT_MODEL = os.getenv("EXTRACT_MODEL", "claude-haiku-4-5-20251001")

# Email (magic link)
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER or "noreply@localhost")
# If SMTP_HOST is empty, magic links are printed to the server console
# (useful for local development / first-time admin login).

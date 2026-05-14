"""tailor-studio configuration."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("STUDIO_DATA_DIR", ROOT / "tailor_studio" / "data"))
PROFILES_DIR = DATA_DIR / "profiles"
OUTPUTS_DIR = DATA_DIR / "outputs"
DB_PATH = Path(os.getenv("STUDIO_DB_PATH", DATA_DIR / "studio.db"))

DATA_DIR.mkdir(parents=True, exist_ok=True)
PROFILES_DIR.mkdir(parents=True, exist_ok=True)
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

PORT = int(os.getenv("STUDIO_PORT", "8001"))
HOST = os.getenv("STUDIO_HOST", "127.0.0.1")
WORKERS = int(os.getenv("STUDIO_WORKERS", "4"))
MAX_RESUME_BYTES = 10 * 1024 * 1024
MAX_URLS_PER_BATCH = int(os.getenv("STUDIO_MAX_URLS_PER_BATCH", "200"))

# ── Single-user auth ─────────────────────────────────────────────────────
AUTH_EMAIL = os.getenv("STUDIO_AUTH_EMAIL", "").strip().lower()
AUTH_PASSWORD_HASH = os.getenv("STUDIO_AUTH_PASSWORD_HASH", "").strip()
SESSION_SECRET = os.getenv("STUDIO_SESSION_SECRET", "").strip()
SESSION_COOKIE = "studio_session"
SESSION_TTL_SECONDS = 14 * 24 * 3600  # 14 days
# Default cookie Secure=false so http://127.0.0.1:8001 works during dev.
# When you expose only via the cloudflared tunnel, set STUDIO_COOKIE_SECURE=true
# so the session cookie is HTTPS-only.
COOKIE_SECURE = os.getenv("STUDIO_COOKIE_SECURE", "false").lower() in ("1", "true", "yes")
AUTH_ENABLED = bool(AUTH_EMAIL and AUTH_PASSWORD_HASH and SESSION_SECRET)

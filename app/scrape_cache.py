"""URL-keyed disk cache for fetch_job_posting results.

Cuts repeat HTTP + Haiku-extract cost when the same JD URL appears under
multiple profiles (or when a job is reposted within the TTL window).

Keyed by SHA-256 of the canonicalized URL (strip + lower + drop trailing /).
TTL is 7 days — postings rarely change content within that window, and stale
hits are always recoverable via `bypass_cache=True`.

Mirrors the on-disk pattern used by jd_spec_cache, adjacency_cache,
bullet_rewrite_cache, and tailor_cache.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Optional

from . import config


SCRAPE_CACHE_DIR = config.DATA_DIR / "scrape_cache"
TTL_SECONDS = 7 * 24 * 3600  # 7 days
_MIN_DESC_CHARS = 200  # don't cache failed/empty scrapes


def _key(url: str) -> str:
    canonical = (url or "").strip().rstrip("/").lower()
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _path(url: str) -> Path:
    return SCRAPE_CACHE_DIR / f"{_key(url)}.json"


def get(url: str) -> Optional[dict]:
    """Return cached payload if fresh + sane, else None."""
    p = _path(url)
    if not p.exists():
        return None
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    fetched_at = rec.get("fetched_at") or 0
    if time.time() - fetched_at > TTL_SECONDS:
        return None
    payload = rec.get("payload")
    if not isinstance(payload, dict):
        return None
    if len((payload.get("description") or "").strip()) < _MIN_DESC_CHARS:
        return None
    return payload


def put(url: str, payload: dict) -> None:
    """Persist a successful scrape. Silently no-ops on empty descriptions
    so we never cache a failure."""
    if not isinstance(payload, dict):
        return
    if len((payload.get("description") or "").strip()) < _MIN_DESC_CHARS:
        return
    try:
        SCRAPE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        rec = {"fetched_at": time.time(), "url": url, "payload": payload}
        _path(url).write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass  # best-effort


def invalidate(url: str) -> None:
    """Force the next fetch_job_posting(url) to hit the network."""
    p = _path(url)
    try:
        if p.exists():
            p.unlink()
    except OSError:
        pass

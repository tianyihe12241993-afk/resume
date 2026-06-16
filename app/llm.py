"""Shared Anthropic client factory with a process-wide concurrency cap.

Every module builds its client via `make_client()` so that ALL Claude calls —
across every job and every fan-out thread — share one global semaphore. This
caps total simultaneous requests regardless of STUDIO_WORKERS x inner fan-out,
so a large batch can't bury your Anthropic rate limit (which otherwise triggers
429 backoff and stalls the whole queue). Clients also carry a bounded timeout +
retry count so a stalled connection fails fast instead of hanging a worker.
"""
from __future__ import annotations

import threading

from anthropic import Anthropic

from . import config

# One semaphore for the entire process. BoundedSemaphore guards against an
# accidental extra release inflating the limit.
_GATE = threading.BoundedSemaphore(max(1, config.ANTHROPIC_MAX_CONCURRENCY))


def make_client() -> Anthropic:
    """Anthropic client whose `.messages.create` is wrapped to acquire the
    global concurrency gate (and configured with timeout + retries)."""
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Edit .env and restart the server."
        )
    client = Anthropic(
        api_key=config.ANTHROPIC_API_KEY,
        timeout=config.ANTHROPIC_TIMEOUT,
        max_retries=config.ANTHROPIC_MAX_RETRIES,
    )
    _orig_create = client.messages.create

    def _gated_create(*args, **kwargs):
        with _GATE:
            return _orig_create(*args, **kwargs)

    # Shadow the bound method on this client's messages resource (set once in
    # the SDK's __init__, so the override sticks for the client's lifetime).
    client.messages.create = _gated_create
    return client

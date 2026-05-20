"""Work-type classification: remote / hybrid / onsite / unknown.

Deterministic, regex-based fallback used when a per-ATS scraper does not
return a structured workplace-type value. Per-ATS extraction in
``app/scraping.py`` is the primary source; this module is the safety net
that runs on title + location + description text.

Public surface: ``classify_work_type``.
"""
from __future__ import annotations

import re
from typing import Optional

WORK_TYPES = ("remote", "hybrid", "onsite")

# Compiled once at import.
_REMOTE_STRONG = re.compile(
    r"\b(fully\s+remote|100%\s+remote|remote[- ]first|remote[- ]only"
    r"|work\s+from\s+home|wfh|telecommut\w*|distributed\s+team)\b",
    re.IGNORECASE,
)
_HYBRID_STRONG = re.compile(
    r"\b(hybrid"
    r"|\d+\s+days?\s+(?:per\s+week\s+)?(?:in\s+(?:the\s+)?(?:office|person)|onsite|on[- ]site)"
    r"|(?:in[- ](?:office|person)|on[- ]site)\s+\d+\s+days?"
    r")\b",
    re.IGNORECASE,
)
_ONSITE_STRONG = re.compile(
    r"\b(on[- ]site\s+(?:role|position|only|required)"
    r"|in[- ](?:office|person)\s+(?:role|position|only|required)"
    r"|no\s+remote|not\s+remote|fully\s+on[- ]site)\b",
    re.IGNORECASE,
)
# Exact-match location strings that imply remote.
_REMOTE_LOC = {
    "remote", "remote-us", "remote, us", "remote (us)", "remote us",
    "anywhere", "anywhere in the us", "anywhere in the u.s.",
    "worldwide", "global", "us remote", "u.s. remote",
    "remote, united states", "remote - united states",
}


def _norm_loc(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def classify_work_type(
    title: str = "",
    location: str = "",
    description: str = "",
) -> Optional[str]:
    """Return ``"remote"``, ``"hybrid"``, ``"onsite"``, or ``None``.

    Rules run in order of precedence; first match wins. The first three are
    text-pattern rules across all three inputs; the last is an exact-match
    rule on the location field alone (handles strings like "Remote, US").

    Returns ``None`` when no signal is strong enough — callers should store
    that as NULL/unknown rather than guessing.
    """
    blob = " ".join(s for s in (title, location, description) if s)
    if not blob.strip():
        return None

    loc_norm = _norm_loc(location)
    title_low = (title or "").lower()
    loc_strong_remote = (
        loc_norm in _REMOTE_LOC
        or (loc_norm and re.search(r"\bremote\b", loc_norm)
            and "office" not in loc_norm
            and "hybrid" not in loc_norm
            and len(loc_norm) <= 40)
    )

    # Strong-remote phrases win over hybrid (hybrid posts often note
    # "remote during onboarding" or similar, but a "fully remote" line is
    # decisive).
    if _REMOTE_STRONG.search(blob):
        return "remote"

    # If the location itself is clearly remote and there is no explicit
    # hybrid signal in title or location, trust the location over a stray
    # mention of "hybrid" in the description body (common in benefits or
    # perks copy).
    if loc_strong_remote and "hybrid" not in loc_norm and "hybrid" not in title_low:
        return "remote"

    # Hybrid before onsite — "3 days in office" beats a generic "in person" line.
    if _HYBRID_STRONG.search(blob):
        return "hybrid"

    if _ONSITE_STRONG.search(blob):
        return "onsite"

    if loc_strong_remote:
        return "remote"

    return None


def normalize_work_type(value: Optional[str]) -> Optional[str]:
    """Map ATS-provided enum values (REMOTE, On-Site, etc.) onto our canonical
    three-value set. Returns None on unrecognized input."""
    if not value:
        return None
    v = value.strip().lower().replace("_", "").replace("-", "").replace(" ", "")
    if v in {"remote", "fullyremote", "remoteonly", "wfh"}:
        return "remote"
    if v in {"hybrid", "flexible", "hybridremote"}:
        return "hybrid"
    if v in {"onsite", "office", "inoffice", "inperson", "onpremise", "onpremises"}:
        return "onsite"
    return None

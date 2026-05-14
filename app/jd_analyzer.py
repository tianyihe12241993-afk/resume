"""JD analyzer — pass 1 of the constrained-rewrite tailoring pipeline.

Takes a scraped job description and returns a structured keyword spec that
downstream passes (coverage map, per-bullet rewrite, gap report) read from.

The spec is the single source of truth for "what does the JD ask for, and how
heavily?" Cached by SHA-256 of the JD text so re-running is free.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Optional

from anthropic import Anthropic

from . import config


_JD_ANALYZER_SYSTEM = """You analyze a job description and emit a structured keyword spec used by a resume-tailoring system. The spec drives ATS keyword matching, so precision matters more than coverage — a few high-confidence terms beat many noisy ones.

Output STRICT JSON inside <json>...</json> tags. No prose, no markdown.

SCHEMA:
{
  "role_family": "<short canonical role, e.g. 'backend engineer', 'ml engineer', 'product manager'>",
  "seniority": "<one of: junior, mid, senior, staff, principal, lead, manager, director, null>",
  "years_required": <integer or null — minimum years explicitly stated; null if not stated>,
  "hard_skills": [
    {
      "term": "<canonical form of a concrete technology, tool, language, framework, platform, or measurable methodology>",
      "weight": <float 0.0–1.0>,
      "aliases": ["<common synonym/abbreviation>", ...]
    },
    ...
  ],
  "soft_signals": [
    {
      "term": "<domain word, industry, or qualitative attribute — e.g. 'fintech', 'high-throughput', 'distributed systems', 'mentorship'>",
      "weight": <float 0.0–1.0>,
      "aliases": []
    },
    ...
  ],
  "must_have_phrases": [
    "<literal phrase from the JD that an ATS keyword search would likely use, verbatim — e.g. '5+ years of Python', 'production machine learning'>"
  ]
}

WEIGHTING RULES (apply consistently — downstream code orders bullets by these):
- 0.9–1.0: appears in a "Requirements" / "Must have" / "Qualifications" section AND mentioned 2+ times OR called out as required.
- 0.7–0.89: appears in a requirements section once, OR mentioned multiple times across the JD.
- 0.4–0.69: appears in "Nice to have" / "Preferred" / "Bonus" sections, OR mentioned once in body text.
- 0.1–0.39: tangential mention, single occurrence in a long list.

HARD SKILLS — what counts:
- Languages (Python, Go, TypeScript, ...)
- Frameworks/libraries (React, Django, PyTorch, ...)
- Platforms/infra (Kubernetes, AWS, Snowflake, ...)
- Concrete tools (Terraform, Datadog, ...)
- Concrete methodologies with industry-standard names (TDD, CI/CD, A/B testing, ...)
- DO NOT include: vague phrases ("strong communication", "ownership"), job titles, company names, generic verbs.

SOFT SIGNALS — what counts:
- Industry/domain words (fintech, healthtech, e-commerce, defense, ...)
- Qualitative attributes that recruiters often search (high-throughput, low-latency, real-time, mission-critical, ...)
- Team/leadership signals when explicitly required (mentorship, cross-functional, technical leadership, ...)

ALIASES — include only widely-used short forms or near-synonyms:
- "Kubernetes" → ["k8s"]
- "Google Cloud" → ["GCP"]
- "PostgreSQL" → ["Postgres"]
- "JavaScript" → ["JS"]
- DO NOT invent aliases. If unsure, leave the list empty.

MUST_HAVE_PHRASES — extract literal substrings from the JD that an ATS keyword filter is likely to use. Years-of-experience phrases ("3+ years of X"), required degrees, required certifications, and explicit "must have" callouts. Cap at ~8 phrases.

CANONICALIZATION:
- Use the most common canonical spelling: "PostgreSQL" not "postgres", "Node.js" not "nodejs", "REST APIs" not "REST".
- Deduplicate: a term and its alias do NOT both appear as separate hard_skills entries.
- Cap hard_skills at 25 and soft_signals at 10. Quality over quantity.
"""


_client_singleton: Optional[Anthropic] = None


def _client() -> Anthropic:
    global _client_singleton
    if _client_singleton is None:
        if not config.ANTHROPIC_API_KEY:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Edit .env and restart the server."
            )
        _client_singleton = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client_singleton


def _extract_tagged_json(text: str) -> dict:
    m = re.search(r"<json>\s*(\{.*?\})\s*</json>", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    m = re.search(r"(\{.*\})", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    raise ValueError(f"No JSON in response: {text[:400]}")


def _jd_hash(jd_text: str, title: str, company: str) -> str:
    h = hashlib.sha256()
    h.update(title.strip().encode("utf-8"))
    h.update(b"\x00")
    h.update(company.strip().encode("utf-8"))
    h.update(b"\x00")
    h.update(jd_text.strip().encode("utf-8"))
    return h.hexdigest()


_spec_cache: dict[str, dict] = {}
_SPEC_CACHE_DIR = config.DATA_DIR / "jd_spec_cache"


def _spec_cache_path(digest: str) -> Path:
    return _SPEC_CACHE_DIR / f"{digest}.json"


def _load_cached_spec(digest: str) -> Optional[dict]:
    mem = _spec_cache.get(digest)
    if mem is not None:
        return mem
    path = _spec_cache_path(digest)
    if not path.exists():
        return None
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    _spec_cache[digest] = spec
    return spec


def _save_cached_spec(digest: str, spec: dict) -> None:
    _spec_cache[digest] = spec
    try:
        _SPEC_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _spec_cache_path(digest).write_text(
            json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        # Cache is best-effort; running without disk persistence is fine.
        pass


def analyze_jd(
    jd_text: str,
    *,
    title: str = "",
    company: str = "",
) -> dict:
    """Return the structured keyword spec for a JD. Cached by content hash
    in-memory and on disk under DATA_DIR/jd_spec_cache/."""
    if not jd_text or not jd_text.strip():
        raise ValueError("Empty JD text.")

    digest = _jd_hash(jd_text, title, company)
    cached = _load_cached_spec(digest)
    if cached is not None:
        return cached

    user = (
        f"Job title: {title or '(unknown)'}\n"
        f"Company: {company or '(unknown)'}\n"
        f"\nJob description:\n{jd_text.strip()[:18000]}"
    )

    resp = _client().messages.create(
        model=config.EXTRACT_MODEL,
        max_tokens=4000,
        temperature=0,
        system=_JD_ANALYZER_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    spec = _extract_tagged_json(text)
    spec = _normalize(spec)
    _save_cached_spec(digest, spec)
    return spec


def _normalize(spec: dict) -> dict:
    """Defensive cleanup so downstream passes can trust the shape."""
    out = {
        "role_family": (spec.get("role_family") or "").strip(),
        "seniority": (spec.get("seniority") or None),
        "years_required": spec.get("years_required"),
        "hard_skills": [],
        "soft_signals": [],
        "must_have_phrases": [],
    }
    if isinstance(out["seniority"], str):
        out["seniority"] = out["seniority"].strip().lower() or None
    yr = out["years_required"]
    if isinstance(yr, bool):
        out["years_required"] = None
    elif isinstance(yr, int):
        pass
    elif isinstance(yr, float):
        out["years_required"] = int(yr)
    elif isinstance(yr, str) and yr.strip().isdigit():
        out["years_required"] = int(yr.strip())
    else:
        out["years_required"] = None

    seen_terms: set[str] = set()
    for item in spec.get("hard_skills") or []:
        term = (item.get("term") or "").strip()
        if not term:
            continue
        key = term.lower()
        if key in seen_terms:
            continue
        seen_terms.add(key)
        weight = item.get("weight")
        try:
            weight = max(0.0, min(1.0, float(weight)))
        except (TypeError, ValueError):
            weight = 0.5
        aliases = [a.strip() for a in (item.get("aliases") or []) if isinstance(a, str) and a.strip()]
        out["hard_skills"].append({"term": term, "weight": weight, "aliases": aliases})
    out["hard_skills"].sort(key=lambda s: s["weight"], reverse=True)

    soft_seen: set[str] = set()
    for item in spec.get("soft_signals") or []:
        term = (item.get("term") or "").strip()
        if not term:
            continue
        key = term.lower()
        if key in soft_seen:
            continue
        soft_seen.add(key)
        weight = item.get("weight")
        try:
            weight = max(0.0, min(1.0, float(weight)))
        except (TypeError, ValueError):
            weight = 0.5
        out["soft_signals"].append({"term": term, "weight": weight, "aliases": []})
    out["soft_signals"].sort(key=lambda s: s["weight"], reverse=True)

    for phrase in spec.get("must_have_phrases") or []:
        if isinstance(phrase, str) and phrase.strip():
            out["must_have_phrases"].append(phrase.strip())

    return out


if __name__ == "__main__":
    import sys
    from pathlib import Path

    from .scraping import fetch_job_posting

    if len(sys.argv) < 2:
        print("Usage: python -m app.jd_analyzer <url-or-textfile>", file=sys.stderr)
        sys.exit(2)

    arg = sys.argv[1]
    if arg.startswith("http://") or arg.startswith("https://"):
        info = fetch_job_posting(arg)
        title = info.get("title", "")
        company = info.get("company", "")
        jd_text = info.get("description", "")
    else:
        p = Path(arg)
        jd_text = p.read_text(encoding="utf-8")
        title = ""
        company = ""

    spec = analyze_jd(jd_text, title=title, company=company)
    print(json.dumps(spec, indent=2, ensure_ascii=False))

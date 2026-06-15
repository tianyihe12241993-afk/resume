"""Relevance scoring: rate discovered jobs 0-100 against a profile's resume.

Uses the cheap EXTRACT_MODEL (Claude Haiku) and batches several jobs per call.
Each job gets an integer `score` and a one-line `score_reason` for the review UI.
"""
from __future__ import annotations

import json
import re

from anthropic import Anthropic
from docx import Document

from app import config as app_config

from . import storage

BATCH = 8          # jobs per Haiku call
MAX_JOBS = 100     # hard cap on jobs scored per discovery run
_DESC_CHARS = 1500


def _client() -> Anthropic:
    return Anthropic(api_key=app_config.ANTHROPIC_API_KEY)


def resume_plaintext(profile_id: int) -> str:
    path = storage.base_resume_path(profile_id)
    if not path.exists():
        return ""
    try:
        doc = Document(str(path))
    except Exception:
        return ""
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _extract_json_array(text: str) -> list:
    m = re.search(r"<json>\s*(\[.*?\])\s*</json>", text, re.DOTALL)
    if not m:
        m = re.search(r"(\[.*\])", text, re.DOTALL)
    if not m:
        raise ValueError(f"No JSON array in response: {text[:300]}")
    return json.loads(m.group(1))


def score_jobs(profile_id: int, jobs: list[dict], preferences: str = "") -> list[dict]:
    """Annotate each job with `score` (0-100) and `score_reason`, sorted desc.

    Mutates and returns the input list (capped to MAX_JOBS). If scoring can't run
    (no API key / no resume), jobs keep score=None and original order.
    """
    jobs = jobs[:MAX_JOBS]
    resume = resume_plaintext(profile_id)[:6000]
    if not jobs or not resume or not app_config.ANTHROPIC_API_KEY:
        for j in jobs:
            j.setdefault("score", None)
            j.setdefault("score_reason", None)
        return jobs

    client = _client()
    pref = (preferences or "").strip() or "(none specified)"

    for start in range(0, len(jobs), BATCH):
        chunk = jobs[start:start + BATCH]
        listing = "\n\n".join(
            f"[{i}] {j.get('title','')} @ {j.get('company','')} "
            f"({j.get('location','')})\n{(j.get('description') or '')[:_DESC_CHARS]}"
            for i, j in enumerate(chunk)
        )
        prompt = f"""You rank how well jobs fit a candidate. Score each job 0-100 for fit with the candidate's resume and stated preferences. 100 = ideal match (seniority, skills, domain all align); 0 = irrelevant. Be discriminating — do not give everything a high score.

CANDIDATE PREFERENCES: {pref}

CANDIDATE RESUME:
{resume}

JOBS:
{listing}

Return ONLY <json>[{{"i": <index>, "score": <int 0-100>, "reason": "<=12 words"}}, ...]</json> with one object per job index above."""

        try:
            resp = client.messages.create(
                model=app_config.EXTRACT_MODEL,
                max_tokens=1200,
                messages=[{"role": "user", "content": prompt}],
            )
            arr = _extract_json_array(resp.content[0].text)
            by_i = {int(o["i"]): o for o in arr if "i" in o}
        except Exception:
            by_i = {}

        for i, j in enumerate(chunk):
            o = by_i.get(i)
            if o is not None:
                try:
                    j["score"] = max(0, min(100, int(o.get("score"))))
                except Exception:
                    j["score"] = None
                j["score_reason"] = (o.get("reason") or "").strip() or None
            else:
                j["score"] = None
                j["score_reason"] = None

    jobs.sort(key=lambda j: (j.get("score") if j.get("score") is not None else -1),
              reverse=True)
    return jobs

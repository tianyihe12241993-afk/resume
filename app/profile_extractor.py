"""Deep candidate profile extraction.

Once per uploaded resume, we run Sonnet over the full document and produce a
structured "candidate corpus" that the bullet rewriter uses as additional
grounding. The base-resume text alone is too sparse — a bullet like "Built
mail backend services" tells the rewriter nothing about the 200K-concurrent
Netty/NIO work that was actually done. This extractor surfaces every named
and implicit skill, every signature system, every domain the candidate
worked in.

Cache key: SHA-256 of the resume's plain text + prompt version.
Disk path: ``data/profile_cache/{sha256}.json``.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Optional

from anthropic import Anthropic

from . import config
from .llm import make_client


# Bump this when the extraction prompt changes — old caches become invalid.
_PROFILE_PROMPT_VERSION = "1"


_PROFILE_CACHE_DIR = config.DATA_DIR / "profile_cache"


_SYSTEM = """You are an expert at reading a resume and extracting the candidate's full implicit and explicit experience corpus.

Your job: produce a structured profile that a downstream resume rewriter will use as evidence when tailoring bullets to a target job description. The rewriter sees one bullet at a time; without your profile it has no idea what the candidate has actually done across the whole resume.

Be aggressive about extraction. The goal is COVERAGE — surface every skill, domain, system, and capability that this candidate can legitimately defend in an interview based on what's written in the resume. Do not invent things, but do infer reasonable implications.

Output STRICT JSON inside <json>…</json> tags. No prose outside.

{
  "all_skills": [string]
      // Every named skill, tech, language, framework, database, platform,
      // tool, methodology, protocol, library, or service mentioned anywhere
      // in the resume. Use canonical names ("PostgreSQL" not "postgres",
      // "Kubernetes" not "k8s"). Sort by approximate prominence in the resume.
      // Include 50+ items if the resume supports it.

  "implicit_skills": [string]
      // Skills the resume *implies* without naming. Examples:
      //   • "Built service handling 200K concurrent connections" → distributed systems,
      //     high-concurrency engineering, capacity planning, performance optimization
      //   • "Mentored 5 engineers" → mentorship, tech leadership, code review
      //   • "On-call rotation across 1000+ servers" → SRE, incident response, observability
      //   • "Cross-colocation deployment" → multi-region, deployment automation, networking
      // Include 20+ items if reasonable.

  "domains": [string]
      // Areas of expertise this resume documents (3-10 items). E.g.
      // "backend infrastructure", "ML systems", "ad-tech", "mail platforms",
      // "developer tools", "data platforms". Be specific to the resume.

  "signature_systems": [
    {
      "name": string,         // e.g. "Yahoo Mail IMAP service"
      "summary": string,      // 1-sentence description grounded in the resume
      "scale": string,        // numbers if mentioned: "200K concurrent connections / 1000+ servers"
      "tech": [string]        // tech stack used
    }
  ]
      // The 3-8 systems/products the candidate clearly built, scaled, or
      // owned, with the actual numbers from the resume.

  "quantified_achievements": [
    {"metric": string, "context": string}
  ]
      // Every measurable result with its context. "30% latency reduction —
      // re-architected messaging flow". Include all numbers from the resume.

  "industries": [string]
      // 1-5 industries / verticals (search, ads, e-commerce, mail, fintech,
      // autonomous vehicles, etc.) the resume covers.

  "canonical_strengths": string
      // 2-3 sentence summary of what makes this candidate distinctive.
      // Tone: factual, specific, no marketing language.
}

Extraction guidelines:
- Read every bullet. Many bullets contain MULTIPLE skills, list them all.
- "Built X using Y, Z" → X, Y, Z all go in all_skills.
- Recognize implicit work: an IMAP server implies distributed systems, networking, concurrency, protocol implementation.
- Use canonical names. "Java NIO" → both "Java" and "NIO".
- Include both broad terms ("distributed systems") and narrow terms ("Netty framework").
- Never invent skills not grounded in the resume text.
- Aim for COMPLETENESS over brevity. A long list is better than a short one — the rewriter benefits from more evidence to draw on.
"""


def _key(text: str) -> str:
    h = hashlib.sha256()
    h.update(_PROFILE_PROMPT_VERSION.encode("utf-8"))
    h.update(b"\x00")
    h.update(text.strip().encode("utf-8"))
    return h.hexdigest()


def _cache_path(key: str) -> Path:
    return _PROFILE_CACHE_DIR / f"{key}.json"


_mem_cache: dict[str, dict] = {}


def _client() -> Anthropic:
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")
    return make_client()


def _extract_json(text: str) -> dict:
    """Pull the JSON object out of Claude's <json>…</json> output."""
    m = re.search(r"<json>\s*(\{.*?\})\s*</json>", text, re.DOTALL)
    if not m:
        m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not m:
        m = re.search(r"(\{.*\})", text, re.DOTALL)
    if not m:
        raise ValueError("No JSON in profile-extractor response.")
    return json.loads(m.group(1))


def extract_candidate_profile(resume_text: str) -> dict:
    """Return the structured candidate profile for ``resume_text``.

    Disk-cached by content hash + prompt version. Re-uploads of the same
    document are free; resume edits invalidate the cache automatically.
    """
    resume_text = (resume_text or "").strip()
    if not resume_text:
        return _empty_profile()

    key = _key(resume_text)
    if key in _mem_cache:
        return _mem_cache[key]
    p = _cache_path(key)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            _mem_cache[key] = data
            return data
        except (OSError, json.JSONDecodeError):
            pass

    client = _client()
    resp = client.messages.create(
        model=config.TAILOR_MODEL,  # Sonnet — worth it for a one-time per-resume pass
        max_tokens=4000,
        temperature=0,
        system=[{"type": "text", "text": _SYSTEM}],
        messages=[{
            "role": "user",
            "content": (
                "Extract the candidate's full experience profile from the "
                f"resume below.\n\n<resume>\n{resume_text[:30_000]}\n</resume>"
            ),
        }],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    try:
        data = _extract_json(text)
    except (ValueError, json.JSONDecodeError):
        return _empty_profile()

    # Normalize shape: every expected key is present so callers can rely on it.
    data = _normalize(data)

    try:
        _PROFILE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    _mem_cache[key] = data
    return data


def _empty_profile() -> dict:
    return {
        "all_skills": [], "implicit_skills": [], "domains": [],
        "signature_systems": [], "quantified_achievements": [],
        "industries": [], "canonical_strengths": "",
    }


def _normalize(d: dict) -> dict:
    out = _empty_profile()
    for k in out.keys():
        v = d.get(k)
        if k == "canonical_strengths":
            out[k] = (v or "").strip() if isinstance(v, str) else ""
        elif isinstance(v, list):
            out[k] = v
    return out


def profile_summary_text(profile: dict, *, max_chars: int = 6000) -> str:
    """Render the profile as a compact text block for the bullet rewriter's
    cached prompt prefix. Keep under ~6K chars so it doesn't dominate the
    token budget."""
    if not profile or not isinstance(profile, dict):
        return ""
    bits: list[str] = []

    cs = profile.get("canonical_strengths") or ""
    if cs:
        bits.append(f"WHO THIS CANDIDATE IS: {cs}")

    skills = profile.get("all_skills") or []
    if skills:
        bits.append("ALL SKILLS (named + listed in the resume):\n" + ", ".join(skills))

    implicit = profile.get("implicit_skills") or []
    if implicit:
        bits.append("IMPLICIT SKILLS (inferred from accomplishments):\n" + ", ".join(implicit))

    domains = profile.get("domains") or []
    if domains:
        bits.append("DOMAINS: " + ", ".join(domains))

    signature = profile.get("signature_systems") or []
    if signature:
        sig_lines = []
        for s in signature[:8]:
            n = (s.get("name") or "").strip()
            summ = (s.get("summary") or "").strip()
            scale = (s.get("scale") or "").strip()
            tech = ", ".join(s.get("tech") or [])
            line = f"- {n}"
            if summ: line += f": {summ}"
            if scale: line += f" [{scale}]"
            if tech: line += f" — tech: {tech}"
            sig_lines.append(line)
        bits.append("SIGNATURE SYSTEMS:\n" + "\n".join(sig_lines))

    achievements = profile.get("quantified_achievements") or []
    if achievements:
        a_lines = [f"- {a.get('metric','')}: {a.get('context','')}".strip()
                   for a in achievements[:15] if a.get("metric")]
        if a_lines:
            bits.append("QUANTIFIED RESULTS:\n" + "\n".join(a_lines))

    text = "\n\n".join(bits)
    if len(text) > max_chars:
        text = text[:max_chars] + "…"
    return text

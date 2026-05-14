"""Adjacency proposer — Pass 2.5 between coverage_map and bullet_rewriter.

The deterministic adjacency dict in coverage_map.py only catches tech-to-tech
relationships (Spring Boot → Java). It's blind to concept-level adjacencies
that emerge from how a candidate phrases real work — "production monitoring,
telemetry, structured logging" is observability under a different name, but
the dict has no entry for it.

This module fills the gap with one Haiku call per gap term. Each call sees
every bullet at once and proposes up to 3 truthful matches with verbatim
supporting language. Promotions get appended to `covered_adjacent`; the
coverage summary is recomputed. The defensive validator rejects any LLM
citation whose supporting_language isn't actually a substring of the cited
bullet — protects against citation hallucinations.
"""
from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from anthropic import Anthropic

from . import config
from .tailoring import ResumeStruct


_SYSTEM = """You evaluate whether a JD requirement is truthfully supported by something in a candidate's resume bullets — even when the resume uses different words.

Be conservative. The candidate must have ACTUALLY DONE WORK that evidences the requirement. "Adjacent" is acceptable; "aspirational" is NOT. If you cannot point to specific language in the bullet that supports the claim, return no match.

You will be given ONE JD term and the candidate's full bullet list. Return at most 3 strongest matches.

A match is valid only when:
- The bullet's verbatim language describes work the candidate performed that DEMONSTRATES the JD term's underlying capability.
- A reasonable hiring manager would agree the bullet is evidence — not just topically adjacent.

VALID adjacency examples:
- JD: "observability" — bullet says "production monitoring, telemetry, and structured logging" → MATCH (the work IS observability under a different name).
- JD: "concurrent architectures" — bullet says "async background workers with retry-safe job queues" → MATCH.
- JD: "real-time systems" — bullet says "WebSocket-based dashboards updating sub-second on backend events" → MATCH.

INVALID adjacency examples:
- JD: "Kafka" — bullet says "built event pipelines" → NO MATCH (could be batch, queues, anything; doesn't evidence Kafka specifically).
- JD: "machine learning" — bullet says "used SQL to analyze user data" → NO MATCH (SQL analysis is not ML).
- JD: "TypeScript" — bullet says "wrote frontend components in React" → NO MATCH (React != TypeScript).
- JD: "Pipecat" — anything other than Pipecat itself → NO MATCH (named-product gaps require the product name).

HARD REJECT — distinct outputs or opposite directions whose interview questions diverge completely:
- JD: "TTS" / "text-to-speech" — bullet describes "ASR" / "speech recognition" / "transcription" → NO MATCH. TTS produces audio FROM text; ASR produces text FROM audio. They are opposite-direction technologies that require entirely different models, training data, and engineering. Working on one is NOT evidence of the other.
- JD: "model training" — bullet describes only model inference / serving → NO MATCH (and vice versa). Different careers, different toolchains.
- JD: "<a specific named product>" (e.g. Pipecat, Daily, Snowflake) — anything other than that product → NO MATCH. Named-product gaps require the product name.

PERMITTED bridges (admit these as MATCH when the supporting language is concrete):
- Backend ↔ frontend bullets in full-stack work — full-stack bullets that describe BOTH client and server logic count as evidence of backend OR frontend.
- "API design / API integration" — bullets describing REST/GraphQL endpoint design, schema work, or service-to-service integration count, even when phrased as frontend orchestration.
- "Data engineering / ETL pipelines" — bullets describing transformation flows, scheduled jobs, or data-quality steps that ingest, normalize, or move data between systems count.
- "Distributed systems" — bullets describing async workers, queues, multi-service coordination, or fan-out/fan-in patterns count.
- "Production AI / model serving" — bullets describing deploying, scaling, or monitoring AI/ML systems in production (even if the candidate didn't train the model) count toward "model serving" but NOT "model training".
- "Observability" — bullets that name any TWO of {logging, metrics, monitoring, tracing, alerting, telemetry, structured logs, dashboards} count.
- "Streaming / real-time" — bullets describing WebSocket flows, event-driven dashboards, real-time feeds, sub-second update loops, or message-queue-driven UIs count.

THE GENERAL RULE: prefer admitting a defensible bridge to leaving it as a gap, AS LONG AS the supporting_language quotes a concrete piece of work and the candidate could speak to the cited bullet in an interview. The HARD REJECT list is the floor — those are claims the candidate cannot defend. Everything else is on a continuum and you should err on the side of MATCH when the bullet shows real adjacent work.

OUTPUT FORMAT — strict JSON inside <json>...</json> tags. No prose outside.

{
  "matches": [
    {
      "job_idx": <int>,
      "bullet_idx": <int>,
      "supporting_language": "<VERBATIM substring of the cited bullet — exact characters, no paraphrasing>",
      "rationale": "<one sentence: why this bullet evidences the JD term>"
    }
  ]
}

If no bullet truthfully evidences the JD term, return {"matches": []}.

Better zero matches than a stretched match. Stretched matches mislead the downstream rewriter and cause hallucinations downstream.
"""


_client_singleton: Optional[Anthropic] = None


def _client() -> Anthropic:
    global _client_singleton
    if _client_singleton is None:
        if not config.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY is not set. Edit .env and restart the server.")
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


def _format_bullets(resume: ResumeStruct) -> str:
    lines: list[str] = []
    for j, job in enumerate(resume.jobs):
        for b, bullet in enumerate(job.bullets):
            t = (bullet or "").strip()
            if t:
                lines.append(f"[job {j} bullet {b}]: {t}")
    return "\n".join(lines)


def _validate_match(match: dict, resume: ResumeStruct) -> bool:
    """The supporting_language must be a verbatim substring of the cited bullet.

    Catches both citation hallucinations (LLM points at the wrong bullet) and
    paraphrasing (LLM quotes "monitoring" but the bullet actually says
    "production monitoring").
    """
    ji = match.get("job_idx")
    bi = match.get("bullet_idx")
    sl = match.get("supporting_language", "")
    if not isinstance(ji, int) or not isinstance(bi, int) or not sl:
        return False
    if ji < 0 or ji >= len(resume.jobs):
        return False
    job = resume.jobs[ji]
    if bi < 0 or bi >= len(job.bullets):
        return False
    return sl.strip().lower() in (job.bullets[bi] or "").lower()


_ADJ_CACHE_DIR = config.DATA_DIR / "adjacency_cache"
_adj_mem_cache: dict[str, list[dict]] = {}


def _adj_cache_key(term: str, weight: float, role_family: str, bullets_block: str) -> str:
    blob = json.dumps({
        "model": config.EXTRACT_MODEL,
        "system": _SYSTEM,
        "term": term,
        "weight": round(float(weight), 3),
        "role_family": role_family,
        "bullets": bullets_block,
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _propose_for_term(term: str, weight: float, role_family: str, bullets_block: str) -> list[dict]:
    """One Haiku call. Returns raw match dicts (pre-validation). Cached on disk."""
    key = _adj_cache_key(term, weight, role_family, bullets_block)
    cached = _adj_mem_cache.get(key)
    if cached is None:
        path = _ADJ_CACHE_DIR / f"{key}.json"
        if path.exists():
            try:
                cached = json.loads(path.read_text(encoding="utf-8"))
                _adj_mem_cache[key] = cached
            except (OSError, json.JSONDecodeError):
                cached = None
    if cached is not None:
        return cached

    user = (
        f"JD TERM: \"{term}\" (weight {weight:.2f})\n"
        f"JD ROLE: {role_family or '(unknown)'}\n\n"
        f"RESUME BULLETS:\n{bullets_block}\n\n"
        f"For the JD term, identify up to 3 bullets whose actual content truthfully evidences this term. "
        f"Quote the supporting language verbatim. Better none than a stretched match."
    )
    resp = _client().messages.create(
        model=config.EXTRACT_MODEL,
        max_tokens=900,
        temperature=0,
        system=_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    parsed = _extract_tagged_json(text)
    out: list[dict] = []
    for m in parsed.get("matches") or []:
        if not isinstance(m, dict):
            continue
        sl = (m.get("supporting_language") or "").strip()
        ji = m.get("job_idx")
        bi = m.get("bullet_idx")
        if not sl or not isinstance(ji, int) or not isinstance(bi, int):
            continue
        out.append({
            "job_idx": ji,
            "bullet_idx": bi,
            "supporting_language": sl,
            "rationale": (m.get("rationale") or "").strip(),
        })
    _adj_mem_cache[key] = out
    try:
        _ADJ_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (_ADJ_CACHE_DIR / f"{key}.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass
    return out


def propose_adjacencies(
    spec: dict,
    coverage_map: dict,
    resume: ResumeStruct,
    *,
    parallel: int = 6,
    min_weight: float = 0.0,
) -> dict:
    """Augment `coverage_map` by promoting LLM-found adjacencies from gap.

    Returns a NEW coverage map. The original is not mutated.
    """
    hard = (coverage_map.get("hard_skills") or {})
    gap = list(hard.get("gap") or [])
    if not gap:
        return coverage_map

    bullets_block = _format_bullets(resume)
    if not bullets_block.strip():
        return coverage_map

    role_family = spec.get("role_family") or ""
    targets = [g for g in gap if float(g.get("weight") or 0.0) >= min_weight]
    if not targets:
        return coverage_map

    def _run(gap_entry: dict) -> tuple[dict, list[dict]]:
        term = gap_entry.get("term", "")
        weight = float(gap_entry.get("weight") or 0.0)
        try:
            raw = _propose_for_term(term, weight, role_family, bullets_block)
        except Exception:
            raw = []
        valid = [m for m in raw if _validate_match(m, resume)]
        return gap_entry, valid

    if parallel > 1 and len(targets) > 1:
        with ThreadPoolExecutor(max_workers=parallel) as ex:
            futs = [ex.submit(_run, g) for g in targets]
            results = [f.result() for f in as_completed(futs)]
    else:
        results = [_run(g) for g in targets]

    by_term: dict[str, list[dict]] = {entry.get("term", ""): matches for entry, matches in results}

    promoted: list[dict] = []
    new_gap: list[dict] = []
    for g in gap:
        term = g.get("term")
        matches = by_term.get(term, []) if term else []
        if matches:
            via_entries: list[dict] = []
            for m in matches:
                via_entries.append({
                    "via": m["supporting_language"],
                    "rationale": m.get("rationale", ""),
                    "evidence": [{
                        "section": "bullet",
                        "job_idx": m["job_idx"],
                        "bullet_idx": m["bullet_idx"],
                        "text": resume.jobs[m["job_idx"]].bullets[m["bullet_idx"]],
                    }],
                })
            promoted.append({
                "term": term,
                "weight": float(g.get("weight") or 0.0),
                "via": via_entries,
                "source": "llm_proposed",
            })
        else:
            new_gap.append(g)

    new_hard = {
        "covered_exact": list(hard.get("covered_exact") or []),
        "covered_adjacent": list(hard.get("covered_adjacent") or []) + promoted,
        "gap": new_gap,
    }

    spec_skills = spec.get("hard_skills") or []
    total_w = sum(float(s.get("weight") or 0.0) for s in spec_skills)
    if total_w > 0:
        covered_w = (
            sum(float(s.get("weight") or 0.0) for s in new_hard["covered_exact"])
            + 0.7 * sum(float(s.get("weight") or 0.0) for s in new_hard["covered_adjacent"])
        )
        weighted = covered_w / total_w
    else:
        weighted = 0.0

    out = dict(coverage_map)
    out["hard_skills"] = new_hard
    out["summary"] = {
        "exact_count": len(new_hard["covered_exact"]),
        "adjacent_count": len(new_hard["covered_adjacent"]),
        "gap_count": len(new_hard["gap"]),
        "weighted_coverage": round(weighted, 3),
        "llm_promotions": len(promoted),
    }
    return out


if __name__ == "__main__":
    import sys
    from pathlib import Path

    from .coverage_map import build_coverage_map
    from .jd_analyzer import analyze_jd
    from .scraping import fetch_job_posting
    from .tailoring import parse_resume_from_path

    if len(sys.argv) < 3:
        print(
            "Usage: python -m app.adjacency_proposer <jd-url-or-textfile> <resume.docx>",
            file=sys.stderr,
        )
        sys.exit(2)

    jd_arg = sys.argv[1]
    resume_path = Path(sys.argv[2])

    if jd_arg.startswith(("http://", "https://")):
        info = fetch_job_posting(jd_arg)
        spec = analyze_jd(
            info.get("description", ""),
            title=info.get("title", ""),
            company=info.get("company", ""),
        )
    else:
        spec = analyze_jd(Path(jd_arg).read_text(encoding="utf-8"))

    resume = parse_resume_from_path(resume_path)
    base = build_coverage_map(spec, resume)
    augmented = propose_adjacencies(spec, base, resume)

    print("=== Coverage BEFORE adjacency proposer ===")
    print(json.dumps(base["summary"], indent=2))
    print("\n=== Coverage AFTER adjacency proposer ===")
    print(json.dumps(augmented["summary"], indent=2))

    print("\n=== LLM-proposed promotions ===")
    promotions = [p for p in augmented["hard_skills"]["covered_adjacent"] if p.get("source") == "llm_proposed"]
    if not promotions:
        print("(none)")
    for p in promotions:
        print(f"\n* {p['term']} (weight {p['weight']:.2f})")
        for v in p["via"]:
            ev = v["evidence"][0]
            print(f"  via: {v['via']!r}")
            print(f"    [job {ev['job_idx']} bullet {ev['bullet_idx']}]: {ev['text'][:140].strip()}{'…' if len(ev['text']) > 140 else ''}")
            if v.get("rationale"):
                print(f"    why: {v['rationale']}")

    print("\n=== Remaining gaps ===")
    for g in augmented["hard_skills"]["gap"]:
        print(f"  - {g['term']} (weight {g.get('weight', 0):.2f})")

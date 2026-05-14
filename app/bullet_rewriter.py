"""Bullet rewriter — pass 3 of the constrained-rewrite pipeline.

Per-bullet Sonnet call. Each call receives:
- the original bullet
- the per-bullet allow-list (covered_adjacent JD terms whose via-evidence is in
  this exact bullet — these are the terms an upstream check verified truthful
  for THIS bullet, not just somewhere on the resume)
- canonicalization swaps available for terms the bullet already mentions as an
  alias (k8s → Kubernetes when the JD uses Kubernetes)
- the top-weighted gap terms as an explicit "off-limits" list

The model returns {rewritten, surfaced, reason}. Output flows through the
deterministic validator (pass 4); failed validations revert to the original
and the failure reason is preserved on the result.
"""
from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from anthropic import Anthropic

from . import config
from .bullet_validator import apply_to_bullets
from .tailoring import ResumeStruct


_REWRITE_CACHE_DIR = config.DATA_DIR / "bullet_rewrite_cache"
_rewrite_mem_cache: dict[str, dict] = {}


def _rewrite_cache_key(
    bullet: str,
    surfaceable: list[dict],
    canonicalize: list[tuple[str, str]],
    forbidden: list[str],
    jd_hard_skills: list[dict] | None = None,
    jd_text: str = "",
) -> str:
    """Hash all inputs that determine the rewriter's output. Same inputs
    -> same key -> same cached result, regardless of API non-determinism.

    `jd_hard_skills` is included because it's now part of the prompt prefix
    (added to clear Sonnet's 1024-token minimum cacheable-prefix threshold);
    entries written before prompt caching was introduced will not collide.
    """
    norm = {
        "model": config.TAILOR_MODEL,
        "system": _SYSTEM,
        "bullet": bullet.strip(),
        "surfaceable": sorted(
            [(s.get("term", ""), round(float(s.get("weight") or 0.0), 3),
              s.get("via", ""))
             for s in (surfaceable or [])]
        ),
        "canonicalize": sorted([(a, c) for a, c in (canonicalize or ())]),
        "forbidden": sorted([t for t in (forbidden or [])]),
        "jd_hard_skills": sorted(
            [(s.get("term", ""), round(float(s.get("weight") or 0.0), 3))
             for s in (jd_hard_skills or [])]
        ) if jd_hard_skills else None,
        # Hash the JD text rather than store it raw — keeps keys short.
        "jd_text_hash": hashlib.sha256((jd_text or "").strip().encode("utf-8")).hexdigest() if jd_text else None,
    }
    blob = json.dumps(norm, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _load_cached_rewrite(key: str) -> Optional[dict]:
    mem = _rewrite_mem_cache.get(key)
    if mem is not None:
        return mem
    path = _REWRITE_CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    try:
        out = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    _rewrite_mem_cache[key] = out
    return out


def _save_cached_rewrite(key: str, out: dict) -> None:
    _rewrite_mem_cache[key] = out
    try:
        _REWRITE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (_REWRITE_CACHE_DIR / f"{key}.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


_SYSTEM = """You rewrite a single resume bullet to better match a target job posting. The candidate has confirmed they can defend any term on the "surfaceable" list in interview — your job is to weave JD vocabulary into the bullet wherever the bullet's content makes the introduction defensible. Aim to add at least one JD-relevant term to every bullet that has any topical overlap with the JD.

THREE IRON RULES — violations invalidate the output:
1. NEVER fabricate METRICS, EMPLOYERS, or PRODUCTS. Every percentage, latency, user count, team size, company name, and product name from the original must appear verbatim in the rewrite — do not change, drop, or add these.
2. The "surfaceable" list is JD vocabulary the candidate has confirmed they have experience with elsewhere on the resume. You may introduce ANY term from this list into the bullet, provided the bullet's content makes the term defensible (i.e. the work described is genuinely the kind of work that term refers to). The "canonicalize" list contains alias→canonical swaps (e.g. write "Kubernetes" where the original wrote "k8s") when the JD uses the canonical form.
3. The "off-limits" list contains JD terms the candidate has explicitly NOT claimed. NEVER mention them, even adjacently or aspirationally.

Be aggressive about surfacing — a rewrite that pulls in two or three JD terms naturally is better than a verbatim original. If the bullet describes work in a domain the JD cares about (backend, AI/ML, infra, etc.), find at least one JD term to weave in.

REWRITE GUIDELINES:
- Preserve every metric, every employer, every product, every tech name from the original — verbatim. You may add NEW tech terms from the surfaceable list, but you may not change or drop existing ones.
- Lead with JD-relevant nouns when natural. Promote JD vocabulary to the start of clauses.
- Shift verbs ("built" → "engineered", "designed" → "architected") to match JD seniority.
- Keep ≤ 1.5× the original's token count.
- Third-person action-verb voice. No "I", "we", "my", "our".
- Do not mention the target company name or target role title.
- If the original already covers a surfaceable term, do not duplicate it; pick a different one.

OUTPUT FORMAT — emit STRICT JSON inside <json>...</json> tags. No prose outside the tags.

{
  "rewritten": "<the rewritten bullet (or original verbatim if no improvement is possible)>",
  "surfaced": ["<term from surfaceable list you successfully worked in>", ...],
  "reason": "<one terse sentence: what you changed, or 'no change'>"
}
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


@dataclass
class BulletRewrite:
    job_idx: int
    bullet_idx: int
    original: str
    rewritten: str
    surfaced: list[str] = field(default_factory=list)
    reason: str = ""
    allowed_surface_terms: list[str] = field(default_factory=list)
    error: Optional[str] = None


def _build_per_bullet_allowlist(coverage_map: dict) -> dict[tuple[int, int], list[dict]]:
    """LEGACY restrictive variant: per-bullet allow-list scoped to terms whose
    via-evidence sits in that exact bullet. Kept for callers that want strict
    grounding. The default rewriter now uses the resume-wide allow-list below.
    """
    out: dict[tuple[int, int], list[dict]] = {}
    for entry in (coverage_map.get("hard_skills") or {}).get("covered_adjacent") or []:
        term = entry.get("term")
        weight = float(entry.get("weight") or 0.0)
        for via in entry.get("via") or []:
            for ev in via.get("evidence") or []:
                if ev.get("section") != "bullet":
                    continue
                j = ev.get("job_idx")
                b = ev.get("bullet_idx")
                if j is None or b is None:
                    continue
                out.setdefault((j, b), []).append({
                    "term": term,
                    "weight": weight,
                    "via": via.get("via", ""),
                })
    for key, items in out.items():
        seen: set[str] = set()
        unique: list[dict] = []
        for it in items:
            if it["term"].lower() in seen:
                continue
            seen.add(it["term"].lower())
            unique.append(it)
        unique.sort(key=lambda x: x["weight"], reverse=True)
        out[key] = unique
    return out


def _build_resume_wide_allowlist(
    coverage_map: dict, claimed_terms: list[str] | None = None,
) -> list[dict]:
    """Aggressive (default) variant: all JD terms the candidate has confirmed
    experience with — covered_exact + covered_adjacent (any evidence anywhere)
    + user-claimed terms. The rewriter gets this full list per bullet and
    weaves in whatever fits the bullet's content. Sorted by weight desc.
    """
    out: list[dict] = []
    seen: set[str] = set()

    hard = (coverage_map.get("hard_skills") or {})
    for entry in (hard.get("covered_exact") or []):
        term = (entry.get("term") or "").strip()
        if not term or term.lower() in seen:
            continue
        seen.add(term.lower())
        out.append({
            "term": term,
            "weight": float(entry.get("weight") or 0.0),
            "via": "exact",
        })
    for entry in (hard.get("covered_adjacent") or []):
        term = (entry.get("term") or "").strip()
        if not term or term.lower() in seen:
            continue
        seen.add(term.lower())
        # Pick a representative via-phrase if available so the rewriter has
        # context for which kind of work supports the term.
        via_label = "adjacent"
        for via in entry.get("via") or []:
            v = via.get("via")
            if v: via_label = v; break
        out.append({
            "term": term,
            "weight": float(entry.get("weight") or 0.0),
            "via": via_label,
        })
    for term in (claimed_terms or []):
        term = (term or "").strip()
        if not term or term.lower() in seen:
            continue
        seen.add(term.lower())
        out.append({"term": term, "weight": 1.0, "via": "user-claimed"})

    out.sort(key=lambda x: x["weight"], reverse=True)
    return out


def _build_aliases_dict(spec: dict) -> dict[str, list[str]]:
    """JD spec aliases as a {canonical: [aliases]} dict for the validator."""
    out: dict[str, list[str]] = {}
    for skill in spec.get("hard_skills") or []:
        term = skill.get("term")
        aliases = [a for a in (skill.get("aliases") or []) if isinstance(a, str) and a.strip()]
        if term and aliases:
            out[term] = aliases
    return out


def _bullet_canonical_swaps(bullet: str, aliases: dict[str, list[str]]) -> list[tuple[str, str]]:
    """Pairs of (alias_present_in_bullet, canonical_form) for THIS bullet only."""
    pairs: list[tuple[str, str]] = []
    for canonical, alts in aliases.items():
        for a in alts:
            if re.search(rf"(?<![A-Za-z0-9_-]){re.escape(a)}(?![A-Za-z0-9_-])", bullet, re.IGNORECASE):
                pairs.append((a, canonical))
                break
    return pairs


def _build_forbidden(
    coverage_map: dict,
    claimed_terms: list[str] | None = None,
    top_n: int = 6,
) -> list[str]:
    """Top-weighted gap terms the rewriter is told to never mention.
    Subtracts user-claimed terms — if you've claimed it, it's no longer a gap."""
    gaps = (coverage_map.get("hard_skills") or {}).get("gap") or []
    claimed_lower = {(t or "").lower() for t in (claimed_terms or [])}
    gaps_sorted = sorted(gaps, key=lambda g: float(g.get("weight") or 0.0), reverse=True)
    return [
        g["term"] for g in gaps_sorted
        if g.get("term") and g["term"].lower() not in claimed_lower
    ][:top_n]


def rewrite_bullet(
    bullet: str,
    surfaceable: list[dict],
    *,
    canonicalize: list[tuple[str, str]] = (),
    forbidden: list[str] = (),
    jd_hard_skills: list[dict] | None = None,
    jd_text: str = "",
) -> dict:
    """One Sonnet call. Returns {rewritten, surfaced, reason}.

    `surfaceable` items: {"term", "weight", "via" (optional)}.
    `canonicalize` pairs: (alias_in_bullet, canonical_form).
    `forbidden`: list of JD terms the rewriter must not mention.
    `jd_hard_skills`: full JD spec hard_skills list — useful additional
        context, also part of the cached prefix.
    `jd_text`: raw JD description — included as the bulk of the cached prefix
        so Sonnet 4.6's ~2048-token minimum cacheable-prefix threshold is
        comfortably cleared. Identical across all bullets within one
        rewrite_resume() call, so it gets paid for once per (JD, profile).
    """
    if not bullet or not bullet.strip():
        return {"rewritten": bullet, "surfaced": [], "reason": "empty input"}

    cache_key = _rewrite_cache_key(
        bullet, surfaceable, list(canonicalize), list(forbidden),
        jd_hard_skills=list(jd_hard_skills or []),
        jd_text=jd_text,
    )
    cached = _load_cached_rewrite(cache_key)
    if cached is not None:
        return cached

    if surfaceable:
        surface_block = "\n".join(
            f"- {s['term']} (weight {float(s['weight']):.2f})"
            + (f"  [via {s['via']}]" if s.get("via") else "")
            for s in surfaceable
        )
    else:
        surface_block = "(none — no JD-truthful terms to surface in this bullet)"

    if canonicalize:
        canonical_block = "\n".join(f"- {a} → {c}" for a, c in canonicalize)
    else:
        canonical_block = "(none)"

    forbidden_block = ", ".join(forbidden) if forbidden else "(none)"

    # Full JD-spec hard_skills list — context for the model + cache-prefix
    # padding so the shared block reliably clears Sonnet's 1024-token minimum.
    jd_skills_lines: list[str] = []
    for s in (jd_hard_skills or []):
        term = (s.get("term") or "").strip()
        if not term:
            continue
        weight = float(s.get("weight") or 0.0)
        aliases = ", ".join(s.get("aliases") or [])
        line = f"- {term} (weight {weight:.2f})"
        if aliases:
            line += f"  [aliases: {aliases}]"
        jd_skills_lines.append(line)
    jd_skills_block = "\n".join(jd_skills_lines) if jd_skills_lines else "(none provided)"

    # Prompt-caching layout: anything that's stable across the ~13 bullet calls
    # within one (JD, profile) run sits at the START of the prompt with
    # `cache_control: {type: ephemeral}` markers. Sonnet's prompt cache keys on
    # the exact prefix up to each marker, so:
    #   - System prompt: identical across every call ever → cached forever-ish
    #     (5-min TTL, refreshed on use)
    #   - Surfaceable + forbidden blocks: identical across all bullets within
    #     one rewrite_resume() invocation → cached for that batch.
    # Per-bullet content (the bullet itself + canonicalize swaps) is the only
    # part billed at full price on every call.
    resp = _client().messages.create(
        model=config.TAILOR_MODEL,
        max_tokens=800,
        temperature=0,
        system=[
            {
                "type": "text",
                "text": _SYSTEM,
                "cache_control": {"type": "ephemeral"},
            },
        ],
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "Target job description (for context — do not quote "
                        f"verbatim):\n<jd>\n{(jd_text or '').strip()[:18000]}\n</jd>\n\n"
                        "JD hard-skill terms with weights (full spec for "
                        f"context):\n{jd_skills_block}\n\n"
                        "Surfaceable terms (verified truthful for THIS bullet, "
                        f"weight 0–1):\n{surface_block}\n\n"
                        f"Off-limits (gaps — NEVER mention):\n{forbidden_block}"
                    ),
                    "cache_control": {"type": "ephemeral"},
                },
                {
                    "type": "text",
                    "text": (
                        f"Original bullet:\n{bullet}\n\n"
                        "Canonicalize (alias→canonical swaps allowed for this "
                        f"bullet):\n{canonical_block}"
                    ),
                },
            ],
        }],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    parsed = _extract_tagged_json(text)
    out = {
        "rewritten": (parsed.get("rewritten") or bullet).strip(),
        "surfaced": [s for s in (parsed.get("surfaced") or []) if isinstance(s, str) and s.strip()],
        "reason": (parsed.get("reason") or "").strip(),
    }
    _save_cached_rewrite(cache_key, out)
    return out


def rewrite_resume(
    resume: ResumeStruct,
    spec: dict,
    coverage_map: dict,
    *,
    parallel: int = 6,
    claimed_terms: list[str] | None = None,
    jd_text: str = "",
) -> list[BulletRewrite]:
    """Rewrite every bullet in the resume. Sonnet calls run in a ThreadPool.

    Result is sorted by (job_idx, bullet_idx). On per-bullet exceptions, the
    original is preserved and the error string is recorded on the result.
    """
    # Aggressive default: every bullet gets the full set of resume-wide
    # surfaceable terms (covered_exact + covered_adjacent + claimed). The
    # rewriter weaves in whatever fits the bullet's content.
    surfaceable_all = _build_resume_wide_allowlist(coverage_map, claimed_terms)
    aliases = _build_aliases_dict(spec)
    forbidden = _build_forbidden(coverage_map, claimed_terms=claimed_terms)
    # Pass the full JD hard_skills list to every rewrite call. Identical across
    # all bullets within one rewrite_resume() call → cached at the API level.
    jd_hard_skills = list(spec.get("hard_skills") or [])

    tasks: list[tuple[int, int, str, list[dict]]] = []
    for j_idx, job in enumerate(resume.jobs):
        for b_idx, bullet in enumerate(job.bullets):
            tasks.append((j_idx, b_idx, bullet, surfaceable_all))

    def _run(j: int, b: int, bullet: str, surfaceable: list[dict]) -> BulletRewrite:
        canonical = _bullet_canonical_swaps(bullet, aliases)
        try:
            out = rewrite_bullet(
                bullet,
                surfaceable,
                canonicalize=canonical,
                forbidden=forbidden,
                jd_hard_skills=jd_hard_skills,
                jd_text=jd_text,
            )
            return BulletRewrite(
                job_idx=j, bullet_idx=b, original=bullet,
                rewritten=out["rewritten"],
                surfaced=out["surfaced"],
                reason=out["reason"],
                allowed_surface_terms=[s["term"] for s in surfaceable],
            )
        except Exception as e:
            return BulletRewrite(
                job_idx=j, bullet_idx=b, original=bullet,
                rewritten=bullet,
                surfaced=[],
                reason="",
                allowed_surface_terms=[s["term"] for s in surfaceable],
                error=f"{type(e).__name__}: {e}",
            )

    results: list[BulletRewrite] = []
    if parallel > 1 and len(tasks) > 1:
        with ThreadPoolExecutor(max_workers=parallel) as ex:
            futs = [ex.submit(_run, j, b, bul, s) for (j, b, bul, s) in tasks]
            for fut in as_completed(futs):
                results.append(fut.result())
    else:
        for j, b, bul, s in tasks:
            results.append(_run(j, b, bul, s))

    results.sort(key=lambda r: (r.job_idx, r.bullet_idx))
    return results


def rewrite_and_validate(
    resume: ResumeStruct,
    spec: dict,
    coverage_map: dict,
    *,
    parallel: int = 6,
    max_length_ratio: float = 1.5,
    claimed_terms: list[str] | None = None,
    jd_text: str = "",
) -> list[dict]:
    """End-to-end pass 3 + pass 4. One dict per bullet:

    {job_idx, bullet_idx, original, rewritten, final, surfaced, reason,
     was_reverted, issues, error}

    `final` is what should actually be written to the docx — `rewritten` if it
    passed validation, `original` if it failed (or if the rewriter errored).
    """
    rewrites = rewrite_resume(
        resume, spec, coverage_map,
        parallel=parallel, claimed_terms=claimed_terms,
        jd_text=jd_text,
    )
    aliases = _build_aliases_dict(spec)

    pairs = [(r.original, r.rewritten) for r in rewrites]
    surface_per = [set(r.allowed_surface_terms) for r in rewrites]

    validations = apply_to_bullets(
        pairs,
        allowed_surface_terms_per_bullet=surface_per,
        aliases=aliases,
        max_length_ratio=max_length_ratio,
    )

    out: list[dict] = []
    for rw, val in zip(rewrites, validations):
        out.append({
            "job_idx": rw.job_idx,
            "bullet_idx": rw.bullet_idx,
            "original": rw.original,
            "rewritten": rw.rewritten,
            "final": val["final"],
            "surfaced": rw.surfaced,
            "reason": rw.reason,
            "was_reverted": val["was_reverted"],
            "issues": val["issues"],
            "error": rw.error,
        })
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
            "Usage: python -m app.bullet_rewriter <jd-url-or-textfile> <resume.docx>",
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
    cmap = build_coverage_map(spec, resume)
    results = rewrite_and_validate(resume, spec, cmap)

    print(f"\n=== Coverage summary ===")
    print(json.dumps(cmap["summary"], indent=2))
    print(f"\n=== Bullets ({len(results)} total) ===")
    n_changed = n_reverted = n_unchanged = 0
    for r in results:
        if r["error"]:
            marker = "ERR"
        elif r["was_reverted"]:
            marker = "REVERT"; n_reverted += 1
        elif r["original"].strip() == r["final"].strip():
            marker = "SAME"; n_unchanged += 1
        else:
            marker = "REWRITE"; n_changed += 1
        print(f"\n[job {r['job_idx']} bullet {r['bullet_idx']}] {marker}")
        print(f"  ORIG : {r['original']}")
        if r["original"].strip() != r["final"].strip():
            print(f"  FINAL: {r['final']}")
        if r["surfaced"]:
            print(f"  SURFACED: {r['surfaced']}")
        if r["was_reverted"]:
            print(f"  REVERTED (rewritten was): {r['rewritten']}")
            print(f"  ISSUES: {r['issues']}")
        if r["reason"] and r["reason"].lower() != "no change":
            print(f"  REASON: {r['reason']}")
        if r["error"]:
            print(f"  ERROR: {r['error']}")
    print(f"\n=== {n_changed} rewritten, {n_reverted} reverted, {n_unchanged} unchanged ===")

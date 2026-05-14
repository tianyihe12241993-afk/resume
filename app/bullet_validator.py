"""Bullet validator — pass 4 of the constrained-rewrite pipeline.

Deterministic guardrail. Every (original, rewritten) bullet pair the rewriter
emits passes through here. Pairs that fail any check are reverted to the
original; the failure reason is recorded so the bidder can see in a diff view
why a rewrite was rejected.

Four checks, in order of severity:

1. Hallucinated terms — rewritten introduces a tech-name-like noun that
   wasn't in the original AND isn't in the JD-supplied surface allow-list.
2. Dropped tech terms — a tech-name-like noun present in the original is
   missing from the rewritten (or its declared alias).
3. Dropped/modified metrics — every digit-bearing token in the original
   must appear verbatim in the rewritten.
4. Length blowout — rewritten token count > max_length_ratio × original.

The validator is intentionally over-inclusive on noun extraction (it picks
up "Senior" as well as "Kubernetes"). Symmetric extraction means common
capitalized English cancels out — what gets caught is real drift.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# Tech-name-like token shapes:
#   ACRONYM   — 2+ uppercase letters/digits (AWS, API, EKS, JWT, S3)
#   CAMEL     — PascalCase / camelCase with a second-word boundary (GraphQL, JavaScript, PostgreSQL)
#   DOT_TECH  — dot-bearing names (Node.js, Vue.js, .NET)
#   SYM_TECH  — `+`/`#` bearing names (C++, C#, F#)
#   PROPER    — single capitalized word mid-sentence (Walmart, Java, Python)
_ACRONYM   = re.compile(r"\b[A-Z][A-Z0-9]{1,}s?\b")
_CAMEL     = re.compile(r"\b[A-Z][a-z]+(?:[A-Z][a-zA-Z]*)+\b")
_DOT_TECH  = re.compile(r"\b[A-Za-z]+(?:\.[A-Za-z]+)+\b|\.[A-Z][A-Za-z]+\b")
_SYM_TECH  = re.compile(r"\b[A-Z][a-z]?\+\+|\b[A-Z][a-z]?#")
_PROPER    = re.compile(r"\b[A-Z][a-z]+\b")

_METRIC = re.compile(r"(?<!\w)\$?\d[\d.,]*[A-Za-z%]*")
_NAME_CHAR = r"[A-Za-z0-9_-]"


@dataclass
class ValidationResult:
    valid: bool
    issues: list[str] = field(default_factory=list)

    @property
    def first_issue(self) -> str | None:
        return self.issues[0] if self.issues else None


def extract_terms(text: str) -> set[str]:
    """Return the set of tech-name-like tokens in `text`, lowercased.

    Sentence-initial words are lowercased before extraction so capitalized
    sentence-starters ("Led", "Architected") don't get picked up as proper
    nouns.
    """
    if not text:
        return set()

    # Lowercase the first word of each sentence so sentence-starters are excluded.
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    normalized_parts: list[str] = []
    for s in sentences:
        if not s:
            continue
        # Find the first alphabetic char and lowercase from there to next non-letter.
        m = re.match(r"^([^A-Za-z]*)([A-Za-z]+)(.*)$", s, re.DOTALL)
        if m:
            normalized_parts.append(m.group(1) + m.group(2).lower() + m.group(3))
        else:
            normalized_parts.append(s)
    normalized = " ".join(normalized_parts)

    out: set[str] = set()
    for pat in (_ACRONYM, _CAMEL, _DOT_TECH, _SYM_TECH, _PROPER):
        for m in pat.finditer(normalized):
            tok = m.group(0)
            # Strip trailing pluralizing 's' from acronyms so "APIs" matches "API"
            if pat is _ACRONYM and tok.endswith("s") and len(tok) > 2:
                tok = tok[:-1]
            out.add(tok.lower())
    return out


def extract_metrics(text: str) -> list[str]:
    """Return digit-bearing tokens as they appear (preserves units like %, M, ms)."""
    if not text:
        return []
    return [m.group(0) for m in _METRIC.finditer(text)]


def _token_count(text: str) -> int:
    return len(text.split())


def _alias_groups(aliases: dict[str, list[str]] | None) -> list[set[str]]:
    """Return one lowercased equivalence class per canonical term."""
    if not aliases:
        return []
    groups: list[set[str]] = []
    for canonical, alts in aliases.items():
        if not isinstance(canonical, str) or not canonical.strip():
            continue
        members = {canonical.strip().lower()}
        for a in alts or []:
            if isinstance(a, str) and a.strip():
                members.add(a.strip().lower())
        groups.append(members)
    return groups


def _phrase_in(text_lower: str, phrase_lower: str) -> bool:
    """True if `phrase_lower` appears in `text_lower` with name-aware boundaries."""
    pat = re.compile(rf"(?<!{_NAME_CHAR}){re.escape(phrase_lower)}(?!{_NAME_CHAR})")
    return bool(pat.search(text_lower))


def _phrase_words(phrase: str) -> set[str]:
    """Constituent alphabetic word tokens of a phrase (lowercased)."""
    return {w.lower() for w in re.findall(r"[A-Za-z]+", phrase) if w}


def validate_bullet(
    original: str,
    rewritten: str,
    *,
    allowed_surface_terms: set[str] | list[str] = (),
    aliases: dict[str, list[str]] | None = None,
    max_length_ratio: float = 1.3,
) -> ValidationResult:
    """Validate a rewritten bullet against its original.

    Args:
        original: the bullet from the candidate's resume.
        rewritten: the rewriter's output.
        allowed_surface_terms: JD terms the rewriter was told it could surface
            (i.e. covered_exact + covered_adjacent terms relevant to this bullet).
        aliases: optional map of canonical_term -> [alias, ...]. If a term
            from the original is replaced by one of its aliases, that's allowed.
        max_length_ratio: rewritten can be at most this many times the
            original's token count.
    """
    issues: list[str] = []

    if not rewritten or not rewritten.strip():
        return ValidationResult(valid=False, issues=["rewritten bullet is empty"])

    rew_text = rewritten.strip()
    orig_lower = original.lower()
    rew_lower = rew_text.lower()
    orig_terms = extract_terms(original)
    rew_terms = extract_terms(rew_text)

    allowed_lc = {t.lower() for t in allowed_surface_terms if isinstance(t, str) and t.strip()}

    # Multi-word allow-list: if "ML systems" is in the allow-list and the
    # rewritten text contains the literal phrase "ml systems", the constituent
    # tokens ("ml", "systems") shouldn't count as hallucinations even though
    # the multi-word phrase isn't in the single-token allow-set. Mirrors the
    # multi-word alias logic below.
    allowed_phrase_tokens: set[str] = set()
    for term in allowed_surface_terms:
        if not isinstance(term, str) or not term.strip():
            continue
        if " " in term or "-" in term:
            if _phrase_in(rew_lower, term.lower()):
                allowed_phrase_tokens.update(_phrase_words(term))

    # Walk every alias group. If members appear in BOTH original and rewritten,
    # the rewriter performed a sanctioned alias substitution: the rewritten-side
    # tokens aren't hallucinations, and the original-side tokens are allowed to
    # be missing from the rewritten. This handles single-word (k8s↔Kubernetes)
    # and multi-word (GCP↔Google Cloud) substitutions uniformly.
    allowed_subst_tokens: set[str] = set()
    substituted_orig_tokens: set[str] = set()
    for group in _alias_groups(aliases):
        in_orig = [m for m in group if _phrase_in(orig_lower, m)]
        in_rew = [m for m in group if _phrase_in(rew_lower, m)]
        if in_orig and in_rew:
            for m in in_rew:
                allowed_subst_tokens.update(_phrase_words(m))
            for m in in_orig:
                substituted_orig_tokens.update(_phrase_words(m))

    # 1. Hallucinated terms.
    new_terms = rew_terms - orig_terms - allowed_lc - allowed_subst_tokens - allowed_phrase_tokens
    if new_terms:
        issues.append(f"hallucinated terms: {sorted(new_terms)}")

    # 2. Dropped tech terms.
    dropped = sorted(t for t in orig_terms if t not in rew_terms and t not in substituted_orig_tokens)
    if dropped:
        issues.append(f"dropped tech terms: {dropped}")

    # 3. Metric preservation. Every digit-bearing token in original must appear verbatim.
    orig_metrics = extract_metrics(original)
    missing_metrics: list[str] = []
    for m in orig_metrics:
        if m not in rew_text:
            missing_metrics.append(m)
    if missing_metrics:
        issues.append(f"missing/modified metrics: {missing_metrics}")

    # 4. Length blowout.
    orig_n = _token_count(original)
    rew_n = _token_count(rew_text)
    if orig_n > 0 and rew_n > orig_n * max_length_ratio:
        issues.append(
            f"length blowout: {rew_n} tokens > {max_length_ratio:.2f}× original "
            f"({orig_n})"
        )

    return ValidationResult(valid=not issues, issues=issues)


def apply_to_bullets(
    pairs: list[tuple[str, str]],
    *,
    allowed_surface_terms_per_bullet: list[set[str]] | None = None,
    aliases: dict[str, list[str]] | None = None,
    max_length_ratio: float = 1.3,
) -> list[dict]:
    """Validate a batch of (original, rewritten) pairs.

    Returns one dict per pair: {final, was_reverted, issues}. `final` is the
    bullet that should actually be written to the docx — `rewritten` if valid,
    `original` if any check failed.
    """
    out: list[dict] = []
    for i, (orig, rew) in enumerate(pairs):
        allowed = (
            allowed_surface_terms_per_bullet[i]
            if allowed_surface_terms_per_bullet and i < len(allowed_surface_terms_per_bullet)
            else set()
        )
        res = validate_bullet(
            orig, rew,
            allowed_surface_terms=allowed,
            aliases=aliases,
            max_length_ratio=max_length_ratio,
        )
        out.append({
            "final": rew if res.valid else orig,
            "was_reverted": not res.valid,
            "issues": res.issues,
        })
    return out

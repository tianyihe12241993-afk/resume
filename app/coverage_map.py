"""Coverage map — pass 2 of the constrained-rewrite pipeline.

Reads the JD spec from `jd_analyzer` and the candidate's `ResumeStruct`, and
tags every hard_skill from the spec as one of:

  - covered_exact     — the term (or a JD-supplied alias) appears verbatim in
                        the resume. Evidence is attached so the rewriter knows
                        which bullets/sections it may surface the term from.
  - covered_adjacent  — the term itself does not appear, but a directional
                        adjacency rule maps a resume term to it (e.g. "Spring
                        Boot" in the resume is evidence for the JD's "Java").
  - gap               — neither path covers it. The rewriter is forbidden from
                        claiming this term; the gap report surfaces it to the
                        user.

The adjacency rules are intentionally narrow and directional. When in doubt,
we leave a term in `gap` and let the user override — false coverage is worse
than a flagged gap.

This module is deterministic and does NOT call the LLM.
"""
from __future__ import annotations

import re
from typing import Optional

from .tailoring import ResumeStruct


# resume_term (lowercased) -> list of JD terms it provides truthful evidence for.
# Directional: seeing the key in the resume is evidence the value is covered;
# the reverse is NOT implied (Java alone is not evidence of Spring Boot).
# Conservative starter set — extend over time.
_IMPLICATIONS: dict[str, list[str]] = {
    # JVM ecosystem
    "spring boot": ["java", "jvm"],
    "spring": ["java", "jvm"],
    "kotlin": ["jvm"],
    "scala": ["jvm"],

    # Python web frameworks
    "django": ["python"],
    "flask": ["python"],
    "fastapi": ["python"],

    # Other web frameworks → host language
    "rails": ["ruby", "ruby on rails"],
    "ruby on rails": ["ruby"],
    "express": ["node.js", "javascript"],
    "express.js": ["node.js", "javascript"],
    "nest.js": ["node.js", "typescript"],
    "next.js": ["react", "javascript"],
    "react native": ["react", "javascript"],
    "angular": ["typescript", "javascript"],
    "vue.js": ["javascript"],
    "vue": ["javascript"],
    "svelte": ["javascript"],

    # Typed dialects
    "typescript": ["javascript"],

    # Cloud / infra adjacencies
    "eks": ["kubernetes", "aws"],
    "gke": ["kubernetes", "google cloud"],
    "aks": ["kubernetes", "azure"],
    "ecs": ["aws", "containers"],
    "rds": ["aws"],
    "lambda": ["aws", "serverless"],
    "cloud functions": ["serverless", "google cloud"],
    "cloud run": ["serverless", "google cloud", "containers"],
    "bigquery": ["sql", "google cloud", "data warehousing"],
    "redshift": ["sql", "aws", "data warehousing"],
    "athena": ["sql", "aws"],
    "snowflake": ["sql", "data warehousing"],
    "databricks": ["spark", "sql", "data engineering"],

    # Databases
    "postgresql": ["sql", "rdbms"],
    "postgres": ["sql", "rdbms"],
    "mysql": ["sql", "rdbms"],
    "mariadb": ["sql", "rdbms"],
    "sqlite": ["sql"],
    "sql server": ["sql", "rdbms"],
    "oracle db": ["sql", "rdbms"],
    "dynamodb": ["nosql", "aws"],
    "mongodb": ["nosql"],
    "cassandra": ["nosql", "distributed systems"],
    "redis": ["caching", "in-memory store"],
    "elasticsearch": ["search", "distributed systems"],

    # ML / AI
    "pytorch": ["deep learning", "machine learning"],
    "tensorflow": ["deep learning", "machine learning"],
    "jax": ["deep learning", "machine learning"],
    "scikit-learn": ["machine learning"],
    "xgboost": ["machine learning"],
    "hugging face": ["machine learning", "nlp", "transformers"],
    "transformers": ["machine learning", "nlp"],
    "langchain": ["llm", "machine learning"],

    # Streaming / data
    "kafka": ["streaming", "event-driven", "distributed systems"],
    "kinesis": ["streaming", "aws"],
    "pub/sub": ["streaming", "google cloud"],
    "pubsub": ["streaming", "google cloud"],
    "spark": ["distributed systems", "big data"],
    "flink": ["streaming", "distributed systems"],
    "airflow": ["orchestration", "data engineering"],
    "dbt": ["data engineering", "sql"],

    # CI/CD / IaC
    "terraform": ["iac", "infrastructure as code"],
    "pulumi": ["iac", "infrastructure as code"],
    "cloudformation": ["iac", "infrastructure as code", "aws"],
    "github actions": ["ci/cd"],
    "circleci": ["ci/cd"],
    "jenkins": ["ci/cd"],
    "argocd": ["ci/cd", "kubernetes", "gitops"],

    # Observability
    "datadog": ["observability", "monitoring"],
    "grafana": ["observability", "monitoring"],
    "prometheus": ["observability", "monitoring"],
    "splunk": ["observability", "logging"],
    "opentelemetry": ["observability", "tracing"],

    # API / RPC styles
    "graphql": ["api"],
    "grpc": ["api", "rpc"],
    "rest": ["api"],
    "rest apis": ["api"],
    "rest api": ["api"],
}


# Boundary detection: what counts as "part of a tech name" for the purpose
# of detecting word edges. Letters/digits/underscore are obvious; we exclude
# `.`, `+`, `#`, `/` from this set so terms like "Python." (sentence-final)
# still match — names that contain those chars (Node.js, C++, C#) work
# because the chars adjacent to the FULL match (not the special char) are
# checked.
_NAME_CHAR = r"[A-Za-z0-9_-]"


def _make_pattern(term: str) -> re.Pattern:
    """Case-insensitive match with name-aware boundaries.

    Handles symbol-bearing names (C++, C#, Node.js, .NET) without false
    positives like Java→JavaScript.
    """
    t = term.strip()
    if not t:
        return re.compile(r"(?!x)x")  # never matches
    return re.compile(
        rf"(?<!{_NAME_CHAR}){re.escape(t)}(?!{_NAME_CHAR})",
        re.IGNORECASE,
    )


def _find_evidence(term: str, resume: ResumeStruct) -> list[dict]:
    """Return every place in the resume where `term` appears verbatim."""
    pat = _make_pattern(term)
    out: list[dict] = []

    if resume.summary and pat.search(resume.summary):
        out.append({"section": "summary", "text": resume.summary})

    for j_idx, job in enumerate(resume.jobs):
        if job.title_text and pat.search(job.title_text):
            out.append({"section": "job_title", "job_idx": j_idx, "text": job.title_text})
        for b_idx, bullet in enumerate(job.bullets):
            if bullet and pat.search(bullet):
                out.append({
                    "section": "bullet",
                    "job_idx": j_idx,
                    "bullet_idx": b_idx,
                    "text": bullet,
                })

    for s_idx, sk in enumerate(resume.skills):
        haystack_items = sk.items or ""
        haystack_cat = sk.category or ""
        if pat.search(haystack_items) or pat.search(haystack_cat):
            out.append({
                "section": "skills",
                "skill_idx": s_idx,
                "category": haystack_cat,
                "text": haystack_items,
            })

    return out


def _dedup_evidence(evs: list[dict]) -> list[dict]:
    seen: set = set()
    out: list[dict] = []
    for e in evs:
        key = (
            e.get("section"),
            e.get("job_idx"),
            e.get("bullet_idx"),
            e.get("skill_idx"),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def _adjacency_evidence(jd_term: str, resume: ResumeStruct) -> list[dict]:
    """For a JD term, find resume terms whose IMPLICATIONS include it."""
    target = jd_term.strip().lower()
    if not target:
        return []
    via: list[dict] = []
    for resume_term, implied in _IMPLICATIONS.items():
        if target not in (i.lower() for i in implied):
            continue
        ev = _find_evidence(resume_term, resume)
        if ev:
            via.append({"via": resume_term, "evidence": ev})
    return via


def build_coverage_map(spec: dict, resume: ResumeStruct) -> dict:
    """Produce the coverage map. Pure function; no I/O."""
    covered_exact: list[dict] = []
    covered_adjacent: list[dict] = []
    gap: list[dict] = []

    for skill in spec.get("hard_skills") or []:
        term = (skill.get("term") or "").strip()
        if not term:
            continue
        weight = float(skill.get("weight") or 0.0)
        aliases = skill.get("aliases") or []

        evidence = _find_evidence(term, resume)
        for alias in aliases:
            if isinstance(alias, str) and alias.strip():
                evidence.extend(_find_evidence(alias, resume))
        evidence = _dedup_evidence(evidence)

        if evidence:
            covered_exact.append({"term": term, "weight": weight, "evidence": evidence})
            continue

        adj = _adjacency_evidence(term, resume)
        if adj:
            covered_adjacent.append({"term": term, "weight": weight, "via": adj})
        else:
            gap.append({"term": term, "weight": weight})

    soft_covered: list[dict] = []
    soft_gap: list[dict] = []
    for sig in spec.get("soft_signals") or []:
        term = (sig.get("term") or "").strip()
        if not term:
            continue
        weight = float(sig.get("weight") or 0.0)
        ev = _find_evidence(term, resume)
        if ev:
            soft_covered.append({"term": term, "weight": weight, "evidence": ev})
        else:
            soft_gap.append({"term": term, "weight": weight})

    total_w = sum(float(s.get("weight") or 0.0) for s in (spec.get("hard_skills") or []))
    if total_w > 0:
        # Adjacent matches count as 0.7× — they're truthful but weaker than verbatim.
        covered_w = (
            sum(s["weight"] for s in covered_exact)
            + 0.7 * sum(s["weight"] for s in covered_adjacent)
        )
        weighted = covered_w / total_w
    else:
        weighted = 0.0

    return {
        "hard_skills": {
            "covered_exact": covered_exact,
            "covered_adjacent": covered_adjacent,
            "gap": gap,
        },
        "soft_signals": {
            "covered": soft_covered,
            "gap": soft_gap,
        },
        "summary": {
            "exact_count": len(covered_exact),
            "adjacent_count": len(covered_adjacent),
            "gap_count": len(gap),
            "weighted_coverage": round(weighted, 3),
        },
    }


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    from .jd_analyzer import analyze_jd
    from .scraping import fetch_job_posting
    from .tailoring import parse_resume_from_path

    if len(sys.argv) < 3:
        print(
            "Usage: python -m app.coverage_map <jd-url-or-textfile> <resume.docx>",
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
    print(json.dumps(cmap, indent=2, ensure_ascii=False))

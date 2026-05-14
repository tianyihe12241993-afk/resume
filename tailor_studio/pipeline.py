"""Background pipeline. One JobUrl -> tailored .docx + coverage report.

Uses the constrained-rewrite chain: jd_analyzer -> coverage_map ->
adjacency_proposer -> bullet_rewriter (+validator) -> apply_tailoring.
"""
from __future__ import annotations

import json
import os
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.adjacency_proposer import propose_adjacencies
from app.bullet_rewriter import rewrite_and_validate
from app.coverage_map import _make_pattern, build_coverage_map
from app.jd_analyzer import analyze_jd
from app.scraping import fetch_job_posting
from app.similarity import compare as similarity_compare, docx_text
from app.tailoring import (
    apply_tailoring,
    normalize_job_info,
    parse_resume_from_path,
    tailor_resume,
)

from . import config, storage
from .db import (
    Batch, JobUrl, Profile, SessionLocal,
    STATUS_ANALYZING, STATUS_DONE, STATUS_ERROR, STATUS_FETCHING,
    STATUS_NEEDS_JD, STATUS_TAILORING,
)


_PRIORITY = {
    "ai / ml": 0, "ai/ml": 0, "ml": 0, "machine learning": 0,
    "ml tools": 1, "devops": 2, "backend": 3, "programming": 4,
    "cloud": 5, "frontend": 6, "databases": 7, "data": 8,
}

_SKILL_ROW_BY_TERM = {
    "ai / ml": [
        "llm", "large language model", "asr", "tts", "text-to-speech",
        "automatic speech recognition", "speech recognition", "multimodal",
        "rag", "embedding", "vector search", "prompt engineering",
        "machine learning", "deep learning", "nlp", "model serving",
        "model deployment", "avatar rendering", "computer vision",
    ],
    "ml tools": [
        "pytorch", "tensorflow", "scikit-learn", "huggingface", "hugging face",
        "langchain", "llamaindex", "openai api", "pipecat", "daily",
        "transformers",
    ],
    "devops": [
        "kubernetes", "k8s", "docker", "container", "container orchestration",
        "observability", "metrics", "tracing", "instrumentation",
        "prometheus", "grafana", "datadog", "ci/cd", "terraform",
        "github actions", "automated testing", "test automation",
    ],
    "backend": [
        "real-time", "streaming", "concurrent", "concurrency", "low-latency",
        "latency optimization", "distributed systems", "message queues",
        "event-driven", "api orchestration", "rest api", "graphql",
        "grpc", "microservices", "websocket",
    ],
    "cloud": [
        "aws", "gcp", "google cloud", "azure", "ec2", "lambda",
        "cloud run", "vertex ai",
    ],
}


def _which_skill_row(term: str) -> Optional[str]:
    t = term.lower()
    for row_label, terms in _SKILL_ROW_BY_TERM.items():
        for keyword in terms:
            if keyword in t:
                return row_label
    return None


def _enrich_skill_rows(rows, spec, final_bullets):
    out = []
    for category, items in rows:
        cat_label = (category or "").rstrip(":").strip().lower()
        new_items = items
        for skill in spec.get("hard_skills") or []:
            term = (skill.get("term") or "").strip()
            if not term:
                continue
            target_row = _which_skill_row(term)
            if target_row is None or not cat_label.startswith(target_row):
                continue
            if not any(_make_pattern(term).search(b) for b in final_bullets):
                continue
            if _make_pattern(term).search(new_items):
                continue
            new_items = new_items.rstrip(".") + ", " + term
        out.append((category, new_items))
    return out


def _apply_claimed_terms(rows, claimed_terms):
    if not claimed_terms:
        return list(rows)
    out = [[c, i] for c, i in rows]
    for term in claimed_terms:
        term = (term or "").strip()
        if not term:
            continue
        target = _which_skill_row(term)
        target_idx = None
        if target is not None:
            for i, (cat, _) in enumerate(out):
                cat_label = (cat or "").rstrip(":").strip().lower()
                if cat_label.startswith(target):
                    target_idx = i
                    break
        if target_idx is None:
            target_idx = 0
        cat, items = out[target_idx]
        if _make_pattern(term).search(items):
            continue
        out[target_idx][1] = items.rstrip(".") + ", " + term
    return [(c, i) for c, i in out]


def _resolve_jd(ju: JobUrl) -> tuple[str, str, str, str]:
    """Return (jd_text, title, company, location). Scrape if needed."""
    if ju.description and len(ju.description.strip()) >= 200:
        return (
            ju.description,
            ju.title or "",
            ju.company or "",
            ju.location or "",
        )
    raw = fetch_job_posting(ju.url)
    info = normalize_job_info(raw, url=ju.url)
    return (
        info.get("description", "") or "",
        info.get("title", "") or "",
        info.get("company", "") or "",
        info.get("location", "") or "",
    )


def _run_single(job_url_id: int) -> None:
    db = SessionLocal()
    try:
        ju = db.get(JobUrl, job_url_id)
        if ju is None:
            return
        batch = ju.batch
        profile = batch.profile
        src_docx = storage.base_resume_path(profile.id)
        if not src_docx.exists():
            ju.status = STATUS_ERROR
            ju.error_message = "Profile has no base resume uploaded."
            db.commit()
            return

        # 1. Fetch JD
        ju.status = STATUS_FETCHING
        ju.error_message = None
        db.commit()
        try:
            jd_text, title, company, location = _resolve_jd(ju)
        except Exception as e:
            ju.status = STATUS_NEEDS_JD
            ju.error_message = f"Scrape failed: {e}. Paste JD manually."
            db.commit()
            return
        if not jd_text or len(jd_text.strip()) < 200:
            ju.status = STATUS_NEEDS_JD
            ju.error_message = "Auto-scrape returned too little text. Paste JD manually."
            db.commit()
            return
        if title and not ju.title:
            ju.title = title
        if company and not ju.company:
            ju.company = company
        if location and not ju.location:
            ju.location = location
        if not ju.description:
            ju.description = jd_text
        db.commit()

        # 2. Analyze + coverage
        ju.status = STATUS_ANALYZING
        db.commit()
        spec = analyze_jd(jd_text, title=ju.title or "", company=ju.company or "")
        resume_struct = parse_resume_from_path(src_docx)
        cmap = build_coverage_map(spec, resume_struct)
        cmap = propose_adjacencies(spec, cmap, resume_struct)
        coverage_initial = dict(cmap["summary"])
        original_text = docx_text(src_docx)
        coverage_initial["similarity"] = similarity_compare(original_text, jd_text)

        # 3. Per-bullet rewrite + validate. Feed claimed_terms in: any term
        # the user has explicitly claimed becomes available to the rewriter
        # (and is removed from the off-limits gap list).
        ju.status = STATUS_TAILORING
        db.commit()
        claimed_for_rewriter: list[str] = []
        if ju.claimed_terms:
            try:
                claimed_for_rewriter = [
                    t for t in json.loads(ju.claimed_terms) if isinstance(t, str)
                ]
            except (TypeError, ValueError):
                claimed_for_rewriter = []
        bullet_results = rewrite_and_validate(
            resume_struct, spec, cmap,
            claimed_terms=claimed_for_rewriter,
            jd_text=jd_text,
        )
        bullets_per_job = [[] for _ in resume_struct.jobs]
        for r in bullet_results:
            bullets_per_job[r["job_idx"]].append(r["final"])

        # 4. Summary via legacy single-shot, plus skills reorder + enrich
        legacy = tailor_resume(
            resume_struct,
            {
                "title": ju.title or "",
                "company": ju.company or "",
                "location": ju.location or "",
                "description": jd_text,
            },
            system_prompt=profile.tailor_prompt,
        )

        def _key(s):
            cat = (s.category or "").strip().rstrip(":").lower()
            for k, v in _PRIORITY.items():
                if cat.startswith(k):
                    return v
            return 99

        reordered = sorted(resume_struct.skills, key=_key)
        rows = [(s.category, s.items) for s in reordered]
        flat_bullets = [b for jb in bullets_per_job for b in jb]
        enriched = _enrich_skill_rows(rows, spec, flat_bullets)

        claimed = []
        if ju.claimed_terms:
            try:
                claimed = [t for t in json.loads(ju.claimed_terms) if isinstance(t, str)]
            except (TypeError, ValueError):
                claimed = []
        if claimed:
            enriched = _apply_claimed_terms(enriched, claimed)

        merged = {
            "summary": legacy.get("summary", "") or resume_struct.summary,
            "bullets": bullets_per_job,
            "skill_categories": [c for c, _ in enriched],
            "skill_items": [i for _, i in enriched],
        }

        out_path = storage.generated_docx_path(batch.id, ju.id)
        apply_tailoring(src_docx, resume_struct, merged, out_path)

        # 5. Final coverage on the rewritten doc
        final_struct = parse_resume_from_path(out_path)
        final_cmap = build_coverage_map(spec, final_struct)
        coverage_final = dict(final_cmap["summary"])
        coverage_final["covered_exact"] = [
            {"term": c["term"], "weight": c["weight"]}
            for c in sorted(
                final_cmap["hard_skills"]["covered_exact"],
                key=lambda x: -x["weight"],
            )
        ]
        coverage_final["gap"] = [
            {"term": g["term"], "weight": g["weight"]}
            for g in sorted(
                final_cmap["hard_skills"]["gap"],
                key=lambda x: -x["weight"],
            )
        ]
        coverage_final["must_have_phrases"] = list(spec.get("must_have_phrases") or [])
        tailored_text = docx_text(out_path)
        coverage_final["similarity"] = similarity_compare(tailored_text, jd_text)

        ju.docx_filename = out_path.name
        ju.coverage_initial = json.dumps(coverage_initial)
        ju.coverage_final = json.dumps(coverage_final)
        ju.spec_json = json.dumps(spec)
        ju.status = STATUS_DONE
        ju.error_message = None
        db.commit()

    except Exception as e:
        traceback.print_exc()
        try:
            ju = db.get(JobUrl, job_url_id)
            if ju is not None:
                ju.status = STATUS_ERROR
                ju.error_message = f"{type(e).__name__}: {e}"
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


_executor: Optional[ThreadPoolExecutor] = None
_executor_lock = threading.Lock()


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    with _executor_lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(
                max_workers=config.WORKERS, thread_name_prefix="studio"
            )
    return _executor


def enqueue(job_url_id: int) -> None:
    _get_executor().submit(_run_single, job_url_id)

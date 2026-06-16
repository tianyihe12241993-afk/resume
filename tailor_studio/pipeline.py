"""Background pipeline. One JobUrl -> tailored .docx + coverage report.

Uses the constrained-rewrite chain: jd_analyzer -> coverage_map ->
adjacency_proposer -> bullet_rewriter (+validator) -> apply_tailoring.
"""
from __future__ import annotations

import json
import os
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from app.adjacency_proposer import propose_adjacencies
from app.bullet_rewriter import rewrite_and_validate, _build_resume_wide_allowlist
from app.coverage_map import _make_pattern, build_coverage_map
from app.jd_analyzer import analyze_jd
from app.scraping import fetch_job_posting, JobFetchError
from app.similarity import compare as similarity_compare, docx_text
from app.tailoring import (
    apply_tailoring,
    normalize_job_info,
    parse_resume_from_path,
    tailor_summary,
    tailor_skills,
)

from . import config, storage
from .db import (
    JobUrl, SessionLocal,
    STATUS_ANALYZING, STATUS_DONE, STATUS_ERROR, STATUS_FETCHING,
    STATUS_NEEDS_JD, STATUS_PENDING, STATUS_TAILORING,
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


def _resolve_jd(ju: JobUrl) -> tuple[str, str, str, str, Optional[str]]:
    """Return (jd_text, title, company, location, work_type). Scrape if needed."""
    if ju.description and len(ju.description.strip()) >= 200:
        return (
            ju.description,
            ju.title or "",
            ju.company or "",
            ju.location or "",
            ju.work_type,
        )
    raw = fetch_job_posting(ju.url)
    info = normalize_job_info(raw, url=ju.url)
    return (
        info.get("description", "") or "",
        info.get("title", "") or "",
        info.get("company", "") or "",
        info.get("location", "") or "",
        info.get("work_type"),
    )


# job_id -> monotonic time the worker started it. Lets the watchdog tell a
# genuinely-held job (live worker) from an orphan (no worker), and detect one
# held implausibly long.
_inflight: dict[int, float] = {}
_inflight_lock = threading.Lock()


def _run_single(job_url_id: int) -> None:
    with _inflight_lock:
        _inflight[job_url_id] = time.monotonic()
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
        ju.fail_reason = None
        db.commit()
        try:
            jd_text, title, company, location, work_type = _resolve_jd(ju)
        except JobFetchError as e:
            # Classified failure: "expired" is terminal (skip); everything else
            # is recoverable by pasting the JD manually.
            ju.status = STATUS_ERROR if e.category == "expired" else STATUS_NEEDS_JD
            ju.fail_reason = e.category
            ju.error_message = e.message
            db.commit()
            return
        except Exception as e:
            ju.status = STATUS_NEEDS_JD
            ju.fail_reason = "fetch_failed"
            ju.error_message = (
                f"Couldn't fetch the page ({type(e).__name__}). "
                "Open it in your browser and paste the JD manually."
            )
            db.commit()
            return
        if not jd_text or len(jd_text.strip()) < 200:
            ju.status = STATUS_NEEDS_JD
            ju.fail_reason = "empty_jd"
            ju.error_message = (
                "Loaded the page but the job description was too short to use. "
                "Open it and paste the full JD manually."
            )
            db.commit()
            return
        if title and not ju.title:
            ju.title = title
        if company and not ju.company:
            ju.company = company
        if location and not ju.location:
            ju.location = location
        if work_type and not ju.work_type:
            ju.work_type = work_type
        if not ju.description:
            ju.description = jd_text
        db.commit()

        # 2. Analyze + coverage
        ju.status = STATUS_ANALYZING
        db.commit()
        spec = analyze_jd(jd_text, title=ju.title or "", company=ju.company or "")
        # Guard: a page that scraped >200 chars but yields almost no real
        # requirements isn't a usable JD (login wall, JS shell, cookie banner,
        # generic landing page). Tailoring against it produces a meaningless
        # ~0% coverage "done". Flag it for manual JD instead.
        if len(spec.get("hard_skills") or []) < 3:
            ju.status = STATUS_NEEDS_JD
            ju.fail_reason = "empty_jd"
            ju.error_message = (
                "The page didn't contain a usable job description (no real "
                "skills/requirements found). Open it and paste the JD manually."
            )
            db.commit()
            return
        resume_struct = parse_resume_from_path(src_docx)
        cmap_base = build_coverage_map(spec, resume_struct)
        # LLM adjacency is always run here — it feeds the skills allowlist, so
        # the tailored resume depends on it regardless of scoring config.
        cmap = propose_adjacencies(spec, cmap_base, resume_struct)
        # Score the "before" the same way we'll score the "after": with LLM
        # adjacency when FINAL_ADJACENCY is on, deterministic-only when off — so
        # the displayed before/after is always an apples-to-apples comparison.
        coverage_initial = dict((cmap if config.FINAL_ADJACENCY else cmap_base)["summary"])
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
        # Lazy-extract a deep candidate profile from the base resume — every
        # named + implicit skill, every signature system, every quantified
        # result. The bullet rewriter uses this as additional grounding so
        # individual bullets can speak to JD skills documented elsewhere in
        # the resume but not the bullet itself.
        candidate_profile = None
        try:
            from app.profile_extractor import extract_candidate_profile
            candidate_profile = extract_candidate_profile(docx_text(src_docx))
        except Exception:
            candidate_profile = None

        bullet_results = rewrite_and_validate(
            resume_struct, spec, cmap,
            claimed_terms=claimed_for_rewriter,
            jd_text=jd_text,
            candidate_profile=candidate_profile,
        )
        bullets_per_job = [[] for _ in resume_struct.jobs]
        for r in bullet_results:
            bullets_per_job[r["job_idx"]].append(r["final"])

        # 4. Summary via a fast summary-ONLY call (the legacy full-resume
        # single-shot generated the whole doc just for its summary — a big,
        # slow output that hit the request timeout). Skills reorder + enrich
        # follow.
        tailored_summary = tailor_summary(
            resume_struct,
            {
                "title": ju.title or "",
                "company": ju.company or "",
                "description": jd_text,
            },
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

        # LLM skills-rewriter on top of the deterministic enriched baseline:
        # reorder rows + items by JD priority, canonicalize names to the JD's
        # spelling, and fold in any JD skill the candidate truthfully has. It
        # may ONLY add terms in the resume-wide allowlist (covered exact +
        # adjacent + user-claimed) — so it surfaces real, defensible skills
        # and never fabricates. Falls back to `enriched` on any failure.
        try:
            jd_terms = [
                s.get("term", "")
                for s in sorted(
                    spec.get("hard_skills") or [],
                    key=lambda x: -float(x.get("weight", 0) or 0),
                )
                if s.get("term")
            ]
            allowed = [
                e.get("term", "")
                for e in _build_resume_wide_allowlist(cmap, claimed)
                if e.get("term")
            ]
            rewritten = tailor_skills(enriched, jd_terms, allowed)
            if rewritten:
                enriched = rewritten
        except Exception:
            traceback.print_exc()

        merged = {
            "summary": tailored_summary or resume_struct.summary,
            "bullets": bullets_per_job,
            "skill_categories": [c for c, _ in enriched],
            "skill_items": [i for _, i in enriched],
        }

        out_path = storage.generated_docx_path(batch.id, ju.id)
        apply_tailoring(src_docx, resume_struct, merged, out_path)

        # 5. Final coverage on the rewritten doc.
        #
        # EXACT matches are recomputed on the rewritten doc (deterministic).
        # ADJACENCY is CARRIED FORWARD from the initial LLM judgment, not
        # re-judged: tailoring only ADDS JD vocabulary — it never removes the
        # candidate's real experience — so a term legitimately judged adjacent
        # before is still adjacent after (unless it got promoted to exact).
        # This makes the score (a) robust: no second batch of LLM calls that can
        # time out under load and crater the number, and (b) MONOTONIC: promoting
        # adjacent→exact gains 0.3x weight and new exacts add weight, so the
        # final score can only meet or beat the initial. Tailoring never lowers
        # the displayed score.
        final_struct = parse_resume_from_path(out_path)
        final_det = build_coverage_map(spec, final_struct)
        final_exact = list(final_det["hard_skills"]["covered_exact"])
        exact_terms = {(e.get("term") or "").lower() for e in final_exact}
        init_adj = (cmap.get("hard_skills") or {}).get("covered_adjacent") or []
        carried_adj = [a for a in init_adj if (a.get("term") or "").lower() not in exact_terms]
        adj_terms = {(a.get("term") or "").lower() for a in carried_adj}
        gap = [
            {"term": s.get("term"), "weight": float(s.get("weight") or 0.0)}
            for s in (spec.get("hard_skills") or [])
            if s.get("term")
            and s["term"].lower() not in exact_terms
            and s["term"].lower() not in adj_terms
        ]
        total_w = sum(float(s.get("weight") or 0.0) for s in (spec.get("hard_skills") or []))
        covered_w = (
            sum(float(e.get("weight") or 0.0) for e in final_exact)
            + 0.7 * sum(float(a.get("weight") or 0.0) for a in carried_adj)
        )
        weighted = round(covered_w / total_w, 3) if total_w > 0 else 0.0
        final_cmap = {
            "hard_skills": {
                "covered_exact": final_exact,
                "covered_adjacent": carried_adj,
                "gap": gap,
            },
            "soft_signals": final_det.get("soft_signals", {}),
            "summary": {
                "exact_count": len(final_exact),
                "adjacent_count": len(carried_adj),
                "gap_count": len(gap),
                "weighted_coverage": weighted,
            },
        }
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
        ju.fail_reason = None
        db.commit()

    except Exception as e:
        traceback.print_exc()
        try:
            ju = db.get(JobUrl, job_url_id)
            if ju is not None:
                ju.status = STATUS_ERROR
                ju.fail_reason = "processing_error"
                ju.error_message = (
                    f"Tailoring failed internally ({type(e).__name__}). "
                    "This is a system error, not a problem with the posting — retry it."
                )
                db.commit()
        except Exception:
            pass
    finally:
        db.close()
        with _inflight_lock:
            _inflight.pop(job_url_id, None)


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


def requeue_orphans() -> int:
    """On server startup, re-enqueue jobs left mid-flight by a previous
    process. The thread-pool queue is in-memory; if uvicorn restarts while
    any rows are pending / fetching / analyzing / tailoring, those rows
    sit in the DB but nothing is picking them up.

    Resets such rows to STATUS_PENDING (clearing any partial error message)
    and submits them to the executor. Returns the count.
    """
    db = SessionLocal()
    try:
        rows = (
            db.query(JobUrl)
            .filter(JobUrl.status.in_([
                STATUS_PENDING, STATUS_FETCHING, STATUS_ANALYZING, STATUS_TAILORING,
            ]))
            .all()
        )
        ids: list[int] = []
        for ju in rows:
            ju.status = STATUS_PENDING
            ju.error_message = None
            ids.append(ju.id)
        if ids:
            db.commit()
        for jid in ids:
            enqueue(jid)
        return len(ids)
    finally:
        db.close()


# How long a job may sit in an in-flight status before the watchdog reclaims it.
_WATCHDOG_INTERVAL = int(os.getenv("STUDIO_WATCHDOG_INTERVAL", "120"))   # seconds
_WATCHDOG_STUCK_AFTER = int(os.getenv("STUDIO_WATCHDOG_STUCK_AFTER", "900"))  # 15 min


def _watchdog_once() -> int:
    """Reclaim jobs wedged in an in-flight status. Two cases:
      • No live worker holds it (not in `_inflight`) — an orphan (worker died,
        or status set but never picked up). Always safe to requeue.
      • A live worker has held it longer than _WATCHDOG_STUCK_AFTER — genuinely
        stuck (should be rare now that calls time out). Requeue so progress
        resumes; the stale worker's late result is harmless (the row is moving).
    Returns the number reclaimed."""
    db = SessionLocal()
    try:
        rows = (
            db.query(JobUrl)
            .filter(JobUrl.status.in_([
                STATUS_FETCHING, STATUS_ANALYZING, STATUS_TAILORING,
            ]))
            .all()
        )
        now = time.monotonic()
        reclaim: list[int] = []
        with _inflight_lock:
            for ju in rows:
                started = _inflight.get(ju.id)
                if started is None or (now - started) > _WATCHDOG_STUCK_AFTER:
                    reclaim.append(ju.id)
                    _inflight.pop(ju.id, None)
        for ju in rows:
            if ju.id in reclaim:
                ju.status = STATUS_PENDING
                ju.error_message = None
        if reclaim:
            db.commit()
            for jid in reclaim:
                enqueue(jid)
        return len(reclaim)
    finally:
        db.close()


_watchdog_started = False


def start_watchdog() -> None:
    """Launch the background watchdog loop (idempotent)."""
    global _watchdog_started
    if _watchdog_started:
        return
    _watchdog_started = True

    def _loop():
        while True:
            time.sleep(_WATCHDOG_INTERVAL)
            try:
                n = _watchdog_once()
                if n:
                    print(f"[watchdog] reclaimed {n} stuck job(s)")
            except Exception:
                traceback.print_exc()

    threading.Thread(target=_loop, name="studio-watchdog", daemon=True).start()

"""Background pipeline that processes a JobUrl end-to-end."""
from __future__ import annotations

import os
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from docx import Document

from . import storage, tailoring
from .db import SessionLocal
from .models import (
    STATUS_DONE,
    STATUS_ERROR,
    STATUS_FETCHING,
    STATUS_NEEDS_JD,
    STATUS_TAILORING,
    JobUrl,
)
from .scraping import fetch_job_posting

# Cap concurrency to respect both DB pool + Claude API + network bandwidth.
# Override with RESUME_MAKER_WORKERS env var.
_MAX_WORKERS = int(os.getenv("RESUME_MAKER_WORKERS", "6"))
_executor = ThreadPoolExecutor(
    max_workers=_MAX_WORKERS, thread_name_prefix="tailor-worker"
)


def _run_single(job_url_id: int) -> None:
    """Process one JobUrl to completion (or to NEEDS_JD if scrape fails)."""
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

        # 1. Fetch JD (unless admin already provided one manually)
        if not (ju.description and len(ju.description.strip()) >= 50):
            ju.status = STATUS_FETCHING
            ju.error_message = None
            db.commit()
            try:
                raw = fetch_job_posting(ju.url)
                info = tailoring.normalize_job_info(raw, url=ju.url)
                ju.company = info.get("company", "") or ju.company
                ju.title = info.get("title", "") or ju.title
                ju.location = info.get("location", "") or ju.location
                ju.description = info.get("description", "") or ju.description
                if not ju.description or len(ju.description.strip()) < 200:
                    ju.status = STATUS_NEEDS_JD
                    ju.error_message = (
                        "Auto-scrape returned too little text. "
                        "Paste the job description manually."
                    )
                    db.commit()
                    return
            except Exception as e:
                ju.status = STATUS_NEEDS_JD
                ju.error_message = f"Scrape failed: {e}. Paste JD manually."
                db.commit()
                return

        # 2. Tailor via Claude
        ju.status = STATUS_TAILORING
        db.commit()

        doc = Document(str(src_docx))
        resume = tailoring.parse_resume(doc)
        tailored = tailoring.tailor_resume(
            resume,
            {
                "company": ju.company or "",
                "title": ju.title or "",
                "location": ju.location or "",
                "description": ju.description or "",
            },
        )

        docx_out = storage.generated_docx_path(batch.id, ju.id)
        tailoring.apply_tailoring(src_docx, resume, tailored, docx_out)
        ju.docx_filename = docx_out.name
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


def enqueue(job_url_id: int) -> None:
    """Fire-and-forget — queued behind a bounded worker pool."""
    _executor.submit(_run_single, job_url_id)

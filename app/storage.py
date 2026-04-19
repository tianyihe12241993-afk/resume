"""Filesystem helpers for base resumes and generated outputs."""
from __future__ import annotations

from pathlib import Path

from . import config


def base_resume_path(profile_id: int) -> Path:
    return config.BASE_RESUMES_DIR / f"{profile_id}.docx"


def batch_dir(batch_id: int) -> Path:
    d = config.OUTPUTS_DIR / f"batch_{batch_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def generated_docx_path(batch_id: int, job_url_id: int) -> Path:
    return batch_dir(batch_id) / f"{job_url_id}.docx"


def generated_pdf_path(batch_id: int, job_url_id: int) -> Path:
    return batch_dir(batch_id) / f"{job_url_id}.pdf"

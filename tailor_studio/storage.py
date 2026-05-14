"""File path helpers for tailor-studio."""
from __future__ import annotations

from pathlib import Path

from . import config


def base_resume_path(profile_id: int) -> Path:
    """Return the canonical base-resume location for a profile."""
    return config.PROFILES_DIR / f"profile_{profile_id}.docx"


def generated_docx_path(batch_id: int, job_url_id: int) -> Path:
    return config.OUTPUTS_DIR / f"batch_{batch_id}__job_{job_url_id}.docx"

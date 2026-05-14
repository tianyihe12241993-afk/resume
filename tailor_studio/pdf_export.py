"""Lazy .docx -> .pdf converter.

Uses docx2pdf, which on Windows drives Microsoft Word via COM. Two gotchas:

1. **COM threading.** Each thread that drives Word via COM must call
   pythoncom.CoInitialize() first. uvicorn handlers run in a thread pool,
   so we initialize per-call. Without this, the second request from a
   different worker thread fails with "CoInitialize has not been called".

2. **Word doesn't parallelize cleanly.** Multiple simultaneous COM calls
   into one Word.Application cause races. We serialize through a process-
   wide lock so concurrent /pdf downloads run sequentially.

PDF is generated lazily on first download and cached to disk + the
JobUrl.pdf_filename column. Subsequent downloads serve the cached file.
"""
from __future__ import annotations

import logging
import threading
import traceback
from pathlib import Path
from typing import Optional

from docx2pdf import convert

from . import config


_lock = threading.Lock()
_log = logging.getLogger("tailor_studio.pdf_export")


def _pdf_path_for(docx_filename: str) -> Path:
    """e.g. 'batch_1__job_42.docx' -> OUTPUTS_DIR / 'batch_1__job_42.pdf'"""
    return config.OUTPUTS_DIR / (Path(docx_filename).stem + ".pdf")


def _convert_with_com(docx_path: Path, pdf_path: Path) -> None:
    """Run docx2pdf inside a CoInitialize/CoUninitialize pair so it's safe
    to call from any worker thread."""
    import pythoncom
    pythoncom.CoInitialize()
    try:
        convert(str(docx_path), str(pdf_path))
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


def make_pdf(docx_filename: str) -> tuple[Optional[Path], Optional[str]]:
    """Convert the named .docx (in OUTPUTS_DIR) to a sibling .pdf.

    Returns (Path, None) on success, (None, error_message) on failure.
    Idempotent — if the .pdf already exists and is fresher than the .docx,
    returns it without re-converting.
    """
    docx_path = config.OUTPUTS_DIR / docx_filename
    if not docx_path.exists():
        return None, f"docx not found: {docx_filename}"
    pdf_path = _pdf_path_for(docx_filename)
    if pdf_path.exists() and pdf_path.stat().st_mtime >= docx_path.stat().st_mtime:
        return pdf_path, None

    with _lock:
        # Re-check under lock — another thread may have produced it while we waited.
        if pdf_path.exists() and pdf_path.stat().st_mtime >= docx_path.stat().st_mtime:
            return pdf_path, None
        try:
            _convert_with_com(docx_path, pdf_path)
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            _log.error("PDF conversion failed for %s: %s\n%s",
                       docx_filename, err, traceback.format_exc())
            return None, err

    if pdf_path.exists():
        return pdf_path, None
    return None, "convert() returned but no .pdf appeared on disk"

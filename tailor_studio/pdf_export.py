"""Lazy .docx -> .pdf converter.

Fidelity matters: the bidder submits this PDF to employers, so the layout must
match the .docx exactly. That rules out re-rendering libraries (reportlab /
weasyprint) and leaves the two engines that open the real .docx: LibreOffice
and Microsoft Word. We try them in order of robustness:

1. **LibreOffice headless** (`soffice --headless --convert-to pdf`). No COM, no
   desktop session, parallel-safe, no zombie processes. Preferred when present.
2. **Microsoft Word via COM** (`win32com`). Always available on a typical
   Windows + Office box, but flakier — needs CoInitialize per worker thread,
   doesn't parallelize, and can leave WINWORD.EXE running if not closed
   carefully. We drive it directly (no docx2pdf wrapper) so we control
   visibility, alerts, and teardown.

Nothing is imported at module load, so importing this module never fails even
if neither engine is installed — make_pdf() just returns a clear error string.

PDF is generated lazily on first download and cached to disk + the
JobUrl.pdf_filename column. Subsequent downloads serve the cached file.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import traceback
from pathlib import Path
from typing import Optional

from . import config


_lock = threading.Lock()
_log = logging.getLogger("tailor_studio.pdf_export")

# wdExportFormatPDF
_WD_FORMAT_PDF = 17


def _pdf_path_for(docx_filename: str) -> Path:
    """e.g. 'batch_1__job_42.docx' -> OUTPUTS_DIR / 'batch_1__job_42.pdf'"""
    return config.OUTPUTS_DIR / (Path(docx_filename).stem + ".pdf")


def _find_soffice() -> Optional[str]:
    """Locate the LibreOffice binary via PATH or common install locations."""
    env = os.getenv("SOFFICE_PATH")
    if env and Path(env).exists():
        return env
    found = shutil.which("soffice") or shutil.which("soffice.exe")
    if found:
        return found
    candidates = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        "/usr/bin/soffice",
        "/usr/local/bin/soffice",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None


def _convert_with_libreoffice(soffice: str, docx_path: Path, pdf_path: Path) -> None:
    """Headless LibreOffice conversion. soffice writes <stem>.pdf into the
    output dir; that already matches our target name."""
    out_dir = pdf_path.parent
    proc = subprocess.run(
        [
            soffice, "--headless", "--norestore", "--nolockcheck",
            "--convert-to", "pdf:writer_pdf_Export",
            "--outdir", str(out_dir), str(docx_path),
        ],
        capture_output=True, text=True, timeout=120,
    )
    produced = out_dir / (docx_path.stem + ".pdf")
    if not produced.exists():
        raise RuntimeError(
            f"soffice exited {proc.returncode}: "
            f"{(proc.stderr or proc.stdout or '').strip()[:300]}"
        )
    if produced != pdf_path:
        produced.replace(pdf_path)


def _convert_with_word(docx_path: Path, pdf_path: Path) -> None:
    """Drive Microsoft Word via COM. Runs invisibly, suppresses dialogs, and
    always tears the document + app down so no WINWORD.EXE is left behind."""
    import pythoncom
    import win32com.client as win32

    pythoncom.CoInitialize()
    word = None
    doc = None
    try:
        word = win32.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0  # wdAlertsNone
        doc = word.Documents.Open(
            str(docx_path), ReadOnly=True, AddToRecentFiles=False, Visible=False
        )
        doc.ExportAsFixedFormat(str(pdf_path), _WD_FORMAT_PDF)
    finally:
        try:
            if doc is not None:
                doc.Close(SaveChanges=0)  # wdDoNotSaveChanges
        except Exception:
            pass
        try:
            if word is not None:
                word.Quit()
        except Exception:
            pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


def _engine_label() -> str:
    """Human-readable name of the engine make_pdf would use, for diagnostics."""
    if _find_soffice():
        return "LibreOffice"
    try:
        import win32com.client  # noqa: F401
        return "Microsoft Word"
    except Exception:
        return "none"


def make_pdf(docx_filename: str) -> tuple[Optional[Path], Optional[str]]:
    """Convert the named .docx (in OUTPUTS_DIR) to a sibling .pdf.

    Returns (Path, None) on success, (None, error_message) on failure.
    Idempotent — if the .pdf already exists and is fresher than the .docx,
    returns it without re-converting. Tries LibreOffice, then Word.
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

        errors: list[str] = []

        soffice = _find_soffice()
        if soffice:
            try:
                _convert_with_libreoffice(soffice, docx_path, pdf_path)
                if pdf_path.exists():
                    return pdf_path, None
            except Exception as e:
                err = f"LibreOffice: {type(e).__name__}: {e}"
                errors.append(err)
                _log.warning("LibreOffice conversion failed for %s: %s",
                             docx_filename, err)

        try:
            _convert_with_word(docx_path, pdf_path)
            if pdf_path.exists():
                return pdf_path, None
            errors.append("Word: convert returned but no .pdf appeared")
        except ImportError:
            errors.append(
                "Word: pywin32 not installed (pip install pywin32) and no "
                "LibreOffice found"
            )
        except Exception as e:
            err = f"Word: {type(e).__name__}: {e}"
            errors.append(err)
            _log.error("Word conversion failed for %s: %s\n%s",
                       docx_filename, err, traceback.format_exc())

    return None, "; ".join(errors) or "no PDF engine available"

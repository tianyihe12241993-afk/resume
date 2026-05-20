"""Disk-space pruning: drop generated artifacts older than N days, keep
the lightweight work-history metadata in the DB.

What gets pruned (default: >7 days old, by mtime):
- tailor_studio/data/outputs/*.docx  and  *.pdf  — generated resumes
- data/bullet_rewrite_cache/*.json
- data/adjacency_cache/*.json
- data/tailor_cache/*.json
- data/jd_spec_cache/*.json
- data/scrape_cache/*.json

What gets cleared on each pruned JobUrl row:
- docx_filename, pdf_filename (download links go away)
- description (the JD text — sometimes 10KB per row)
- coverage_initial, coverage_final, spec_json, claimed_terms (JSON blobs)

What is KEPT (the "work history"):
- url, company, title, location, work_type
- application_status, applied_at, application_note, application_source
- download_count
- status (pipeline status — usually 'done' for pruned rows)
- created_at, updated_at, batch_id

Usage:
    .venv/bin/python -m scripts.prune_old_outputs            # default 7d
    .venv/bin/python -m scripts.prune_old_outputs --days 14
    .venv/bin/python -m scripts.prune_old_outputs --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from sqlalchemy import text as sql_text

from tailor_studio import config
from tailor_studio.db import JobUrl, init_db, get_session


CACHE_DIRS_TO_PRUNE = [
    config.DATA_DIR.parent / "data" / "bullet_rewrite_cache",
    config.DATA_DIR.parent / "data" / "adjacency_cache",
    config.DATA_DIR.parent / "data" / "tailor_cache",
    config.DATA_DIR.parent / "data" / "jd_spec_cache",
    config.DATA_DIR.parent / "data" / "scrape_cache",
]


def _humanize(n_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n_bytes < 1024:
            return f"{n_bytes:.1f} {unit}"
        n_bytes /= 1024
    return f"{n_bytes:.1f} TB"


def prune_outputs_dir(cutoff: float, dry_run: bool) -> tuple[int, int]:
    """Delete .docx/.pdf in OUTPUTS_DIR older than cutoff. Returns
    (files_removed, bytes_reclaimed)."""
    out_dir = config.OUTPUTS_DIR
    if not out_dir.exists():
        return 0, 0
    removed = 0
    bytes_removed = 0
    for entry in out_dir.iterdir():
        if not entry.is_file():
            continue
        if entry.suffix.lower() not in (".docx", ".pdf"):
            continue
        try:
            mtime = entry.stat().st_mtime
            size = entry.stat().st_size
        except OSError:
            continue
        if mtime > cutoff:
            continue
        if not dry_run:
            try:
                entry.unlink()
            except OSError as e:
                print(f"  warn: could not delete {entry.name}: {e}", file=sys.stderr)
                continue
        removed += 1
        bytes_removed += size
    return removed, bytes_removed


def prune_cache_dir(d: Path, cutoff: float, dry_run: bool) -> tuple[int, int]:
    if not d.exists():
        return 0, 0
    removed = 0
    bytes_removed = 0
    for entry in d.iterdir():
        if not entry.is_file():
            continue
        try:
            mtime = entry.stat().st_mtime
            size = entry.stat().st_size
        except OSError:
            continue
        if mtime > cutoff:
            continue
        if not dry_run:
            try:
                entry.unlink()
            except OSError:
                continue
        removed += 1
        bytes_removed += size
    return removed, bytes_removed


def clear_orphaned_metadata(dry_run: bool) -> tuple[int, int]:
    """For each JobUrl row whose docx file is missing, clear the heavyweight
    fields (description, coverage JSONs, docx/pdf filenames). Returns
    (rows_touched, bytes_saved_estimate)."""
    init_db()
    db = get_session()
    try:
        # Pull only the rows that have a docx_filename set — those are the
        # ones that may have orphan metadata to clean up after the file
        # disappears.
        rows = db.query(JobUrl).filter(JobUrl.docx_filename.is_not(None)).all()
        rows_touched = 0
        bytes_saved = 0
        for ju in rows:
            docx_path = config.OUTPUTS_DIR / ju.docx_filename if ju.docx_filename else None
            file_gone = bool(docx_path and not docx_path.exists())
            if not file_gone:
                continue
            # Estimate bytes saved by clearing these columns.
            for field in ("description", "coverage_initial", "coverage_final",
                          "spec_json", "claimed_terms"):
                v = getattr(ju, field, None)
                if isinstance(v, str):
                    bytes_saved += len(v.encode("utf-8"))
            if not dry_run:
                ju.docx_filename = None
                ju.pdf_filename = None
                ju.description = None
                ju.coverage_initial = None
                ju.coverage_final = None
                ju.spec_json = None
                ju.claimed_terms = None
            rows_touched += 1
        if not dry_run:
            db.commit()
            # Reclaim freed pages in SQLite.
            db.execute(sql_text("VACUUM"))
        return rows_touched, bytes_saved
    finally:
        db.close()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7,
                        help="Delete artifacts older than this many days (default: 7).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be deleted, but make no changes.")
    args = parser.parse_args(argv)

    cutoff = time.time() - args.days * 86400
    verb = "Would delete" if args.dry_run else "Deleted"

    # 1) Generated outputs
    n, b = prune_outputs_dir(cutoff, args.dry_run)
    print(f"outputs/      {verb}: {n:>5} files, {_humanize(b)}")

    # 2) Claude caches
    total_n = 0
    total_b = 0
    for d in CACHE_DIRS_TO_PRUNE:
        n, b = prune_cache_dir(d, cutoff, args.dry_run)
        total_n += n
        total_b += b
        if n:
            print(f"  {d.name:<28} {verb.lower():<14} {n:>5} entries, {_humanize(b)}")
    print(f"caches/       {verb}: {total_n:>5} entries, {_humanize(total_b)}")

    # 3) Clear orphaned metadata. We do this AFTER the file deletes so the
    # "is the file gone?" check picks up everything from this run.
    rows, bytes_saved = clear_orphaned_metadata(args.dry_run)
    print(f"db rows       {verb}: {rows:>5} rows cleared, ~{_humanize(bytes_saved)} freed")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

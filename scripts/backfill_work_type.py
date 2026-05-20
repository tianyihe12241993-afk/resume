"""One-shot backfill: populate JobUrl.work_type using the text classifier.

Walks every JobUrl, runs ``app.work_type.classify_work_type`` against the
already-stored title/location/description, and writes the result. Skips
rows that already have a non-null work_type.

No network calls, no LLM cost. Catches the cases where the location string
or JD body has a clear remote/hybrid/onsite signal — typically ~70%
of rows. Run again after re-scraping any rows for full ATS-structured
coverage.

Usage:
    .venv/bin/python -m scripts.backfill_work_type
    .venv/bin/python -m scripts.backfill_work_type --dry-run
"""
from __future__ import annotations

import argparse
import collections
import sys

from app.work_type import classify_work_type
from tailor_studio.db import JobUrl, init_db, get_session


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would change but do not commit.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Recompute and overwrite even rows that already have work_type set.",
    )
    args = parser.parse_args(argv)

    init_db()
    db = get_session()
    try:
        q = db.query(JobUrl)
        if not args.force:
            q = q.filter(JobUrl.work_type.is_(None))
        rows = q.all()
        print(f"Scanning {len(rows)} job_url rows…")

        counts = collections.Counter()
        changed = 0
        for ju in rows:
            wt = classify_work_type(
                title=ju.title or "",
                location=ju.location or "",
                description=ju.description or "",
            )
            counts[wt or "unknown"] += 1
            if wt and ju.work_type != wt:
                if not args.dry_run:
                    ju.work_type = wt
                changed += 1

        if not args.dry_run:
            db.commit()

        print(f"\nClassification distribution:")
        for k in ("remote", "hybrid", "onsite", "unknown"):
            print(f"  {k:<8} {counts[k]:>5}")
        verb = "would update" if args.dry_run else "updated"
        print(f"\n{verb} {changed} rows.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

"""Daily discovery scheduler (in-process APScheduler).

One cron job per enabled SearchConfig fires `pipeline.enqueue_discovery` at the
profile's configured local hour. Review-then-tailor: this only produces a ranked
`discovered` batch — it never tailors automatically.
"""
from __future__ import annotations

from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler

from .db import SessionLocal, SearchConfig

PACIFIC = ZoneInfo("America/Los_Angeles")

_scheduler: BackgroundScheduler | None = None


def _job_id(profile_id: int) -> str:
    return f"discovery-{profile_id}"


def _fire(profile_id: int) -> None:
    from . import pipeline   # lazy import to avoid a cycle at module load
    pipeline.enqueue_discovery(profile_id)


def start() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(timezone=PACIFIC)
    _scheduler.start()
    sync()


def sync() -> None:
    """Reconcile scheduled jobs with the current set of enabled SearchConfigs."""
    if _scheduler is None:
        return
    db = SessionLocal()
    try:
        configs = db.query(SearchConfig).all()
        wanted: dict[int, int] = {
            c.profile_id: c.schedule_hour for c in configs if c.enabled
        }
    finally:
        db.close()

    for j in list(_scheduler.get_jobs()):
        if j.id.startswith("discovery-"):
            pid = int(j.id.rsplit("-", 1)[1])
            if pid not in wanted:
                _scheduler.remove_job(j.id)
    for pid, hour in wanted.items():
        _scheduler.add_job(
            _fire, "cron", hour=hour, minute=0, args=[pid],
            id=_job_id(pid), replace_existing=True,
        )

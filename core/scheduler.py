"""
core/scheduler.py
------------------
APScheduler wired to fire run_reminder_for_slot() at each meal time.

Uses your existing sync SessionLocal from core.database — no async needed.
"""

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from core.database import SessionLocal
from services.reminder.reminder_service import run_reminder_for_slot, MEAL_SLOTS

logger = logging.getLogger(__name__)

# BackgroundScheduler runs in a daemon thread — works perfectly with
# FastAPI's sync startup (no asyncio conflict)
scheduler = BackgroundScheduler(timezone="Asia/Kolkata")


def _make_job(slot: str):
    """Factory that closes the DB session even if the job raises."""
    def _job():
        db = SessionLocal()
        try:
            run_reminder_for_slot(db, slot)
        except Exception as exc:
            logger.error("Reminder job '%s' crashed: %s", slot, exc, exc_info=True)
        finally:
            db.close()

    _job.__name__ = f"reminder_{slot}"
    return _job


def start_scheduler() -> None:
    for flag, label, hour in MEAL_SLOTS:
        scheduler.add_job(
            _make_job(flag),
            trigger=CronTrigger(hour=hour, minute=0),
            id=f"reminder_{flag}",
            replace_existing=True,
            misfire_grace_time=300,   # retry up to 5 min late if server was busy
        )
        logger.info("Scheduled reminder job '%s' at %02d:00", flag, hour)

    scheduler.start()
    logger.info("✅ APScheduler started with %d reminder jobs", len(MEAL_SLOTS))


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped")
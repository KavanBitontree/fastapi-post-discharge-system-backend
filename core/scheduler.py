"""
core/scheduler.py
------------------
APScheduler wired to fire run_reminder_for_slot() at each meal time.

Uses your existing sync SessionLocal from core.database — no async needed.
"""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from core.database import SessionLocal
from services.reminder.reminder_service import run_reminder_for_slot, MEAL_SLOTS

logger = logging.getLogger(__name__)
TIMEZONE = ZoneInfo("Asia/Kolkata")

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


def _purge_stale_discharges() -> None:
    """Delete discharge_history rows stuck in 'pending' or 'failed' for > 24 hours."""
    from models.discharge_history import DischargeHistory
    from sqlalchemy import and_

    db = SessionLocal()
    try:
        cutoff = datetime.now(TIMEZONE) - timedelta(hours=24)
        deleted = (
            db.query(DischargeHistory)
            .filter(
                DischargeHistory.status.in_(["pending", "failed"]),
                DischargeHistory.created_at <= cutoff,
            )
            .delete(synchronize_session=False)
        )
        db.commit()
        if deleted:
            logger.info("Purged %d stale discharge record(s) older than 24 h", deleted)
    except Exception as exc:
        db.rollback()
        logger.error("Stale discharge purge failed: %s", exc, exc_info=True)
    finally:
        db.close()


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

    scheduler.add_job(
        _purge_stale_discharges,
        trigger=CronTrigger(hour=2, minute=0),   # runs daily at 02:00 IST
        id="purge_stale_discharges",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info("Scheduled stale discharge purge job at 02:00 IST")

    scheduler.start()
    logger.info("✅ APScheduler started with %d reminder jobs", len(MEAL_SLOTS))


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped")
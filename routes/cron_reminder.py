"""
routes/cron_reminder.py
------------------------
Single cron endpoint called by an external scheduler (e.g. Vercel cron,
GitHub Actions, cron-job.org).

POST /cron/reminders
    → Scans all verified Telegram patients, checks every medication whose
      next_notify_at falls within the last 20 minutes, and sends grouped
      Telegram reminders.

Window logic
────────────
  next_notify_at = 20:00 IST
  Cron fires at 20:00 → ✅ sent
  Cron fires at 20:19 → ✅ sent  (within 20-min window)
  Cron fires at 20:21 → ❌ skipped (missed the window — avoids stale sends)
"""

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from core.config import settings
from core.database import get_db
from services.reminder.reminder_service import run_all_due_reminders

router = APIRouter(prefix="/cron", tags=["Cron"])


def _verify_cron_secret(
    x_cron_secret: str = Header(..., alias="x-cron-secret")
) -> None:
    if x_cron_secret != settings.CRON_SECRET:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing cron secret.",
        )


@router.post("/reminders", dependencies=[Depends(_verify_cron_secret)])
def cron_reminders(db: Session = Depends(get_db)):
    """
    Single endpoint for external cron jobs (e.g. cron-job.org).
    Requires header:  Authorization: Bearer <CRON_SECRET>
    Sends Telegram medication reminders to all verified patients with a
    20-minute delivery window.
    """
    result = run_all_due_reminders(db, window_minutes=20)
    return {
        "message": "Cron reminder job completed.",
        "notified": result["notified"],
        "skipped":  result["skipped"],
    }

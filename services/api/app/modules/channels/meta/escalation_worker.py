"""Escalation sweep loop: 4h reminder + 24h handover resume.

Registered in app/workers/main.py alongside the other pollers. Both sweeps are
bounded and index-backed (ix_leads_pending_reminder for the reminder), so a
15s tick costs a handful of index reads rather than a scan -- which is what
makes it safe to run at every tenant's scale.
"""

import asyncio
import logging

from ....database import async_session

logger = logging.getLogger(__name__)

POLL_SECONDS = 15


async def run_escalation_sweeps() -> None:
    from . import lead_escalation

    while True:
        try:
            async with async_session() as db:
                await lead_escalation.run_reminder_sweep(db)
                await lead_escalation.run_resume_sweep(db)
                await db.commit()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # Idempotent by column state: the next tick re-reads the same rows.
            # A sweep failure must never take the worker process down.
            logger.warning(
                "escalation sweep failed: %s: %s", type(e).__name__, e
            )
        await asyncio.sleep(POLL_SECONDS)
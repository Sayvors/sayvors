"""Pending-leads digest loop.

Registered in app/workers/main.py beside the escalation sweeps.

Its own loop rather than another sweep inside escalation_worker, because the
cadence is wrong for a 15s tick: the digest fires once per tenant per local
day, so polling that often would run "which tenants are due" hundreds of times
for an answer that changes once an hour. The loop ticks hourly and decides
nothing more often than it can.
"""

import asyncio
import logging
import os

from ....database import async_session

logger = logging.getLogger(__name__)

# Hourly. The send hour is per tenant and timezone; hourly is fine enough that
# a digest lands within the hour the tenant asked for.
POLL_SECONDS = int(os.environ.get("LEAD_DIGEST_POLL_SECONDS", "3600"))


async def run_lead_digest_sweeps() -> None:
    from . import lead_digest
    from .lead_escalation import clear_settings_cache

    while True:
        try:
            async with async_session() as db:
                await lead_digest.run_digest_sweep(db)
                await db.commit()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # The daily marker means a failed tick is retried on the next one
            # and no tenant is emailed twice by the retry, so there is nothing
            # to unwind here.
            logger.warning(
                "lead digest loop failed: %s: %s", type(e).__name__, e
            )
        finally:
            clear_settings_cache()
        await asyncio.sleep(POLL_SECONDS)
"""Job reaper — lease expiry, `accepted` reconciler, stuck-lane report.

Three jobs, one loop, all idempotent so running it twice changes nothing:

- **Lease reaper.** A worker that dies mid-call leaves its job in
  `running` with a lease that has passed. The row is returned to the
  queue so it can be reclaimed. Every handler is idempotent by job id,
  so re-running one is safe.

- **`accepted` reconciler.** `accepted` was the design's "row exists,
  dispatch not confirmed" state. Nothing promoted it — dispatching to
  Kafka is best-effort and the lane runner claims from Postgres, not
  from that topic — so a row that landed there was invisible to the
  runner forever. Rows in that state are promoted to `queued`.

- **Stuck-lane report.** Every lane writes a heartbeat row when it
  claims work. A lane that stopped ticking is invisible otherwise: the
  queue simply stops moving and nobody notices until a merchant
  complains. A lane that has been quiet for too long is reported here.

Both sweeps are committed. A sweep that is not committed is a sweep that
did not happen.
"""
import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import async_session
from .models import JobLaneHeartbeat
from .service import promote_accepted_jobs, release_expired_leases

logger = logging.getLogger(__name__)

# How often the reaper runs (seconds).
REAPER_INTERVAL_SECONDS = 30

# How old an `accepted` row must be before it is swept. Gives a
# dispatcher that is mid-flight a moment to promote it properly.
ACCEPTED_GRACE_SECONDS = 60

# How long a lane may be silent before it counts as stuck. The runner
# ticks every second, so a minute of silence means the runner is gone.
LANE_STUCK_SECONDS = 90


async def report_stuck_lanes(db: AsyncSession) -> list[str]:
    """Return the lanes that have not written a heartbeat recently."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=LANE_STUCK_SECONDS)
    rows = (
        await db.execute(
            select(JobLaneHeartbeat).where(JobLaneHeartbeat.last_seen_at < cutoff)
        )
    ).scalars().all()
    stuck = [row.lane for row in rows]
    if stuck:
        logger.error(
            "Job lanes have not ticked for %ss: %s - the queue is not moving "
            "for these lanes",
            LANE_STUCK_SECONDS,
            ", ".join(stuck),
        )
    return stuck


async def reap_in_session(db: AsyncSession) -> dict:
    """One reaper pass on the caller's session. Commits before returning."""
    released = await release_expired_leases(db)
    promoted = await promote_accepted_jobs(
        db, older_than_seconds=ACCEPTED_GRACE_SECONDS
    )
    stuck = await report_stuck_lanes(db)
    await db.commit()
    totals = {"released": released, "promoted": promoted, "stuck_lanes": len(stuck)}
    if released or promoted:
        logger.info("Job reaper: %s", totals)
    return totals


async def reap_once() -> dict:
    """One reaper pass on its own session."""
    async with async_session() as db:
        return await reap_in_session(db)


async def run_job_reaper() -> None:
    """Background loop started from the worker lifespan."""
    interval = max(10, REAPER_INTERVAL_SECONDS)    # Startup jitter so fresh deploys don't fire every worker in lockstep.
    await asyncio.sleep(random.uniform(0, min(10, interval)))
    while True:
        try:
            await reap_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Job reaper pass failed: %s", e)
        await asyncio.sleep(interval)

"""Job handler: run one queued banner/promotion photo analysis.

The composer enqueues on the realtime lane because publication waits on the
result; the row it polls is the source of truth, so a worker crash surfaces
as "failed" on the row instead of a hung publish dialog. Idempotent by the
row's status: a retried job never re-analyses a finished check.
"""
from __future__ import annotations

from typing import Any


async def handle_banner_check_run(job: Any, db: Any) -> dict:
    from ...media import service

    check_id = (job.payload or {}).get("check_id") or job.subject_id
    if not check_id:
        return {"skipped": "missing check_id"}
    # Tenant-scoped lookup inside the service: a job payload is
    # caller-controlled, and analysing another tenant's queued check would
    # bill the wrong tenant for the model call.
    return await service.run_banner_check(db, check_id=check_id, tenant_id=job.tenant_id)

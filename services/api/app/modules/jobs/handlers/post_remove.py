"""post.remove job handler — remove/cancel publish jobs in the background."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ...channels.publish.service import batch_remove_published_posts
from ..models import Job

logger = logging.getLogger(__name__)


async def handle_post_remove(job: Job, db: AsyncSession) -> dict | None:
    payload = job.payload or {}
    job_ids = payload.get("job_ids") or []
    platforms = payload.get("platforms") or []
    if not isinstance(job_ids, list) or not job_ids:
        raise ValueError("job_ids missing from payload")

    if getattr(job, "ui_visible", False):
        job.progress = 10
        job.progress_label = "Removing posts"
        db.add(job)
        await db.flush()

    results = await batch_remove_published_posts(
        db,
        tenant_id=job.tenant_id,
        job_ids=[str(j) for j in job_ids if str(j).strip()],
        platforms=[str(p) for p in platforms if str(p).strip()],
    )

    removed = sum(1 for r in results if r.get("status") == "cancelled" and not (r.get("result") or {}).get("delete_error"))
    failed = sum(1 for r in results if (r.get("result") or {}).get("delete_error"))

    if getattr(job, "ui_visible", False):
        job.progress = 100
        job.progress_label = "Completed" if failed == 0 else "Completed with errors"

    return {
        "removed": removed,
        "failed": failed,
        "results": results,
    }

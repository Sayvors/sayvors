"""post.delete job handler — takes a published post down on schedule.

The job carries the id of the publish job it belongs to. The platform
post id lives on that job's result — it only exists once the publish
succeeded — so the handler reads it from there rather than copying it
into the payload at a time when it does not yet exist.

Idempotent by job id: the runner never runs a terminal job twice, and
the provider's delete is safe to repeat (a post that is already gone
is reported as gone, not as a failure).
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...channels.publish.service import (
    delete_published_from_platform,
    is_removable_method,
    resolve_publish_channel,
)
from ..models import Job

logger = logging.getLogger(__name__)


async def handle_post_delete(job: Job, db: AsyncSession) -> dict | None:
    """Remove a published post from its platform.

    Returns a result dict persisted on Job.result. Raises on a provider
    failure so the runner retries — a promo that must come down on a
    date should not be lost to one flaky call.
    """
    payload = job.payload or {}
    publish_job_id = payload.get("publish_job_id")
    if not publish_job_id:
        raise ValueError("publish_job_id missing from payload")

    publish_job = (
        await db.execute(select(Job).where(Job.id == publish_job_id))
    ).scalar_one_or_none()
    if publish_job is None:
        # The publish job was removed outright — there is nothing left
        # to take down.
        return {"skipped": "the publish job no longer exists"}

    publish_payload = publish_job.payload or {}
    method = publish_payload.get("method", "post")
    if not is_removable_method(method):
        # A profile picture or banner is not a post: it can only be
        # replaced by publishing a new one, never deleted.
        return {"skipped": f"the {method!r} format is not a removable post"}

    if publish_job.status != "succeeded":
        # The post never went out (or failed), so there is nothing on
        # the platform to remove.
        return {"skipped": f"the publish job is {publish_job.status!r}"}

    job_result = publish_job.result or {}
    post_id = (
        job_result.get("id") or job_result.get("name") or job_result.get("media_id")
    )
    if not post_id:
        return {"skipped": "the publish job recorded no platform post id"}

    platform = publish_payload.get("platform")
    external_asset_id = publish_payload.get("external_asset_id")
    if not platform or not external_asset_id:
        raise ValueError("publish job payload is missing its destination")

    channel = await resolve_publish_channel(
        db, job.tenant_id, platform, external_asset_id
    )
    try:
        result = await delete_published_from_platform(
            platform=platform,
            post_id=post_id,
            channel=channel,
            db=db,
        )
    except Exception as e:
        # A post that is already gone is the state we wanted, so a 404
        # is a success. Anything else is a real failure and the runner
        # retries it.
        if getattr(e, "status_code", None) == 404:
            result = {"deleted": True, "already_gone": True}
        else:
            raise

    # Record the removal on the publish job too, so the feed shows the
    # post as taken down rather than as still live. The status and the
    # reason mirror a manual removal, so the feed renders both the same
    # way.
    publish_job.result = {
        **(publish_job.result or {}),
        "deleted": True,
        "delete_results": [result],
    }
    publish_job.status = "cancelled"
    publish_job.last_error = "removed on schedule"
    publish_job.updated_at = datetime.now(timezone.utc)
    db.add(publish_job)

    logger.info(
        "Scheduled removal: took %s post %s down from %s",
        publish_job_id,
        post_id,
        platform,
    )

    return {
        "deleted": True,
        "platform": platform,
        "post_id": post_id,
        "publish_job_id": publish_job_id,
        "provider_result": result,
    }

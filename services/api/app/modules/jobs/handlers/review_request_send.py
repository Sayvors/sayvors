"""Job handler: send one scheduled review request.

The row was created with status "queued" by the bulk scheduler. Delivery flips
it to "sent" or "failed" with the provider error; the handler is idempotent by
the row's status, so a retried job does not send twice.
"""
from __future__ import annotations

from typing import Any

from ...analytics.models import ReviewRequest
from ...analytics.review_requests import deliver_request


async def handle_review_request_send(job: Any, db: Any) -> dict:
    request_id = (job.payload or {}).get("request_id") or job.subject_id
    if not request_id:
        return {"skipped": "missing request_id"}
    row = await db.get(ReviewRequest, request_id)
    if row is None:
        return {"skipped": "request not found", "request_id": request_id}
    await deliver_request(db, row)
    return {"request_id": request_id, "status": row.status}

"""Review-request delivery + click tracking + per-request attribution.

The ask loop has three stages the Growth funnel needs to be honest about:

1. Record  - a request row exists with a unique click token.
2. Deliver - email goes through Resend; WhatsApp goes through the tenant's
             connected Cloud API number and consumes the plan's monthly
             message allowance. A provider failure is stored on the row
             (status "failed", error text), never hidden.
3. Click   - the public redirect marks clicked_at and forwards to the listing's
             Google review composer.

Attribution is deliberately conservative: a review is credited to a request
only when that request was clicked within the attribution window before the
review's timestamp. Multiple reviews can never be credited to the same click
because the matcher walks clicks and reviews in time order.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ..channels.meta.credentials import decrypt_connection_token
from ..channels.meta.models import MetaAsset
from ..channels.meta.service import get_adapter
from ..channels.models import Channel
from ..email.service import send_email
from ..localith.models import LocalithConnection
from .models import ReviewRequest

logger = logging.getLogger(__name__)

ATTRIBUTION_WINDOW_DAYS = 7


def _review_url_from_place(place_id: str | None, maps_url: str | None) -> str | None:
    if place_id:
        return f"https://search.google.com/local/writereview?placeid={place_id}"
    return maps_url or None


async def resolve_review_url(db: AsyncSession, user_id: str, channel_id: str | None) -> str | None:
    """The listing's Google review composer URL, from the synced profile."""
    conn = (
        await db.execute(
            select(LocalithConnection).where(LocalithConnection.user_id == user_id).limit(1)
        )
    ).scalar_one_or_none()
    if conn is not None:
        url = _review_url_from_place(conn.listing_google_id, conn.maps_url)
        if url:
            return url
    if channel_id:
        channel = await db.get(Channel, channel_id)
        if channel is not None:
            meta = channel.metadata_json
            if isinstance(meta, str):
                import json

                try:
                    meta = json.loads(meta)
                except (TypeError, ValueError):
                    meta = {}
            place_id = (meta or {}).get("place_id") if isinstance(meta, dict) else None
            url = _review_url_from_place(place_id, (meta or {}).get("maps_url") if isinstance(meta, dict) else None)
            if url:
                return url
    return None


def tracked_link(token: str | None) -> str | None:
    """The public click URL that records the click then redirects to Google."""
    if not token:
        return None
    base = settings.PUBLIC_API_URL.rstrip("/")
    return f"{base}/api/v1/analytics/review-requests/{token}/click"


def _message(name: str | None, link: str | None) -> str:
    greeting = f"Hi {name}!" if name else "Hi!"
    if link:
        return (
            f"{greeting} Thanks for visiting. Would you mind leaving us a quick review? "
            f"It really helps: {link}"
        )
    return f"{greeting} Thanks for visiting. Would you mind leaving us a quick review? It really helps."


def render_template(body: str | None, name: str | None, link: str | None) -> str | None:
    """Replace {name} / {link} in a saved template. Missing values are safe."""
    if not body:
        return None
    return body.replace("{name}", name or "there").replace("{link}", link or "")


async def send_whatsapp_text(db: AsyncSession, user_id: str, to: str, text: str) -> str:
    """Send through the tenant's connected WhatsApp Cloud API number.

    Raises when no number is connected or Meta rejects the send. The caller
    stores the failure on the request row; it is never silent. A message
    outside the 24-hour customer window will be rejected by Meta unless an
    approved template is used - that limitation is surfaced as the error.
    """
    asset = (
        await db.execute(
            select(MetaAsset)
            .where(
                MetaAsset.tenant_id == user_id,
                MetaAsset.provider == "whatsapp",
                MetaAsset.asset_type == "phone_number",
                MetaAsset.status == "connected",
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if asset is None:
        raise RuntimeError("No connected WhatsApp number.")
    token = decrypt_connection_token(asset.connection) if asset.connection else None
    if not token:
        raise RuntimeError("WhatsApp credentials are not available.")
    adapter = get_adapter("whatsapp")
    return await adapter.send_text_message(asset.external_asset_id, token, to, text)


async def deliver_request(db: AsyncSession, row: ReviewRequest) -> ReviewRequest:
    """Send one request through its channel and persist the real outcome."""
    if row.status in ("sent", "delivered", "clicked", "reviewed"):
        return row

    tracked = tracked_link(row.token)
    message = render_template(row.body, row.contact_name, tracked) or _message(row.contact_name, tracked)
    subject = row.subject or "Would you leave us a quick review?"

    if row.channel == "whatsapp":
        try:
            if not row.contact:
                raise RuntimeError("Missing WhatsApp number.")
            await send_whatsapp_text(db, row.user_id, row.contact, message)
            row.status = "sent"
            row.sent_via = "whatsapp"
            row.error = None
        except Exception as e:
            row.status = "failed"
            row.sent_via = "whatsapp"
            row.error = str(e)[:300]
            logger.warning("WhatsApp review request failed for %s: %s", row.user_id, e)
    elif row.channel == "email":
        try:
            if not row.contact:
                raise RuntimeError("Missing email address.")
            await send_email(
                to=row.contact,
                subject=subject,
                html=f"<p>{message}</p>",
                text=message,
            )
            row.status = "sent"
            row.sent_via = "email"
            row.error = None
        except Exception as e:
            row.status = "failed"
            row.sent_via = "email"
            row.error = str(e)[:300]
            logger.warning("Email review request failed for %s: %s", row.user_id, e)
    else:
        row.status = "sent"
        row.sent_via = "in_person" if row.channel == "in_person" else None

    await db.commit()
    await db.refresh(row)
    return row


async def create_and_deliver(
    db: AsyncSession,
    user_id: str,
    *,
    channel_id: str | None,
    contact: str | None,
    contact_name: str | None,
    channel: str,
    trigger: str,
    deliver: bool,
    subject: str | None = None,
    body: str | None = None,
) -> ReviewRequest:
    """Create the request, optionally deliver it, and commit once."""
    token = secrets.token_urlsafe(24)
    review_url = await resolve_review_url(db, user_id, channel_id)
    row = ReviewRequest(
        user_id=user_id,
        channel_id=channel_id or None,
        contact=(contact or "")[:255] or None,
        contact_name=(contact_name or "")[:120] or None,
        channel=channel,
        trigger=trigger,
        status="queued",
        token=token,
        review_url=review_url,
        subject=(subject or "")[:200] or None,
        body=(body or "")[:8000] or None,
        sent_at=datetime.now(timezone.utc),
    )
    db.add(row)
    if deliver:
        await db.flush()
        return await deliver_request(db, row)
    row.status = "sent"
    row.sent_via = "in_person" if channel == "in_person" else None
    await db.commit()
    await db.refresh(row)
    return row


async def create_queued(
    db: AsyncSession,
    user_id: str,
    *,
    channel_id: str | None,
    contact: str | None,
    contact_name: str | None,
    channel: str,
    trigger: str,
    subject: str | None,
    body: str | None,
) -> ReviewRequest:
    """Create a queued row for the scheduled job, without sending."""
    token = secrets.token_urlsafe(24)
    review_url = await resolve_review_url(db, user_id, channel_id)
    row = ReviewRequest(
        user_id=user_id,
        channel_id=channel_id or None,
        contact=(contact or "")[:255] or None,
        contact_name=(contact_name or "")[:120] or None,
        channel=channel,
        trigger=trigger,
        status="queued",
        token=token,
        review_url=review_url,
        subject=(subject or "")[:200] or None,
        body=(body or "")[:8000] or None,
        sent_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.flush()
    return row


async def track_click(db: AsyncSession, token: str) -> str | None:
    """Mark a click and return the redirect target. None for unknown tokens."""
    row = (
        await db.execute(select(ReviewRequest).where(ReviewRequest.token == token))
    ).scalar_one_or_none()
    if row is None:
        return None
    now = datetime.now(timezone.utc)
    row.clicked_at = now
    if row.status in ("sent", "delivered"):
        row.status = "clicked"
    await db.commit()
    return row.review_url


def attribute_reviews(
    click_times: list[datetime | None],
    review_times: list[datetime | None],
    window_days: int = ATTRIBUTION_WINDOW_DAYS,
) -> int:
    """Count reviews creditable to a click, at most one review per click.

    A review is credited when the most recent unclaimed click is within
    ``window_days`` before the review. This is a conservative time-window
    attribution, not a claim that Google told us who wrote the review.
    """
    def _aware(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)

    clicks = sorted(t for t in (_aware(c) for c in click_times) if t is not None)
    if not clicks:
        return 0
    window = timedelta(days=window_days)
    used = [False] * len(clicks)
    attributed = 0
    for when in sorted(t for t in (_aware(r) for r in review_times) if t is not None):
        for i in range(len(clicks) - 1, -1, -1):
            click = clicks[i]
            if click > when:
                continue
            if when - click > window:
                break
            if not used[i]:
                used[i] = True
                attributed += 1
                break
    return attributed

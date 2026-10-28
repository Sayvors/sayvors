"""Review-request delivery + click tracking + per-request attribution.

The ask loop has three stages the Growth funnel needs to be honest about:

1. Record  - a request row exists with a unique click token.
2. Deliver - WhatsApp is a client-side deep link; SMS/email are server-side
             sends through an env-gated provider. A provider failure is stored
             on the row (status "failed", error text), never hidden.
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

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ..channels.models import Channel
from ..email.service import send_email
from ..localith.models import LocalithConnection
from .models import ReviewInsight, ReviewRequest

logger = logging.getLogger(__name__)

ATTRIBUTION_WINDOW_DAYS = 7
TWILIO_TIMEOUT_SECONDS = 10.0


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


def sms_configured() -> bool:
    return bool(
        settings.TWILIO_ACCOUNT_SID.strip()
        and settings.TWILIO_AUTH_TOKEN.strip()
        and settings.TWILIO_FROM_NUMBER.strip()
    )


async def send_sms(to: str, body: str) -> None:
    """Twilio REST send. Raises on failure so the caller records it."""
    if not sms_configured():
        raise RuntimeError("SMS provider is not configured (TWILIO_* missing).")
    url = (
        f"https://api.twilio.com/2010-04-01/Accounts/"
        f"{settings.TWILIO_ACCOUNT_SID}/Messages.json"
    )
    async with httpx.AsyncClient(timeout=TWILIO_TIMEOUT_SECONDS) as client:
        resp = await client.post(
            url,
            auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
            data={
                "From": settings.TWILIO_FROM_NUMBER,
                "To": to,
                "Body": body[:320],
            },
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Twilio rejected SMS ({resp.status_code}): {resp.text[:180]}")


def _message(name: str | None, review_url: str | None) -> str:
    greeting = f"Hi {name}!" if name else "Hi!"
    if review_url:
        return (
            f"{greeting} Thanks for visiting. Would you mind leaving us a quick review? "
            f"It really helps: {review_url}"
        )
    return f"{greeting} Thanks for visiting. Would you mind leaving us a quick review? It really helps."


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
) -> ReviewRequest:
    """Create the request, optionally deliver it, and commit once.

    WhatsApp/in-person are recorded without a server send (the client opens the
    deep link). SMS/email go through the provider and store the real outcome.
    """
    token = secrets.token_urlsafe(24)
    review_url = await resolve_review_url(db, user_id, channel_id)
    row = ReviewRequest(
        user_id=user_id,
        channel_id=channel_id or None,
        contact=(contact or "")[:255] or None,
        contact_name=(contact_name or "")[:120] or None,
        channel=channel,
        trigger=trigger,
        status="sent",
        token=token,
        review_url=review_url,
        sent_at=datetime.now(timezone.utc),
    )
    db.add(row)

    if deliver and channel in ("sms", "email"):
        if not row.contact:
            row.status = "failed"
            row.error = "Missing contact for delivery."
        elif channel == "sms":
            try:
                await send_sms(row.contact, _message(row.contact_name, review_url))
                row.sent_via = "sms"
            except Exception as e:
                row.status = "failed"
                row.sent_via = "sms"
                row.error = str(e)[:300]
                logger.warning("SMS review request failed for %s: %s", user_id, e)
        else:
            try:
                await send_email(
                    to=row.contact,
                    subject="Would you leave us a quick review?",
                    html=(
                        f"<p>{_message(row.contact_name, None)}</p>"
                        + (
                            f"<p><a href=\"{review_url}\">Leave a review</a></p>"
                            if review_url
                            else ""
                        )
                    ),
                    text=_message(row.contact_name, review_url),
                )
                row.sent_via = "email"
            except Exception as e:
                row.status = "failed"
                row.sent_via = "email"
                row.error = str(e)[:300]
                logger.warning("Email review request failed for %s: %s", user_id, e)
    else:
        row.sent_via = "whatsapp_manual" if channel == "whatsapp" else (
            "in_person" if channel == "in_person" else None
        )

    await db.commit()
    await db.refresh(row)
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
        # Newest click that could explain this review and is still unused.
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

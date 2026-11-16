"""Google Business Profile local-post fields, built from what the user entered.

Pure functions: no network and no database. The publisher sends these fields
as a create, and the edit path sends the same fields as a PATCH, so a post made
at publish time and a post edited later always take the same shape.

Google's LocalPost reference sets the rules encoded here:
- ``summary`` is the body text.
- ``event`` is required for EVENT and OFFER. Its schedule is wall-clock time at
  the business, so instants are converted to the business's local time first.
- ``offer`` accepts only ``couponCode``, ``redeemOnlineUrl`` and
  ``termsConditions``. A ``description`` field is rejected.
- ``callToAction`` is ignored for OFFER (the link goes in
  ``offer.redeemOnlineUrl``), and CALL never carries a URL.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

# Google takes one body field, so the caption and description are joined into
# it and the result is capped here.
SUMMARY_MAX_CHARS = 1500
# An event title is one line on Google's card: the first line of the caption,
# cut to this length. Google's v4 API rejects 59+ characters on
# `event.title` (ValidationError code 3), so 58 is the hard ceiling — for
# EVENT *and* OFFER posts, since OFFER also requires an event block.
EVENT_TITLE_MAX_CHARS = 58
# An event or offer without dates runs for this many days from now.
DEFAULT_WINDOW_DAYS = 7
OFFER_TERMS_DEFAULT = "Terms apply"
OFFER_TERMS_MAX_CHARS = 300
COUPON_CODE_MAX_CHARS = 64
URL_MAX_CHARS = 1000
NANOS_PER_MICROSECOND = 1000

_TOPIC_BY_METHOD = {
    "update": "STANDARD",
    # Legacy name for What's New. Jobs queued before the format split use it.
    "post": "STANDARD",
    "event": "EVENT",
    "offer": "OFFER",
}
_CTA_ACTIONS = {
    "book": "BOOK",
    "order": "ORDER",
    "shop": "SHOP",
    "learn_more": "LEARN_MORE",
    "sign_up": "SIGN_UP",
    "call": "CALL",
}


@dataclass(frozen=True)
class PostFields:
    """The LocalPost fields for one post, and the event window they resolved to.

    ``window`` is ``(start, end)`` as aware UTC for EVENT and OFFER, else None.
    A ``None`` value in ``fields`` means "no button" for the edit path, which
    sends it so Google clears the button. The create path drops it.
    """

    fields: dict[str, Any]
    window: tuple[datetime, datetime] | None


def topic_type_for(method: str) -> str:
    topic = _TOPIC_BY_METHOD.get(method)
    if topic is None:
        raise ValueError(f"GBP supports 'update', 'event' or 'offer', got {method!r}")
    return topic


def parse_instant(value: str | None) -> datetime | None:
    """An ISO-8601 value as aware UTC. A value without an offset is read as UTC."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError as e:
        raise ValueError(f"invalid date {value!r}") from e
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def scheduled_time_rfc3339(scheduled_at: str | None, now: datetime) -> str | None:
    """Google's ``scheduledTime``, or None when the post should go out now.

    Google holds the post in SCHEDULED until that moment and publishes it
    itself. A time that has already passed means "publish now": Google refuses
    a past scheduledTime, and a worker can run late, so the post goes out
    rather than failing on a slot that has already come.
    """
    at = parse_instant(scheduled_at)
    if at is None or at <= now:
        return None
    return at.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_summary(caption: str | None, description: str | None) -> str:
    """The body Google shows: the caption, then the description.

    Google has one body field, so the composer's two fields are joined. A
    description that repeats the caption is not added twice.
    """
    head = (caption or "").strip()
    tail = (description or "").strip()
    if head and tail and tail != head:
        text = f"{head}\n\n{tail}"
    else:
        text = head or tail
    return text[:SUMMARY_MAX_CHARS]


def derive_event_title(caption: str | None, description: str | None) -> str:
    """Fallback name when the merchant did not enter one: caption's first line."""
    source = (caption or "").strip() or (description or "").strip()
    first_line = source.splitlines()[0].strip() if source else ""
    return (first_line or "Event")[:EVENT_TITLE_MAX_CHARS]


# Historic name kept for callers/tests that derive a title from caption text.
event_title = derive_event_title


def resolve_event_title(
    entered: str | None, caption: str | None, description: str | None
) -> str:
    """Google requires an event name; prefer the one entered in the composer."""
    title = (entered or "").strip()
    return title[:EVENT_TITLE_MAX_CHARS] or derive_event_title(caption, description)


def location_timezone(name: str | None):
    """The IANA zone the times were entered in. Invalid names fail loudly."""
    if not name:
        return timezone.utc
    return ZoneInfo(name)


def resolve_window(
    start: datetime | None, end: datetime | None, now: datetime
) -> tuple[datetime, datetime]:
    """The event or offer window, with the defaults applied."""
    begin = start or now
    finish = end or (begin + timedelta(days=DEFAULT_WINDOW_DAYS))
    if finish <= begin:
        raise ValueError("the event or offer must end after it starts")
    return begin, finish


def _date_part(dt: datetime) -> dict[str, int]:
    return {"year": dt.year, "month": dt.month, "day": dt.day}


def _time_part(dt: datetime) -> dict[str, int]:
    return {
        "hours": dt.hour,
        "minutes": dt.minute,
        "seconds": dt.second,
        "nanos": dt.microsecond * NANOS_PER_MICROSECOND,
    }


def event_block(
    title: str, begin: datetime, finish: datetime, timezone_name: str | None = None
) -> dict[str, Any]:
    """LocalPostEvent. Wall-clock fields use the zone the times were entered in.

    Google's TimeInterval has no timezone field, so the business's local
    wall-clock values are what must be sent — never a fixed country offset.
    """
    local_tz = location_timezone(timezone_name)
    start_local = begin.astimezone(local_tz)
    end_local = finish.astimezone(local_tz)
    return {
        "title": title,
        "schedule": {
            "startDate": _date_part(start_local),
            "startTime": _time_part(start_local),
            "endDate": _date_part(end_local),
            "endTime": _time_part(end_local),
        },
    }


def offer_block(
    terms: str | None, coupon: str | None, redeem_url: str | None
) -> dict[str, str]:
    offer = {
        "termsConditions": ((terms or "").strip() or OFFER_TERMS_DEFAULT)[
            :OFFER_TERMS_MAX_CHARS
        ],
    }
    if coupon and coupon.strip():
        offer["couponCode"] = coupon.strip()[:COUPON_CODE_MAX_CHARS]
    if redeem_url and redeem_url.strip():
        offer["redeemOnlineUrl"] = redeem_url.strip()[:URL_MAX_CHARS]
    return offer


def call_to_action_block(
    cta_type: str | None, cta_url: str | None
) -> dict[str, str] | None:
    """Google's CallToAction, or None when the post has no button."""
    key = (cta_type or "").strip().lower()
    if not key:
        return None
    action = _CTA_ACTIONS.get(key)
    if action is None:
        raise ValueError(f"unknown call-to-action {cta_type!r}")
    if action == "CALL":
        return {"actionType": action}
    url = (cta_url or "").strip()
    if not url:
        raise ValueError(f"{action} call-to-action requires a URL")
    return {"actionType": action, "url": url[:URL_MAX_CHARS]}


def build_post_fields(
    *,
    topic: str,
    caption: str | None,
    description: str | None,
    cta_type: str | None,
    cta_url: str | None,
    start: datetime | None,
    end: datetime | None,
    coupon_code: str | None,
    terms: str | None,
    now: datetime,
    event_title: str | None = None,
    timezone_name: str | None = None,
) -> PostFields:
    """The text, button, event and offer fields for one post of ``topic``."""
    fields: dict[str, Any] = {}
    summary = build_summary(caption, description)
    if summary:
        fields["summary"] = summary
    window = None
    if topic in ("EVENT", "OFFER"):
        window = resolve_window(start, end, now)
        fields["event"] = event_block(
            resolve_event_title(event_title, caption, description),
            *window,
            timezone_name=timezone_name,
        )
    if topic == "OFFER":
        # The offer's link is its redeem URL. An offer has no button.
        fields["offer"] = offer_block(terms, coupon_code, cta_url)
    else:
        fields["callToAction"] = call_to_action_block(cta_type, cta_url)
    return PostFields(fields=fields, window=window)

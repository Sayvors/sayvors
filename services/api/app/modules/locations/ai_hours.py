"""Opening hours as a prompt block for customer-facing AI.

The hours were already stored on `location_profiles.hours` (edited in the
Locations screen, synced to Google), but nothing fed them to the WhatsApp /
Instagram assistant — so "what are your working hours?" was answered with
"let me confirm with the team", every time, even though the business had
published them.

This module renders the same data the dashboard shows into a short,
ground-truth block. It is read-only and best-effort: a missing row, a
malformed value or a pre-migration database yields "" and the reply goes out
without hours rather than not going out at all.
"""

import logging
from datetime import date

from sqlalchemy import select

logger = logging.getLogger(__name__)

# Canonical order and spelling. Stored keys are matched case-insensitively
# because Google sync writes "MONDAY" while the manual editor writes "Monday".
_DAYS = (
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
)

# Labels shown for `hours["more"]` entries, which Google models as named
# periods rather than weekdays (brunch, delivery, drive-through...).
_MORE_LABELS = {
    "BRUNCH": "Brunch",
    "DELIVERY": "Delivery",
    "DRIVE_THROUGH": "Drive-through",
    "HAPPY_HOUR": "Happy hour",
    "PICKUP": "Pickup",
    "SENIOR_HOURS": "Senior hours",
    "TAKEOUT": "Takeout",
    "ONLINE_SERVICE_HOURS": "Online service",
}


def _hhmm(value: object) -> str:
    """Normalise a stored time to HH:MM; "" when it is not a time."""
    text = str(value or "").strip()
    if not text:
        return ""
    parts = text.split(":")
    if len(parts) < 2:
        return ""
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        return ""
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return ""
    return f"{hour:02d}:{minute:02d}"


def _weekly_lines(regular: dict | None) -> list[str]:
    by_day = {
        str(k or "").strip().lower(): v
        for k, v in (regular or {}).items()
        if isinstance(v, dict)
    }
    lines: list[str] = []
    for day in _DAYS:
        cfg = by_day.get(day.lower())
        if not cfg:
            continue
        if cfg.get("closed"):
            lines.append(f"- {day}: closed")
            continue
        opened, closed = _hhmm(cfg.get("open")), _hhmm(cfg.get("close"))
        if opened and closed:
            lines.append(f"- {day}: {opened}-{closed}")
    return lines


def _special_lines(special: list | None, today: date) -> list[str]:
    """Upcoming exceptional dates only.

    Old entries are noise the model could repeat as current, so anything
    before today is skipped. The list is capped: a holiday calendar is not
    worth more than a handful of prompt lines.
    """
    lines: list[str] = []
    for entry in (special or [])[:20]:
        if not isinstance(entry, dict):
            continue
        raw = str(entry.get("date") or "").strip()
        try:
            day = date.fromisoformat(raw)
        except ValueError:
            continue
        if day < today:
            continue
        hours = str(entry.get("hours") or "").strip()
        reason = str(entry.get("reason") or "").strip()
        detail = hours or "special hours"
        suffix = f" ({reason})" if reason else ""
        lines.append(f"- {day.isoformat()}: {detail}{suffix}")
    return lines


def _more_lines(more: list | None) -> list[str]:
    lines: list[str] = []
    for entry in (more or [])[:10]:
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("type") or "").strip().upper()
        opened, closed = _hhmm(entry.get("open")), _hhmm(entry.get("close"))
        if not (opened and closed):
            continue
        label = _MORE_LABELS.get(kind, kind.title() or "Hours")
        lines.append(f"- {label}: {opened}-{closed}")
    return lines


def render_hours_block(hours: dict | None, timezone_name: str = "UTC") -> str:
    """Prompt-ready block from a stored `hours` JSON. "" when empty."""
    if not isinstance(hours, dict) or not hours:
        return ""
    weekly = _weekly_lines(hours.get("regular"))
    special = _special_lines(hours.get("special"), date.today())
    more = _more_lines(hours.get("more"))
    if not (weekly or special or more):
        return ""

    lines = [
        "OPENING HOURS (owner-configured — treat as ground truth and answer "
        "from this when asked):",
        *weekly,
    ]
    if more:
        lines += ["Also:", *more]
    if special:
        lines += ["Upcoming special dates:", *special]
    lines.append(
        f"All times are local ({timezone_name or 'UTC'}). "
        "If a day is not listed above, say you will confirm it with the team."
    )
    return "\n".join(lines)


async def opening_hours_block(
    db,
    tenant_id: str,
    listing_id: str | None = None,
    timezone_name: str = "UTC",
) -> str:
    """The hours prompt block for one tenant's location. Never raises."""
    from .models import LocationProfile

    try:
        rows = (
            await db.execute(
                select(LocationProfile)
                .where(LocationProfile.user_id == tenant_id)
                .order_by(LocationProfile.updated_at.desc())
            )
        ).scalars().all()
    except Exception as e:  # noqa: BLE001 - never cost the reply
        logger.warning("opening hours lookup failed tenant=%s: %s", tenant_id, e)
        return ""

    if not rows:
        return ""
    # Prefer the location this channel belongs to; fall back to the most
    # recently edited profile, which is the one the owner is working on.
    chosen = None
    if listing_id:
        chosen = next((r for r in rows if str(r.listing_id) == str(listing_id)), None)
    if chosen is None:
        chosen = next((r for r in rows if r.hours), None)
    if chosen is None:
        return ""
    return render_hours_block(chosen.hours, timezone_name)

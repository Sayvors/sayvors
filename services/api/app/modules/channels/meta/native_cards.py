"""Native WhatsApp cards the assistant can attach to a reply.

The model never sends a card by itself: it appends a hidden marker line
(`SEND_LOCATION` / `SEND_CONTACT`), the pipeline strips it, looks up the
tenant's primary location, and calls the same adapter methods the inbox
composer uses. No marker, no card — the text answer is unchanged.

Coordinates are read from the Google Maps URL the tenant already stores. When
that URL carries no coordinates the location card is skipped and the text
address remains the answer; the pipeline never geocodes or invents a pin.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote_plus

_MARKER = re.compile(r"^\s*SEND_(LOCATION|CONTACT)\s*$", re.IGNORECASE)

_COORD_PATTERNS = (
    # https://www.google.com/maps/@24.7136,46.6753,17z
    re.compile(r"@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)"),
    # https://maps.google.com/?q=24.7136,46.6753
    re.compile(r"[?&]q=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)"),
    # ...!3d24.7136!4d46.6753
    re.compile(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)"),
)


def split_native_card_request(text: str | None) -> tuple[str, str | None]:
    """Strip one hidden `SEND_LOCATION`/`SEND_CONTACT` line.

    Returns (visible reply, "location"|"contact"|None). A malformed or
    duplicate marker is left as ordinary text only if no valid marker is
    found; the first valid marker wins.
    """
    kind: str | None = None
    kept: list[str] = []
    for line in (text or "").splitlines():
        match = _MARKER.match(line)
        if match:
            if kind is None:
                kind = match.group(1).lower()
            continue
        kept.append(line)
    return "\n".join(kept).strip(), kind


def coordinates_from_maps_url(url: str | None) -> tuple[float, float] | None:
    """Best-effort (lat, lng) from a Google Maps URL, else None."""
    if not url:
        return None
    decoded = unquote_plus(str(url))
    for pattern in _COORD_PATTERNS:
        match = pattern.search(decoded)
        if not match:
            continue
        lat = float(match.group(1))
        lng = float(match.group(2))
        if -90 <= lat <= 90 and -180 <= lng <= 180:
            return lat, lng
    return None


@dataclass(frozen=True)
class PrimaryCard:
    """The tenant contact details a native card can be built from."""

    name: str | None
    address: str | None
    phone: str | None
    latitude: float | None
    longitude: float | None


async def primary_card(db, tenant_id: str) -> PrimaryCard | None:
    """The first saved location for this tenant, with parsed coordinates.

    Returns None when the tenant has no location row yet. The caller degrades
    to text; a location row without a maps URL still yields a contact card
    when a phone exists.
    """
    from sqlalchemy import select

    from ...localith.models import LocalithConnection

    row = (
        await db.execute(
            select(LocalithConnection)
            .where(LocalithConnection.user_id == tenant_id)
            .order_by(LocalithConnection.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    coords = coordinates_from_maps_url(row.maps_url)
    return PrimaryCard(
        name=(row.listing_name or "").strip() or None,
        address=(row.address or "").strip() or None,
        phone=(row.phone_number or "").strip() or None,
        latitude=coords[0] if coords else None,
        longitude=coords[1] if coords else None,
    )

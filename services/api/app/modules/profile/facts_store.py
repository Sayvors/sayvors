"""Central, materialised business facts for the AI.

One row per tenant (`tenant_facts`) holding everything the assistant needs to
answer factual questions: identity, contact, services, team and every
location's opening hours. The reply path reads this row through a tool
instead of querying nine tables, so there is one place to inspect and one
place to fix when the assistant "doesn't know" something.

Freshness contract:
  * write paths rebuild eagerly (profile, hours, services, team),
  * a read older than ``TTL_SECONDS`` rebuilds on demand,
  * a missing row rebuilds on demand.
The row is a cache with a source of truth behind it — never the other way
around.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .models import TenantFacts

logger = logging.getLogger(__name__)

TTL_SECONDS = 600

_DAYS = (
    ("mon", "Mon", "Monday"),
    ("tue", "Tue", "Tuesday"),
    ("wed", "Wed", "Wednesday"),
    ("thu", "Thu", "Thursday"),
    ("fri", "Fri", "Friday"),
    ("sat", "Sat", "Saturday"),
    ("sun", "Sun", "Sunday"),
)


def _as_aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _slot_range(slot: dict) -> str:
    start = str(slot.get("start") or slot.get("open") or "").strip()
    end = str(slot.get("end") or slot.get("close") or "").strip()
    return f"{start}–{end}" if start and end else ""


def _day_token(raw) -> str:
    """One day's opening token: '09:00–17:00', '09:00–13:00 & 17:00–21:00', 'closed'."""
    if isinstance(raw, dict):
        # Locations shape: {open, close, closed}
        if raw.get("closed"):
            return "closed"
        value = _slot_range(raw)
        return value or "closed"
    if isinstance(raw, list):
        slots = [_slot_range(s) for s in raw[:3] if isinstance(s, dict)]
        slots = [s for s in slots if s]
        return " & ".join(slots) if slots else "closed"
    return "closed"


def normalise_schedule(hours: dict | None) -> dict[str, str]:
    """Any stored hours shape → {mon..sun: token}, in week order."""
    if not isinstance(hours, dict) or not hours:
        return {}
    regular = hours.get("regular") if isinstance(hours.get("regular"), dict) else None
    by_day: dict[str, str] = {}
    if regular:
        lowered = {str(k).strip().lower(): v for k, v in regular.items()}
        for key, _short, long_name in _DAYS:
            raw = lowered.get(long_name.lower()) or lowered.get(key)
            if raw is not None:
                by_day[key] = _day_token(raw)
        return by_day
    # Legacy WhatsApp profile shape: {mon: [{start, end}], ...}
    for key, _short, _long in _DAYS:
        if key in hours:
            by_day[key] = _day_token(hours[key])
    return by_day


def compress_schedule(schedule: dict[str, str]) -> str:
    """'Mon–Thu 09:00–17:00, Fri closed, Sat–Sun 09:00–17:00'."""
    if not schedule:
        return ""
    tokens = [(short, schedule.get(key, "closed")) for key, short, _long in _DAYS]
    parts: list[str] = []
    index = 0
    while index < len(tokens):
        end = index
        while end + 1 < len(tokens) and tokens[end + 1][1] == tokens[index][1]:
            end += 1
        label = (
            tokens[index][0]
            if end == index
            else f"{tokens[index][0]}–{tokens[end][0]}"
        )
        value = tokens[index][1]
        parts.append(f"{label} closed" if value == "closed" else f"{label} {value}")
        index = end + 1
    return ", ".join(parts)


def _location_label(location: dict) -> str:
    name = str(location.get("name") or "").strip()
    address = str(location.get("address") or "").strip()
    if name and address and address.lower() != name.lower():
        return f"{name} ({address})"
    return name or address or str(location.get("listing_id") or "location")


def render_locations(locations: list[dict]) -> str:
    """Multi-location hours, with identical schedules grouped.

    The assistant must be able to say "we have three branches: Al-Malaz and
    Olaya open 9-5, Dammam opens 10-10" in one sentence instead of listing
    every day of every branch.
    """
    if not locations:
        return ""
    scheduled = [loc for loc in locations if loc.get("schedule")]
    if not scheduled:
        return ""

    if len(scheduled) == len(locations):
        distinct = {loc["schedule"] for loc in scheduled}
        if len(distinct) == 1 and len(locations) > 1:
            names = "; ".join(_location_label(loc) for loc in locations)
            return (
                f"All {len(locations)} locations ({names}): "
                f"{scheduled[0]['schedule']}"
            )

    if len(locations) == 1:
        loc = locations[0]
        label = _location_label(loc)
        schedule = loc.get("schedule") or "hours not set"
        return f"{label}: {schedule}"

    lines = [f"We have {len(locations)} locations:"]
    for loc in locations:
        label = _location_label(loc)
        schedule = loc.get("schedule") or "hours not set"
        lines.append(f"- {label}: {schedule}")
    return "\n".join(lines)


async def _user_row(db, tenant_id: str):
    from ..users.models import User

    return await db.get(User, tenant_id)


async def _whatsapp_profile(db, tenant_id: str) -> dict:
    """Business profile stored from the tenant's WhatsApp number, if any."""
    try:
        from ..channels.meta.models import MetaAsset

        asset = (
            await db.execute(
                select(MetaAsset)
                .where(
                    MetaAsset.tenant_id == tenant_id,
                    MetaAsset.provider == "whatsapp",
                    MetaAsset.active.is_(True),
                )
                .order_by(MetaAsset.updated_at.desc())
            )
        ).scalars().first()
        if asset is None:
            return {}
        return dict((asset.asset_metadata or {}).get("business_profile") or {})
    except Exception as e:  # noqa: BLE001 - facts are an enhancement
        logger.warning("WhatsApp profile facts failed tenant=%s: %s", tenant_id, e)
        return {}


async def _services(db, tenant_id: str) -> dict:
    try:
        from ..channels.models import BusinessService, Channel

        rows = (
            await db.execute(
                select(BusinessService)
                .join(Channel, Channel.id == BusinessService.channel_id)
                .where(Channel.user_id == tenant_id)
                .order_by(BusinessService.name)
            )
        ).scalars().all()
    except Exception as e:  # noqa: BLE001
        logger.warning("service facts failed tenant=%s: %s", tenant_id, e)
        return {"offered": [], "not_offered": []}
    offered = sorted({r.name.strip() for r in rows if r.is_offered and (r.name or "").strip()})
    not_offered = sorted({r.name.strip() for r in rows if not r.is_offered and (r.name or "").strip()})
    return {"offered": offered[:40], "not_offered": not_offered[:20]}


async def _team(db, tenant_id: str) -> list[dict]:
    try:
        from ..team.models import TeamMember, TeamRole
        from ..users.models import User

        rows = (
            await db.execute(
                select(User, TeamRole)
                .join(TeamMember, TeamMember.user_id == User.id)
                .join(TeamRole, TeamRole.id == TeamMember.role_id)
                .where(
                    TeamMember.tenant_id == tenant_id,
                    TeamMember.status == "active",
                )
                .order_by(TeamRole.name, User.first_name)
                .limit(20)
            )
        ).all()
    except Exception as e:  # noqa: BLE001
        logger.warning("team facts failed tenant=%s: %s", tenant_id, e)
        return []
    members: list[dict] = []
    for user, role in rows:
        name = " ".join(
            part for part in (
                str(user.first_name or "").strip(),
                str(user.last_name or "").strip(),
            ) if part
        ).strip()
        if name:
            members.append({"name": name, "role": str(role.name or "").strip()})
    return members


async def _locations(db, tenant_id: str) -> list[dict]:
    """Every location with its address and normalised hours."""
    try:
        from ..localith.models import LocalithConnection
        from ..locations.models import LocationProfile

        profiles = (
            await db.execute(
                select(LocationProfile)
                .where(LocationProfile.user_id == tenant_id)
                .order_by(LocationProfile.updated_at.desc())
            )
        ).scalars().all()
        connections = (
            await db.execute(
                select(LocalithConnection).where(LocalithConnection.user_id == tenant_id)
            )
        ).scalars().all()
    except Exception as e:  # noqa: BLE001
        logger.warning("location facts failed tenant=%s: %s", tenant_id, e)
        return []

    by_listing = {str(c.listing_id): c for c in connections}
    out: list[dict] = []
    for profile in profiles:
        connection = by_listing.get(str(profile.listing_id))
        schedule = compress_schedule(normalise_schedule(profile.hours))
        out.append({
            "listing_id": str(profile.listing_id),
            "name": (getattr(connection, "listing_name", "") or "").strip(),
            "address": (getattr(connection, "address", "") or "").strip(),
            "website": (getattr(connection, "website_url", "") or "").strip(),
            "schedule": schedule,
        })
    return out


async def build_facts(db, tenant_id: str, user=None) -> dict:
    """Read the sources and shape one facts document. Never raises."""
    user = user or await _user_row(db, tenant_id)
    if user is None:
        return {"version": 1, "business": {}, "locations": []}

    profile = await _whatsapp_profile(db, tenant_id)
    services = await _services(db, tenant_id)
    team = await _team(db, tenant_id)
    locations = await _locations(db, tenant_id)

    # Pre-removal tenants saved hours only on the old WhatsApp profile editor.
    # Until they re-save under Locations, expose that schedule as the main
    # location so the answer is still correct.
    if not any(loc.get("schedule") for loc in locations):
        legacy_schedule = compress_schedule(normalise_schedule(profile.get("hours")))
        if legacy_schedule:
            locations.append({
                "listing_id": "whatsapp-legacy",
                "name": (getattr(user, "business_name", None) or "").strip(),
                "address": str(profile.get("address") or "").strip(),
                "website": "",
                "schedule": legacy_schedule,
            })

    owner = " ".join(
        part for part in (
            str(getattr(user, "first_name", "") or "").strip(),
            str(getattr(user, "last_name", "") or "").strip(),
        ) if part
    ).strip()

    websites = profile.get("websites") or []
    if isinstance(websites, str):
        websites = [websites]

    return {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "business": {
            "name": (getattr(user, "business_name", None) or "").strip(),
            "type": (getattr(user, "business_type", None) or "").strip(),
            "description": (getattr(user, "business_description", None) or "").strip(),
            "sells": (getattr(user, "business_sells", None) or "").strip(),
            "doesnt_sell": (getattr(user, "business_doesnt_sell", None) or "").strip(),
            "owner": owner,
        },
        "contact": {
            "address": str(profile.get("address") or "").strip(),
            "email": str(profile.get("email") or "").strip(),
            "websites": [str(w).strip() for w in websites if str(w or "").strip()][:3],
        },
        "services": services,
        "team": team,
        "locations": locations,
    }


async def rebuild_facts(db, tenant_id: str, user=None) -> dict:
    """Build and persist the facts row. Returns the facts document."""
    facts = await build_facts(db, tenant_id, user)
    row = await db.get(TenantFacts, tenant_id)
    if row is None:
        row = TenantFacts(
            tenant_id=tenant_id,
            facts=facts,
            version=int(facts.get("version") or 1),
        )
        db.add(row)
    else:
        row.facts = facts
        row.version = int(row.version or 1) + 1
        row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return facts


async def rebuild_facts_safe(db, tenant_id: str, user=None) -> None:
    """Best-effort rebuild for write paths — never breaks the save."""
    try:
        await rebuild_facts(db, tenant_id, user)
    except Exception as e:  # noqa: BLE001
        logger.warning("facts rebuild failed tenant=%s: %s", tenant_id, e)


async def get_facts(db, tenant_id: str, *, max_age_seconds: int = TTL_SECONDS) -> dict:
    """The cached facts document, rebuilt when missing or stale."""
    row = await db.get(TenantFacts, tenant_id)
    fresh = (
        row is not None
        and _as_aware(row.updated_at) is not None
        and _as_aware(row.updated_at) > datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
    )
    if row is not None and fresh:
        return dict(row.facts or {})
    return await rebuild_facts(db, tenant_id)


def render_core(facts: dict) -> str:
    """Small identity block always worth injecting."""
    business = facts.get("business") or {}
    lines = ["BUSINESS IDENTITY (owner-configured, treat as ground truth):"]
    name = business.get("name") or ""
    btype = business.get("type") or ""
    if name and btype:
        lines.append(f"- {name} ({btype})")
    elif name:
        lines.append(f"- {name}")
    if business.get("description"):
        lines.append(f"- About: {business['description'][:600]}")
    if business.get("sells"):
        lines.append(f"- Sells / offers: {business['sells'][:400]}")
    if business.get("doesnt_sell"):
        lines.append(f"- Does NOT offer: {business['doesnt_sell'][:300]}")
    return "\n".join(lines) if len(lines) > 1 else ""

"""Tenant-scoped business facts used to classify a branch and choose questions.

Merchant overrides win over Google-synced values because they represent what
the owner says is true today. Every field retained in the profile is also
reported through ``source_fields`` so generated questions can explain their
inputs without exposing private data.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..channels.models import Channel
from ..locations.models import LocationBusinessOverride, LocationProfile


def _metadata(channel: Any) -> dict:
    try:
        value = json.loads(getattr(channel, "metadata_json", None) or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _categories(value: Any) -> dict:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): item
        for key, item in value.items()
        if item is not None and str(key) in {"category", "subcategories", "sub_subcategories"}
    }


def _services(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str):
            label = item.strip()
        elif isinstance(item, dict):
            label = str(item.get("label") or item.get("name") or "").strip()
        else:
            continue
        if label and label not in out:
            out.append(label)
    return out


def build_branch_facts(channel: Any, profile: Any, override: Any) -> dict:
    """Merge Google facts and merchant overrides into one bounded profile."""
    meta = _metadata(channel)
    override_categories = _categories(getattr(override, "categories", None))
    profile_categories = _categories(getattr(profile, "categories", None))
    hours = getattr(override, "hours", None) or getattr(profile, "hours", None) or {}
    service_area = getattr(profile, "service_area", None) or []
    attributes = getattr(profile, "attributes", None) or {}
    facts = {
        "name": getattr(override, "name", None) or getattr(channel, "display_name", ""),
        "address": meta.get("address") or meta.get("locality"),
        "locality": meta.get("locality"),
        "phone": meta.get("phone"),
        "website": meta.get("website"),
        "maps_url": meta.get("maps_url"),
        "categories": override_categories or profile_categories,
        "description": getattr(profile, "description", None),
        "services": _services(getattr(override, "services", None)),
        "hours": hours if isinstance(hours, dict) else {},
        "service_area": list(service_area) if isinstance(service_area, list) else [],
        "attributes": dict(attributes) if isinstance(attributes, dict) else {},
        "opening_date": getattr(profile, "opening_date", None),
    }
    facts["source_fields"] = tuple(
        key for key, value in facts.items() if value not in (None, "", [], {})
    )
    return facts


async def load_branch_facts(
    db: AsyncSession, tenant_id: str, channel_id: str
) -> dict:
    """Load branch facts with tenant scope and merchant-override precedence."""
    channel = (
        await db.execute(
            select(Channel).where(
                Channel.id == channel_id,
                Channel.user_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if channel is None:
        raise ValueError("channel_not_owned")
    meta = _metadata(channel)
    listing_id = str(meta.get("location_id") or channel.listing_key or "")
    profile = (
        await db.execute(
            select(LocationProfile).where(
                LocationProfile.user_id == tenant_id,
                LocationProfile.listing_id == listing_id,
            )
        )
    ).scalar_one_or_none()
    override = (
        await db.execute(
            select(LocationBusinessOverride).where(
                LocationBusinessOverride.user_id == tenant_id,
                LocationBusinessOverride.listing_id == listing_id,
            )
        )
    ).scalar_one_or_none()
    return build_branch_facts(channel, profile, override)

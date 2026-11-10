"""Locations backing service.

Native Google Business Profile is the only listing source. Google-synced
fields (name, address, phone, website, Maps URL) come from the channel
metadata written by the OAuth callback and review worker; editable sections
(description, categories, hours, service area, attributes, opening date) are
stored in `location_profiles` and pushed with the Business Information API.
"""
import copy
import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..channels.models import Channel
from .models import LocationGroup, LocationProfile

logger = logging.getLogger(__name__)

GOOGLE_SYNCED_FIELDS = [
    "name",
    "phone",
    "website",
    "description",
    "categories",
    "hours.regular",
    "hours.special",
    "hours.more",
]


def _known_synced(meta: dict) -> set[str]:
    """Fields the channel's stored report considers present on Google.

    Older rows were written before hours/categories were tracked. Backfill the
    defaults on read, minus any section the last push explicitly rejected, so
    a refresh does not show a false "Stored in Sayvors" badge.
    """
    stored = meta.get("google_synced")
    if not isinstance(stored, list):
        return set(GOOGLE_SYNCED_FIELDS)
    failed: set[str] = set()
    skipped = meta.get("google_failed") or meta.get("google_skipped")
    if isinstance(skipped, dict):
        for section in skipped:
            failed.add("categories" if section.startswith("categories") else section)
    return set(stored) | (set(GOOGLE_SYNCED_FIELDS) - failed)


def _has_failed(meta: dict, section: str) -> bool:
    """Whether a push section has a recorded Google failure to retry.

    `google_failed` keys are the section keys `push_profile` reports (e.g.
    "categories.additional", "hours.regular"). A sub-section failure must
    re-push the whole section, so match on the section prefix.
    """
    failed = meta.get("google_failed") or {}
    if not isinstance(failed, dict):
        return False
    return any(
        key == section or key.startswith(section + ".")
        for key in failed
    )


def channel_meta(channel: Channel) -> dict:
    """The channel's stored Google listing metadata."""
    try:
        meta = json.loads(channel.metadata_json or "{}")
    except (TypeError, ValueError):
        return {}
    return meta if isinstance(meta, dict) else {}


def listing_id_of(channel: Channel) -> str:
    """Stable listing key: Google location id, never the display name."""
    meta = channel_meta(channel)
    return str(
        meta.get("location_id")
        or channel.platform_user_id
        or channel.listing_key
        or channel.id
    )


def is_native_google(
    channel: Channel, statuses: tuple[str, ...] = ("active",)
) -> bool:
    """True for a Google-OAuth channel in one of `statuses`.

    Expired channels are still listed so the merchant can see their data and a
    reconnect prompt instead of an empty Locations page.
    """
    return channel.platform == "google_reviews" and channel.status in statuses


async def native_channels(
    db: AsyncSession,
    user_id: str,
    statuses: tuple[str, ...] = ("active",),
) -> list[Channel]:
    """Every native Google listing for the tenant, oldest first."""
    rows = (
        await db.execute(
            select(Channel)
            .where(
                Channel.user_id == user_id,
                Channel.platform == "google_reviews",
                Channel.status.in_(statuses),
            )
            .order_by(Channel.created_at)
        )
    ).scalars().all()
    return [ch for ch in rows if is_native_google(ch, statuses)]


async def channel_for_listing(
    db: AsyncSession,
    user_id: str,
    listing_id: str,
    statuses: tuple[str, ...] = ("active",),
) -> Channel | None:
    for channel in await native_channels(db, user_id, statuses):
        if listing_id_of(channel) == listing_id or channel.id == listing_id:
            return channel
    return None


async def disconnected_listing_ids(db: AsyncSession, user_id: str) -> set[str]:
    """Listing ids whose Google connection is explicitly disconnected."""
    return {
        listing_id_of(ch)
        for ch in await native_channels(db, user_id, statuses=("disconnected",))
    }


async def _profile(db: AsyncSession, user_id: str, listing_id: str) -> LocationProfile:
    try:
        result = await db.execute(
            select(LocationProfile).where(
                LocationProfile.user_id == user_id,
                LocationProfile.listing_id == listing_id,
            )
        )
        profile = result.scalar_one_or_none()
        if profile is None:
            profile = LocationProfile(user_id=user_id, listing_id=listing_id)
            db.add(profile)
            await db.flush()
        return profile
    except Exception as e:
        # Table missing on dev DBs that haven't run migrations — don't 500 the page.
        if "UndefinedTableError" in type(e).__name__ or "does not exist" in str(e):
            logger.debug("location_profiles missing, returning ephemeral profile: %s", e)
            try:
                await db.rollback()
            except Exception:
                pass
            return LocationProfile(user_id=user_id, listing_id=listing_id)
        raise


def _status_of(channel: Channel | None) -> str:
    return channel.status if channel is not None else "unknown"


async def _google_country(channel: Channel, meta: dict) -> str | None:
    """Read a location's storefront region from Google (best effort).

    Used only when the channel metadata predates the country field. Once
    resolved it is stored on the channel, so this is one call per old row.
    """
    from ...config import settings

    if settings.TESTING or not (channel.access_token or channel.refresh_token):
        return None
    from ..channels.google_business import GBP_BIZINFO_API, GoogleBusinessClient
    from ..channels.service import decrypt_token

    access = decrypt_token(channel.access_token) if channel.access_token else None
    refresh = decrypt_token(channel.refresh_token) if channel.refresh_token else None
    client = GoogleBusinessClient(access or "", refresh)
    try:
        google_id = meta.get("location_id") or listing_id_of(channel)
        resp = await client._authed_request(
            "GET",
            f"{GBP_BIZINFO_API}/locations/{google_id}",
            params={"readMask": "storefrontAddress"},
        )
        if resp.status_code != 200:
            return None
        code = (
            ((resp.json().get("storefrontAddress") or {}).get("regionCode") or "")
            .strip()
            .upper()[:2]
        )
        return code or None
    except Exception as e:  # noqa: BLE001 - fallback is the account country
        logger.debug("Country backfill failed for %s: %s", listing_id_of(channel), e)
        return None
    finally:
        await client.close()


async def get_profile(
    db: AsyncSession, user_id: str, listing_id: str
) -> dict:
    """Merged profile for one native Google listing (auto-creates the local row)."""
    try:
        profile = await _profile(db, user_id, listing_id)
        await db.commit()
    except Exception as e:
        if "UndefinedTableError" in type(e).__name__ or "does not exist" in str(e):
            logger.debug("get_profile fallback for missing table: %s", e)
            try:
                await db.rollback()
            except Exception:
                pass
            # Return ephemeral in-memory profile so the page still loads
            profile = LocationProfile(user_id=user_id, listing_id=listing_id)
        else:
            raise

    # Fetch after the try/except: the missing-table fallback in _profile
    # rolls the session back, and rollback expires every loaded object.
    # Touching an expired attribute below would trigger a sync lazy-load
    # (MissingGreenlet); a fresh select repopulates it inside the await.
    channel = await channel_for_listing(
        db, user_id, listing_id, statuses=("active", "expired")
    )
    meta = channel_meta(channel) if channel is not None else {}
    stored_skipped = meta.get("google_failed") or meta.get("google_skipped")

    # The category catalog is region-specific. Prefer the region Google
    # returns for this location's storefront; fall back to the account country
    # instead of assuming Saudi Arabia for every tenant.
    profile_country = meta.get("country") or meta.get("region_code")
    if not profile_country and channel is not None:
        profile_country = await _google_country(channel, meta)
        if profile_country:
            meta["country"] = profile_country
            channel.metadata_json = json.dumps(meta)
            await db.commit()
    if not profile_country:
        from ..users.models import User

        profile_country = (
            await db.execute(select(User.country).where(User.id == user_id))
        ).scalar_one_or_none()
    profile_country = (
        str(profile_country).strip().upper()[:2] if profile_country else None
    )

    # Local edits win section-by-section; anything never edited locally falls
    # back to the Google snapshot fetched at connect/worker time.
    local_hours = dict(profile.hours or {})
    hours = dict(meta.get("hours") or {})
    for section in ("regular", "special", "more"):
        if section in local_hours:
            hours[section] = local_hours[section]
    local_categories = dict(profile.categories or {})
    categories = (
        local_categories
        if local_categories
        else dict(meta.get("categories") or {})
    )
    local_attributes = dict(profile.attributes or {})
    attributes = local_attributes or dict(meta.get("attributes") or {})
    service_area = list(profile.service_area or []) or list(meta.get("service_area") or [])

    merged = {
        "listing_id": listing_id,
        "name": "",
        "address": None,
        "country": profile_country,
        "phone": None,
        "website": None,
        "maps_url": None,
        "status": "unknown",
        "is_verified": None,
        "description": profile.description,
        "categories": categories,
        "hours": hours,
        "service_area": service_area,
        "attributes": attributes,
        "opening_date": profile.opening_date.isoformat() if profile.opening_date else None,
        "google_synced": [],
        "google_skipped": {},
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }
    if channel is not None:
        # A local edit that differs from the Google snapshot has not reached
        # Google, even if an older sync report claimed otherwise. This is the
        # difference that matters: the stored report is a history, the values
        # are the truth.
        synced_fields = _known_synced(meta)
        local_categories = dict(profile.categories or {})
        google_categories = dict(meta.get("categories") or {})
        if local_categories and local_categories != google_categories:
            synced_fields.discard("categories")
        merged.update({
            "name": channel.display_name or "",
            "address": meta.get("address"),
            "phone": meta.get("phone"),
            "website": meta.get("website"),
            "maps_url": meta.get("maps_url"),
            "status": _status_of(channel),
            "is_verified": None,
            # Google's own description fills the gap until the merchant
            # saves a local override, which always wins.
            "description": profile.description
            if profile.description is not None
            else meta.get("description"),
            "google_synced": sorted(synced_fields),
            "google_skipped": (
                dict(stored_skipped) if isinstance(stored_skipped, dict) else {}
            ),
        })
    return merged


async def _push_profile_native(
    channel: Channel,
    *,
    name: str | None = None,
    phone: str | None = None,
    website: str | None = None,
    description: str | None = None,
    categories: dict | None = None,
    hours: dict | None = None,
    opening_date: str | None = None,
    attributes: dict | None = None,
    service_area: list | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Best-effort native push of the sections that changed in this save.

    Local storage stays the source of truth regardless — a rejected section
    is logged (never raised), so one bad section can't fail the save.
    """
    from ..channels.google_business import GoogleBusinessClient
    from ..channels.service import decrypt_token

    access = decrypt_token(channel.access_token) if channel.access_token else None
    refresh = decrypt_token(channel.refresh_token) if channel.refresh_token else None
    if not access and not refresh:
        logger.warning(
            "Native locations push skipped for %s: channel has no tokens",
            listing_id_of(channel))
        return [], {"channel": "channel has no tokens"}
    google_id = channel_meta(channel).get("location_id") or listing_id_of(channel)
    client = GoogleBusinessClient(access or "", refresh)
    try:
        report = await client.push_profile(
            google_id,
            name=name,
            phone=phone,
            website=website,
            description=description,
            categories=categories,
            hours=hours,
            opening_date=opening_date,
            attributes=attributes,
            service_area=service_area,
        )
    except Exception as e:
        logger.warning("Native locations push failed for %s: %s", google_id, e)
        return [], {"channel": str(e)[:200]}
    finally:
        await client.close()
    skipped = report.get("skipped") or {}
    for section, reason in skipped.items():
        logger.warning("Native locations push skipped %s for %s: %s",
                       section, google_id, reason)
    return report.get("pushed", []), skipped


async def update_profile(
    db: AsyncSession,
    user_id: str,
    listing_id: str,
    description: str | None,
    categories: dict | None,
    hours: dict | None,
    service_area: list | None,
    attributes: dict | None,
    opening_date: str | None = None,
    name: str | None = None,
    phone: str | None = None,
    website: str | None = None,
) -> dict:
    """Save a profile locally, then push the sections that changed to Google.

    The local save always lands first; per-section push results come back in
    `google_synced` and a rejected section only logs. A listing with no native
    channel (for example a stale id) still saves locally but never pushes.
    """
    import datetime as _dt

    profile = await _profile(db, user_id, listing_id)
    channel = await channel_for_listing(db, user_id, listing_id)
    if channel is None:
        expired = await channel_for_listing(
            db, user_id, listing_id, statuses=("expired",)
        )
        if expired is not None:
            raise ValueError(
                "Google connection expired — reconnect Google before updating "
                "this location."
            )

    # Only changed values are pushed. A bulk save sends every column for every
    # row; without this, an unchanged branch would cost four Google patches.
    # A section the last push rejected is always retried: the value is already
    # stored locally, so "unchanged" must not mean "never try again".
    push_name = push_phone = push_website = None
    failed_meta = channel_meta(channel) if channel is not None else {}
    if channel is not None:
        meta = failed_meta
        meta_changed = False
        if name is not None:
            clean_name = name.strip()[:255]
            if clean_name and (
                clean_name != (channel.display_name or "") or _has_failed(meta, "name")
            ):
                channel.display_name = clean_name
                push_name = clean_name
        if phone is not None:
            clean_phone = phone.strip() or None
            if clean_phone != meta.get("phone") or _has_failed(meta, "phone"):
                meta["phone"] = clean_phone
                push_phone = clean_phone
                meta_changed = True
        if website is not None:
            clean_website = website.strip() or None
            if clean_website != meta.get("website") or _has_failed(meta, "website"):
                meta["website"] = clean_website
                push_website = clean_website
                meta_changed = True
        if meta_changed:
            channel.metadata_json = json.dumps(meta)

    push_description = None
    if description is not None:
        new_description = description[:750]
        if new_description != profile.description or _has_failed(failed_meta, "description"):
            profile.description = new_description
            push_description = new_description
    push_categories = None
    if categories is not None:
        old_categories = dict(profile.categories or {})
        if not old_categories and channel is not None:
            # The OAuth import stores Google's current categories on the
            # channel, not in location_profiles. Seed from it so a primary-only
            # save cannot silently clear Google's additional categories.
            old_categories = dict(channel_meta(channel).get("categories") or {})
        merged_cats = dict(old_categories)
        if categories.get("primary") is not None:
            merged_cats["primary"] = str(categories.get("primary", ""))[:255]
        if categories.get("additional") is not None:
            merged_cats["additional"] = [str(c)[:255] for c in categories.get("additional", [])][:50]
        if merged_cats != old_categories or _has_failed(failed_meta, "categories"):
            profile.categories = merged_cats
            push_categories = merged_cats
    push_hours = None
    if hours is not None:
        old_hours = dict(profile.hours or {})
        merged_hours = dict(old_hours)
        if hours.get("regular") is not None:
            merged_hours["regular"] = dict(hours.get("regular", {}))
        if hours.get("special") is not None:
            merged_hours["special"] = list(hours.get("special", []))[:100]
        if hours.get("more") is not None:
            merged_hours["more"] = list(hours.get("more", []))[:100]
        if merged_hours != old_hours or _has_failed(failed_meta, "hours"):
            profile.hours = merged_hours
            push_hours = merged_hours
    push_service_area = None
    if service_area is not None:
        cleaned_areas = [str(a).strip()[:255] for a in service_area if str(a).strip()][:100]
        if cleaned_areas != list(profile.service_area or []) or _has_failed(
            failed_meta, "service_area"
        ):
            profile.service_area = cleaned_areas
            push_service_area = cleaned_areas
    push_attributes = None
    if attributes is not None:
        old_attributes = dict(profile.attributes or {})
        merged_attributes = {
            str(k)[:120]: str(v)[:500] for k, v in list(attributes.items())[:100]
        }
        if merged_attributes != old_attributes or _has_failed(failed_meta, "attributes"):
            profile.attributes = merged_attributes
            push_attributes = merged_attributes
    push_opening_date = None
    if opening_date is not None:
        try:
            parsed_date = _dt.date.fromisoformat(str(opening_date))
        except ValueError:
            raise ValueError(f"Invalid opening_date {opening_date!r}, use YYYY-MM-DD")
        if parsed_date != profile.opening_date or _has_failed(failed_meta, "opening_date"):
            profile.opening_date = parsed_date
            push_opening_date = parsed_date.isoformat()
    profile.updated_at = datetime.now(timezone.utc)
    await db.commit()

    # The AI's facts row mirrors this schedule; rebuild now so a customer's
    # next "what are your hours?" is answered with the saved value.
    from ..profile.facts_store import rebuild_facts_safe

    await rebuild_facts_safe(db, user_id)

    pushed: list[str] = []
    skipped: dict[str, str] = {}
    merged_synced: set[str] = set()
    if channel is not None:
        pushed, skipped = await _push_profile_native(
            channel,
            name=push_name,
            phone=push_phone,
            website=push_website,
            description=push_description,
            categories=push_categories,
            hours=push_hours,
            opening_date=push_opening_date,
            attributes=push_attributes,
            service_area=push_service_area,
        )
        meta = channel_meta(channel)
        failed_map = dict(meta.get("google_failed") or {})
        for section, reason in skipped.items():
            failed_map[section] = reason
        for section in pushed:
            failed_map.pop(section, None)
            base = "categories" if section.startswith("categories") else section
            for key in list(failed_map):
                if key == base or key.startswith(base + "."):
                    failed_map.pop(key, None)
        meta["google_failed"] = failed_map
        merged_synced = _known_synced(meta)
        merged_synced.update(pushed)
        for section in skipped:
            merged_synced.discard(section)
            if section.startswith("categories"):
                merged_synced.discard("categories")
            if section.startswith("hours"):
                merged_synced.discard("hours.regular")
                merged_synced.discard("hours.special")
                merged_synced.discard("hours.more")
        # A successful push makes the local value the new Google snapshot.
        # A failed or skipped section leaves the old snapshot untouched, so
        # get_profile's local-vs-snapshot comparison stays honest.
        if "categories" in pushed and profile.categories:
            meta["categories"] = dict(profile.categories)
        if profile.hours:
            meta_hours = meta.setdefault("hours", {})
            for section in ("regular", "special", "more"):
                if f"hours.{section}" not in pushed:
                    continue
                value = (profile.hours or {}).get(section)
                meta_hours[section] = (
                    dict(value or {}) if section == "regular" else list(value or [])
                )
        if "description" in pushed:
            meta["description"] = profile.description
        meta["google_synced"] = sorted(merged_synced)
        meta["google_skipped"] = skipped
        channel.metadata_json = json.dumps(meta)
        await db.commit()

    out = await get_profile(db, user_id, listing_id)
    out["google_pushed"] = pushed
    out["google_skipped"] = skipped
    return out


# --- location groups -------------------------------------------------------
#
# Groups are pure bookkeeping: a name plus the listing IDs it covers. The
# frontend expands a group into the same "scope" shape it already builds for
# "All branches", so nothing downstream needs to know groups exist.


async def list_groups(db: AsyncSession, user_id: str) -> list[dict]:
    result = await db.execute(
        select(LocationGroup)
        .where(LocationGroup.user_id == user_id)
        .order_by(LocationGroup.position, LocationGroup.created_at)
    )
    return [
        {
            "id": g.id,
            "name": g.name,
            "listing_ids": list(g.listing_ids or []),
            "position": g.position,
        }
        for g in result.scalars().all()
    ]


async def create_group(db: AsyncSession, user_id: str, name: str, listing_ids: list[str]) -> dict:
    result = await db.execute(
        select(LocationGroup).where(LocationGroup.user_id == user_id)
    )
    existing = list(result.scalars().all())
    taken = {g.name.strip().lower() for g in existing}
    name = name.strip()
    if name.lower() in taken:
        raise ValueError(f"You already have a group called {name!r}")
    if not listing_ids:
        raise ValueError("Pick at least one location for the group")

    group = LocationGroup(
        user_id=user_id,
        name=name,
        listing_ids=_dedupe(listing_ids),
        position=len(existing),
    )
    db.add(group)
    await db.commit()
    return {
        "id": group.id,
        "name": group.name,
        "listing_ids": list(group.listing_ids or []),
        "position": group.position,
    }


async def update_group(
    db: AsyncSession, user_id: str, group_id: str, name: str | None, listing_ids: list[str] | None
) -> dict | None:
    group = await _group(db, user_id, group_id)
    if group is None:
        return None
    if name is not None:
        name = name.strip()
        result = await db.execute(
            select(LocationGroup).where(
                LocationGroup.user_id == user_id, LocationGroup.id != group_id
            )
        )
        if name.lower() in {g.name.strip().lower() for g in result.scalars().all()}:
            raise ValueError(f"You already have a group called {name!r}")
        group.name = name
    if listing_ids is not None:
        if not listing_ids:
            raise ValueError("A group needs at least one location")
        group.listing_ids = _dedupe(listing_ids)
    group.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {
        "id": group.id,
        "name": group.name,
        "listing_ids": list(group.listing_ids or []),
        "position": group.position,
    }


async def delete_group(db: AsyncSession, user_id: str, group_id: str) -> bool:
    group = await _group(db, user_id, group_id)
    if group is None:
        return False
    await db.delete(group)
    await db.commit()
    return True


async def _group(db: AsyncSession, user_id: str, group_id: str) -> LocationGroup | None:
    result = await db.execute(
        select(LocationGroup).where(
            LocationGroup.user_id == user_id, LocationGroup.id == group_id
        )
    )
    return result.scalar_one_or_none()


def _dedupe(listing_ids: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in listing_ids:
        lid = str(raw).strip()
        if lid and lid not in seen:
            seen.add(lid)
            out.append(lid)
    return out


# ── Create a Google location ─────────────────────────────────────────

def _source_channel_for_google(channels: list[Channel]) -> Channel | None:
    """A connected Google channel supplies the account id and OAuth tokens."""
    with_tokens = [c for c in channels if c.access_token or c.refresh_token]
    if not with_tokens:
        return None
    active = [c for c in with_tokens if c.status == "active"]
    return (active or with_tokens)[0]


def _storefront_address(
    *,
    street: str,
    city: str,
    country: str,
    state: str | None = None,
    postal_code: str | None = None,
    language_code: str = "en",
) -> dict:
    address: dict = {
        "regionCode": (country or "").strip().upper()[:2],
        "languageCode": language_code or "en",
        "locality": city.strip(),
        "addressLines": [street.strip()],
    }
    if state and state.strip():
        address["administrativeArea"] = state.strip()
    if postal_code and postal_code.strip():
        address["postalCode"] = postal_code.strip()
    return address


def _create_payload(body: dict) -> dict:
    """The create body. Optional fields are omitted, never sent empty."""
    language = (body.get("language_code") or "en").strip() or "en"
    has_storefront = bool(body.get("has_storefront", True))
    payload: dict = {
        "languageCode": language,
        "title": body["name"].strip(),
        "phoneNumbers": {"primaryPhone": body["phone"].strip()},
    }
    if body.get("website"):
        payload["websiteUri"] = body["website"].strip()
    if body.get("description"):
        payload["profile"] = {"description": body["description"].strip()[:750]}
    if has_storefront:
        payload["storefrontAddress"] = _storefront_address(
            street=body["street"],
            city=body["city"],
            country=body["country"],
            state=body.get("state"),
            postal_code=body.get("postal_code"),
            language_code=language,
        )
    latitude, longitude = body.get("latitude"), body.get("longitude")
    if latitude is not None and longitude is not None:
        payload["latlng"] = {
            "latitude": float(latitude),
            "longitude": float(longitude),
        }
    return payload


def _is_readonly_address_component(error: Exception, field: str) -> bool:
    """True when Google says the named address component is read-only.

    Pakistan and several other countries reject a client-provided
    administrativeArea with READ_ONLY_ADDRESS_COMPONENTS.
    """
    detail = str(getattr(error, "message", error))
    return (
        getattr(error, "status_code", None) == 400
        and "READ_ONLY_ADDRESS_COMPONENTS" in detail
        and f"storefront_address.{field}" in detail
    )


def _friendly_location_error(status: int, detail: str) -> str:
    """Turn Google's ErrorInfo JSON into a message a merchant can act on."""
    if "READ_ONLY_ADDRESS_COMPONENTS" in detail:
        if "administrative_area" in detail:
            return (
                "Google treats the state/province as read-only for this country. "
                "Go back to Address, clear State / province, and try again."
            )
        return (
            "Google treats part of this address as read-only for this country. "
            "Go back to Address, remove the state/province, and try again. If it "
            "still fails, create the location in Google Business Profile."
        )
    if "MISSING_ADDRESS_COMPONENTS" in detail:
        return (
            "Google needs a city and a complete street address for this country. "
            "Go back to Address, fill in the city and street, and try again."
        )
    if "PIN_DROP_REQUIRED" in detail:
        return (
            "Google cannot locate this address precisely enough to create the "
            "location. Create it in Google Business Profile with a map pin, then "
            "connect the listing here."
        )
    if "INVALID_ARGUMENT" in detail and "storefront_address" in detail:
        return (
            "Google could not accept this address. Check the country, city, postal "
            "code, and street. Use a real street address, not a Google Maps link or "
            "a Plus Code by itself."
        )
    if "INVALID_ARGUMENT" in detail and "categories" in detail:
        return (
            "Google does not recognize the selected category. Choose a category "
            "from Google's list and try again."
        )
    if "INVALID_ARGUMENT" in detail and "phone" in detail:
        return (
            "Google rejected the phone number. Use the international format, for "
            "example +92 346 0561173."
        )
    if "INVALID_ARGUMENT" in detail and ("website" in detail or "uri" in detail):
        return "Google rejected the website. Use a valid https:// address."
    if "INVALID_ARGUMENT" in detail and "profile" in detail:
        return (
            "Google requires a business description for this category. Add one "
            "and try again."
        )
    if status == 400:
        return (
            "Google rejected the location details. Check the address, phone, "
            "website, and category, then try again."
        )
    return "Google could not create the location right now. Try again in a moment."


def _search_payload(body: dict) -> dict:
    """Minimal Location for googleLocations.search (title is required)."""
    language = (body.get("language_code") or "en").strip() or "en"
    payload: dict = {
        "languageCode": language,
        "title": body["name"].strip(),
    }
    if body.get("phone"):
        payload["phoneNumbers"] = {"primaryPhone": str(body["phone"]).strip()}
    if (
        body.get("has_storefront", True)
        and body.get("street")
        and body.get("city")
        and body.get("country")
    ):
        payload["storefrontAddress"] = _storefront_address(
            street=body["street"],
            city=body["city"],
            country=body["country"],
            state=body.get("state"),
            postal_code=body.get("postal_code"),
            language_code=language,
        )
    return payload


async def _google_client(
    db: AsyncSession, channel: Channel
):
    from ..channels.google_business import GoogleBusinessClient
    from ..channels.service import decrypt_token, encrypt_token

    access = decrypt_token(channel.access_token) if channel.access_token else None
    refresh = decrypt_token(channel.refresh_token) if channel.refresh_token else None
    if not access and not refresh:
        raise ValueError("Connect Google Business Profile first.")
    client = GoogleBusinessClient(access or "", refresh)
    client.set_known_expiry(channel.token_expires_at)

    async def _persist(token: str, expires_at) -> None:
        channel.access_token = encrypt_token(token)
        channel.token_expires_at = expires_at
        db.add(channel)
        await db.commit()

    client.set_token_persister(_persist)
    return client


async def search_google_locations(
    db: AsyncSession, user_id: str, body: dict
) -> list[dict]:
    """GoogleLocations.search before creation, so duplicates are visible."""
    from ..channels.google_reviews import (
        GoogleReviewsError,
        location_address,
        location_phone,
    )

    channels = list(
        (
            await db.execute(
                select(Channel).where(
                    Channel.user_id == user_id,
                    Channel.platform == "google_reviews",
                )
            )
        ).scalars().all()
    )
    source = _source_channel_for_google(channels)
    if source is None:
        raise ValueError("Connect Google Business Profile first.")
    client = await _google_client(db, source)
    payload = _search_payload(body)
    try:
        rows = await client.search_google_locations(
            location=payload,
            page_size=5,
        )
    except GoogleReviewsError as e:
        raise ValueError(
            "Google could not check for existing locations: "
            f"{e.message if hasattr(e, 'message') else str(e)}"
        ) from e
    finally:
        await client.close()

    out: list[dict] = []
    for row in rows:
        loc = row.get("location") if isinstance(row, dict) else None
        if not isinstance(loc, dict):
            loc = {}
        title = loc.get("title") or row.get("name") or "Existing Google listing"
        out.append({
            "name": str(title),
            "location_name": loc.get("name"),
            "address": location_address(loc) or None,
            "place_id": (loc.get("metadata") or {}).get("placeId")
            or row.get("placeId"),
            "request_admin_rights_url": row.get("requestAdminRightsUrl"),
        })
    return out


async def list_google_categories(
    db: AsyncSession,
    user_id: str,
    query: str,
    region_code: str,
    *,
    exact: bool = False,
) -> list[dict]:
    """Search Google's category catalog for the create-location picker.

    The catalog is the authority; the browser never invents category IDs.
    ``query`` is matched by Google against the front of the display name.
    """
    from ..channels.google_reviews import GoogleReviewsError

    channels = list(
        (
            await db.execute(
                select(Channel).where(
                    Channel.user_id == user_id,
                    Channel.platform == "google_reviews",
                )
            )
        ).scalars().all()
    )
    source = _source_channel_for_google(channels)
    if source is None:
        raise ValueError("Connect Google Business Profile first.")
    client = await _google_client(db, source)
    wanted = (query or "").strip()
    exact_id: str | None = None
    try:
        rows = await client.search_categories(
            query,
            region_code=region_code,
        )
        # The filter returns every category containing the text, not only an
        # exact match. A picker click sends the exact display name, so resolve
        # that name explicitly when it fell outside the first page. Without
        # this a valid category can look "not listed" in the UI.
        if exact and wanted and not any(
            isinstance(row, dict)
            and str(row.get("displayName") or "").strip().lower() == wanted.lower()
            for row in rows
        ):
            exact_id = await client.resolve_category_id(
                wanted, region_code=region_code
            )
    except GoogleReviewsError as e:
        detail = getattr(e, "message", str(e))
        raise ValueError(f"Google could not load categories: {detail}") from e
    finally:
        await client.close()

    out: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        display = str(row.get("displayName") or "").strip()
        if not name or not display or name in seen:
            continue
        seen.add(name)
        out.append({"name": name, "display_name": display})
    if exact_id and exact_id not in seen:
        out.append({"name": exact_id, "display_name": wanted})
    wanted_key = wanted.lower()
    out.sort(
        key=lambda item: (
            item["display_name"].lower() != wanted_key,
            item["display_name"].lower(),
        )
    )
    return out


async def create_google_location(
    db: AsyncSession, user_id: str, body: dict
) -> dict:
    """Create a location in Google, then persist it as a native channel.

    Google's create call is the authority: the local row is written only
    after Google returns the new resource. A duplicate local key is reused
    instead of creating a second channel.
    """
    from ..channels.google_reviews import (
        GoogleReviewsError,
        location_address,
        location_category,
        location_description,
        location_phone,
        location_website,
    )
    from ..channels.service import encrypt_token

    channels = list(
        (
            await db.execute(
                select(Channel).where(
                    Channel.user_id == user_id,
                    Channel.platform == "google_reviews",
                )
            )
        ).scalars().all()
    )
    source = _source_channel_for_google(channels)
    if source is None:
        raise ValueError("Connect Google Business Profile first.")
    account_id = str(source.platform_user_id or "").split("/")[-1]
    if not account_id:
        raise ValueError("The connected Google account has no account id.")

    has_storefront = bool(body.get("has_storefront", True))
    country = str(body.get("country") or "").strip().upper()[:2]
    language = (body.get("language_code") or "en").strip() or "en"
    service_area_names: list[str] = [
        str(value).strip()
        for value in (body.get("service_area") or [])
        if str(value).strip()
    ]

    client = await _google_client(db, source)
    try:
        # Search excludes locations the account already manages, so also check
        # the managed list. Without this a second branch with the same phone or
        # name/address would silently create a duplicate on Google.
        existing_locations: list[dict] = []
        try:
            existing_locations = await client.list_locations(account_id)
        except GoogleReviewsError:
            logger.warning("Could not list existing Google locations before create", exc_info=True)

        def _norm(value: object) -> str:
            return " ".join(str(value or "").lower().split())

        def _phone(value: object) -> str:
            return "".join(ch for ch in str(value or "") if ch.isdigit())

        wanted_name = _norm(body["name"])
        wanted_phone = _phone(body.get("phone"))
        wanted_city = _norm(body.get("city"))
        wanted_street = _norm(body.get("street"))
        for loc in existing_locations:
            if not isinstance(loc, dict):
                continue
            loc_title = _norm(loc.get("title"))
            loc_address = _norm(location_address(loc))
            same_city = bool(wanted_city and wanted_city in loc_address)
            same_street = bool(wanted_street and wanted_street in loc_address)
            same_phone = bool(
                wanted_phone and _phone(location_phone(loc)) == wanted_phone
            )
            if (same_city or same_street) and (
                same_phone
                or (wanted_name and loc_title == wanted_name)
                or (wanted_name and loc_title.startswith(wanted_name))
            ):
                raise ValueError(
                    f"A matching location already exists in your Google account: "
                    f"{loc.get('title') or 'Unnamed location'}. Open it from Locations instead of creating a duplicate."
                )

        category_id = await client.resolve_category_id(
            body["category"], region_code=country
        )
        if not category_id:
            raise ValueError(
                f"Google does not recognize the category “{body['category']}”. "
                "Use a category name from Google Business Profile, for example "
                "“Computer software store” or “Restaurant”."
            )
        payload = _create_payload(body)
        payload["categories"] = {"primaryCategory": {"name": category_id}}

        # Service areas are free text locally; Google only accepts place IDs.
        # A service-area-only business still gets the region, even when the
        # Places key is missing or no name resolves, so create is not blocked
        # by an optional section.
        if service_area_names or not has_storefront:
            service_area: dict = {
                "businessType": (
                    "CUSTOMER_AND_BUSINESS_LOCATION"
                    if has_storefront
                    else "CUSTOMER_LOCATION_ONLY"
                ),
                "regionCode": country,
            }
            if service_area_names:
                from .places import PlacesError, resolve_service_area

                try:
                    place_infos = await resolve_service_area(
                        service_area_names,
                        language_code=language,
                        region_code=country or "SA",
                    )
                except PlacesError as e:
                    logger.warning("Service areas skipped for create: %s", e)
                    place_infos = []
                if place_infos:
                    service_area["places"] = {"placeInfos": place_infos}
            payload["serviceArea"] = service_area

        request_id = (body.get("request_id") or str(uuid.uuid4()))[:50]
        # Validate first so obvious category/address problems do not create a
        # half-finished local flow. Google still makes the real decision on
        # the second call; validateOnly never creates a listing.
        #
        # The validate call gets its own request id. requestId is Google's
        # duplicate-request key, so reusing one id for both calls can make
        # Google replay the validation response instead of creating a
        # location on the second call.
        async def _validate_and_create(candidate: dict) -> dict:
            await client.create_location(
                account_id,
                candidate,
                request_id=str(uuid.uuid4())[:50],
                validate_only=True,
            )
            return await client.create_location(
                account_id, candidate, request_id=request_id
            )

        try:
            created = await _validate_and_create(payload)
        except GoogleReviewsError as e:
            if not _is_readonly_address_component(e, "administrative_area"):
                raise
            # Pakistan and several other countries reject a client-provided
            # state/province. Drop it and let Google derive it; city, postal
            # code and address lines are still sent.
            retry_payload = copy.deepcopy(payload)
            (retry_payload.get("storefrontAddress") or {}).pop(
                "administrativeArea", None
            )
            logger.info("Retrying Google create without administrativeArea")
            created = await _validate_and_create(retry_payload)
    except GoogleReviewsError as e:
        status = getattr(e, "status_code", 502)
        detail = getattr(e, "message", str(e))
        if status == 403:
            raise ValueError(
                "Google did not grant permission to create a location for this "
                "account. The connected Google user must be an owner or manager "
                "with Business Profile create access."
            ) from e
        if status == 409:
            raise ValueError(
                "Google says this location already exists. Run the duplicate "
                "check and request access instead of creating a duplicate."
            ) from e
        if "PIN_DROP_REQUIRED" in str(detail):
            raise ValueError(
                "Google cannot locate this address precisely enough to create "
                "the location. Create it in Google Business Profile with a map "
                "pin, then connect the listing here."
            ) from e
        logger.warning("Google location create rejected (%s): %s", status, detail)
        raise ValueError(_friendly_location_error(status, detail)) from e
    finally:
        await client.close()

    resource = created.get("name") if isinstance(created, dict) else None
    if not resource:
        raise ValueError("Google created no location resource; try again.")
    location_id = str(resource).split("/")[-1]
    title = str(created.get("title") or body["name"]).strip()
    phone = location_phone(created) or body.get("phone")
    website = location_website(created) or body.get("website")
    category = location_category(created) or body.get("category")
    address = location_address(created) or ", ".join(
        part for part in [
            body.get("street"), body.get("city"), body.get("state"),
            body.get("postal_code"), body.get("country"),
        ] if part
    )
    metadata = {
        "location_id": location_id,
        "account_name": channel_meta(source).get("account_name"),
        "place_id": (created.get("metadata") or {}).get("placeId"),
        # Business Information API v1 spells it mapsUri. The older v4 API
        # used mapsUrl, which this code used to read and always got None.
        "maps_url": (created.get("metadata") or {}).get("mapsUri"),
        "address": address,
        "category": category,
        "phone": phone,
        "website": website,
        "description": location_description(created) or body.get("description"),
        "service_area": service_area_names,
        "country": country,
        "language_code": language,
        "profile_fields_checked": False,
        "created_via": "sayvors",
    }

    existing = (
        await db.execute(
            select(Channel).where(
                Channel.user_id == user_id,
                Channel.platform == "google_reviews",
                Channel.listing_key == location_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.access_token = source.access_token
        existing.refresh_token = source.refresh_token
        existing.token_expires_at = source.token_expires_at
        existing.display_name = title
        existing.metadata_json = json.dumps(metadata)
        await db.commit()
        return {
            "listing_id": location_id,
            "channel_id": existing.id,
            "name": title,
            "address": address,
            "status": existing.status,
            "created": False,
        }

    channel = Channel(
        id=str(uuid.uuid4()),
        user_id=user_id,
        platform="google_reviews",
        platform_user_id=account_id,
        display_name=title,
        access_token=source.access_token,
        refresh_token=source.refresh_token,
        token_expires_at=source.token_expires_at,
        status="active",
        metadata_json=json.dumps(metadata),
        listing_key=location_id,
    )
    db.add(channel)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = (
            await db.execute(
                select(Channel).where(
                    Channel.user_id == user_id,
                    Channel.platform == "google_reviews",
                    Channel.listing_key == location_id,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            raise
        return {
            "listing_id": location_id,
            "channel_id": existing.id,
            "name": existing.display_name or title,
            "address": address,
            "status": existing.status,
            "created": False,
        }
    return {
        "listing_id": location_id,
        "channel_id": channel.id,
        "name": title,
        "address": address,
        "status": channel.status,
        "created": True,
    }

"""Locations backing service.

Native Google Business Profile is the only listing source. Google-synced
fields (name, address, phone, website, Maps URL) come from the channel
metadata written by the OAuth callback and review worker; editable sections
(description, categories, hours, service area, attributes, opening date) are
stored in `location_profiles` and pushed with the Business Information API.
"""
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

GOOGLE_SYNCED_FIELDS = ["name", "phone", "website", "description"]


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
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }
    if channel is not None:
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
            "google_synced": list(GOOGLE_SYNCED_FIELDS),
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
) -> list[str]:
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
        return []
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
        return []
    finally:
        await client.close()
    for section, reason in (report.get("skipped") or {}).items():
        logger.warning("Native locations push skipped %s for %s: %s",
                       section, google_id, reason)
    return report.get("pushed", [])


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
    push_name = push_phone = push_website = None
    if channel is not None:
        meta = channel_meta(channel)
        meta_changed = False
        if name is not None:
            clean_name = name.strip()[:255]
            if clean_name and clean_name != (channel.display_name or ""):
                channel.display_name = clean_name
                push_name = clean_name
        if phone is not None:
            clean_phone = phone.strip() or None
            if clean_phone != meta.get("phone"):
                meta["phone"] = clean_phone
                push_phone = clean_phone
                meta_changed = True
        if website is not None:
            clean_website = website.strip() or None
            if clean_website != meta.get("website"):
                meta["website"] = clean_website
                push_website = clean_website
                meta_changed = True
        if meta_changed:
            channel.metadata_json = json.dumps(meta)

    push_description = None
    if description is not None:
        new_description = description[:750]
        if new_description != profile.description:
            profile.description = new_description
            push_description = new_description
    push_categories = None
    if categories is not None:
        old_categories = dict(profile.categories or {})
        merged_cats = dict(old_categories)
        if categories.get("primary") is not None:
            merged_cats["primary"] = str(categories.get("primary", ""))[:255]
        if categories.get("additional") is not None:
            merged_cats["additional"] = [str(c)[:255] for c in categories.get("additional", [])][:50]
        if merged_cats != old_categories:
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
        if merged_hours != old_hours:
            profile.hours = merged_hours
            push_hours = merged_hours
    push_service_area = None
    if service_area is not None:
        cleaned_areas = [str(a).strip()[:255] for a in service_area if str(a).strip()][:100]
        if cleaned_areas != list(profile.service_area or []):
            profile.service_area = cleaned_areas
            push_service_area = cleaned_areas
    push_attributes = None
    if attributes is not None:
        old_attributes = dict(profile.attributes or {})
        merged_attributes = {
            str(k)[:120]: str(v)[:500] for k, v in list(attributes.items())[:100]
        }
        if merged_attributes != old_attributes:
            profile.attributes = merged_attributes
            push_attributes = merged_attributes
    push_opening_date = None
    if opening_date is not None:
        try:
            parsed_date = _dt.date.fromisoformat(str(opening_date))
        except ValueError:
            raise ValueError(f"Invalid opening_date {opening_date!r}, use YYYY-MM-DD")
        if parsed_date != profile.opening_date:
            profile.opening_date = parsed_date
            push_opening_date = parsed_date.isoformat()
    profile.updated_at = datetime.now(timezone.utc)
    await db.commit()

    # The AI's facts row mirrors this schedule; rebuild now so a customer's
    # next "what are your hours?" is answered with the saved value.
    from ..profile.facts_store import rebuild_facts_safe

    await rebuild_facts_safe(db, user_id)

    pushed: list[str] = []
    if channel is not None:
        pushed = await _push_profile_native(
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
    out = await get_profile(db, user_id, listing_id)
    out["google_synced"] = pushed
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
    postal_code: str | None,
) -> dict:
    address: dict = {
        "regionCode": (country or "").strip().upper()[:2],
        "languageCode": "en",
        "locality": city.strip(),
        "addressLines": [street.strip()],
    }
    if postal_code and postal_code.strip():
        address["postalCode"] = postal_code.strip()
    return address


def _create_payload(body: dict) -> dict:
    return {
        "languageCode": "en",
        "title": body["name"].strip(),
        "phoneNumbers": {"primaryPhone": body["phone"].strip()},
        "storefrontAddress": _storefront_address(
            street=body["street"],
            city=body["city"],
            country=body["country"],
            postal_code=body.get("postal_code"),
        ),
        **(
            {"websiteUri": body["website"].strip()}
            if body.get("website")
            else {}
        ),
    }


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
    payload = _create_payload(body)
    try:
        rows = await client.search_google_locations(
            location=payload,
            query=f"{body['name']} {body['street']} {body['city']}",
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
        wanted_phone = _phone(body["phone"])
        wanted_city = _norm(body["city"])
        for loc in existing_locations:
            if not isinstance(loc, dict):
                continue
            loc_title = _norm(loc.get("title"))
            loc_address = _norm(location_address(loc))
            same_city = bool(wanted_city and wanted_city in loc_address)
            same_phone = bool(
                wanted_phone and _phone(location_phone(loc)) == wanted_phone
            )
            if same_city and (
                same_phone
                or (wanted_name and loc_title == wanted_name)
                or (wanted_name and loc_title.startswith(wanted_name))
            ):
                raise ValueError(
                    f"A matching location already exists in your Google account: "
                    f"{loc.get('title') or 'Unnamed location'}. Open it from Locations instead of creating a duplicate."
                )

        category_id = await client.resolve_category_id(
            body["category"], region_code=body["country"].upper()[:2]
        )
        if not category_id:
            raise ValueError(
                f"Google does not recognize the category “{body['category']}”. "
                "Use a category name from Google Business Profile, for example "
                "“Computer software store” or “Restaurant”."
            )
        payload = _create_payload(body)
        payload["categories"] = {"primaryCategory": {"name": category_id}}
        request_id = (body.get("request_id") or str(uuid.uuid4()))[:50]
        # Validate first so obvious category/address problems do not create a
        # half-finished local flow. Google still makes the real decision on
        # the second call; validateOnly never creates a listing.
        #
        # The validate call gets its own request id. requestId is Google's
        # duplicate-request key, so reusing one id for both calls can make
        # Google replay the validation response instead of creating a
        # location on the second call.
        await client.create_location(
            account_id,
            payload,
            request_id=str(uuid.uuid4())[:50],
            validate_only=True,
        )
        created = await client.create_location(
            account_id, payload, request_id=request_id
        )
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
        raise ValueError(f"Google rejected the location: {detail}") from e
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
            body.get("street"), body.get("city"),
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
        "description": None,
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

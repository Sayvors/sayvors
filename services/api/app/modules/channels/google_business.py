"""Google Business Profile (Business Information) adapter — locations read/write.

The Locations page writes exclusively through this client using each
tenant's native Google OAuth tokens — the `business.manage` scope already
covers these endpoints.

Reference: https://developers.google.com/my-business/reference/businessinformation

Design notes (all verified against the reference):
- `locations.patch` takes an updateMask of fully-qualified field names.
  Verified shapes: `title`, `phoneNumbers.primaryPhone`,
  `categories.primaryCategory` / `categories.additionalCategories`
  (`{name: "gcid:..."}`), `websiteUri`, `profile.description`,
  `openInfo.openingDate`, `regularHours.periods[]` with string times
  ("HH:MM"), `specialHours`, `moreHours[]`, `serviceArea`.
- Attributes go through the DEDICATED `locations.updateAttributes`
  endpoint (`PATCH v1/locations/*/attributes` + attributeMask) — never
  inside locations.patch.
- Writes are split per section so one rejected section (e.g. an unknown
  attribute) can never fail the whole profile push. Local storage stays
  the source of truth for our UI; Google push is best-effort sync.
- Category names ("Software company") must resolve to Google category IDs
  (`categories.list` + displayName match). Unresolvable names are SKIPPED
  with a warning — a wrong category is worse than a skipped one.
- Service areas are free-form place names locally; Google needs place IDs,
  so service-area push is intentionally not implemented (logged).
"""
import logging
import re

from .google_reviews import GoogleReviewsClient, GoogleReviewsError

logger = logging.getLogger(__name__)

GBP_BIZINFO_API = "https://mybusinessbusinessinformation.googleapis.com/v1"
# v1alpha carries per-field edit lifecycle status (PENDING / REJECTED / ...).
# It is not always enabled on a project; callers fall back to hasPendingEdits.
GBP_BIZINFO_API_ALPHA = "https://mybusinessbusinessinformation.googleapis.com/v1alpha"

DAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
_DAY_INDEX = {d: i for i, d in enumerate(DAYS)}

# Google's extendedFieldData keys (snake_case top-level Location fields) →
# the Sayvors profile section names. Used to translate per-field edit
# lifecycle status into the sections the Locations UI shows.
GOOGLE_FIELD_TO_SECTION = {
    "title": "name",
    "phone_numbers": "phone",
    "website_uri": "website",
    "regular_hours": "hours.regular",
    "special_hours": "hours.special",
    "more_hours": "hours.more",
    "service_area": "service_area",
    "profile": "description",
    "categories": "categories",
    "open_info": "opening_date",
    "storefront_address": "address",
}

# EditLifecycleStage → short status key used by the API/UI.
EDIT_STAGE_TO_STATUS = {
    "EDIT_LIFECYCLE_STAGE_ACCEPTED": "accepted",
    "EDIT_LIFECYCLE_STAGE_PENDING": "pending",
    "EDIT_LIFECYCLE_STAGE_REJECTED": "rejected",
    "EDIT_LIFECYCLE_STAGE_UPDATED_BY_GOOGLE": "google_updated",
    "EDIT_LIFECYCLE_STAGE_DRAFT": "draft",
    "EDIT_LIFECYCLE_STAGE_UNSPECIFIED": "unspecified",
}


def parse_edit_status(extended: dict) -> dict[str, dict]:
    """Per-section edit status from an ExtendedLocation response.

    Returns ``{section: {stage, rejection_reason, update_time, source}}``.
    Fields with no recorded edit are absent — the caller treats absence as
    "never submitted", which is distinct from "pending" or "rejected".
    """
    out: dict[str, dict] = {}
    field_data = (extended or {}).get("extendedFieldData") or {}
    if not isinstance(field_data, dict):
        return out
    for field, data in field_data.items():
        section = GOOGLE_FIELD_TO_SECTION.get(field)
        if section is None or not isinstance(data, dict):
            continue
        out[section] = _edit_entry(data)
    return out


def parse_attribute_edit_status(extended: dict) -> dict[str, dict]:
    """Per-attribute edit status from an ExtendedAttributes response.

    Attributes have their own endpoint, so they never appear in the
    location's extendedFieldData. The response carries one entry per
    attribute in ``extendedAttributes``, each with its own field metadata.
    Returns ``{attribute: {...}}``.
    """
    out: dict[str, dict] = {}
    entries = (extended or {}).get("extendedAttributes") or []
    if not isinstance(entries, list):
        return out
    for item in entries:
        if not isinstance(item, dict):
            continue
        data = item.get("extendedFieldData")
        if not isinstance(data, dict):
            continue
        merchant = item.get("attributeProvidedByMerchant") or {}
        name = str(merchant.get("name") or item.get("name") or "")
        if not name:
            continue
        out[name] = _edit_entry(data)
    return out


def parse_attribute_values(extended: dict) -> dict[str, str]:
    """The attribute values Google shows today, per attribute.

    Reads ``attributeSeenByConsumers`` from an ExtendedAttributes response and
    returns ``{attribute name: value}`` in Sayvors' own shape.
    """
    out: dict[str, str] = {}
    entries = (extended or {}).get("extendedAttributes") or []
    if not isinstance(entries, list):
        return out
    for item in entries:
        if not isinstance(item, dict):
            continue
        seen = item.get("attributeSeenByConsumers") or {}
        if not isinstance(seen, dict):
            continue
        name = str(seen.get("name") or "").strip()
        if not name:
            continue
        key = name.split("/")[-1]
        value = ""
        if "booleanValue" in seen:
            value = "yes" if seen.get("booleanValue") else "no"
        elif seen.get("stringValue"):
            value = str(seen.get("stringValue"))
        elif seen.get("uriValues"):
            uris = [
                str(u.get("uri") or "").strip()
                for u in seen.get("uriValues") or []
                if isinstance(u, dict)
            ]
            value = ", ".join(u for u in uris if u)
        elif seen.get("enumValue"):
            value = str(seen.get("enumValue"))
        if value:
            out[key] = value
    return out


def _edit_entry(data: dict) -> dict:
    """One ExtendedFieldData object as Sayvors' status shape."""
    stage_raw = str(data.get("lastEditLifecycleStage") or "")
    return {
        "stage": EDIT_STAGE_TO_STATUS.get(stage_raw, stage_raw.lower() or "unspecified"),
        "rejection_reason": data.get("rejectionReason"),
        "update_time": data.get("updateTime"),
        "source": data.get("source"),
    }


# The day keys Sayvors stores hours under (the frontend's HOURS_DAYS).
_HOUR_DAYS = [
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
]


def _time_of_day_to_hhmm(tod: dict | None) -> str:
    """A Google TimeOfDay as "HH:MM" ("24:00" is the end of the day)."""
    if not isinstance(tod, dict):
        return "00:00"
    hours = int(tod.get("hours") or 0)
    minutes = int(tod.get("minutes") or 0)
    if hours >= 24:
        return "24:00"
    return f"{hours:02d}:{minutes:02d}"


def google_periods_to_hours(periods: list[dict] | None) -> dict[str, dict]:
    """Google's ``regularHours.periods`` → Sayvors' ``{day: {open, close}}``.

    A day Google lists as 00:00–24:00 is an all-day opening; a day Google
    leaves out is closed.
    """
    out: dict[str, dict] = {
        day: {"open": "", "close": "", "closed": True, "all_day": False}
        for day in _HOUR_DAYS
    }
    for period in periods or []:
        if not isinstance(period, dict):
            continue
        open_day = str(period.get("openDay") or "").strip().capitalize()
        if open_day not in out:
            continue
        close_day = str(period.get("closeDay") or open_day).strip().capitalize()
        opened = _time_of_day_to_hhmm(period.get("openTime"))
        closed = _time_of_day_to_hhmm(period.get("closeTime"))
        entry = out[open_day]
        entry["closed"] = False
        entry["open"] = opened
        entry["close"] = closed
        entry["all_day"] = opened == "00:00" and closed == "24:00"
        # An overnight range belongs to the next day's entry in Sayvors.
        if close_day != open_day and close_day in out:
            out[close_day]["closed"] = False
            out[close_day]["open"] = closed
            out[close_day]["close"] = opened
    return out


def google_special_hours_to_entries(periods: list[dict] | None) -> list[dict]:
    """Google's ``specialHours.specialHourPeriods`` → Sayvors' entries."""
    out: list[dict] = []
    for period in periods or []:
        if not isinstance(period, dict):
            continue
        start = period.get("startDate") or {}
        end = period.get("endDate") or {}
        if not start:
            continue
        date = f"{int(start.get('year') or 0):04d}-{int(start.get('month') or 0):02d}-{int(start.get('day') or 0):02d}"
        if period.get("closed"):
            out.append({"date": date, "hours": "Closed", "reason": ""})
            continue
        opened = _time_of_day_to_hhmm(period.get("openTime"))
        closed = _time_of_day_to_hhmm(period.get("closeTime"))
        out.append(
            {
                "date": date,
                "hours": f"{opened} - {closed}",
                "reason": "",
            }
        )
    return out


def parse_consumer_values(extended: dict) -> dict:
    """What Google shows today, per Sayvors section.

    ``locationSeenByConsumers`` is the live, customer-facing listing: the
    values a visitor sees right now, which can lag the merchant's own
    submission while Google reviews it.
    """
    consumer = (extended or {}).get("locationSeenByConsumers") or {}
    if not isinstance(consumer, dict):
        return {}
    out: dict = {}

    def put(key: str, value) -> None:
        if value not in (None, "", [], {}):
            out[key] = value

    put("name", consumer.get("title"))
    put("phone", (consumer.get("phoneNumbers") or {}).get("primaryPhone"))
    put("website", consumer.get("websiteUri"))
    put("description", (consumer.get("profile") or {}).get("description"))
    put("address", consumer.get("storefrontAddress"))

    categories = consumer.get("categories") or {}
    primary = categories.get("primaryCategory") or {}
    additional = [
        str((c or {}).get("displayName") or "").strip()
        for c in categories.get("additionalCategories") or []
    ]
    if primary or additional:
        out["categories"] = {
            "primary": str(primary.get("displayName") or "").strip(),
            "additional": [a for a in additional if a],
        }

    regular = consumer.get("regularHours") or {}
    if regular.get("periods"):
        out["hours.regular"] = google_periods_to_hours(regular.get("periods"))
    special = consumer.get("specialHours") or {}
    if special.get("specialHourPeriods"):
        out["hours.special"] = google_special_hours_to_entries(
            special.get("specialHourPeriods")
        )
    more = consumer.get("moreHours")
    if more:
        out["hours.more"] = more

    area = consumer.get("serviceArea")
    if area:
        out["service_area"] = area

    opening = (consumer.get("openInfo") or {}).get("openingDate")
    if opening:
        out["opening_date"] = opening
    return out

# Frontend More-hours options → GBP MoreHoursType enum. Unknown types are
# skipped with a warning (Google 400s the whole call otherwise).
MORE_HOURS_TYPES = {
    "ACCESS": "ACCESS",
    "BREAKFAST": "BREAKFAST",
    "BRUNCH": "BRUNCH",
    "DELIVERY": "DELIVERY",
    "DINNER": "DINNER",
    "DRIVE THROUGH": "DRIVE_THROUGH",
    "DRIVE-THROUGH": "DRIVE_THROUGH",
    "HAPPY HOUR": "HAPPY_HOUR",
    "KITCHEN": "KITCHEN",
    "LUNCH": "LUNCH",
    "ONLINE SERVICE": "ONLINE_SERVICE_HOURS",
    "PICKUP": "PICKUP",
    "SENIOR HOURS": "SENIOR_HOURS",
    "TAKEOUT": "TAKEOUT",
}

# Free-form attribute keys (normalized) → Google merchant attribute IDs.
# Only well-known boolean attributes: presence semantics the API documents.
# Unknown keys are skipped with a warning — Google ignores nothing and
# rejects unknown IDs, so guessing would fail the whole attributes call.
ATTRIBUTE_IDS = {
    "wheelchair accessible entrance": "wheelchair_accessible_entrance",
    "wheelchair accessible parking": "wheelchair_accessible_parking",
    "wheelchair accessible restroom": "wheelchair_accessible_restroom",
    "wheelchair accessible seating": "wheelchair_accessible_seating",
    "free wifi": "has_wifi",
    "wifi": "has_wifi",
    "outdoor seating": "has_outdoor_seating",
    "dine in": "has_dine_in",
    "dine-in": "has_dine_in",
    "takeout": "has_takeout",
    "takeaway": "has_takeout",
    "delivery": "has_delivery",
    "drive through": "has_drive_through",
    "drive-through": "has_drive_through",
    "accepts credit cards": "accepts_credit_cards",
    "accepts debit cards": "accepts_debit_cards",
    "accepts cash": "accepts_cash_only",
    "gender neutral restroom": "has_gender_neutral_restrooms",
    "family friendly": "is_family_friendly",
    "good for children": "is_good_for_children",
    "free parking": "has_free_parking_lot",
    "paid parking": "has_paid_parking_lot",
    "street parking": "has_free_street_parking",
    "pet friendly": "allows_dogs",
    "dogs allowed": "allows_dogs",
    "air conditioning": "has_air_conditioning",
    "live music": "has_live_music",
    "sports bar": "is_sports_bar",
    "online appointments": "has_online_appointments",
    "on site services": "has_on_site_services",
    "on-site services": "has_on_site_services",
}

_TRUE = {"true", "yes", "1", "y", "on", "available", "offered"}
_FALSE = {"false", "no", "0", "n", "off", "unavailable", "not offered"}


def _parse_hhmm(value: str) -> tuple[int, int] | None:
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", value or "")
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if 0 <= h <= 23 and 0 <= mi <= 59:
        return h, mi
    return None


def _tod(value: tuple[int, int] | None, *, end_of_day: bool = False) -> dict:
    """(h, m) → Google TimeOfDay. `end_of_day` means midnight at 24:00."""
    if end_of_day:
        return {"hours": 24, "minutes": 0}
    h, m = value or (0, 0)
    return {"hours": h, "minutes": m}


def build_regular_periods(regular: dict) -> list[dict]:
    """Our {Day: {open, close, closed, all_day}} → GBP periods.

    Google's regularHours.periods take TimeOfDay objects, not "HH:MM"
    strings. Overnight ranges (close < open) roll closeDay to the next day;
    an all-day day closes at 24:00 on the same day. Closed days are omitted
    (absence = closed in the GBP model). Day names match case-insensitively.
    """
    by_day = {str(k or "").strip().lower(): v for k, v in (regular or {}).items()}
    periods: list[dict] = []
    for day in DAYS:
        cfg = by_day.get(day.lower()) or {}
        if cfg.get("closed"):
            continue
        opened = _parse_hhmm(str(cfg.get("open") or ""))
        closed = _parse_hhmm(str(cfg.get("close") or ""))
        if cfg.get("all_day") or (opened and closed and opened == closed == (0, 0)):
            periods.append({
                "openDay": day,
                "openTime": _tod((0, 0)),
                "closeDay": day,
                "closeTime": _tod((0, 0), end_of_day=True),
            })
            continue
        if not opened or not closed:
            continue
        close_day = day
        if closed < opened:
            close_day = DAYS[(_DAY_INDEX[day] + 1) % 7]
        periods.append({
            "openDay": day,
            "openTime": _tod(opened),
            "closeDay": close_day,
            "closeTime": _tod(closed),
        })
    return periods


def parse_special_entry(entry: dict) -> dict | None:
    """Our {date, hours, reason} → SpecialHourPeriod. Returns None when the
    free-text hours can't be parsed (caller skips with a warning)."""
    import datetime as _dt

    try:
        day = _dt.date.fromisoformat(str(entry.get("date") or ""))
    except ValueError:
        return None
    period: dict = {
        "startDate": {"year": day.year, "month": day.month, "day": day.day},
    }
    hours = str(entry.get("hours") or "").strip().lower()
    if "closed" in hours:
        period["closed"] = True
        return period
    m = re.fullmatch(r"\s*(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})\s*",
                     str(entry.get("hours") or ""))
    if not m:
        return None
    opened, closed = _parse_hhmm(m.group(1)), _parse_hhmm(m.group(2))
    if not opened or not closed:
        return None
    period["openTime"] = _tod(opened)
    period["closeTime"] = _tod(closed)
    return period


def build_more_hours(entries: list[dict]) -> tuple[list[dict], list[str]]:
    """Our [{type, open, close}] → MoreHours list. Returns (built, skipped)."""
    built: list[dict] = []
    skipped: list[str] = []
    for e in entries or []:
        hours_type = MORE_HOURS_TYPES.get(str(e.get("type") or "").strip().upper())
        opened = _parse_hhmm(str(e.get("open") or ""))
        closed = _parse_hhmm(str(e.get("close") or ""))
        if not hours_type or not opened or not closed:
            skipped.append(str(e.get("type") or "?"))
            continue
        built.append({
            "hoursTypeId": hours_type,
            "periods": [{
                "openDay": "MONDAY",
                "openTime": _tod(opened),
                "closeDay": "SUNDAY",
                "closeTime": _tod(closed),
            }],
        })
    return built, skipped


def build_attributes(user_attrs: dict) -> tuple[list[dict], list[str]]:
    """Free-form {key: value} → updateAttributes entries.

    Only curated boolean attributes are sent (presence semantics Google
    documents); everything else is skipped with a warning instead of
    risking the whole call on a guessed attributeId or encoding.
    Returns (entries, skipped_keys).
    """
    entries: list[dict] = []
    skipped: list[str] = []
    for key, value in (user_attrs or {}).items():
        attr_id = ATTRIBUTE_IDS.get(str(key or "").strip().lower())
        v = str(value or "").strip().lower()
        if not attr_id or (v not in _TRUE and v not in _FALSE):
            skipped.append(str(key))
            continue
        entries.append({
            "attributeId": attr_id,
            "values": [{"boolValue": v in _TRUE}],
        })
    return entries, skipped


class GoogleBusinessClient(GoogleReviewsClient):
    """Business Information API: location read/write + attributes + categories.

    Inherits OAuth mechanics (refresh, retry, persister) from the reviews
    client — same app, same tokens, same `business.manage` scope.
    """

    def _location_name(self, location_id: str) -> str:
        lid = (location_id or "").strip()
        # Accept both bare ids and full resource names.
        if "/" in lid:
            lid = lid.split("/")[-1]
        return f"locations/{lid}"

    async def get_location(self, location_id: str, read_mask: str | None = None) -> dict:
        """Full BusinessLocation resource (read-only probe of scopes/shape).

        The v1 API requires a readMask; ``read_mask`` is a comma-separated
        field list. Without one the call is refused with 400.
        """
        params = {"readMask": read_mask} if read_mask else None
        resp = await self._authed_request(
            "GET", f"{GBP_BIZINFO_API}/{self._location_name(location_id)}",
            params=params,
        )
        if resp.status_code != 200:
            raise GoogleReviewsError(
                f"get_location failed ({resp.status_code}): {resp.text[:300]}",
                resp.status_code)
        data = resp.json()
        return data if isinstance(data, dict) else {}

    async def get_extended_location(self, location_id: str) -> dict:
        """ExtendedLocation: merchant data, consumer data, per-field edit status.

        v1alpha endpoint. Raises GoogleReviewsError when the alpha API is not
        enabled on the project (404) or not authorized (403), so the caller can
        fall back to the coarse ``metadata.hasPendingEdits`` flag.
        """
        resp = await self._authed_request(
            "GET",
            f"{GBP_BIZINFO_API_ALPHA}/{self._location_name(location_id)}:getExtended",
        )
        if resp.status_code != 200:
            raise GoogleReviewsError(
                f"get_extended_location failed ({resp.status_code}): {resp.text[:300]}",
                resp.status_code,
            )
        data = resp.json()
        return data if isinstance(data, dict) else {}

    async def get_extended_attributes(self, location_id: str) -> dict:
        """ExtendedAttributes: per-attribute edit status.

        Attributes live on their own endpoint, so ``locations.getExtended``
        never reports their lifecycle. Returns {} when the alpha API is off.
        """
        resp = await self._authed_request(
            "GET",
            f"{GBP_BIZINFO_API_ALPHA}/{self._location_name(location_id)}"
            f"/attributes:getExtended",
        )
        if resp.status_code != 200:
            raise GoogleReviewsError(
                f"get_extended_attributes failed ({resp.status_code}): {resp.text[:300]}",
                resp.status_code,
            )
        data = resp.json()
        return data if isinstance(data, dict) else {}

    async def get_phone_numbers(self, location_id: str) -> dict:
        """Current primary/additional phones, needed for a complete patch."""
        resp = await self._authed_request(
            "GET",
            f"{GBP_BIZINFO_API}/{self._location_name(location_id)}",
            params={"readMask": "phoneNumbers"},
        )
        if resp.status_code != 200:
            raise GoogleReviewsError(
                f"get_phone_numbers failed ({resp.status_code}): {resp.text[:300]}",
                resp.status_code,
            )
        data = resp.json()
        return (data.get("phoneNumbers") or {}) if isinstance(data, dict) else {}

    async def get_service_items(self, location_id: str) -> list[dict]:
        """Google's current service list for the location."""
        resp = await self._authed_request(
            "GET",
            f"{GBP_BIZINFO_API}/{self._location_name(location_id)}",
            params={"readMask": "serviceItems"},
        )
        if resp.status_code != 200:
            raise GoogleReviewsError(
                f"get_service_items failed ({resp.status_code}): {resp.text[:300]}",
                resp.status_code,
            )
        data = resp.json() or {}
        return list(data.get("serviceItems") or [])

    async def push_service_items(self, location_id: str, items: list[dict]) -> dict:
        """Replace the location's whole service list.

        Google treats ``serviceItems`` as a complete object — "updating
        individual services is not supported" — so the caller must send the
        full list, including the entries it wants to keep.
        """
        return await self.patch_location(
            location_id, {"serviceItems": items}, "serviceItems"
        )

    async def patch_location(self, location_id: str, body: dict,
                             update_mask: str) -> dict:
        """PATCH one section group. Raises GoogleReviewsError on rejection."""
        from urllib.parse import urlencode

        qs = urlencode({"updateMask": update_mask})
        resp = await self._authed_request(
            "PATCH",
            f"{GBP_BIZINFO_API}/{self._location_name(location_id)}?{qs}",
            json=body)
        if resp.status_code not in (200,):
            raise GoogleReviewsError(
                f"patch_location [{update_mask}] failed "
                f"({resp.status_code}): {resp.text[:300]}",
                resp.status_code)
        data = resp.json()
        return data if isinstance(data, dict) else {}

    async def update_attributes(self, location_id: str,
                                entries: list[dict]) -> dict:
        """Dedicated attributes endpoint (never inside locations.patch)."""
        from urllib.parse import urlencode

        mask = ",".join(f"attributes/{e['attributeId']}" for e in entries)
        qs = urlencode({"attributeMask": mask})
        resp = await self._authed_request(
            "PATCH",
            f"{GBP_BIZINFO_API}/{self._location_name(location_id)}/attributes?{qs}",
            json={"attributes": entries})
        if resp.status_code not in (200,):
            raise GoogleReviewsError(
                f"update_attributes failed ({resp.status_code}): "
                f"{resp.text[:300]}",
                resp.status_code)
        data = resp.json()
        return data if isinstance(data, dict) else {}

    async def list_categories(self, page_token: str | None = None,
                              page_size: int = 100,
                              region_code: str = "US",
                              language_code: str = "en",
                              filter_text: str | None = None) -> dict:
        """One page of the Google category catalog.

        ``filter_text`` uses the documented ``filter=displayName=...`` prefix
        search. Without it the catalog must be paginated, which is both slow
        and capped (the catalog has more than ten pages of 100).
        """
        from urllib.parse import urlencode

        params = {
            "pageSize": max(1, min(int(page_size), 100)),
            "view": "FULL",
            "languageCode": language_code or "en",
            "regionCode": (region_code or "US").upper()[:2],
        }
        if page_token:
            params["pageToken"] = page_token
        if filter_text and filter_text.strip():
            value = filter_text.strip()
            # Google's filter grammar rejects unquoted multi-word values
            # (displayName=Software company -> 400). Single words are accepted
            # either way; quote only when needed.
            if any(character.isspace() for character in value):
                value = f'"{value}"'
            params["filter"] = f"displayName={value}"
        resp = await self._authed_request(
            "GET", f"{GBP_BIZINFO_API}/categories?{urlencode(params)}")
        if resp.status_code != 200:
            raise GoogleReviewsError(
                f"list_categories failed ({resp.status_code}): "
                f"{resp.text[:300]}",
                resp.status_code)
        data = resp.json()
        return data if isinstance(data, dict) else {}

    async def search_categories(
        self,
        query: str,
        *,
        region_code: str = "US",
        language_code: str = "en",
        page_size: int = 50,
    ) -> list[dict]:
        """Category catalog search for the create-location picker."""
        page = await self.list_categories(
            page_size=page_size,
            region_code=region_code,
            language_code=language_code,
            filter_text=query,
        )
        return list(page.get("categories") or [])

    async def resolve_category_id(self, display_name: str,
                                  max_pages: int = 10,
                                  region_code: str = "US",
                                  language_code: str = "en") -> str | None:
        """Display name ("Software company") → Google category id.

        Uses the documented displayName filter first, then matches
        case-insensitively. Returns None when unmatched — callers MUST skip
        categories rather than guess, a wrong category is worse than an
        unpushed one.
        """
        wanted = (display_name or "").strip().lower()
        if not wanted:
            return None
        token: str | None = None
        for _ in range(max_pages):
            try:
                page = await self.list_categories(
                    page_token=token,
                    region_code=region_code,
                    language_code=language_code,
                    filter_text=display_name,
                )
            except GoogleReviewsError as e:
                logger.warning("Category catalog unreachable: %s", e)
                return None
            for cat in page.get("categories", []) or []:
                if str(cat.get("displayName") or "").strip().lower() == wanted:
                    name = str(cat.get("name") or "")
                    return name or None
            token = page.get("nextPageToken")
            if not token:
                break
        logger.warning("No Google category id for %r — skipping categories push",
                       display_name)
        return None

    async def search_google_locations(
        self,
        *,
        location: dict | None = None,
        query: str | None = None,
        page_size: int = 5,
    ) -> list[dict]:
        """Check Google for an existing/claimed listing before creation.

        ``location`` must include at least ``title`` for Google to match on
        structured details; a free-text query is the fallback. Returns the
        raw ``googleLocations`` entries (name, address, requestAdminRightsUrl).
        """
        if location is None and not (query or "").strip():
            raise ValueError("A location or query is required.")
        body: dict = {"pageSize": max(1, min(int(page_size), 10))}
        if location is not None:
            body["location"] = location
        else:
            body["query"] = str(query).strip()
        resp = await self._authed_request(
            "POST", f"{GBP_BIZINFO_API}/googleLocations:search", json=body)
        if resp.status_code != 200:
            raise GoogleReviewsError(
                f"googleLocations.search failed ({resp.status_code}): "
                f"{resp.text[:300]}",
                resp.status_code)
        data = resp.json()
        rows = data.get("googleLocations") if isinstance(data, dict) else None
        return list(rows or [])

    async def create_location(
        self,
        account_id: str,
        location: dict,
        *,
        request_id: str,
        validate_only: bool = False,
    ) -> dict:
        """Create a Business Profile location in ``account_id``.

        We validate with Google first when the caller asks for it; a 200 on a
        real call means Google accepted the location and it now exists.
        """
        from urllib.parse import urlencode

        params = urlencode({
            "requestId": (request_id or "")[:50],
            "validateOnly": "true" if validate_only else "false",
        })
        resp = await self._authed_request(
            "POST",
            f"{GBP_BIZINFO_API}/accounts/{account_id}/locations?{params}",
            json=location,
        )
        if resp.status_code not in (200, 201):
            raise GoogleReviewsError(
                f"accounts.locations.create failed ({resp.status_code}): "
                f"{resp.text[:500]}",
                resp.status_code)
        data = resp.json()
        return data if isinstance(data, dict) else {}

    async def push_profile(
        self,
        location_id: str,
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
    ) -> dict:
        """Push profile sections, one API call per section group.

        Returns {"pushed": [...], "skipped": {section: reason}} — a rejected
        section never fails the others. Local storage stays the source of
        truth regardless; this reports what Google accepted.
        """
        pushed: list[str] = []
        skipped: dict[str, str] = {}

        core_body: dict = {}
        core_mask: list[str] = []
        core_sections: list[str] = []
        if description is not None:
            core_body["profile"] = {"description": description[:750]}
            core_mask.append("profile.description")
            core_sections.append("description")
        if opening_date:
            import datetime as _dt

            try:
                day = _dt.date.fromisoformat(opening_date)
                core_body["openInfo"] = {"openingDate": {
                    "year": day.year, "month": day.month, "day": day.day}}
                core_mask.append("openInfo.openingDate")
                core_sections.append("opening_date")
            except ValueError:
                skipped["opening_date"] = f"unparseable date {opening_date!r}"
        if core_body:
            try:
                await self.patch_location(location_id, core_body, ",".join(core_mask))
                pushed.extend(core_sections)
            except GoogleReviewsError as e:
                skipped["core"] = str(e)[:200]

        # Service areas are place IDs, not free text. Resolve through Places
        # API (New) only when the merchant actually changed the list.
        if service_area is not None:
            from ..locations.places import PlacesError, resolve_service_area

            names = [str(name).strip() for name in service_area if str(name).strip()]
            if not names:
                skipped["service_area"] = "empty; Google keeps the current area"
            else:
                try:
                    place_infos = await resolve_service_area(names)
                except PlacesError as e:
                    skipped["service_area"] = str(e)[:200]
                else:
                    if not place_infos:
                        skipped["service_area"] = (
                            "no service area resolved to a Google region place"
                        )
                    else:
                        try:
                            await self.patch_location(
                                location_id,
                                {"serviceArea": {"places": {"placeInfos": place_infos}}},
                                "serviceArea.places.placeInfos",
                            )
                            pushed.append("service_area")
                        except GoogleReviewsError as e:
                            skipped["service_area"] = str(e)[:200]

        # Identity fields are patched one by one so a title Google reserves
        # for verified locations cannot block a phone or website update.
        identity_sections: list[tuple[str, dict, str]] = []
        if name is not None:
            identity_sections.append(("name", {"title": name[:255]}, "title"))
        if website is not None:
            identity_sections.append((
                "website", {"websiteUri": website[:255]}, "websiteUri"
            ))
        for section, body, mask in identity_sections:
            try:
                await self.patch_location(location_id, body, mask)
                pushed.append(section)
            except GoogleReviewsError as e:
                skipped[section] = str(e)[:200]

        # PhoneNumbers has the same complete-object rule as Categories:
        # "During updates, both fields must be set. Clients may not update just
        # the primary or additional phone numbers using the update mask."
        # updateMask=phoneNumbers.primaryPhone returns 400. Preserve any
        # additional numbers Google already has.
        if phone is not None:
            try:
                existing_phones = await self.get_phone_numbers(location_id)
                additional = [
                    str(value)[:40]
                    for value in (existing_phones.get("additionalPhones") or [])
                    if str(value).strip()
                ][:2]
                await self.patch_location(
                    location_id,
                    {
                        "phoneNumbers": {
                            "primaryPhone": phone[:40],
                            "additionalPhones": additional,
                        }
                    },
                    "phoneNumbers",
                )
                pushed.append("phone")
            except GoogleReviewsError as e:
                skipped["phone"] = str(e)[:200]

        if categories is not None:
            try:
                primary = (categories.get("primary") or "").strip()
                resolved_primary: str | None = None
                if primary:
                    resolved_primary = await self.resolve_category_id(primary)
                    if not resolved_primary:
                        skipped["categories.primary"] = f"no Google id for {primary!r}"

                requested_additional = [
                    str(name).strip()
                    for name in (categories.get("additional") or [])[:10]
                    if str(name).strip()
                ]
                resolved_additional: list[dict] = []
                unresolved_additional: list[str] = []
                for name in requested_additional:
                    resolved = await self.resolve_category_id(name)
                    if resolved:
                        resolved_additional.append({"name": resolved})
                    else:
                        unresolved_additional.append(name)
                if unresolved_additional:
                    skipped["categories.additional"] = (
                        "no Google id for " + ", ".join(unresolved_additional[:5])
                    )

                # Google requires BOTH fields on every categories update and
                # explicitly rejects categories.primaryCategory /
                # categories.additionalCategories as update masks:
                # "Clients are prohibited from individually updating the
                # primary or additional categories using the update mask."
                # Send the complete Categories object under mask "categories".
                if resolved_primary:
                    await self.patch_location(
                        location_id,
                        {
                            "categories": {
                                "primaryCategory": {"name": resolved_primary},
                                "additionalCategories": resolved_additional,
                            }
                        },
                        "categories",
                    )
                    pushed.append("categories")
                elif requested_additional:
                    skipped["categories"] = (
                        "cannot update additional categories without a resolvable primary category"
                    )
            except GoogleReviewsError as e:
                skipped["categories"] = str(e)[:200]

        hours = hours or {}
        if hours.get("regular") is not None:
            try:
                await self.patch_location(
                    location_id,
                    {"regularHours": {"periods": build_regular_periods(hours["regular"])}},
                    "regularHours")
                pushed.append("hours.regular")
            except GoogleReviewsError as e:
                skipped["hours.regular"] = str(e)[:200]
        if hours.get("special") is not None:
            specials, unparsed = [], 0
            for entry in hours["special"] or []:
                parsed = parse_special_entry(entry if isinstance(entry, dict) else {})
                if parsed:
                    specials.append(parsed)
                else:
                    unparsed += 1
            if unparsed:
                skipped["hours.special_unparsed"] = f"{unparsed} entries not mappable"
            try:
                await self.patch_location(
                    location_id,
                    {"specialHours": {"specialHourPeriods": specials}},
                    "specialHours")
                pushed.append("hours.special")
            except GoogleReviewsError as e:
                skipped["hours.special"] = str(e)[:200]
        if hours.get("more") is not None:
            built, skipped_types = build_more_hours(hours["more"] or [])
            if skipped_types:
                skipped["hours.more_types"] = f"unknown types: {', '.join(skipped_types)}"
            try:
                await self.patch_location(
                    location_id, {"moreHours": built}, "moreHours")
                pushed.append("hours.more")
            except GoogleReviewsError as e:
                skipped["hours.more"] = str(e)[:200]

        if attributes is not None:
            entries, skipped_keys = build_attributes(attributes)
            if skipped_keys:
                skipped["attributes.keys"] = f"not mappable: {', '.join(skipped_keys[:10])}"
            if entries:
                try:
                    await self.update_attributes(location_id, entries)
                    pushed.append("attributes")
                except GoogleReviewsError as e:
                    skipped["attributes"] = str(e)[:200]

        return {"pushed": pushed, "skipped": skipped}

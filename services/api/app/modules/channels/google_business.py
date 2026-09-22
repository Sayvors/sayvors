"""Google Business Profile (Business Information) adapter — locations read/write.

Used when LOCATIONS_WRITE_PROVIDER=google (GBP API access granted). Same
OAuth app and tenant tokens as the reviews client — the `business.manage`
scope already covers these endpoints.

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

DAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
_DAY_INDEX = {d: i for i, d in enumerate(DAYS)}

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


def build_regular_periods(regular: dict) -> list[dict]:
    """Our {Day: {open, close, closed}} → GBP periods (string "HH:MM" times).

    Overnight ranges (close <= open) roll closeDay to the next day.
    Closed days are omitted (absence = closed in the GBP model).
    Stored day names are matched case-insensitively ("Monday" or "MONDAY").
    """
    by_day = {str(k or "").strip().lower(): v for k, v in (regular or {}).items()}
    periods: list[dict] = []
    for day in DAYS:
        cfg = by_day.get(day.lower()) or {}
        if cfg.get("closed"):
            continue
        opened = _parse_hhmm(str(cfg.get("open") or ""))
        closed = _parse_hhmm(str(cfg.get("close") or ""))
        if not opened or not closed:
            continue
        close_day = day
        if closed <= opened:
            close_day = DAYS[(_DAY_INDEX[day] + 1) % 7]
        periods.append({
            "openDay": day,
            "openTime": f"{opened[0]:02d}:{opened[1]:02d}",
            "closeDay": close_day,
            "closeTime": f"{closed[0]:02d}:{closed[1]:02d}",
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
    period["openTime"] = f"{opened[0]:02d}:{opened[1]:02d}"
    period["closeTime"] = f"{closed[0]:02d}:{closed[1]:02d}"
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
                "openTime": f"{opened[0]:02d}:{opened[1]:02d}",
                "closeDay": "SUNDAY",
                "closeTime": f"{closed[0]:02d}:{closed[1]:02d}",
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

    async def get_location(self, location_id: str) -> dict:
        """Full BusinessLocation resource (read-only probe of scopes/shape)."""
        resp = await self._authed_request(
            "GET", f"{GBP_BIZINFO_API}/{self._location_name(location_id)}")
        if resp.status_code != 200:
            raise GoogleReviewsError(
                f"get_location failed ({resp.status_code}): {resp.text[:300]}",
                resp.status_code)
        data = resp.json()
        return data if isinstance(data, dict) else {}

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
                              page_size: int = 100) -> dict:
        """One page of the Google category catalog (displayName matching)."""
        from urllib.parse import urlencode

        params = {"pageSize": page_size, "view": "FULL"}
        if page_token:
            params["pageToken"] = page_token
        resp = await self._authed_request(
            "GET", f"{GBP_BIZINFO_API}/categories?{urlencode(params)}")
        if resp.status_code != 200:
            raise GoogleReviewsError(
                f"list_categories failed ({resp.status_code}): "
                f"{resp.text[:300]}",
                resp.status_code)
        data = resp.json()
        return data if isinstance(data, dict) else {}

    async def resolve_category_id(self, display_name: str,
                                  max_pages: int = 10) -> str | None:
        """Display name ("Software company") → Google category id.

        Paginates the catalog and matches case-insensitively. Returns None
        when unmatched — callers MUST skip categories rather than guess,
        a wrong category is worse than an unpushed one.
        """
        wanted = (display_name or "").strip().lower()
        if not wanted:
            return None
        token: str | None = None
        for _ in range(max_pages):
            try:
                page = await self.list_categories(page_token=token)
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

    async def push_profile(
        self,
        location_id: str,
        *,
        description: str | None = None,
        categories: dict | None = None,
        hours: dict | None = None,
        opening_date: str | None = None,
        attributes: dict | None = None,
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
        if description is not None:
            core_body["profile"] = {"description": description[:750]}
            core_mask.append("profile.description")
        if opening_date:
            import datetime as _dt

            try:
                day = _dt.date.fromisoformat(opening_date)
                core_body["openInfo"] = {"openingDate": {
                    "year": day.year, "month": day.month, "day": day.day}}
                core_mask.append("openInfo.openingDate")
            except ValueError:
                skipped["opening_date"] = f"unparseable date {opening_date!r}"
        if core_body:
            try:
                await self.patch_location(location_id, core_body, ",".join(core_mask))
                pushed.append("description" if description is not None else "core")
                if "openInfo.openingDate" in core_mask:
                    pushed.append("opening_date")
            except GoogleReviewsError as e:
                skipped["core"] = str(e)[:200]

        if categories is not None:
            try:
                body: dict = {}
                mask: list[str] = []
                primary = (categories.get("primary") or "").strip()
                if primary:
                    resolved = await self.resolve_category_id(primary)
                    if resolved:
                        body["primaryCategory"] = {"name": resolved}
                        mask.append("categories.primaryCategory")
                    else:
                        skipped["categories.primary"] = f"no Google id for {primary!r}"
                additional = []
                for name in (categories.get("additional") or [])[:10]:
                    resolved = await self.resolve_category_id(str(name))
                    if resolved:
                        additional.append({"name": resolved})
                    else:
                        skipped.setdefault("categories.additional",
                                           f"no Google id for {name!r}")
                if additional:
                    body["additionalCategories"] = additional
                    mask.append("categories.additionalCategories")
                if body:
                    await self.patch_location(location_id, {"categories": body},
                                              ",".join(mask))
                    pushed.append("categories")
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

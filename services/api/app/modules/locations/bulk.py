"""Bulk CSV edit for business locations.

Download a template with current native Google listing data, edit offline,
upload to apply. All updates flow through the existing update_profile() path
so each row gets the same native Business Information API push as a single
location edit. Address, city and zip are display-only: Google requires a
structured postal address, so free-text address edits are not pushed.
"""
from __future__ import annotations

import csv
import io
import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from . import service

logger = logging.getLogger(__name__)

MAX_ROWS = 500
MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB

TEMPLATE_COLUMNS = [
    "listing_id",
    "name",
    "phone",
    "website",
    "description",
    "address",
    "city",
    "zip_code",
    "category",
    "hours_regular",
    "special_hours",
    "opening_date",
    "attributes",
    "service_area",
]


async def build_template_data(db: AsyncSession, user_id: str) -> list[dict]:
    """Build a list of dicts with current native listing data."""
    channels = await service.native_channels(db, user_id)

    rows = []
    for channel in channels:
        lid = service.listing_id_of(channel)
        profile = await service.get_profile(db, user_id, lid)
        meta = service.channel_meta(channel)

        hours = profile.get("hours") or {}
        categories = profile.get("categories") or {}

        rows.append({
            "listing_id": lid,
            "name": channel.display_name or "",
            "phone": meta.get("phone") or "",
            "website": meta.get("website") or "",
            "description": profile.get("description") or "",
            "address": meta.get("address") or "",
            "city": "",
            "zip_code": "",
            "category": categories.get("primary") or "",
            "hours_regular": hours.get("regular") or {},
            "special_hours": hours.get("special") or [],
            "opening_date": profile.get("opening_date") or "",
            "attributes": profile.get("attributes") or {},
            "service_area": profile.get("service_area") or [],
        })

    return rows


async def build_template_csv(db: AsyncSession, user_id: str) -> str:
    """Generate a CSV template pre-filled with current listing data."""
    rows = await build_template_data(db, user_id)

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=TEMPLATE_COLUMNS)
    writer.writeheader()

    for r in rows:
        writer.writerow({
            "listing_id": r["listing_id"],
            "name": r["name"],
            "phone": r["phone"],
            "website": r["website"],
            "description": r["description"],
            "address": r["address"],
            "city": r["city"],
            "zip_code": r["zip_code"],
            "category": r["category"],
            "hours_regular": __import__("json").dumps(r["hours_regular"]) if r["hours_regular"] else "",
            "special_hours": __import__("json").dumps(r["special_hours"]) if r["special_hours"] else "",
            "opening_date": r["opening_date"],
            "attributes": __import__("json").dumps(r["attributes"]) if r["attributes"] else "",
            "service_area": ",".join(r["service_area"]) if r["service_area"] else "",
        })

    return buf.getvalue()


async def apply_bulk_csv(
    db: AsyncSession, user_id: str, csv_text: str
) -> dict:
    """Parse and apply a bulk CSV. Returns a per-row report."""
    if len(csv_text.encode("utf-8")) > MAX_FILE_BYTES:
        raise ValueError(f"File too large (max {MAX_FILE_BYTES // (1024*1024)} MB)")

    reader = csv.DictReader(io.StringIO(csv_text))
    if reader.fieldnames is None:
        raise ValueError("CSV has no header row")

    missing = [c for c in ["listing_id"] if c not in reader.fieldnames]
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")

    rows = list(reader)
    if len(rows) > MAX_ROWS:
        raise ValueError(f"Too many rows (max {MAX_ROWS})")

    # Verify all listing_ids belong to this tenant's native Google channels.
    channels = await service.native_channels(db, user_id)
    owned_ids = {service.listing_id_of(ch) for ch in channels}

    results: list[dict] = []
    success = 0
    failed = 0

    for i, row in enumerate(rows, start=2):  # row 2 = first data row (1-indexed, header=1)
        listing_id = (row.get("listing_id") or "").strip()
        if not listing_id:
            results.append({"row": i, "listing_id": "", "status": "error", "error": "missing listing_id"})
            failed += 1
            continue
        if listing_id not in owned_ids:
            results.append({"row": i, "listing_id": listing_id, "status": "error", "error": "listing not found or not owned"})
            failed += 1
            continue

        try:
            # Parse fields
            description = row.get("description")
            if description is not None:
                description = description.strip() or None

            categories = None
            cat = (row.get("category") or "").strip()
            if cat:
                categories = {"primary": cat}

            hours = None
            hours_regular_raw = (row.get("hours_regular") or "").strip()
            special_hours_raw = (row.get("special_hours") or "").strip()
            if hours_regular_raw or special_hours_raw:
                hours = {}
                if hours_regular_raw:
                    try:
                        hours["regular"] = json.loads(hours_regular_raw)
                    except json.JSONDecodeError:
                        raise ValueError("hours_regular must be valid JSON")
                if special_hours_raw:
                    try:
                        hours["special"] = json.loads(special_hours_raw)
                    except json.JSONDecodeError:
                        raise ValueError("special_hours must be valid JSON")

            service_area = None
            sa_raw = (row.get("service_area") or "").strip()
            if sa_raw:
                service_area = [a.strip() for a in sa_raw.split(",") if a.strip()]

            attributes = None
            attr_raw = (row.get("attributes") or "").strip()
            if attr_raw:
                try:
                    attributes = json.loads(attr_raw)
                except json.JSONDecodeError:
                    raise ValueError("attributes must be valid JSON")

            opening_date = (row.get("opening_date") or "").strip() or None

            # Identity fields are native Google fields; empty cells mean
            # "leave unchanged", matching the single-location editor.
            name = (row.get("name") or "").strip() or None
            phone = (row.get("phone") or "").strip() or None
            website = (row.get("website") or "").strip() or None

            # Update profile + native Google in one path.
            await service.update_profile(
                db,
                user_id,
                listing_id,
                description=description,
                categories=categories,
                hours=hours,
                service_area=service_area,
                attributes=attributes,
                opening_date=opening_date,
                name=name,
                phone=phone,
                website=website,
            )

            results.append({"row": i, "listing_id": listing_id, "status": "ok"})
            success += 1
        except Exception as e:
            results.append({"row": i, "listing_id": listing_id, "status": "error", "error": str(e)[:200]})
            failed += 1
            # Roll back this row's changes
            try:
                await db.rollback()
            except Exception:
                pass

    await db.commit()

    return {
        "total": len(rows),
        "success": success,
        "failed": failed,
        "results": results,
    }
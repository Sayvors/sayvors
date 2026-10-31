"""Opening hours reach the assistant's prompt.

The hours were already stored (and shown on the Locations screen) but the
WhatsApp/Instagram prompt never included them, so "what are your working
hours?" could only be answered with "I'll confirm with the team".
"""
from datetime import date, timedelta

import pytest

from app.modules.locations.ai_hours import opening_hours_block, render_hours_block


def _hours() -> dict:
    soon = (date.today() + timedelta(days=3)).isoformat()
    return {
        "regular": {
            "Monday": {"open": "09:00", "close": "17:00"},
            "Tuesday": {"open": "9:0", "close": "17:0"},
            "Friday": {"closed": True},
        },
        "special": [
            {"date": soon, "hours": "closed", "reason": "Holiday"},
            {"date": "2020-01-01", "hours": "closed", "reason": "Old"},
        ],
        "more": [{"type": "DELIVERY", "open": "18:00", "close": "22:00"}],
    }


def test_renders_weekly_hours_closed_days_and_special_dates():
    block = render_hours_block(_hours(), "Asia/Riyadh")

    assert "- Monday: 09:00-17:00" in block
    assert "- Tuesday: 09:00-17:00" in block, "stored times are normalised"
    assert "- Friday: closed" in block
    assert "- Delivery: 18:00-22:00" in block
    assert "Holiday" in block
    assert "Asia/Riyadh" in block


def test_past_special_dates_are_not_repeated_as_current():
    block = render_hours_block(_hours())
    assert "2020-01-01" not in block


def test_empty_hours_render_nothing():
    assert render_hours_block({}) == ""
    assert render_hours_block(None) == ""
    assert render_hours_block({"regular": {}}) == ""


@pytest.mark.asyncio
async def test_block_is_read_from_the_location_profile(db, user_id):
    from app.modules.locations.models import LocationProfile

    db.add(LocationProfile(
        id="hours-loc-1",
        user_id=user_id,
        listing_id="loc-1",
        hours={"regular": {"Monday": {"open": "08:30", "close": "16:30"}}},
    ))
    await db.commit()

    block = await opening_hours_block(db, user_id, listing_id="loc-1")

    assert "08:30-16:30" in block


@pytest.mark.asyncio
async def test_missing_location_yields_no_block(db, user_id):
    assert await opening_hours_block(db, user_id) == ""

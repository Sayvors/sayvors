"""Google edit-status snapshots: cache, quota budget, alpha fallback, polling.

These cover the contract the Locations page's one-minute poll depends on: a
burst of readers must cost one Google fan-out, a spent budget must degrade to
the last snapshot instead of failing, and a project without the v1alpha
channel must still get real (coarser) status from the stable v1 masks.
"""
import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.config import settings
from app.modules.channels.google_reviews import GoogleReviewsError
from app.modules.channels.models import Channel
from app.modules.channels.service import encrypt_token
from app.modules.locations import google_status
from app.modules.locations import service as locations


@pytest.fixture(autouse=True)
def _clean_status_state():
    """The cache and budget are process-global; a test must not inherit them."""
    google_status.reset_process_state()
    yield
    google_status.reset_process_state()


def _channel(listing_id: str = "loc-status") -> Channel:
    return Channel(
        id=f"ch-{listing_id}",
        user_id="u-1",
        platform="google_reviews",
        platform_user_id="acc-1",
        display_name="Test Place",
        status="active",
        listing_key=listing_id,
        access_token=encrypt_token("at"),
        refresh_token=encrypt_token("rt"),
        metadata_json=json.dumps({"location_id": listing_id}),
    )


class _FakeGoogle:
    """Stands in for GoogleBusinessClient's network methods."""

    def __init__(
        self,
        *,
        extended: dict | None = None,
        attributes: dict | None = None,
        services: list[dict] | None = None,
        updated: dict | None = None,
        alpha_error: Exception | None = None,
    ):
        self.extended = extended or {}
        self.attributes = attributes or {}
        self.services = services or []
        self.updated = updated or {}
        self.alpha_error = alpha_error
        self.calls = {"extended": 0, "attributes": 0, "services": 0, "updated": 0}

    async def get_extended_location(self, location_id):
        self.calls["extended"] += 1
        if self.alpha_error is not None:
            raise self.alpha_error
        return self.extended

    async def get_extended_attributes(self, location_id):
        self.calls["attributes"] += 1
        return self.attributes

    async def get_service_items(self, location_id):
        self.calls["services"] += 1
        return self.services

    async def get_google_updated(self, location_id, read_mask):
        self.calls["updated"] += 1
        assert read_mask, "getGoogleUpdated requires a readMask"
        return self.updated


def _patch_client(monkeypatch, fake: _FakeGoogle) -> None:
    base = "app.modules.channels.google_business.GoogleBusinessClient"
    for name in (
        "get_extended_location",
        "get_extended_attributes",
        "get_service_items",
        "get_google_updated",
    ):
        monkeypatch.setattr(f"{base}.{name}", getattr(fake, name))


def _extended(stage: str) -> dict:
    return {
        "locationProvidedByMerchant": {"title": "Merchant Name"},
        "locationSeenByConsumers": {"title": "Live Name"},
        "extendedFieldData": {
            "regular_hours": {
                "lastEditLifecycleStage": f"EDIT_LIFECYCLE_STAGE_{stage.upper()}",
                "updateTime": "2026-11-17T09:00:00Z",
                "source": "SOURCE_API",
            }
        },
    }


@pytest.mark.asyncio
async def test_snapshot_is_shared_between_readers(monkeypatch):
    """N page views of one branch must cost one Google fan-out, not N."""
    fake = _FakeGoogle(extended=_extended("pending"))
    _patch_client(monkeypatch, fake)
    channel = _channel()

    first = await google_status.snapshot(channel, "loc-status")
    second = await google_status.snapshot(channel, "loc-status")

    assert fake.calls["extended"] == 1
    assert first["source"] == "live"
    assert second["source"] == "cache"
    assert second["sections"]["hours.regular"]["stage"] == "pending"
    assert second["checked_at"] is not None
    assert second["age_seconds"] is not None


@pytest.mark.asyncio
async def test_pending_edit_polls_faster_than_accepted(monkeypatch):
    """Review in progress is the only reason to poll every minute."""
    fake = _FakeGoogle(extended=_extended("pending"))
    _patch_client(monkeypatch, fake)
    pending = await google_status.snapshot(_channel("loc-pending"), "loc-pending")
    assert pending["next_poll_after"] == google_status.ACTIVE_POLL_SECONDS == 60

    google_status.reset_process_state()
    accepted_fake = _FakeGoogle(extended=_extended("accepted"))
    _patch_client(monkeypatch, accepted_fake)
    accepted = await google_status.snapshot(_channel("loc-accepted"), "loc-accepted")
    assert accepted["next_poll_after"] == google_status.IDLE_POLL_SECONDS == 300


@pytest.mark.asyncio
async def test_spent_budget_serves_the_last_snapshot_as_stale(monkeypatch):
    """A manual refresh cannot exceed the budget; the page gets truth + age."""
    monkeypatch.setattr(settings, "GBP_STATUS_QPM_BUDGET", 1)
    fake = _FakeGoogle(extended=_extended("pending"))
    _patch_client(monkeypatch, fake)
    channel = _channel("loc-budget")

    live = await google_status.snapshot(channel, "loc-budget")
    assert live["source"] == "live"

    forced = await google_status.snapshot(channel, "loc-budget", force=True)
    assert forced["source"] == "stale"
    assert forced["sections"]["hours.regular"]["stage"] == "pending"
    assert forced["checked_at"] == live["checked_at"]
    # The budget refused the refresh: no second Google call was made.
    assert fake.calls["extended"] == 1


@pytest.mark.asyncio
async def test_alpha_404_falls_back_to_the_stable_masks(monkeypatch):
    """Projects without v1alpha still get pending / changed-by-Google truth."""
    fake = _FakeGoogle(
        alpha_error=GoogleReviewsError("not enabled", 404),
        updated={
            "pendingMask": "regularHours",
            "diffMask": "title,phoneNumbers",
            "location": {"title": "Live Name"},
        },
    )
    _patch_client(monkeypatch, fake)

    snap = await google_status.snapshot(_channel("loc-alpha"), "loc-alpha")

    assert snap["alpha_available"] is False
    assert snap["reason"] == "alpha_404"
    assert snap["sections"]["hours.regular"]["stage"] == "pending"
    assert snap["sections"]["name"]["stage"] == "google_updated"
    assert snap["sections"]["phone"]["stage"] == "google_updated"
    # Absence from both masks is not proof of acceptance: no invented entry.
    assert "categories" not in snap["sections"]
    assert snap["current"]["name"] == "Live Name"
    assert fake.calls["updated"] == 1


def test_field_masks_map_to_the_same_sections_as_alpha():
    from app.modules.channels.google_business import masks_to_sections

    assert masks_to_sections("regularHours,specialHours,moreHours") == {
        "hours.regular",
        "hours.special",
        "hours.more",
    }
    assert masks_to_sections("title,phoneNumbers.primaryPhone") == {"name", "phone"}
    assert masks_to_sections("openInfo,serviceItems") == {"opening_date", "services"}
    assert masks_to_sections(None) == set()


def test_service_items_edit_status_is_mapped():
    """serviceItems is a top-level Location field, so Google reports it."""
    from app.modules.channels.google_business import parse_edit_status

    status = parse_edit_status(
        {
            "extendedFieldData": {
                "service_items": {
                    "lastEditLifecycleStage": "EDIT_LIFECYCLE_STAGE_PENDING"
                }
            }
        }
    )
    assert status["services"]["stage"] == "pending"


def test_profile_model_exposes_the_check_timestamp():
    """Without this field the UI cannot tell "never checked" from "clean"."""
    from app.modules.locations.schemas import LocationProfileOut

    out = LocationProfileOut(
        listing_id="loc-1",
        name="Test Place",
        status="active",
        google_checked_at="2026-11-17T10:00:00Z",
    )
    assert out.google_checked_at == "2026-11-17T10:00:00Z"


@pytest.mark.asyncio
async def test_status_endpoint_returns_the_poll_contract(
    client, db, user_id, monkeypatch
):
    db.add(
        Channel(
            id="ch-loc-endpoint",
            user_id=user_id,
            platform="google_reviews",
            platform_user_id="acc-endpoint",
            display_name="Endpoint Place",
            status="active",
            listing_key="loc-endpoint",
            access_token=encrypt_token("at"),
            refresh_token=encrypt_token("rt"),
            metadata_json=json.dumps({"location_id": "loc-endpoint"}),
        )
    )
    await db.commit()
    _patch_client(monkeypatch, _FakeGoogle(extended=_extended("pending")))

    resp = client.get("/api/v1/locations/loc-endpoint/google-status")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sections"]["hours.regular"]["stage"] == "pending"
    assert body["next_poll_after"] == 60
    assert body["checked_at"]
    assert body["source"] == "live"
    assert body["current"]["name"] == "Live Name"


@pytest.mark.asyncio
async def test_status_endpoint_without_tokens_is_unavailable(client, db, user_id):
    """No OAuth tokens means "unknown", never a fabricated accepted."""
    db.add(
        Channel(
            id="ch-loc-notoken",
            user_id=user_id,
            platform="google_reviews",
            platform_user_id="acc-notoken",
            display_name="No Token Place",
            status="active",
            listing_key="loc-notoken",
            metadata_json=json.dumps({"location_id": "loc-notoken"}),
        )
    )
    await db.commit()

    resp = client.get("/api/v1/locations/loc-notoken/google-status")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "unavailable"
    assert body["reason"] == "not_connected"
    assert body["sections"] == {}
    assert body["checked_at"] is None


@pytest.mark.asyncio
async def test_get_profile_carries_the_check_timestamp(db, user_id):
    db.add(
        Channel(
            id="ch-loc-profile",
            user_id=user_id,
            platform="google_reviews",
            platform_user_id="acc-profile",
            display_name="Profile Place",
            status="active",
            listing_key="loc-profile",
            metadata_json=json.dumps({"location_id": "loc-profile"}),
        )
    )
    await db.commit()

    profile = await locations.get_profile(db, user_id, "loc-profile")

    # No tokens: the snapshot is empty and the timestamp stays null, which is
    # exactly how the UI distinguishes "not checked" from "checked, clean".
    assert profile["google_status"] == {}
    assert profile["google_checked_at"] is None


@pytest.mark.asyncio
async def test_alpha_unavailable_is_not_retried_every_refresh(monkeypatch):
    """A project without v1alpha must not pay for the same 404 every minute.

    The 404 is a quota unit too, and the answer only changes when Google
    enables the API or the merchant reconnects.
    """
    fake = _FakeGoogle(
        alpha_error=GoogleReviewsError("not enabled", 404),
        updated={"pendingMask": "regularHours"},
    )
    _patch_client(monkeypatch, fake)
    channel = _channel("loc-alpha-cache")

    first = await google_status.snapshot(channel, "loc-alpha-cache")
    second = await google_status.snapshot(channel, "loc-alpha-cache", force=True)

    assert first["reason"] == "alpha_404"
    # Same honest reason, remembered rather than re-learned.
    assert second["reason"] == "alpha_404"
    assert fake.calls["extended"] == 1
    assert fake.calls["updated"] == 2
    assert second["sections"]["hours.regular"]["stage"] == "pending"


@pytest.mark.asyncio
async def test_service_items_ride_along_with_the_extended_response(monkeypatch):
    """serviceItems is a Location field: a separate request buys nothing."""
    fake = _FakeGoogle(
        extended={
            **_extended("pending"),
            "locationProvidedByMerchant": {
                "title": "Merchant Name",
                "serviceItems": [
                    {"freeFormServiceItem": {"label": {"displayName": "Oil change"}}}
                ],
            },
        }
    )
    _patch_client(monkeypatch, fake)

    snap = await google_status.snapshot(_channel("loc-svc"), "loc-svc")

    assert fake.calls["services"] == 0
    assert snap["current"]["services"] == [{"name": "Oil change", "offered": True}]


@pytest.mark.asyncio
async def test_service_items_are_fetched_when_the_payload_omits_them(monkeypatch):
    """Absence is not proof of an empty list — ask for the authoritative one."""
    fake = _FakeGoogle(
        extended=_extended("pending"),
        services=[
            {"structuredServiceItem": {"serviceTypeId": "gcid:plumber"}},
        ],
    )
    _patch_client(monkeypatch, fake)

    snap = await google_status.snapshot(_channel("loc-svc-fetch"), "loc-svc-fetch")

    assert fake.calls["services"] == 1
    assert snap["current"]["services"] == [{"name": "plumber", "offered": True}]


@pytest.mark.asyncio
async def test_attributes_are_not_refetched_while_fresh(monkeypatch):
    """Attributes change only when the merchant edits them; polling is waste."""
    fake = _FakeGoogle(
        extended=_extended("accepted"),
        attributes={
            "extendedAttributes": [
                {
                    "attributeProvidedByMerchant": {
                        "name": "attributes/wheelchair_accessible_entrance"
                    },
                    "extendedFieldData": {
                        "lastEditLifecycleStage": "EDIT_LIFECYCLE_STAGE_ACCEPTED"
                    },
                }
            ]
        },
    )
    _patch_client(monkeypatch, fake)
    channel = _channel("loc-attrs")

    first = await google_status.snapshot(channel, "loc-attrs")
    second = await google_status.snapshot(channel, "loc-attrs", force=True)

    assert fake.calls["extended"] == 2
    assert fake.calls["attributes"] == 1
    # The reused reading still reaches the page.
    assert second["sections"]["attributes"]["stage"] == "accepted"
    assert first["sections"]["attributes"] == second["sections"]["attributes"]


def test_pending_attribute_keeps_the_minute_cadence():
    """A pending attribute is the one case worth re-reading every minute."""
    now = 1_000_000.0
    accepted = {
        "ok": True,
        "attributes_at": now - 120,
        "sections": {"attributes": {"stage": "accepted"}},
    }
    pending = {
        "ok": True,
        "attributes_at": now - 120,
        "sections": {"attributes": {"stage": "pending"}},
    }

    assert google_status._attributes_reusable(accepted, now) is True
    assert google_status._attributes_reusable(pending, now) is False
    # Nothing to reuse before a successful read.
    assert google_status._attributes_reusable(None, now) is False
    assert google_status._attributes_reusable({"ok": False}, now) is False

"""Google-cover monitor: record a published cover, detect Google replacing it.

No network: the GBP client is injected as a fake so the drift logic is tested
against real service code and the real in-memory DB, not against mocks of it.
"""
from datetime import datetime, timedelta, timezone

from app.modules.media import cover_monitor


TENANT = "11111111-1111-1111-1111-111111111111"
CHANNEL = "google:12345"


class _FakeClient:
    """Minimal stand-in for GoogleBusinessClient.list_media."""

    def __init__(self, items):
        self.items = items
        self.calls = []

    async def list_media(self, account_id, location_id, *, category=None):
        self.calls.append((account_id, location_id, category))
        return {"mediaItems": self.items, "totalMediaItemCount": len(self.items)}


def _item(name, url=""):
    return {
        "name": name,
        "googleUrl": url,
        "locationAssociation": {"category": "COVER"},
    }


async def test_record_publish_creates_an_ok_monitor(db):
    row = await cover_monitor.record_publish(
        db,
        tenant_id=TENANT,
        channel_id=CHANNEL,
        user_id=TENANT,
        account_id="accounts/1",
        location_id="locations/9",
        expected_name="locations/9/media/cover-a",
        image_url="https://example.com/a.jpg",
        google_url="https://lh3.googleusercontent.com/a",
    )

    assert row.status == "ok"
    assert row.expected_name == "locations/9/media/cover-a"
    assert row.drift_count == 0
    assert row.actual_image_url == "https://lh3.googleusercontent.com/a"


async def test_check_marks_changed_when_google_replaced_the_cover(db):
    row = await cover_monitor.record_publish(
        db, tenant_id=TENANT, channel_id=CHANNEL, user_id=TENANT,
        account_id="accounts/1", location_id="locations/9",
        expected_name="locations/9/media/cover-a",
        image_url="https://example.com/a.jpg", google_url="https://lh3.googleusercontent.com/a",
    )
    client = _FakeClient([_item("locations/9/media/cover-b", "https://lh3.googleusercontent.com/b")])

    result = await cover_monitor.check_one(db, row, client)

    assert result["status"] == "changed"
    assert row.status == "changed"
    assert row.drift_count == 1
    assert row.actual_name == "locations/9/media/cover-b"
    assert row.actual_image_url == "https://lh3.googleusercontent.com/b"


async def test_check_keeps_ok_when_cover_is_unchanged(db):
    row = await cover_monitor.record_publish(
        db, tenant_id=TENANT, channel_id=CHANNEL, user_id=TENANT,
        account_id="accounts/1", location_id="locations/9",
        expected_name="locations/9/media/cover-a",
        image_url="https://example.com/a.jpg", google_url="https://lh3.googleusercontent.com/a",
    )
    client = _FakeClient([_item("locations/9/media/cover-a", "https://lh3.googleusercontent.com/a")])

    result = await cover_monitor.check_one(db, row, client)

    assert result["status"] == "ok"
    assert row.drift_count == 0


async def test_check_reports_error_when_google_has_no_cover(db):
    row = await cover_monitor.record_publish(
        db, tenant_id=TENANT, channel_id=CHANNEL, user_id=TENANT,
        account_id="accounts/1", location_id="locations/9",
        expected_name="locations/9/media/cover-a",
        image_url="https://example.com/a.jpg", google_url="https://lh3.googleusercontent.com/a",
    )

    result = await cover_monitor.check_one(db, row, _FakeClient([]))

    assert result["status"] == "error"
    assert "no cover" in result["message"].lower()


async def test_acknowledge_rebases_the_expected_cover(db):
    row = await cover_monitor.record_publish(
        db, tenant_id=TENANT, channel_id=CHANNEL, user_id=TENANT,
        account_id="accounts/1", location_id="locations/9",
        expected_name="locations/9/media/cover-a",
        image_url="https://example.com/a.jpg", google_url="https://lh3.googleusercontent.com/a",
    )
    await cover_monitor.check_one(
        db, row, _FakeClient([_item("locations/9/media/cover-b", "https://lh3.googleusercontent.com/b")])
    )

    result = await cover_monitor.acknowledge(db, TENANT, row.id)

    assert result["status"] == "ok"
    assert row.expected_name == "locations/9/media/cover-b"
    assert row.drift_count == 0


async def test_channel_client_factory_returns_none_for_missing_channel(db):
    factory = cover_monitor.channel_client_factory(db)

    assert await factory("google:missing") is None


async def test_check_due_only_checks_rows_older_than_the_interval(db):
    old = await cover_monitor.record_publish(
        db, tenant_id=TENANT, channel_id=CHANNEL, user_id=TENANT,
        account_id="accounts/1", location_id="locations/9",
        expected_name="locations/9/media/old", image_url="https://example.com/old.jpg",
    )
    fresh = await cover_monitor.record_publish(
        db, tenant_id=TENANT, channel_id="google:other", user_id=TENANT,
        account_id="accounts/1", location_id="locations/10",
        expected_name="locations/10/media/fresh", image_url="https://example.com/fresh.jpg",
    )
    old.last_checked_at = datetime.now(timezone.utc) - timedelta(hours=2)
    fresh.last_checked_at = datetime.now(timezone.utc)
    await db.commit()
    clients = {
        CHANNEL: _FakeClient([_item("locations/9/media/old")]),
        "google:other": _FakeClient([_item("locations/10/media/fresh")]),
    }

    result = await cover_monitor.check_due(
        db, lambda channel_id: clients[channel_id], min_interval_hours=1
    )

    assert result["checked"] == 1
    assert len(clients[CHANNEL].calls) == 1
    assert clients["google:other"].calls == []

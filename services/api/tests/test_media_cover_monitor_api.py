"""Cover monitor HTTP surface: the publish composer reads this section."""
from app.modules.media import cover_monitor


async def test_cover_monitors_lists_the_real_google_cover(client, db, user_id):
    await cover_monitor.record_publish(
        db,
        tenant_id=user_id,
        channel_id="google:1",
        user_id=user_id,
        account_id="accounts/1",
        location_id="locations/9",
        expected_name="locations/9/media/a",
        image_url="https://example.com/mine.jpg",
        google_url="https://lh3.googleusercontent.com/a",
    )

    res = client.get("/api/v1/media/cover-monitors")

    assert res.status_code == 200, res.text
    row = res.json()[0]
    assert row["status"] == "ok"
    assert row["image_url"] == "https://lh3.googleusercontent.com/a"
    assert row["expected_image_url"] == "https://example.com/mine.jpg"


async def test_acknowledge_clears_the_change_warning(client, db, user_id):
    row = await cover_monitor.record_publish(
        db, tenant_id=user_id, channel_id="google:2", user_id=user_id,
        account_id="accounts/1", location_id="locations/10",
        expected_name="locations/10/media/a", image_url="https://example.com/a.jpg",
    )
    row.status = "changed"
    row.actual_name = "locations/10/media/b"
    row.actual_image_url = "https://lh3.googleusercontent.com/b"
    row.drift_count = 2
    await db.commit()

    res = client.post(f"/api/v1/media/cover-monitors/{row.id}/acknowledge")

    assert res.status_code == 200, res.text
    assert res.json()["status"] == "ok"
    listed = client.get("/api/v1/media/cover-monitors").json()
    assert listed[0]["status"] == "ok"
    assert listed[0]["drift_count"] == 0


async def test_cover_monitors_is_tenant_scoped(client, db, user_id):
    await cover_monitor.record_publish(
        db, tenant_id=user_id, channel_id="google:mine", user_id=user_id,
        account_id="accounts/1", location_id="locations/1",
        expected_name="n", image_url="https://example.com/1.jpg",
    )
    await cover_monitor.record_publish(
        db, tenant_id="someone-else", channel_id="google:theirs", user_id="someone-else",
        account_id="accounts/2", location_id="locations/2",
        expected_name="n2", image_url="https://example.com/2.jpg",
    )

    rows = client.get("/api/v1/media/cover-monitors").json()

    assert [r["channel_id"] for r in rows] == ["google:mine"]

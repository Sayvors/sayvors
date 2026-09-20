"""Location posts CRUD + publish + sync (Google push is monkeypatched)."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.localith.models import LocalithConnection
from app.modules.posts import service as posts


async def _connection(db, user_id):
    db.add(LocalithConnection(
        id="conn-post-1", user_id=user_id, listing_id="loc-1",
        listing_name="Test Place", listing_google_id="g1",
    ))
    await db.commit()


def _draft(listing_id="loc-1", **over):
    data = {
        "listing_id": listing_id, "location_name": "Test Place",
        "business_name": "Sayvors", "title": "Offer", "post_type": "update",
        "description": "Weekend deal", "tags": ["offer"], "keywords": ["deal"],
        "image_urls": [], "cta_type": None, "cta_url": None,
        "action": "draft", "scheduled_on": None,
    }
    data.update(over)
    return data


@pytest.mark.asyncio
async def test_create_draft_and_list(db, user_id):
    res = await posts.create_post(db, user_id, _draft())
    assert res["post"]["status"] == "draft"
    assert res["google_published"] is False
    rows = await posts.list_posts(db, user_id, "loc-1")
    assert len(rows) == 1
    assert rows[0]["title"] == "Offer"


@pytest.mark.asyncio
async def test_create_schedule_requires_future_date(db, user_id):
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    with pytest.raises(ValueError):
        await posts.create_post(db, user_id, _draft(action="schedule", scheduled_on=past))
    with pytest.raises(ValueError):
        await posts.create_post(db, user_id, _draft(action="schedule", scheduled_on=None))


@pytest.mark.asyncio
async def test_publish_now_calls_localith(monkeypatch, db, user_id):
    await _connection(db, user_id)
    calls = []

    def _fake_publish(listing_id, **kw):
        calls.append((listing_id, kw))
        return {"id": "pub-1"}

    monkeypatch.setattr(
        "integrations.channels.embedsocial.publish_media_post", _fake_publish
    )
    created = await posts.create_post(db, user_id, _draft())
    res = await posts.publish_post(db, user_id, created["post"]["id"])
    assert res["google_published"] is True
    assert res["post"]["status"] == "published"
    assert res["post"]["published_at"]
    assert calls[0][0] == "loc-1"
    assert calls[0][1]["caption"] == "Weekend deal"


@pytest.mark.asyncio
async def test_publish_rejects_unconnected_listing(monkeypatch, db, user_id):
    await _connection(db, user_id)

    def _boom(*a, **k):
        raise AssertionError("must not reach Google")

    monkeypatch.setattr(
        "integrations.channels.embedsocial.publish_media_post", _boom
    )
    created = await posts.create_post(db, user_id, _draft(listing_id="other"))
    with pytest.raises(ValueError):
        await posts.publish_post(db, user_id, created["post"]["id"])


@pytest.mark.asyncio
async def test_failed_publish_marks_row(monkeypatch, db, user_id):
    await _connection(db, user_id)

    def _fail(*a, **k):
        raise RuntimeError("Localith exploded")

    monkeypatch.setattr(
        "integrations.channels.embedsocial.publish_media_post", _fail
    )
    created = await posts.create_post(db, user_id, _draft())
    with pytest.raises(RuntimeError):
        await posts.publish_post(db, user_id, created["post"]["id"])
    rows = await posts.list_posts(db, user_id, "loc-1")
    assert rows[0]["status"] == "failed"
    assert "exploded" in (rows[0]["error"] or "")


@pytest.mark.asyncio
async def test_update_and_delete(db, user_id):
    created = await posts.create_post(db, user_id, _draft())
    pid = created["post"]["id"]
    out = await posts.update_post(db, user_id, pid, {"title": "New title"})
    assert out["post"]["title"] == "New title"
    await posts.delete_post(db, user_id, pid)
    assert await posts.list_posts(db, user_id, "loc-1") == []
    with pytest.raises(ValueError):
        await posts.delete_post(db, user_id, pid)


@pytest.mark.asyncio
async def test_publish_due_only_publishes_due(monkeypatch, db, user_id):
    await _connection(db, user_id)
    calls = []

    def _fake_publish(listing_id, **kw):
        calls.append(listing_id)
        return {"id": "pub-x"}

    monkeypatch.setattr(
        "integrations.channels.embedsocial.publish_media_post", _fake_publish
    )
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    # Bypass the future-date guard by creating drafts then marking scheduled.
    due = await posts.create_post(db, user_id, _draft())
    later = await posts.create_post(db, user_id, _draft())
    await posts.update_post(db, user_id, due["post"]["id"],
                            {"status": "scheduled", "scheduled_on": past})
    await posts.update_post(db, user_id, later["post"]["id"],
                            {"status": "scheduled", "scheduled_on": future})
    totals = await posts.publish_due(db)
    assert totals == {"checked": 1, "published": 1, "failed": 0,
                      "retried": 0, "skipped": 0, "errors": []}
    assert calls == ["loc-1"]


@pytest.mark.asyncio
async def test_cannot_publish_published_or_archived(db, user_id):
    created = await posts.create_post(db, user_id, _draft())
    pid = created["post"]["id"]
    await posts.update_post(db, user_id, pid, {"status": "archived"})
    with pytest.raises(ValueError):
        await posts.publish_post(db, user_id, pid)


def _future(hours=2):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


@pytest.mark.asyncio
async def test_delete_at_validation(db, user_id):
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    with pytest.raises(ValueError):
        await posts.create_post(db, user_id, _draft(delete_at=past))
    publish_at = _future(3)
    delete_at = _future(1)
    with pytest.raises(ValueError):
        await posts.create_post(
            db, user_id,
            _draft(action="schedule", scheduled_on=publish_at, delete_at=delete_at),
        )
    res = await posts.create_post(
        db, user_id,
        _draft(action="schedule", scheduled_on=delete_at, delete_at=publish_at,
               end_date=_future(4)),
    )
    assert res["post"]["delete_at"]
    assert res["post"]["end_date"]
    assert res["post"]["status"] == "scheduled"


@pytest.mark.asyncio
async def test_update_delete_at_set_and_cancel(db, user_id):
    created = await posts.create_post(db, user_id, _draft())
    pid = created["post"]["id"]
    out = await posts.update_post(db, user_id, pid, {"delete_at": _future()})
    assert out["post"]["delete_at"]
    # Absent key leaves it untouched.
    out = await posts.update_post(db, user_id, pid, {"title": "T2"})
    assert out["post"]["delete_at"]
    # Explicit null cancels.
    out = await posts.update_post(db, user_id, pid, {"delete_at": None})
    assert out["post"]["delete_at"] is None


@pytest.mark.asyncio
async def test_publish_stores_google_id_and_end_date(monkeypatch, db, user_id):
    await _connection(db, user_id)
    calls = []

    def _fake_publish(listing_id, **kw):
        calls.append(kw)
        return {"id": "pub-9"}

    monkeypatch.setattr(
        "integrations.channels.embedsocial.publish_media_post", _fake_publish
    )
    created = await posts.create_post(db, user_id, _draft(end_date=_future(48)))
    res = await posts.publish_post(db, user_id, created["post"]["id"])
    assert res["post"]["google_post_id"] == "pub-9"
    assert calls[0]["end_date"]


@pytest.mark.asyncio
async def test_retry_then_park(monkeypatch, db, user_id):
    await _connection(db, user_id)

    def _fail(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(
        "integrations.channels.embedsocial.publish_media_post", _fail
    )
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    created = await posts.create_post(db, user_id, _draft())
    pid = created["post"]["id"]
    await posts.update_post(db, user_id, pid, {"status": "scheduled", "scheduled_on": past})
    with pytest.raises(RuntimeError):
        await posts.publish_post(db, user_id, pid)
    rows = await posts.list_posts(db, user_id, "loc-1")
    assert rows[0]["status"] == "scheduled"  # kept for retry, not parked
    totals = await posts.publish_due(db)
    assert totals["checked"] == 0  # backoff not elapsed: skipped silently
    # Exhaust attempts -> parked as failed for the manual Retry button.
    from app.modules.posts.models import LocationPost
    from sqlalchemy import select as _select
    for _ in range(posts.MAX_PUBLISH_ATTEMPTS):
        try:
            await posts.publish_post(db, user_id, pid)
        except RuntimeError:
            pass
    row = (await db.execute(
        _select(LocationPost).where(LocationPost.id == pid)
    )).scalar_one()
    assert row.status == "failed"
    assert row.next_retry_at is None
    totals = await posts.publish_due(db)
    assert totals["checked"] == 0


@pytest.mark.asyncio
async def test_delete_due_removes_only_due(db, user_id):
    from datetime import datetime as _dt
    from app.modules.posts.models import LocationPost

    async def _row(delete_at):
        p = LocationPost(id=f"p-{delete_at is not None}-{len(await posts.list_posts(db, user_id))}",
                         user_id=user_id, listing_id="loc-1", status="scheduled",
                         delete_at=delete_at)
        db.add(p)
        await db.commit()
        return p.id

    now = _dt.now(timezone.utc)
    due_id = await _row(now - timedelta(minutes=1))
    future_id = await _row(now + timedelta(days=1))
    totals = await posts.delete_due(db)
    assert totals == {"checked": 1, "deleted": 1}
    remaining = await posts.list_posts(db, user_id, "loc-1")
    assert [r["id"] for r in remaining] == [future_id]
    assert due_id not in [r["id"] for r in remaining]


async def _notif_types(db, user_id):
    from sqlalchemy import select as _select

    from app.modules.notifications.models import Notification

    rows = (
        await db.execute(
            _select(Notification.type).where(Notification.user_id == user_id)
        )
    ).scalars().all()
    return list(rows)


@pytest.mark.asyncio
async def test_schedule_create_notifies(db, user_id):
    res = await posts.create_post(
        db, user_id, _draft(action="schedule", scheduled_on=_future())
    )
    assert res["post"]["status"] == "scheduled"
    types = await _notif_types(db, user_id)
    assert types.count("post_scheduled") == 1


@pytest.mark.asyncio
async def test_manual_publish_notifies_published(monkeypatch, db, user_id):
    await _connection(db, user_id)

    def _fake_publish(listing_id, **kw):
        return {"id": "pub-n"}

    monkeypatch.setattr(
        "integrations.channels.embedsocial.publish_media_post", _fake_publish
    )
    created = await posts.create_post(db, user_id, _draft())
    await posts.publish_post(db, user_id, created["post"]["id"])
    assert "post_published" in await _notif_types(db, user_id)


@pytest.mark.asyncio
async def test_parked_failure_notifies_but_retry_does_not(monkeypatch, db, user_id):
    await _connection(db, user_id)

    def _fail(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(
        "integrations.channels.embedsocial.publish_media_post", _fail
    )
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    created = await posts.create_post(db, user_id, _draft())
    pid = created["post"]["id"]
    await posts.update_post(db, user_id, pid, {"status": "scheduled", "scheduled_on": past})
    with pytest.raises(RuntimeError):
        await posts.publish_post(db, user_id, pid)
    # Still scheduled (retrying): no failure notification yet.
    assert "post_failed" not in await _notif_types(db, user_id)
    from app.modules.posts.models import LocationPost
    from sqlalchemy import select as _select

    row = (await db.execute(
        _select(LocationPost).where(LocationPost.id == pid)
    )).scalar_one()
    row.attempts = posts.MAX_PUBLISH_ATTEMPTS - 1
    await db.commit()
    with pytest.raises(RuntimeError):
        await posts.publish_post(db, user_id, pid)
    assert "post_failed" in await _notif_types(db, user_id)


@pytest.mark.asyncio
async def test_localith_error_body_reaches_post_error(monkeypatch, db, user_id):
    """A 400 from Localith must surface its body (which field, what limit)
    on the row — previously only a bare status code survived."""
    import httpx

    from integrations.channels import embedsocial

    await _connection(db, user_id)

    def _fake_post(url, **kw):
        req = httpx.Request("POST", url)
        return httpx.Response(400, text='{"errors":{"caption":"too long"}}', request=req)

    monkeypatch.setattr(embedsocial.httpx, "post", _fake_post)
    monkeypatch.setenv("LOCALITH_API_KEY", "test-key")
    created = await posts.create_post(db, user_id, _draft())
    pid = created["post"]["id"]
    await posts.update_post(db, user_id, pid,
                            {"status": "scheduled", "scheduled_on": _future()})
    with pytest.raises(RuntimeError, match="caption"):
        await posts.publish_post(db, user_id, pid)
    from sqlalchemy import select as _select

    from app.modules.posts.models import LocationPost

    row = (await db.execute(
        _select(LocationPost).where(LocationPost.id == pid)
    )).scalar_one()
    assert "too long" in (row.error or "")


@pytest.mark.asyncio
async def test_worker_summary_one_row_per_user(monkeypatch, db, user_id):
    from app.modules.users.models import User

    await _connection(db, user_id)
    uid2 = f"{user_id}-b"
    db.add(User(id=uid2, first_name="T", last_name="U",
                email="second@example.com", password_hash="x"))
    db.add(__import__("app.modules.localith.models", fromlist=["LocalithConnection"]).LocalithConnection(
        id="conn-post-2", user_id=uid2, listing_id="loc-1",
        listing_name="Test Place", listing_google_id="g1",
    ))
    await db.commit()

    def _fake_publish(listing_id, **kw):
        return {"id": "pub-w"}

    monkeypatch.setattr(
        "integrations.channels.embedsocial.publish_media_post", _fake_publish
    )
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    for uid in (user_id, uid2):
        created = await posts.create_post(db, uid, _draft())
        await posts.update_post(db, uid, created["post"]["id"],
                                {"status": "scheduled", "scheduled_on": past})
    # create_post already emitted a post_scheduled row each; isolate worker rows.
    from sqlalchemy import delete as _delete

    from app.modules.notifications.models import Notification

    await db.execute(_delete(Notification).where(Notification.user_id.in_([user_id, uid2])))
    await db.commit()
    totals = await posts.publish_due(db)
    assert totals["published"] == 2
    for uid in (user_id, uid2):
        types = await _notif_types(db, uid)
        assert types.count("post_published") == 1, types


@pytest.mark.asyncio
async def test_event_requires_start_date(db, user_id):
    with pytest.raises(ValueError, match="start date"):
        await posts.create_post(db, user_id, _draft(post_type="event"))
    res = await posts.create_post(
        db, user_id,
        _draft(post_type="event", title="Grand Opening",
               start_date=_future(24), end_date=_future(48)),
    )
    assert res["post"]["start_date"]
    assert res["post"]["end_date"]


@pytest.mark.asyncio
async def test_offer_maps_coupon_terms_cta_to_google(monkeypatch, db, user_id):
    await _connection(db, user_id)
    calls = []

    def _fake_publish(listing_id, **kw):
        calls.append(kw)
        return {"id": "pub-offer"}

    monkeypatch.setattr(
        "integrations.channels.embedsocial.publish_media_post", _fake_publish
    )
    created = await posts.create_post(
        db, user_id,
        _draft(post_type="offer", title="20% Off",
               coupon_code="SAVE20", terms_conditions="Dine-in only.",
               cta_type="shop", cta_url="https://shop.example.com"),
    )
    assert created["post"]["coupon_code"] == "SAVE20"
    await posts.publish_post(db, user_id, created["post"]["id"])
    body = calls[0]
    assert body["post_type"] == "offer"
    assert body["voucher_code"] == "SAVE20"
    assert "Dine-in only." in body["caption"]
    assert "Weekend deal" in body["caption"]
    assert body["cta_type"] == "shop"
    assert body["cta_url"] == "https://shop.example.com"


@pytest.mark.asyncio
async def test_delete_at_becomes_google_end_for_dated_posts(monkeypatch, db, user_id):
    """Scheduled deletion removes the Google copy too — via endDate, the
    only Google-side removal Localith supports (no post delete exists)."""
    await _connection(db, user_id)
    calls = []

    def _fake_publish(listing_id, **kw):
        calls.append(kw)
        return {"id": "pub-end"}

    monkeypatch.setattr(
        "integrations.channels.embedsocial.publish_media_post", _fake_publish
    )
    delete_at = _future(72)
    created = await posts.create_post(
        db, user_id,
        _draft(post_type="event", title="Show",
               start_date=_future(24), delete_at=delete_at),
    )
    await posts.publish_post(db, user_id, created["post"]["id"])
    from datetime import datetime as _dt
    from datetime import timezone as _tz

    def _instant(s: str) -> float:
        d = _dt.fromisoformat(s)
        return d.replace(tzinfo=_tz.utc).timestamp() if d.tzinfo is None else d.timestamp()

    # String forms differ by backend tz handling (sqlite strips offsets,
    # Postgres keeps them) — compare instants.
    assert _instant(calls[0]["end_date"]) == _instant(delete_at)
    assert calls[0]["start_date"]


def test_adapter_body_uses_localith_field_names(monkeypatch):
    """The Google-bound JSON must carry voucherCode/startDate/endDate —
    this is the exact contract Localith documents."""
    from integrations.channels import embedsocial

    seen = {}

    class _Resp:
        status_code = 200
        text = "{}"

        def raise_for_status(self):
            return None

        def json(self):
            return {"id": "x"}

    def _fake_post(url, **kw):
        seen.update(kw["json"])
        return _Resp()

    monkeypatch.setattr(embedsocial.httpx, "post", _fake_post)
    monkeypatch.setenv("LOCALITH_API_KEY", "test-key")
    embedsocial.publish_media_post(
        "loc-1", post_type="offer", title="Deal", caption="Hi",
        voucher_code="SAVE20", start_date="2026-10-01T10:00:00Z",
        end_date="2026-10-31T10:00:00Z",
    )
    assert seen["type"] == "offer"
    assert seen["voucherCode"] == "SAVE20"
    assert seen["startDate"] == "2026-10-01T10:00:00Z"
    assert seen["endDate"] == "2026-10-31T10:00:00Z"


def _fake_llm_provider(content: str, fail_first: bool = False):
    calls = {"n": 0}

    class _Resp:
        def __init__(self, text):
            self.content = text

    class _Provider:
        async def complete(self, req):
            calls["n"] += 1
            if fail_first and calls["n"] == 1:
                raise RuntimeError("primary down")
            return _Resp(content)

    return _Provider(), calls


async def _no_tenant_models(db):
    return []


async def _custom_tenant_model(db):
    from types import SimpleNamespace

    return [(SimpleNamespace(id="custom:model"), None)]


@pytest.mark.asyncio
async def test_ai_draft_parses_and_caps(monkeypatch, db, user_id):
    import json as _json

    from app.modules.posts import service as _svc

    provider, calls = _fake_llm_provider(_json.dumps({
        "description": "Weekend deal! " * 200,
        "tags": ["Offer", "offer", "weekend sale", "x"],
        "keywords": "pizza, Pizza, deals, ",
    }))
    monkeypatch.setattr(
        "app.modules.llm.providers.registry.get_provider_for_model",
        lambda mid: provider,
    )
    monkeypatch.setattr(
        "app.modules.llm.service._resolve_model",
        lambda mid: ("api-x", "groq"),
    )
    monkeypatch.setattr(
        "app.modules.llm.providers.registry.list_tenant_models",
        _custom_tenant_model,
    )
    out = await _svc.draft_post_content(db, user_id, "Weekend Deal", "offer", "Sayvors")
    assert len(out["description"]) <= 1500
    assert out["tags"] == ["offer", "weekend sale", "x"]
    assert out["keywords"] == ["pizza", "deals"]
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_ai_draft_no_enabled_model_raises(db, user_id):
    """No enabled models and no fallback: loud error naming the cause."""
    from app.modules.posts import service as _svc

    import app.modules.llm.providers.registry as _reg

    async def _no_models(db):
        return []

    orig = _reg.list_tenant_models
    _reg.list_tenant_models = _no_models
    try:
        with pytest.raises(ValueError, match="No AI model is enabled"):
            await _svc.draft_post_content(db, user_id, "Hi", "update", None)
    finally:
        _reg.list_tenant_models = orig


@pytest.mark.asyncio
async def test_ai_draft_failure_has_no_fallback(monkeypatch, db, user_id):
    from app.modules.posts import service as _svc

    provider, calls = _fake_llm_provider("{}", fail_first=True)
    monkeypatch.setattr(
        "app.modules.llm.providers.registry.get_provider_for_model",
        lambda mid: provider,
    )
    monkeypatch.setattr(
        "app.modules.llm.service._resolve_model",
        lambda mid: ("api-x", "groq"),
    )
    monkeypatch.setattr(
        "app.modules.llm.providers.registry.list_tenant_models",
        _custom_tenant_model,
    )
    with pytest.raises(RuntimeError, match="AI drafting failed"):
        await _svc.draft_post_content(db, user_id, "Hi", "update", None)
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_ai_draft_rejects_empty_title(db, user_id):
    from app.modules.posts import service as _svc

    with pytest.raises(ValueError):
        await _svc.draft_post_content(db, user_id, "   ", "update", None)


@pytest.mark.asyncio
async def test_ai_draft_garbage_returns_empty_fields(monkeypatch, db, user_id):
    from app.modules.posts import service as _svc

    provider, _ = _fake_llm_provider("not json at all {{{")
    monkeypatch.setattr(
        "app.modules.llm.providers.registry.get_provider_for_model",
        lambda mid: provider,
    )
    monkeypatch.setattr(
        "app.modules.llm.service._resolve_model",
        lambda mid: ("api-x", "groq"),
    )
    monkeypatch.setattr(
        "app.modules.llm.providers.registry.list_tenant_models",
        _custom_tenant_model,
    )
    out = await _svc.draft_post_content(db, user_id, "T", "update", None)
    assert out == {"description": "", "tags": [], "keywords": []}

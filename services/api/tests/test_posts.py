"""Location posts CRUD + publish + sync (Google push is monkeypatched)."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.posts import service as posts


async def _connection(db, user_id, listing_id="loc-1"):
    import json

    from app.modules.channels.models import Channel
    from app.modules.channels.service import encrypt_token

    db.add(Channel(
        id=f"ch-post-{user_id[-12:]}-{listing_id}", user_id=user_id,
        platform="google_reviews",
        platform_user_id="acct-post", display_name="Test Place", status="active",
        listing_key=listing_id, access_token=encrypt_token("at"),
        refresh_token=encrypt_token("rt"),
        metadata_json=json.dumps({"location_id": listing_id}),
    ))
    await db.commit()


def _patch_publish(monkeypatch, *, result=None, error=None):
    """Replace the native publisher with an async recorder."""
    calls = []

    async def _fake(self, token, asset_id, method, media_url, media_type,
                    caption, description, scheduled_at, account_id=None, **kw):
        calls.append({
            "asset_id": asset_id, "method": method, "caption": caption,
            "scheduled_at": scheduled_at, "account_id": account_id, **kw,
        })
        if error:
            raise error
        return result or {"id": "pub-1"}

    monkeypatch.setattr(
        "app.modules.channels.meta.providers.google_publish.GoogleBusinessPublisher.publish_post",
        _fake,
    )
    return calls


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
async def test_publish_now_calls_google(monkeypatch, db, user_id):
    await _connection(db, user_id)
    calls = _patch_publish(monkeypatch, result={"id": "pub-1"})
    created = await posts.create_post(db, user_id, _draft())
    res = await posts.publish_post(db, user_id, created["post"]["id"])
    assert res["google_published"] is True
    assert res["post"]["status"] == "published"
    assert res["post"]["published_at"]
    assert calls[0]["asset_id"] == "loc-1"
    assert calls[0]["account_id"] == "acct-post"
    assert calls[0]["caption"] == "Weekend deal"


@pytest.mark.asyncio
async def test_publish_rejects_unconnected_listing(db, user_id):
    await _connection(db, user_id)
    created = await posts.create_post(db, user_id, _draft(listing_id="other"))
    with pytest.raises(ValueError, match="Connect that Google location"):
        await posts.publish_post(db, user_id, created["post"]["id"])


@pytest.mark.asyncio
async def test_failed_publish_marks_row(monkeypatch, db, user_id):
    await _connection(db, user_id)
    _patch_publish(monkeypatch, error=RuntimeError("Google exploded"))
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
    calls = _patch_publish(monkeypatch)
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
    assert calls[0]["asset_id"] == "loc-1"


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
    calls = _patch_publish(monkeypatch, result={"id": "pub-9"})
    created = await posts.create_post(db, user_id, _draft(end_date=_future(48)))
    res = await posts.publish_post(db, user_id, created["post"]["id"])
    assert res["post"]["google_post_id"] == "pub-9"
    assert calls[0]["end_date"]


@pytest.mark.asyncio
async def test_retry_then_park(monkeypatch, db, user_id):
    await _connection(db, user_id)
    _patch_publish(monkeypatch, error=RuntimeError("down"))
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
    _patch_publish(monkeypatch, result={"id": "pub-n"})
    created = await posts.create_post(db, user_id, _draft())
    await posts.publish_post(db, user_id, created["post"]["id"])
    assert "post_published" in await _notif_types(db, user_id)


@pytest.mark.asyncio
async def test_parked_failure_notifies_but_retry_does_not(monkeypatch, db, user_id):
    await _connection(db, user_id)
    _patch_publish(monkeypatch, error=RuntimeError("down"))
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
async def test_google_error_body_reaches_post_error(monkeypatch, db, user_id):
    """A Google 400 must surface its body (which field, what limit) on the row."""
    from app.modules.channels.google_reviews import GoogleReviewsError

    await _connection(db, user_id)
    _patch_publish(
        monkeypatch,
        error=GoogleReviewsError('create_local_post failed (400): {"error":"caption too long"}', 400),
    )
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
    await _connection(db, uid2)
    await db.commit()

    _patch_publish(monkeypatch, result={"id": "pub-w"})
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
async def test_offer_requires_start_and_end_dates(db, user_id):
    with pytest.raises(ValueError, match="both start and end dates"):
        await posts.create_post(db, user_id, _draft(post_type="offer"))
    with pytest.raises(ValueError, match="after its start date"):
        await posts.create_post(
            db, user_id,
            _draft(post_type="offer", start_date=_future(48), end_date=_future(24)),
        )
    res = await posts.create_post(
        db, user_id,
        _draft(post_type="offer", start_date=_future(24), end_date=_future(48)),
    )
    assert res["post"]["start_date"] and res["post"]["end_date"]


@pytest.mark.asyncio
async def test_offer_maps_coupon_terms_cta_to_google(monkeypatch, db, user_id):
    await _connection(db, user_id)
    calls = _patch_publish(monkeypatch)
    created = await posts.create_post(
        db, user_id,
        _draft(post_type="offer", title="20% Off",
               start_date=_future(24), end_date=_future(48),
               coupon_code="SAVE20", terms_conditions="Dine-in only.",
               cta_type="shop", cta_url="https://shop.example.com"),
    )
    assert created["post"]["coupon_code"] == "SAVE20"
    await posts.publish_post(db, user_id, created["post"]["id"])
    body = calls[0]
    assert body["method"] == "offer"
    assert body["coupon_code"] == "SAVE20"
    assert body["terms_conditions"] == "Dine-in only."
    assert "Weekend deal" in body["caption"]
    assert body["cta_type"] == "shop"
    assert body["cta_url"] == "https://shop.example.com"


@pytest.mark.asyncio
async def test_delete_at_becomes_google_end_for_dated_posts(monkeypatch, db, user_id):
    """Scheduled deletion removes the Google copy too — via the end date."""
    await _connection(db, user_id)
    calls = _patch_publish(monkeypatch, result={"id": "pub-end"})
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


@pytest.mark.asyncio
async def test_ai_draft_empty_content_retried_once_same_model(monkeypatch, db, user_id):
    """Empty replies get one same-model retry (not a fallback), then a
    model-free error for the user."""
    import json as _json

    from app.modules.posts import service as _svc

    calls = {"n": 0}

    class _Resp:
        def __init__(self, text):
            self.content = text

    class _Provider:
        async def complete(self, req):
            calls["n"] += 1
            if calls["n"] == 1:
                return _Resp("")
            return _Resp(_json.dumps({"description": "Second try", "tags": [], "keywords": []}))

    monkeypatch.setattr(
        "app.modules.llm.providers.registry.get_provider_for_model",
        lambda mid: _Provider(),
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
    assert out["description"] == "Second try"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_ai_draft_empty_twice_raises_without_model_name(monkeypatch, db, user_id):
    from app.modules.posts import service as _svc

    class _Resp:
        content = ""

    class _Provider:
        async def complete(self, req):
            return _Resp()

    monkeypatch.setattr(
        "app.modules.llm.providers.registry.get_provider_for_model",
        lambda mid: _Provider(),
    )
    monkeypatch.setattr(
        "app.modules.llm.service._resolve_model",
        lambda mid: ("api-x", "groq"),
    )
    monkeypatch.setattr(
        "app.modules.llm.providers.registry.list_tenant_models",
        _custom_tenant_model,
    )
    with pytest.raises(RuntimeError, match="AI drafting returned nothing"):
        await _svc.draft_post_content(db, user_id, "T", "update", None)


@pytest.mark.asyncio
async def test_sync_endpoint_admin_only(client):
    """C1: /sync triggers a GLOBAL publish/delete pass — only admins may call
    it. The real worker runs its own loop (posts/worker.py)."""
    r = client.post("/api/v1/posts/sync", headers={"host": "localhost"})
    assert r.status_code == 401

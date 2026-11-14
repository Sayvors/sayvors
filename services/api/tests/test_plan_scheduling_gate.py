"""Plan scheduling gate (§34 item 5): the `scheduling` feature key.

The posts module and scheduler worker exist; this gates the *creation* of
scheduled posts on the plan feature. Instant publish and drafts stay open.
Both write paths are covered: POST /posts (action=schedule) and
PUT /posts/{id} (status=scheduled).
"""
import sys
from pathlib import Path

import pytest
from sqlalchemy import select

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.billing.models import Plan
from app.modules.channels.models import Channel

pytestmark = pytest.mark.asyncio

CHANNEL = "test-channel-0000-0000-0000-000000000001"  # conftest channel_id fixture value


async def _set_free_trial_scheduling(db, enabled: bool) -> None:
    plan = (
        await db.execute(select(Plan).where(Plan.slug == "free-trial"))
    ).scalar_one()
    features = dict(plan.features or {})
    features["scheduling"] = enabled
    plan.features = features
    await db.flush()


def _payload(**overrides):
    body = {
        "listing_id": CHANNEL,
        "title": "Weekend offer",
        "post_type": "offer",
        "description": "20% off this weekend.",
        "action": "schedule",
        "scheduled_on": "2026-12-01T10:00:00Z",
    }
    body.update(overrides)
    return body


async def test_create_scheduled_post_denied_without_feature(client, db, monkeypatch):
    await _set_free_trial_scheduling(db, False)
    called = False

    async def should_not_run(*a, **k):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr("app.modules.posts.service.create_post", should_not_run)
    resp = client.post("/api/v1/posts/", json=_payload())
    assert resp.status_code == 403
    assert resp.headers.get("X-Entitlement-Denied") == "scheduling"
    assert called is False


async def test_create_scheduled_post_allowed_with_feature(client, db, monkeypatch):
    await _set_free_trial_scheduling(db, True)

    async def fake_create(db, tenant_id, data):
        raise ValueError("gate-passed")  # service layer runs → 400, not 403

    monkeypatch.setattr("app.modules.posts.service.create_post", fake_create)
    resp = client.post("/api/v1/posts/", json=_payload())
    assert resp.status_code == 400
    assert resp.json()["detail"] == "gate-passed"


async def test_create_instant_publish_not_gated(client, db, monkeypatch):
    await _set_free_trial_scheduling(db, False)

    async def fake_create(db, tenant_id, data):
        raise ValueError("gate-passed")

    monkeypatch.setattr("app.modules.posts.service.create_post", fake_create)
    resp = client.post("/api/v1/posts/", json=_payload(action="publish"))
    assert resp.status_code == 400
    assert resp.json()["detail"] == "gate-passed"


async def test_update_to_scheduled_denied_without_feature(client, db, monkeypatch):
    await _set_free_trial_scheduling(db, False)
    called = False

    async def should_not_run(*a, **k):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr("app.modules.posts.service.update_post", should_not_run)
    resp = client.put("/api/v1/posts/post-1", json={"status": "scheduled"})
    assert resp.status_code == 403
    assert resp.headers.get("X-Entitlement-Denied") == "scheduling"
    assert called is False


async def test_update_to_other_status_not_gated(client, db, monkeypatch):
    await _set_free_trial_scheduling(db, False)

    async def fake_update(db, tenant_id, post_id, data):
        raise ValueError("gate-passed")

    monkeypatch.setattr("app.modules.posts.service.update_post", fake_update)
    resp = client.put("/api/v1/posts/post-1", json={"status": "draft"})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "gate-passed"

"""RBAC enforcement regression tests (team-access audit fixes).

The 403 paths all fire in require_perm / channel-level checks BEFORE any
handler body runs, so no provider mocks are needed. Happy paths for the
underlying services are covered by the endpoint suites; here we prove the
gates exist and are tenant/role-correct.

Reuses test_team_rbac's seeding helpers (same constants + fixture ids).
"""
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.core.deps import get_current_user
from app.modules.team import service
from app.security import create_access_token

from tests.test_team_rbac import CHANNEL, TENANT, _auth_as, _seed_member


# ── suspension is enforced at the auth layer ─────────────


@pytest.mark.asyncio
async def test_suspended_member_blocked_in_get_current_user(db, monkeypatch):
    """Suspend must block EVERY authenticated endpoint — the check lives in
    get_current_user, not only in team get_context."""
    from app.modules.auth import rate_limit as rl

    async def _not_blacklisted(jti):
        return False

    monkeypatch.setattr(rl, "is_token_blacklisted", _not_blacklisted)

    member, mu = await _seed_member(db)
    creds = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials=create_access_token(mu.id, 0)
    )
    # Active member authenticates fine.
    user = await get_current_user(credentials=creds, db=db)
    assert user.id == mu.id

    db_member = await service.get_member(db, TENANT, member.id)
    await service.set_member_status(db, db_member, "suspended")
    await db.commit()

    with pytest.raises(HTTPException) as ei:
        await get_current_user(credentials=creds, db=db)
    assert ei.value.status_code == 403
    assert "suspended" in str(ei.value.detail).lower()


@pytest.mark.asyncio
async def test_owner_without_member_row_authenticates(db, monkeypatch):
    """The owner has tenant_id None — the suspension lookup must not fire."""
    from app.modules.auth import rate_limit as rl

    async def _not_blacklisted(jti):
        return False

    monkeypatch.setattr(rl, "is_token_blacklisted", _not_blacklisted)

    from tests.test_team_rbac import OWNER_ID, _make_owner

    await _make_owner(db)
    creds = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials=create_access_token(OWNER_ID, 0)
    )
    user = await get_current_user(credentials=creds, db=db)
    assert user.id == OWNER_ID


# ── messages ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_viewer_cannot_send_channel_message(client, db, channel_id):
    _member, mu = await _seed_member(db, role_name="Viewer", overrides={CHANNEL: "view"})
    _auth_as(mu)
    res = client.post(
        f"/api/v1/channels/{CHANNEL}/messages",
        json={"content": "hi", "contact_phone": "+15550001"},
    )
    assert res.status_code == 403
    assert "inbox.reply" in res.json()["detail"]


@pytest.mark.asyncio
async def test_viewer_can_read_channel_messages(client, db, channel_id):
    """Read stays possible for a role with inbox.view + channel view."""
    _member, mu = await _seed_member(db, role_name="Viewer", overrides={CHANNEL: "view"})
    _auth_as(mu)
    res = client.get(f"/api/v1/channels/{CHANNEL}/messages")
    assert res.status_code == 200
    assert res.json()["messages"] == []


@pytest.mark.asyncio
async def test_agent_channel_level_none_blocks_messages(client, db, channel_id):
    """inbox.reply alone is not enough — the channel override gates too."""
    _member, mu = await _seed_member(db, role_name="Agent", overrides={CHANNEL: "none"})
    _auth_as(mu)
    res = client.post(
        f"/api/v1/channels/{CHANNEL}/messages",
        json={"content": "hi", "contact_phone": "+15550001"},
    )
    assert res.status_code == 403
    assert "edit access" in res.json()["detail"].lower()
    res = client.get(f"/api/v1/channels/{CHANNEL}/messages")
    assert res.status_code == 404


# ── reviews ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_viewer_cannot_generate_review_reply(client, db, channel_id):
    _member, mu = await _seed_member(db, role_name="Viewer", overrides={CHANNEL: "view"})
    _auth_as(mu)
    res = client.post(
        f"/api/v1/channels/{CHANNEL}/reviews/generate",
        json={"review_id": "rvw_1", "review_text": "great", "rating": 5},
    )
    assert res.status_code == 403
    assert "reviews.reply" in res.json()["detail"]


@pytest.mark.asyncio
async def test_agent_can_list_but_not_approve_replies(client, db, channel_id):
    """The catalog's design: Agents draft (reviews.reply), publishing a reply
    to Google (approve) needs reviews.publish — Admin-only."""
    _member, mu = await _seed_member(db, role_name="Agent", overrides={CHANNEL: "edit"})
    _auth_as(mu)
    res = client.get(f"/api/v1/channels/{CHANNEL}/reviews")
    assert res.status_code == 200
    res = client.post(f"/api/v1/channels/{CHANNEL}/reviews/rvw_1/approve")
    assert res.status_code == 403
    assert "reviews.publish" in res.json()["detail"]


@pytest.mark.asyncio
async def test_agent_channel_view_only_cannot_edit_reply(client, db, channel_id):
    _member, mu = await _seed_member(db, role_name="Agent", overrides={CHANNEL: "view"})
    _auth_as(mu)
    res = client.put(
        f"/api/v1/channels/{CHANNEL}/reviews/rvw_1", json={"reply_text": "thanks!"}
    )
    assert res.status_code == 403
    assert "edit access" in res.json()["detail"].lower()


# ── verification + services ───────────────────────────────


@pytest.mark.asyncio
async def test_viewer_cannot_request_verification(client, db, channel_id):
    _member, mu = await _seed_member(db, role_name="Viewer", overrides={CHANNEL: "view"})
    _auth_as(mu)
    res = client.post(
        f"/api/v1/channels/{CHANNEL}/verification",
        json={"method": "EMAIL", "contact_target": "o@acme.com"},
    )
    assert res.status_code == 403
    assert "channels.edit" in res.json()["detail"]


@pytest.mark.asyncio
async def test_agent_channel_none_cannot_list_services(client, db, channel_id):
    _member, mu = await _seed_member(db, role_name="Agent", overrides={CHANNEL: "none"})
    _auth_as(mu)
    res = client.get(f"/api/v1/channels/{CHANNEL}/services")
    assert res.status_code == 404


# ── meta router ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_viewer_cannot_start_meta_connect(client, db):
    _member, mu = await _seed_member(db, role_name="Viewer")
    _auth_as(mu)
    res = client.post("/api/v1/meta/facebook/connect")
    assert res.status_code == 403
    assert "channels.connect" in res.json()["detail"]


@pytest.mark.asyncio
async def test_agent_cannot_select_meta_assets(client, db):
    _member, mu = await _seed_member(db, role_name="Agent")
    _auth_as(mu)
    res = client.post(
        "/api/v1/meta/instagram/assets/select", json={"asset_ids": ["asset-1"]}
    )
    assert res.status_code == 403
    assert "channels.edit" in res.json()["detail"]


@pytest.mark.asyncio
async def test_agent_cannot_disconnect_meta(client, db):
    _member, mu = await _seed_member(db, role_name="Agent")
    _auth_as(mu)
    res = client.delete("/api/v1/meta/facebook/disconnect")
    assert res.status_code == 403
    assert "channels.remove" in res.json()["detail"]


# ── posts ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_agent_cannot_publish_or_delete_posts(client, db):
    """posts.create / posts.publish are now enforced (were dead permissions)."""
    _member, mu = await _seed_member(db, role_name="Agent")
    _auth_as(mu)
    res = client.post("/api/v1/posts/post-1/publish")
    assert res.status_code == 403
    assert "posts.publish" in res.json()["detail"]
    res = client.delete("/api/v1/posts/post-1")
    assert res.status_code == 403
    assert "posts.publish" in res.json()["detail"]


@pytest.mark.asyncio
async def test_viewer_can_list_posts(client, db):
    _member, mu = await _seed_member(db, role_name="Viewer")
    _auth_as(mu)
    res = client.get("/api/v1/posts")
    assert res.status_code == 200
    assert res.json() == []


# ── media ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_viewer_cannot_delete_media(client, db):
    _member, mu = await _seed_member(db, role_name="Viewer")
    _auth_as(mu)
    res = client.delete("/api/v1/media/media-1")
    assert res.status_code == 403
    assert "media.manage" in res.json()["detail"]


@pytest.mark.asyncio
async def test_viewer_can_list_media(client, db):
    _member, mu = await _seed_member(db, role_name="Viewer")
    _auth_as(mu)
    res = client.get("/api/v1/media")
    assert res.status_code == 200
    assert res.json() == []

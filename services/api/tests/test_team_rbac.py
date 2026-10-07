"""Team RBAC: catalog, role seeding, invite lifecycle, permission gating.

The `client` fixture authenticates every request as the workspace owner
(user_id stub override). Member-path tests re-point get_current_user at a
real member User row so get_context resolves their membership.
"""
import pytest
from fastapi import HTTPException
from sqlalchemy import select as _sel

from app.core.deps import get_current_user
from app.main import app as fastapi_app
from app.modules.team.context import TenantContext
from app.modules.team.models import TeamMember
from app.modules.team.permissions import ALL_PERMISSIONS, ROLE_TEMPLATES, validate_role_permissions
from app.modules.team import service
from app.modules.users.models import User

OWNER_ID = "test-user-0000-0000-0000-000000000001"
TENANT = OWNER_ID  # phase 1: the owner's tenant_id is their own user id
CHANNEL = "test-channel-0000-0000-0000-000000000001"  # conftest channel_id fixture value


async def _make_owner(db):
    existing = (await db.execute(_sel(User).where(User.id == OWNER_ID))).scalar_one_or_none()
    if existing is not None:
        return
    db.add(User(
        id=OWNER_ID, email="owner@acme.com", first_name="Ola", last_name="Owner",
        password_hash="x", business_name="Acme", onboarded=True,
    ))
    await db.commit()


async def _make_member_user(db, email="sara@acme.com", tenant_id=None):
    u = User(
        email=email, first_name="Sara", last_name="S",
        password_hash="x", tenant_id=tenant_id,
    )
    db.add(u)
    await db.commit()
    return u


def _auth_as(user_row):
    async def _dep():
        return user_row
    fastapi_app.dependency_overrides[get_current_user] = _dep


def _auth_owner():
    """Restore the conftest-style owner override (stub user, id = OWNER_ID)."""
    _auth_as(User(
        id=OWNER_ID, email="test@sayvors.com", first_name="Test",
        last_name="User", password_hash="x", onboarded=True,
    ))


async def _seed_member(db, role_name="Agent", status="active", overrides=None):
    """Owner + system roles + member row + member user; returns (member, member_user)."""
    await _make_owner(db)
    roles = await service.ensure_system_roles(db, TENANT)
    role = next(r for r in roles if r.name == role_name)
    mu = await _make_member_user(db, tenant_id=TENANT if status != "invited" else None)
    member, _raw = await service.invite_member(db, TENANT, OWNER_ID, mu.email, role)
    await db.commit()
    if status != "invited":
        member = await service.join_existing_user(db, member, mu)
        await db.commit()
    if overrides:
        await service.set_member_channels(db, member, overrides, tenant_id=TENANT)
        await db.commit()
    return member, mu


def _user_by_email(email):
    return _sel(User).where(User.email == email)


def _member_by_email(email):
    return _sel(TeamMember).where(TeamMember.email == email)


async def _noop_store_session(*a, **k):
    return None


@pytest.fixture
def no_email(monkeypatch):
    """Capture invite emails instead of hitting Resend."""
    sent = []

    async def _fake(to, inviter, business, role, url):
        sent.append({"to": to, "inviter": inviter, "business": business, "role": role, "url": url})

    import app.modules.email.service as email_service
    monkeypatch.setattr(email_service, "send_team_invite_email", _fake)
    return sent


# ── catalog ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_permission_catalog_covers_all(client):
    res = client.get("/api/v1/team/permissions")
    assert res.status_code == 200
    body = res.json()
    flat = {a["permission"] for area in body["areas"] for a in area["actions"]}
    assert flat == set(ALL_PERMISSIONS)
    assert {t["name"] for t in body["role_templates"]} == set(ROLE_TEMPLATES)


# ── roles ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_system_roles_seeded_idempotently(client):
    first = client.get("/api/v1/team/roles").json()["roles"]
    names = {r["name"] for r in first if r["is_system"]}
    assert {"Admin", "Agent", "Viewer"} <= names
    admin = next(r for r in first if r["name"] == "Admin")
    assert "inbox.reply" in admin["permissions"]
    assert "billing.manage" not in admin["permissions"]
    second = client.get("/api/v1/team/roles").json()["roles"]
    assert len([r for r in second if r["is_system"]]) == len([r for r in first if r["is_system"]])


@pytest.mark.asyncio
async def test_custom_role_crud_and_guards(client):
    created = client.post("/api/v1/team/roles", json={
        "name": "Support", "permissions": ["inbox.view", "inbox.reply", "bogus.perm"],
    })
    assert created.status_code == 201
    role = created.json()
    assert role["permissions"] == ["inbox.view", "inbox.reply"]  # unknown dropped
    role_id = role["id"]

    assert client.post("/api/v1/team/roles", json={
        "name": "Support", "permissions": ["inbox.view"],
    }).status_code == 409

    patched = client.patch(f"/api/v1/team/roles/{role_id}", json={
        "permissions": ["inbox.view"],
    })
    assert patched.status_code == 200 and patched.json()["permissions"] == ["inbox.view"]

    system_id = next(
        r["id"] for r in client.get("/api/v1/team/roles").json()["roles"] if r["name"] == "Admin"
    )
    assert client.patch(f"/api/v1/team/roles/{system_id}", json={
        "permissions": ["inbox.view"],
    }).status_code == 400
    assert client.delete(f"/api/v1/team/roles/{system_id}").status_code == 400
    assert client.delete(f"/api/v1/team/roles/{role_id}").status_code == 204


@pytest.mark.asyncio
async def test_cannot_delete_role_in_use(client, db):
    member, _ = await _seed_member(db)
    # system roles refuse deletion outright; a custom role in use → 409
    created = client.post("/api/v1/team/roles", json={
        "name": "Custom", "permissions": ["inbox.view"],
    })
    custom_id = created.json()["id"]
    assert client.patch(
        f"/api/v1/team/members/{member.id}", json={"role_id": custom_id},
    ).status_code == 200
    assert client.delete(f"/api/v1/team/roles/{custom_id}").status_code == 409


# ── context / gating ─────────────────────────────────────


@pytest.mark.asyncio
async def test_owner_context(client):
    body = client.get("/api/v1/team/context").json()
    assert body["is_owner"] is True
    assert body["role_name"] == "Owner"
    assert body["tenant_id"] == TENANT


@pytest.mark.asyncio
async def test_member_context_carries_role_permissions(client, db):
    member, mu = await _seed_member(db, role_name="Agent")
    _auth_as(mu)
    body = client.get("/api/v1/team/context").json()
    assert body["is_owner"] is False
    assert body["role_name"] == "Agent"
    assert "inbox.reply" in body["permissions"]
    assert "billing.manage" not in body["permissions"]


@pytest.mark.asyncio
async def test_viewer_cannot_manage(client, db):
    member, mu = await _seed_member(db, role_name="Viewer")
    _auth_as(mu)
    assert client.get("/api/v1/team/members").status_code == 200  # Viewer keeps team.view
    assert client.post("/api/v1/team/roles", json={
        "name": "X", "permissions": ["inbox.view"],
    }).status_code == 403
    assert client.post("/api/v1/team/invites", json={
        "email": "someone@x.com", "role_id": "r1",
    }).status_code == 403


@pytest.mark.asyncio
async def test_suspended_member_gets_403(client, db):
    member, mu = await _seed_member(db, status="active")
    member.status = "suspended"
    await db.commit()
    _auth_as(mu)
    res = client.get("/api/v1/team/context")
    assert res.status_code == 403
    assert "suspended" in res.json()["detail"].lower()


# ── TenantContext unit behavior ──────────────────────────


def _ctx(perms, overrides, is_owner=False):
    return TenantContext(
        user=None, tenant_id=TENANT,
        member=None if is_owner else object(), role=None,
        permissions=frozenset(perms), channel_overrides=overrides,
    )


def test_channel_level_precedence():
    owner = _ctx(set(), {}, is_owner=True)
    assert owner.channel_level("c1") == "edit"
    agent = _ctx({"channels.view"}, {})
    assert agent.channel_level("c1") == "view"  # role default
    editor = _ctx({"channels.edit"}, {})
    assert editor.channel_level("c1") == "edit"
    overridden = _ctx({"channels.edit"}, {"c1": "none"})
    assert overridden.channel_level("c1") == "none"  # deny beats role default
    assert overridden.can_edit_channel("c1") is False


def test_visible_channel_ids():
    assert _ctx(set(), {}, is_owner=True).visible_channel_ids() is None
    # role default viewers see everything
    assert _ctx({"channels.view"}, {"c1": "none"}).visible_channel_ids() is None
    # no role default → only explicitly granted channels
    restricted = _ctx(set(), {"c1": "view", "c2": "none", "c3": "edit"})
    assert restricted.visible_channel_ids() == {"c1", "c3"}


def test_validate_role_permissions_drops_unknown():
    assert validate_role_permissions(["inbox.view", "nope.x", ""]) == ["inbox.view"]


# ── invite lifecycle ─────────────────────────────────────


@pytest.mark.asyncio
async def test_invite_creates_member_and_emails(client, db, no_email):
    await _make_owner(db)
    roles = client.get("/api/v1/team/roles").json()["roles"]
    agent = next(r for r in roles if r["name"] == "Agent")

    res = client.post("/api/v1/team/invites", json={
        "email": "Sara@Acme.com", "role_id": agent["id"],
    })
    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "invited" and body["role_name"] == "Agent"

    assert len(no_email) == 1
    mail = no_email[0]
    assert mail["to"] == "sara@acme.com"
    assert mail["business"] == "Acme"
    assert mail["role"] == "Agent"
    assert "/invite/" in mail["url"]

    row = await service.get_member(db, TENANT, body["id"])
    assert row.invite_token_hash and row.invite_token_hash != mail["url"].rsplit("/", 1)[-1]
    assert row.status == "invited"


@pytest.mark.asyncio
async def test_invite_guards(client, db):
    await _make_owner(db)
    other = await _make_member_user(db, email="busy@elsewhere.com", tenant_id="other-tenant-1")
    roles = client.get("/api/v1/team/roles").json()["roles"]
    agent = next(r for r in roles if r["name"] == "Agent")

    # inviting the principal themself (conftest stub's email)
    res = client.post("/api/v1/team/invites", json={"email": "test@sayvors.com", "role_id": agent["id"]})
    assert res.status_code == 400
    # unknown role
    res = client.post("/api/v1/team/invites", json={"email": "x@y.com", "role_id": "nope"})
    assert res.status_code == 404
    # person already works elsewhere
    res = client.post("/api/v1/team/invites", json={"email": other.email, "role_id": agent["id"]})
    assert res.status_code == 409
    # re-inviting an active member
    member, _ = await _seed_member(db, status="active")
    res = client.post("/api/v1/team/invites", json={"email": member.email, "role_id": agent["id"]})
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_accept_new_user(client, db, no_email, monkeypatch):
    import app.modules.team.router as team_router
    monkeypatch.setattr(team_router, "store_session", _noop_store_session)

    await _make_owner(db)
    roles = client.get("/api/v1/team/roles").json()["roles"]
    agent = next(r for r in roles if r["name"] == "Agent")
    client.post("/api/v1/team/invites", json={"email": "new@acme.com", "role_id": agent["id"]})
    token = no_email[0]["url"].rsplit("/", 1)[-1]

    # preview works without auth
    preview = client.get(f"/api/v1/team/invites/preview?token={token}").json()
    assert preview["email"] == "new@acme.com"
    assert preview["account_exists"] is False
    assert preview["business_name"] == "Acme"

    # password required
    res = client.post("/api/v1/team/invites/accept", json={"token": token})
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "password_required"

    res = client.post("/api/v1/team/invites/accept", json={
        "token": token, "password": "s3cret-pass", "first_name": "New", "last_name": "Hire",
    })
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "joined" and body["access_token"]

    created = (await db.execute(_user_by_email("new@acme.com"))).scalar_one()
    assert created.tenant_id == TENANT
    assert created.email_verified is True
    from app.security import verify_password
    assert verify_password("s3cret-pass", created.password_hash)

    member = (await db.execute(_member_by_email("new@acme.com"))).scalar_one()
    assert member.status == "active"
    assert member.user_id == created.id
    assert member.invite_token_hash is None  # single-use

    # token cannot be reused
    res = client.post("/api/v1/team/invites/accept", json={
        "token": token, "password": "s3cret-pass",
    })
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_accept_existing_email_requires_login(client, db, no_email, monkeypatch):
    import app.modules.team.router as team_router

    await _make_owner(db)
    existing = await _make_member_user(db, email="old@acme.com")  # tenant_id None
    roles = client.get("/api/v1/team/roles").json()["roles"]
    agent = next(r for r in roles if r["name"] == "Agent")
    client.post("/api/v1/team/invites", json={"email": existing.email, "role_id": agent["id"]})
    token = no_email[0]["url"].rsplit("/", 1)[-1]

    # anonymous accept must NOT graft the existing account
    res = client.post("/api/v1/team/invites/accept", json={"token": token})
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "login_required"
    await db.refresh(existing)
    assert existing.tenant_id is None  # untouched

    # wrong session: bearer auth as a DIFFERENT account
    other = await _make_member_user(db, email="other@acme.com", tenant_id="t2")

    async def _fake_token_auth(t, d):
        # load from the REQUEST's session, exactly like the real
        # get_current_user_token does — a test-session instance would make
        # tenant_id mutations invisible to the endpoint's flush.
        if t == "tok-other":
            return await d.get(User, other.id)
        if t == "tok-existing":
            return await d.get(User, existing.id)
        raise HTTPException(status_code=401)

    monkeypatch.setattr(team_router, "get_current_user_token", _fake_token_auth)
    client.headers["Authorization"] = "Bearer tok-other"
    res = client.post("/api/v1/team/invites/accept", json={"token": token})
    assert res.status_code == 403

    # the real user authenticates and joins
    client.headers["Authorization"] = "Bearer tok-existing"
    res = client.post("/api/v1/team/invites/accept", json={"token": token})
    assert res.status_code == 200
    db.expire_all()
    await db.refresh(existing)
    assert existing.tenant_id == TENANT
    member = (await db.execute(_member_by_email(existing.email))).scalar_one()
    assert member.status == "active" and member.user_id == existing.id
    del client.headers["Authorization"]


@pytest.mark.asyncio
async def test_expired_and_invalid_tokens(client, db, no_email):
    from datetime import datetime, timedelta, timezone

    await _make_owner(db)
    roles = client.get("/api/v1/team/roles").json()["roles"]
    agent = next(r for r in roles if r["name"] == "Agent")
    client.post("/api/v1/team/invites", json={"email": "exp@acme.com", "role_id": agent["id"]})
    token = no_email[0]["url"].rsplit("/", 1)[-1]

    res = client.post("/api/v1/team/invites/accept", json={"token": "garbage-token-value"})
    assert res.status_code == 404

    member = (await db.execute(_member_by_email("exp@acme.com"))).scalar_one()
    member.invite_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await db.commit()
    res = client.post("/api/v1/team/invites/accept", json={
        "token": token, "password": "s3cret-pass",
    })
    assert res.status_code == 410


@pytest.mark.asyncio
async def test_resend_rotates_token(client, db, no_email, monkeypatch):
    import app.modules.team.router as team_router
    monkeypatch.setattr(team_router, "store_session", _noop_store_session)

    member, mu = await _seed_member(db, status="invited")
    old_hash = member.invite_token_hash
    res = client.post(f"/api/v1/team/invites/{member.id}/resend")
    assert res.status_code == 200
    await db.refresh(member)
    assert member.invite_token_hash != old_hash
    assert len(no_email) == 1


@pytest.mark.asyncio
async def test_revoke_pending_invite(client, db, no_email):
    member, _ = await _seed_member(db, status="invited")
    assert client.delete(f"/api/v1/team/invites/{member.id}").status_code == 204
    assert await service.get_member(db, TENANT, member.id) is None


# ── membership management ────────────────────────────────


@pytest.mark.asyncio
async def test_member_channel_overrides_roundtrip(client, db, channel_id):
    member, mu = await _seed_member(db, overrides={CHANNEL: "edit", "ch-ghost": "none"})
    rows = await service.list_member_overrides(db, member.id)
    assert rows == {CHANNEL: "edit"}  # unknown channels dropped

    await service.set_member_channels(db, member, {CHANNEL: "view"}, tenant_id=TENANT)
    rows = await service.list_member_overrides(db, member.id)
    assert rows == {CHANNEL: "view"}


@pytest.mark.asyncio
async def test_remove_member_resets_tenant(client, db, channel_id):
    member, mu = await _seed_member(db, overrides={CHANNEL: "view"})
    assert mu.tenant_id == TENANT
    res = client.delete(f"/api/v1/team/members/{member.id}")
    assert res.status_code == 204
    await db.refresh(mu)
    assert mu.tenant_id is None
    assert await service.get_member(db, TENANT, member.id) is None
    assert await service.list_member_overrides(db, member.id) == {}


@pytest.mark.asyncio
async def test_cannot_modify_or_remove_own_membership(client, db):
    member, mu = await _seed_member(db)
    # owner grants the member a managing role (custom role with team.manage)
    created = client.post("/api/v1/team/roles", json={
        "name": "Manager", "permissions": ["team.manage", "team.view"],
    })
    assert created.status_code == 201
    assert client.patch(
        f"/api/v1/team/members/{member.id}", json={"role_id": created.json()["id"]},
    ).status_code == 200

    _auth_as(mu)
    res = client.patch(f"/api/v1/team/members/{member.id}", json={"status": "suspended"})
    assert res.status_code == 400
    res = client.delete(f"/api/v1/team/members/{member.id}")
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_suspend_and_reactivate(client, db):
    member, mu = await _seed_member(db)
    res = client.patch(f"/api/v1/team/members/{member.id}", json={"status": "suspended"})
    assert res.status_code == 200
    _auth_as(mu)
    assert client.get("/api/v1/team/context").status_code == 403
    _auth_owner()
    res = client.patch(f"/api/v1/team/members/{member.id}", json={"status": "active"})
    assert res.status_code == 200
    _auth_as(mu)
    assert client.get("/api/v1/team/context").status_code == 200


@pytest.mark.asyncio
async def test_members_listing_shape(client, db, channel_id):
    member, mu = await _seed_member(db, overrides={CHANNEL: "edit"})
    body = client.get("/api/v1/team/members").json()
    entries = {e["email"]: e for e in body["members"]}
    owner_entry = entries["owner@acme.com"]
    assert owner_entry["is_owner"] is True and owner_entry["role_name"] == "Owner"
    sara = entries["sara@acme.com"]
    assert sara["status"] == "active"
    assert sara["role_name"] == "Agent"
    assert sara["channels"] == {CHANNEL: "edit"}


@pytest.mark.asyncio
async def test_other_tenant_scoped_everywhere(client, db):
    member, mu = await _seed_member(db)
    # a principal of a DIFFERENT workspace gets 403 from get_context —
    # never a leaky 404 that reveals which ids exist.
    foreign = await _make_member_user(db, email="foreign@x.com", tenant_id="t-foreign")
    _auth_as(foreign)
    assert client.delete(f"/api/v1/team/members/{member.id}").status_code == 403
    assert client.delete(f"/api/v1/team/roles/{member.role_id}").status_code == 403

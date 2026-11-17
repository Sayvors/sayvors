"""Enterprise request emails: admin recipient config + the sales notification.

Two layers are covered because they fail differently:

* the admin endpoints own validation, normalization, duplicates and the cap;
* the notification path owns the outbox hand-off, idempotency keys and the
  guarantee that one bad address cannot suppress the others.

Email is never sent for real: ``send_notification_email`` is replaced with a
capturing stub, so these tests exercise the call contract, not Resend.
"""
import pytest

import app.modules.admin.models  # noqa: F401 (registers tables)

from app.config import settings
from app.modules.admin.enterprise_recipients import (
    MAX_RECIPIENTS,
    RecipientError,
    add_recipient,
    list_recipients,
    recipient_emails,
    remove_recipient,
)
from app.modules.admin.models import EnterpriseRequestRecipient
from app.modules.billing.models import BillingRequest, Plan
from app.modules.billing.plan_notifications import notify_enterprise_request
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

TEST_ADMIN_HASH = "$2b$04$JYhUM7dKG7CjHsWtPoyNvuHgI.uZcJoMA8JruWs3DhtQxc2susyAy"
_HOST = {"host": "localhost"}


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    async def _allow(*args, **kwargs):
        return True

    monkeypatch.setattr("app.modules.auth.rate_limit.rate_limit", _allow)


@pytest.fixture
def admin_headers(client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_PASSWORD_HASH", TEST_ADMIN_HASH)
    login = client.post(
        "/api/v1/admin/login",
        json={"username": "admin", "password": "test-admin-pass"},
        headers=_HOST,
    )
    assert login.status_code == 200
    return {**_HOST, "X-Requested-With": "XMLHttpRequest"}


async def _enterprise_plan(db) -> Plan:
    plan = Plan(
        id="plan-enterprise-recipients-test",
        slug="enterprise",
        name="Enterprise",
        max_messages_per_month=None,
        max_channels=None,
        features={"messaging": True},
        is_active=True,
        sort_order=3,
    )
    db.add(plan)
    await db.commit()
    return plan


async def _tenant(db, tenant_id: str) -> User:
    user = User(
        id=tenant_id,
        email="owner@acme.example",
        first_name="Jane",
        last_name="Doe",
        business_name="Acme Coffee",
        phone="+1 555 0100",
        password_hash="x",
    )
    db.add(user)
    await db.commit()
    return user


async def _request(db, tenant_id: str) -> BillingRequest:
    from app.modules.billing.requests import create_request

    await _enterprise_plan(db)
    request, duplicate = await create_request(
        db,
        tenant_id=tenant_id,
        created_by=tenant_id,
        kind="plan",
        plan_slug="enterprise",
        note="We have 40 locations.",
    )
    assert duplicate is False
    return request


def _capture(monkeypatch):
    calls: list[dict] = []

    async def fake(
        email: str,
        subject: str,
        message: str,
        cta_url: str | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> str:
        calls.append({
            "email": email,
            "subject": subject,
            "message": message,
            "cta_url": cta_url,
            "idempotency_key": idempotency_key,
        })
        return "outbox-id"

    monkeypatch.setattr("app.modules.email.service.send_notification_email", fake)
    return calls


# ---------------------------------------------------------------------------
# Admin configuration
# ---------------------------------------------------------------------------

async def test_recipient_list_roundtrip(client, admin_headers):
    listed = client.get("/api/v1/admin/billing/enterprise-recipients", headers=admin_headers)
    assert listed.status_code == 200
    assert listed.json() == {"items": [], "max_recipients": MAX_RECIPIENTS}

    created = client.post(
        "/api/v1/admin/billing/enterprise-recipients",
        json={"email": " Sales@Example.com "},
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    row = created.json()
    assert row["email"] == "sales@example.com"
    assert row["created_by"] == "admin"

    listed = client.get("/api/v1/admin/billing/enterprise-recipients", headers=admin_headers)
    assert [item["email"] for item in listed.json()["items"]] == ["sales@example.com"]

    removed = client.delete(
        f"/api/v1/admin/billing/enterprise-recipients/{row['id']}", headers=admin_headers
    )
    assert removed.status_code == 204

    listed = client.get("/api/v1/admin/billing/enterprise-recipients", headers=admin_headers)
    assert listed.json()["items"] == []


async def test_recipient_rejects_invalid_email(client, admin_headers):
    response = client.post(
        "/api/v1/admin/billing/enterprise-recipients",
        json={"email": "not-an-email"},
        headers=admin_headers,
    )
    assert response.status_code == 400
    assert "valid email" in response.json()["detail"].lower()


async def test_recipient_rejects_duplicate_case_insensitively(client, admin_headers):
    first = client.post(
        "/api/v1/admin/billing/enterprise-recipients",
        json={"email": "Sales@Example.com"},
        headers=admin_headers,
    )
    assert first.status_code == 201

    duplicate = client.post(
        "/api/v1/admin/billing/enterprise-recipients",
        json={"email": "sales@example.com"},
        headers=admin_headers,
    )
    assert duplicate.status_code == 400
    assert "already" in duplicate.json()["detail"].lower()

    listed = client.get("/api/v1/admin/billing/enterprise-recipients", headers=admin_headers)
    assert len(listed.json()["items"]) == 1


async def test_recipient_cap_is_enforced(client, db, admin_headers):
    db.add_all([
        EnterpriseRequestRecipient(email=f"sales{i}@example.com")
        for i in range(MAX_RECIPIENTS)
    ])
    await db.commit()

    response = client.post(
        "/api/v1/admin/billing/enterprise-recipients",
        json={"email": "one-too-many@example.com"},
        headers=admin_headers,
    )
    assert response.status_code == 400
    assert "limited" in response.json()["detail"].lower()


async def test_removing_unknown_recipient_is_404(client, admin_headers):
    response = client.delete(
        "/api/v1/admin/billing/enterprise-recipients/does-not-exist",
        headers=admin_headers,
    )
    assert response.status_code == 404


async def test_recipient_endpoints_require_admin(client):
    assert client.get("/api/v1/admin/billing/enterprise-recipients").status_code == 401


async def test_service_layers_normalize_and_cap(db):
    row = await add_recipient(db, email="Ops@Agency.Example", operator="operator-a")
    assert row.email == "ops@agency.example"
    assert [item.email for item in await list_recipients(db)] == ["ops@agency.example"]

    # Read-side bound: even if a race or manual insert exceeded the cap, one
    # request can only ever mail MAX_RECIPIENTS addresses.
    db.add_all([
        EnterpriseRequestRecipient(email=f"extra{i}@example.com")
        for i in range(MAX_RECIPIENTS)
    ])
    await db.commit()
    assert len(await recipient_emails(db)) == MAX_RECIPIENTS

    with pytest.raises(RecipientError):
        await add_recipient(db, email="another@example.com", operator="operator-a")

    assert await remove_recipient(db, row.id) is True
    assert await remove_recipient(db, row.id) is False


# ---------------------------------------------------------------------------
# Notification
# ---------------------------------------------------------------------------

async def test_enterprise_request_emails_every_recipient(db, user_id, monkeypatch):
    tenant = await _tenant(db, user_id)
    request = await _request(db, user_id)
    await add_recipient(db, email="sales@agency.example", operator="operator-a")
    await add_recipient(db, email="founder@agency.example", operator="operator-a")
    calls = _capture(monkeypatch)

    queued = await notify_enterprise_request(db, request=request, requested_by=tenant)

    assert queued == 2
    assert [call["email"] for call in calls] == [
        "sales@agency.example",
        "founder@agency.example",
    ]
    first = calls[0]
    assert first["subject"] == "Enterprise plan request: Acme Coffee"
    assert "owner@acme.example" in first["message"]
    assert "+1 555 0100" in first["message"]
    assert "We have 40 locations." in first["message"]
    assert request.id in first["message"]
    assert first["cta_url"] == f"{settings.ADMIN_CONSOLE_URL.rstrip('/')}/requests"
    assert first["idempotency_key"] == f"enterprise-request:{request.id}:sales@agency.example"


async def test_employee_request_names_the_owner_and_the_submitter(db, user_id, monkeypatch):
    """Sales must see the billing contact, plus who actually clicked."""
    await _tenant(db, user_id)
    staff = User(
        id="employee-0000-0000-0000-000000000001",
        email="staff@acme.example",
        first_name="Sam",
        last_name="Staff",
        tenant_id=user_id,
        password_hash="x",
    )
    db.add(staff)
    await db.commit()
    request = await _request(db, user_id)
    await add_recipient(db, email="sales@agency.example", operator="operator-a")
    calls = _capture(monkeypatch)

    await notify_enterprise_request(db, request=request, requested_by=staff)

    body = calls[0]["message"]
    assert "owner@acme.example" in body
    assert "Acme Coffee" in body
    assert "Requested by: staff@acme.example" in body


async def test_no_recipients_is_logged_but_not_fatal(db, user_id, monkeypatch, caplog):
    tenant = await _tenant(db, user_id)
    request = await _request(db, user_id)
    calls = _capture(monkeypatch)

    queued = await notify_enterprise_request(db, request=request, requested_by=tenant)

    assert queued == 0
    assert calls == []
    assert any(
        "no notification recipients" in record.message.lower()
        for record in caplog.records
    )


async def test_one_failing_address_does_not_stop_the_rest(db, user_id, monkeypatch):
    tenant = await _tenant(db, user_id)
    request = await _request(db, user_id)
    await add_recipient(db, email="broken@agency.example", operator="operator-a")
    await add_recipient(db, email="sales@agency.example", operator="operator-a")
    calls = _capture(monkeypatch)

    async def flaky(
        email: str,
        subject: str,
        message: str,
        cta_url: str | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> str:
        if email == "broken@agency.example":
            raise RuntimeError("provider rejected the address")
        calls.append({"email": email, "idempotency_key": idempotency_key})
        return "outbox-id"

    monkeypatch.setattr("app.modules.email.service.send_notification_email", flaky)

    queued = await notify_enterprise_request(db, request=request, requested_by=tenant)

    assert queued == 1
    assert [call["email"] for call in calls] == ["sales@agency.example"]


async def test_enterprise_request_endpoint_triggers_notification(
    client, db, user_id, monkeypatch
):
    """The wired path: a tenant POST creates the request and queues emails."""
    await _tenant(db, user_id)
    await _enterprise_plan(db)
    await add_recipient(db, email="sales@agency.example", operator="operator-a")
    calls = _capture(monkeypatch)

    response = client.post(
        "/api/v1/billing/requests",
        json={"kind": "plan", "plan_slug": "enterprise", "note": "40 locations"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["duplicate"] is False
    assert body["plan_slug"] == "enterprise"
    assert [call["email"] for call in calls] == ["sales@agency.example"]
    # The workspace owner is the billing contact, resolved from the request's
    # tenant id rather than the authenticated principal.
    assert "owner@acme.example" in calls[0]["message"]

    # A duplicate submission must not mail the sales list again.
    again = client.post(
        "/api/v1/billing/requests",
        json={"kind": "plan", "plan_slug": "enterprise", "note": "40 locations"},
    )
    assert again.status_code == 200
    assert again.json()["duplicate"] is True
    assert len(calls) == 1


async def test_non_enterprise_plan_request_does_not_email(
    client, db, user_id, monkeypatch
):
    await _tenant(db, user_id)
    await _enterprise_plan(db)
    await add_recipient(db, email="sales@agency.example", operator="operator-a")
    calls = _capture(monkeypatch)

    # `pro` is not seeded by this module but is seeded by conftest.
    response = client.post(
        "/api/v1/billing/requests",
        json={"kind": "plan", "plan_slug": "pro"},
    )
    assert response.status_code == 200, response.text
    assert calls == []

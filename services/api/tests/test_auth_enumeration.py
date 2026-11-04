"""Signup and verification must not reveal whether an email is registered."""
import pytest
from sqlalchemy import select

from app.modules.users.models import User

SIGNUP_URL = "/api/v1/auth/signup"
SIGNUP_BODY = {
    "first_name": "Test",
    "last_name": "User",
    "email": "enumeration@sayvors.com",
    "password": "Password123!",
    "newsletter": False,
}


@pytest.fixture
def allow_rate_limit(monkeypatch):
    import importlib

    router_module = importlib.import_module("app.modules.auth.router")

    async def _allow(key, max_requests, window_seconds):
        return True

    monkeypatch.setattr(router_module, "rate_limit", _allow)


@pytest.fixture
def email_spies(monkeypatch):
    calls = {"otp": [], "exists": []}

    async def _otp(email, purpose="verification"):
        calls["otp"].append((email, purpose))

    async def _exists(email, name):
        calls["exists"].append((email, name))

    monkeypatch.setattr("app.modules.email.service.send_otp_email", _otp)
    monkeypatch.setattr("app.modules.email.service.send_account_exists_email", _exists)
    return calls


@pytest.mark.asyncio
async def test_signup_is_identical_for_new_and_existing_email(
    client, db, allow_rate_limit, email_spies
):
    first = client.post(SIGNUP_URL, json=SIGNUP_BODY)
    assert first.status_code == 201, first.text
    assert first.json() == {"message": "Check your email to continue."}
    assert not any(
        "refresh_token=" in c for c in first.headers.get_list("set-cookie")
    )
    assert not any("access_token=" in c for c in first.headers.get_list("set-cookie"))

    user = (
        await db.execute(select(User).where(User.email == SIGNUP_BODY["email"]))
    ).scalar_one()
    assert user.plan == "free-trial"
    assert user.ai_credit_cents == 1000

    from app.modules.billing.models import BillingEvent, TenantSubscription

    sub = (
        await db.execute(
            select(TenantSubscription).where(TenantSubscription.tenant_id == user.id)
        )
    ).scalar_one()
    assert sub.status == "active"
    trial_events = (
        await db.execute(
            select(BillingEvent).where(
                BillingEvent.tenant_id == user.id,
                BillingEvent.idempotency_key == f"trial:{user.id}",
            )
        )
    ).scalars().all()
    assert len(trial_events) == 1
    assert trial_events[0].amount_cents == 1000

    user.email_verified = True
    await db.commit()

    second = client.post(SIGNUP_URL, json=SIGNUP_BODY)
    assert second.status_code == 201, second.text
    assert second.json() == first.json()

    rows = (
        await db.execute(select(User).where(User.email == SIGNUP_BODY["email"]))
    ).scalars().all()
    assert len(rows) == 1
    assert email_spies["otp"] == [(SIGNUP_BODY["email"], "signup")]
    assert email_spies["exists"] == [
        (SIGNUP_BODY["email"], SIGNUP_BODY["first_name"])
    ]


@pytest.mark.asyncio
async def test_duplicate_unverified_signup_sends_otp_and_creates_no_second_user(
    client, db, allow_rate_limit, email_spies
):
    first = client.post(SIGNUP_URL, json=SIGNUP_BODY)
    second = client.post(SIGNUP_URL, json=SIGNUP_BODY)

    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    rows = (
        await db.execute(select(User).where(User.email == SIGNUP_BODY["email"]))
    ).scalars().all()
    assert len(rows) == 1
    assert email_spies["otp"] == [
        (SIGNUP_BODY["email"], "signup"),
        (SIGNUP_BODY["email"], "signup"),
    ]
    assert email_spies["exists"] == []


@pytest.mark.asyncio
async def test_verify_email_uses_one_generic_error(client):
    resp = client.post(
        "/api/v1/auth/verify-email",
        json={"token": "definitely-not-a-valid-token"},
    )
    assert resp.status_code == 400
    assert resp.json() == {
        "detail": "Invalid or expired verification token."
    }

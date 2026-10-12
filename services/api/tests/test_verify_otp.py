"""Regression tests for the signup OTP endpoint (SEC-C1).

``verify_signup_otp`` used to skip OTP validation whenever the account was
already ``email_verified``, so anyone who knew a verified user's email could
mint a full session with an arbitrary code — an account-takeover bypass.
These tests pin the corrected behavior: the endpoint only ever signs in an
account it has just verified; verified accounts are refused.
"""
import pytest
from sqlalchemy import select

from app.modules.users.models import User

VERIFY_URL = "/api/v1/auth/verify-otp"


async def _seed_user(db, *, email: str, verified: bool) -> User:
    user = User(
        email=email,
        first_name="Test",
        last_name="User",
        password_hash="x",
        email_verified=verified,
        onboarded=True,
    )
    db.add(user)
    await db.commit()
    return user


@pytest.fixture
def allow_rate_limit(monkeypatch):
    """The router's rate_limit uses Redis ZSETs; tests run without one."""
    import importlib

    # NOTE: "app.modules.auth.router" as a string resolves to the APIRouter
    # object (the package re-exports it), so import the module explicitly.
    router_module = importlib.import_module("app.modules.auth.router")

    async def _allow(key, max_requests, window_seconds):
        return True

    monkeypatch.setattr(router_module, "rate_limit", _allow)


@pytest.mark.asyncio
async def test_verified_user_cannot_mint_session_with_any_code(client, db, allow_rate_limit):
    """The takeover path: verified account + arbitrary code → no session, ever."""

    await _seed_user(db, email="verified@sayvors.com", verified=True)

    resp = client.post(VERIFY_URL, json={"email": "verified@sayvors.com", "code": "000000"})

    assert resp.status_code == 400
    body = resp.json()
    assert "access_token" not in body
    # No session may be established via cookies either.
    assert not any("refresh_token=" in c for c in resp.headers.get_list("set-cookie"))
    # The message routes the legit user to password sign-in.
    assert "already verified" in body["detail"].lower()


@pytest.mark.asyncio
async def test_verified_user_rejects_even_a_plausible_code(client, db, allow_rate_limit):
    """Same bypass, realistic code — the guard is on account state, not the code."""

    await _seed_user(db, email="verified2@sayvors.com", verified=True)

    resp = client.post(VERIFY_URL, json={"email": "verified2@sayvors.com", "code": "123456"})

    assert resp.status_code == 400
    assert "access_token" not in resp.json()


@pytest.mark.asyncio
async def test_unverified_user_wrong_code_rejected(client, db, allow_rate_limit, monkeypatch):
    """Unverified accounts must still present the right code (unchanged behavior)."""

    await _seed_user(db, email="pending@sayvors.com", verified=False)

    async def _wrong_code(email, code):
        return False

    monkeypatch.setattr("app.modules.email.service.verify_otp", _wrong_code)

    resp = client.post(VERIFY_URL, json={"email": "pending@sayvors.com", "code": "999999"})

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid or expired code."


@pytest.mark.asyncio
async def test_unverified_user_correct_code_signs_in(client, db, allow_rate_limit, monkeypatch):
    """The legitimate signup flow: right code → verified in DB + session returned."""

    user = await _seed_user(db, email="newbie@sayvors.com", verified=False)

    async def _right_code(email, code):
        return True

    async def _no_welcome(email, name):
        return None

    monkeypatch.setattr("app.modules.email.service.verify_otp", _right_code)
    monkeypatch.setattr("app.modules.email.service.send_welcome_email", _no_welcome)

    resp = client.post(VERIFY_URL, json={"email": "newbie@sayvors.com", "code": "424242"})

    assert resp.status_code == 200
    body = resp.json()
    assert body.get("access_token")
    assert body["user"]["email"] == "newbie@sayvors.com"
    assert any("refresh_token=" in c for c in resp.headers.get_list("set-cookie"))
    # The account flipped to verified exactly once, in the DB.
    db.expire_all()
    reloaded = (
        await db.execute(select(User).where(User.email == "newbie@sayvors.com"))
    ).scalar_one()
    assert reloaded.id == user.id
    assert reloaded.email_verified is True

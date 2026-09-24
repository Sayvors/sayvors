"""Google sign-in: token verification, find-or-create service, verify endpoint."""
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.security import verify_google_id_token
from app.modules.users.models import User

GOOD_CLAIMS = {
    "sub": "google-sub-001",
    "email": "guser@sayvors.com",
    "email_verified": True,
    "name": "G User",
    "picture": "https://img.example/p.png",
}


def test_verify_accepts_good_claims():
    with patch(
        "app.security.verify_oauth2_token", return_value=dict(GOOD_CLAIMS)
    ) as mock_v:
        claims = verify_google_id_token("tok")
    assert claims["sub"] == "google-sub-001"
    mock_v.assert_called_once()
    # audience must be our client id
    assert mock_v.call_args.kwargs.get("audience") is not None


def test_verify_rejects_invalid_token():
    with patch("app.security.verify_oauth2_token", side_effect=ValueError("bad")):
        with pytest.raises(ValueError, match="invalid_token"):
            verify_google_id_token("tok")


def test_verify_rejects_unverified_email():
    claims = dict(GOOD_CLAIMS, email_verified=False)
    with patch("app.security.verify_oauth2_token", return_value=claims):
        with pytest.raises(ValueError, match="unverified_email"):
            verify_google_id_token("tok")


def test_verify_rejects_missing_sub():
    claims = dict(GOOD_CLAIMS)
    del claims["sub"]
    with patch("app.security.verify_oauth2_token", return_value=claims):
        with pytest.raises(ValueError, match="unverified_email"):
            verify_google_id_token("tok")


async def test_google_signup_creates_user(db):
    from app.modules.auth.service import google_login
    from app.security import verify_password

    with patch("app.modules.auth.service.log_signup", new_callable=AsyncMock) as mock_ev:
        result = await google_login(dict(GOOD_CLAIMS), db, "UA-Test", "1.2.3.4")

    assert "access_token" in result and "refresh_token" in result
    u = await db.get(User, result["user"]["id"])
    assert u.google_sub == "google-sub-001"
    assert u.email_verified is True
    assert u.onboarded is False
    assert u.avatar_url == "https://img.example/p.png"
    assert (u.first_name, u.last_name) == ("G", "User")
    assert verify_password("anypassword1", u.password_hash) is False
    mock_ev.assert_awaited_once()
    assert mock_ev.call_args.kwargs.get("metadata") == {"via": "google"}


async def test_google_links_existing_password_account(db, user_id):
    from app.modules.auth.service import google_login
    from app.security import hash_password, verify_password

    db.add(User(id=user_id, email="guser@sayvors.com", first_name="Old",
                last_name="Name", password_hash=hash_password("Secret123!"),
                onboarded=True))
    await db.commit()

    with patch("app.modules.auth.service.log_login", new_callable=AsyncMock) as mock_ev:
        result = await google_login(dict(GOOD_CLAIMS), db, "UA", "1.2.3.4")

    assert result["user"]["id"] == user_id          # same account, not a new one
    u = await db.get(User, user_id)
    assert u.google_sub == "google-sub-001"         # linked
    assert verify_password("Secret123!", u.password_hash) is True  # password intact
    mock_ev.assert_awaited_once()


async def test_google_signin_refreshes_profile_snapshot(db):
    from app.modules.auth.service import google_login

    db.add(User(email="guser@sayvors.com", first_name="Old", last_name="Name",
                password_hash="x", email_verified=True, onboarded=True,
                google_sub="google-sub-001"))
    await db.commit()

    claims = dict(GOOD_CLAIMS, name="Fresh Name")
    with patch("app.modules.auth.service.log_login", new_callable=AsyncMock) as mock_ev:
        result = await google_login(claims, db, "UA", "1.2.3.4")

    u = await db.get(User, result["user"]["id"])
    assert (u.first_name, u.last_name) == ("Fresh", "Name")
    assert result["user"]["onboarded"] is True
    mock_ev.assert_awaited_once()


async def test_verify_endpoint_success(client, db, user_id):
    with (
        patch("app.modules.auth.router.rate_limit", new_callable=AsyncMock, return_value=True),
        patch("app.modules.auth.router.verify_google_id_token", return_value=dict(GOOD_CLAIMS)),
        patch("app.modules.auth.service.log_signup", new_callable=AsyncMock),
    ):
        resp = client.post(
            "/api/v1/auth/google/verify",
            json={"id_token": "test-id-token-abc123"},
            headers={"User-Agent": "UA"},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" not in data          # refresh travels as httpOnly cookie
    assert set(data["user"]) == {
        "id", "first_name", "last_name", "email", "email_verified", "onboarded",
    }
    assert data["user"]["email"] == "guser@sayvors.com"
    u = await db.get(User, data["user"]["id"])
    assert u.google_sub == "google-sub-001"


async def test_google_signup_sends_welcome_email(db):
    from app.modules.auth.service import google_login

    with (
        patch("app.modules.auth.service.log_signup", new_callable=AsyncMock),
        patch("app.modules.auth.service.send_welcome_email", new_callable=AsyncMock) as mock_mail,
    ):
        await google_login(dict(GOOD_CLAIMS), db, "UA", "1.2.3.4")
    mock_mail.assert_awaited_once()


async def test_verify_endpoint_401_on_invalid_token(client):
    with (
        patch("app.modules.auth.router.rate_limit", new_callable=AsyncMock, return_value=True),
        patch("app.modules.auth.router.verify_google_id_token",
              side_effect=ValueError("invalid_token")),
    ):
        resp = client.post("/api/v1/auth/google/verify", json={"id_token": "test-id-token-bad"})
    assert resp.status_code == 401
    assert "Google sign-in failed" in resp.json()["detail"]


async def test_verify_endpoint_400_on_unverified_email(client):
    with (
        patch("app.modules.auth.router.rate_limit", new_callable=AsyncMock, return_value=True),
        patch("app.modules.auth.router.verify_google_id_token",
              side_effect=ValueError("unverified_email")),
    ):
        resp = client.post("/api/v1/auth/google/verify", json={"id_token": "test-id-token-abc123"})
    assert resp.status_code == 400


async def test_verify_endpoint_503_without_config(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "")
    with patch("app.modules.auth.router.rate_limit",
               new_callable=AsyncMock, return_value=True):
        resp = client.post("/api/v1/auth/google/verify", json={"id_token": "test-id-token-abc123"})
    assert resp.status_code == 503
    assert "GOOGLE_CLIENT_ID" in resp.json()["detail"]

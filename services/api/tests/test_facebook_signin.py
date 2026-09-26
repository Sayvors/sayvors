"""Tests for Continue with Facebook (token verify, service, endpoint, config)."""
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from app.security import verify_facebook_token


def test_login_app_fallback(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "META_APP_ID", "app1")
    monkeypatch.setattr(settings, "META_APP_SECRET", "sec1")
    monkeypatch.setattr(settings, "META_LOGIN_APP_ID", "")
    monkeypatch.setattr(settings, "META_LOGIN_APP_SECRET", "")
    assert settings.facebook_login_app_id == "app1"
    assert settings.facebook_login_app_secret == "sec1"
    monkeypatch.setattr(settings, "META_LOGIN_APP_ID", "app2")
    monkeypatch.setattr(settings, "META_LOGIN_APP_SECRET", "sec2")
    assert settings.facebook_login_app_id == "app2"
    assert settings.facebook_login_app_secret == "sec2"


FB_ME = {"id": "fb-123", "name": "Ada Lovelace", "email": "ada@example.com",
         "picture": {"data": {"url": "https://pic/x.jpg"}}}


def _resp(payload):
    m = Mock()
    m.json.return_value = payload
    return m


def _app(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "META_APP_ID", "app1")
    monkeypatch.setattr(settings, "META_APP_SECRET", "sec1")
    monkeypatch.setattr(settings, "META_LOGIN_APP_ID", "")
    monkeypatch.setattr(settings, "META_LOGIN_APP_SECRET", "")


def test_facebook_verify_ok(monkeypatch):
    _app(monkeypatch)
    with patch("app.security.httpx.get", side_effect=[
        _resp({"data": {"is_valid": True, "app_id": "app1"}}),
        _resp(dict(FB_ME)),
    ]) as mock_get:
        profile = verify_facebook_token("user-token")
    assert profile == {"id": "fb-123", "email": "ada@example.com",
                       "name": "Ada Lovelace", "picture": "https://pic/x.jpg"}
    assert mock_get.call_count == 2


def test_facebook_verify_wrong_app(monkeypatch):
    _app(monkeypatch)
    with patch("app.security.httpx.get",
               return_value=_resp({"data": {"is_valid": True, "app_id": "OTHER"}})):
        with pytest.raises(ValueError, match="invalid_token"):
            verify_facebook_token("tok")


def test_facebook_verify_invalid(monkeypatch):
    _app(monkeypatch)
    with patch("app.security.httpx.get",
               return_value=_resp({"data": {"is_valid": False}})):
        with pytest.raises(ValueError, match="invalid_token"):
            verify_facebook_token("tok")


def test_facebook_verify_missing_email(monkeypatch):
    _app(monkeypatch)
    me = dict(FB_ME)
    del me["email"]
    with patch("app.security.httpx.get", side_effect=[
        _resp({"data": {"is_valid": True, "app_id": "app1"}}),
        _resp(me),
    ]):
        with pytest.raises(ValueError, match="unverified_email"):
            verify_facebook_token("tok")


def test_facebook_verify_network_error(monkeypatch):
    _app(monkeypatch)
    with patch("app.security.httpx.get", side_effect=httpx.ConnectError("down")):
        with pytest.raises(ValueError, match="invalid_token"):
            verify_facebook_token("tok")


FB_PROFILE = {"id": "fb-123", "email": "fbuser@sayvors.com",
              "name": "FB User", "picture": "https://pic/fb.jpg"}


async def test_facebook_signup_creates_user(db):
    from app.modules.auth.service import facebook_login
    from app.modules.users.models import User

    with (
        patch("app.modules.auth.service.log_signup", new_callable=AsyncMock) as mock_ev,
        patch("app.modules.auth.service.send_welcome_email", new_callable=AsyncMock) as mock_mail,
    ):
        result = await facebook_login(dict(FB_PROFILE), db, "UA", "1.2.3.4")

    assert result["user"]["email"] == "fbuser@sayvors.com"
    assert result["user"]["onboarded"] is False
    assert result["user"]["email_verified"] is True
    assert "access_token" in result and "refresh_token" in result
    u = await db.get(User, result["user"]["id"])
    assert u.facebook_id == "fb-123"
    assert u.avatar_url == "https://pic/fb.jpg"
    assert u.google_sub is None
    mock_ev.assert_awaited_once()
    mock_mail.assert_awaited_once()


async def test_facebook_links_existing_password_account(db):
    from app.modules.auth.service import facebook_login
    from app.modules.auth.service import hash_password
    from app.modules.users.models import User

    existing = User(first_name="FB", last_name="User", email=FB_PROFILE["email"],
                    password_hash=hash_password("secret123"), email_verified=True,
                    onboarded=True)
    db.add(existing)
    await db.commit()
    pw_hash = existing.password_hash

    with (
        patch("app.modules.auth.service.log_login", new_callable=AsyncMock),
        patch("app.modules.auth.service.send_welcome_email", new_callable=AsyncMock) as mock_mail,
    ):
        result = await facebook_login(dict(FB_PROFILE), db, "UA", "1.2.3.4")

    assert result["user"]["id"] == existing.id
    after = await db.get(User, existing.id)
    assert after.facebook_id == "fb-123"
    assert after.password_hash == pw_hash          # password login still works
    mock_mail.assert_not_awaited()                 # link = login, not signup


async def test_fb_verify_endpoint_success(client, db, user_id):
    from app.modules.users.models import User

    with (
        patch("app.modules.auth.router.rate_limit", new_callable=AsyncMock, return_value=True),
        patch("app.modules.auth.router.verify_facebook_token", return_value=dict(FB_PROFILE)),
        patch("app.modules.auth.service.log_signup", new_callable=AsyncMock),
    ):
        resp = client.post(
            "/api/v1/auth/facebook/verify",
            json={"access_token": "test-fb-token-abc123"},
            headers={"User-Agent": "UA"},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" not in data          # refresh travels as httpOnly cookie
    assert set(data["user"]) == {
        "id", "first_name", "last_name", "email", "email_verified", "onboarded",
    }
    u = await db.get(User, data["user"]["id"])
    assert u.facebook_id == "fb-123"


async def test_fb_verify_endpoint_401_on_invalid_token(client):
    with (
        patch("app.modules.auth.router.rate_limit", new_callable=AsyncMock, return_value=True),
        patch("app.modules.auth.router.verify_facebook_token",
              side_effect=ValueError("invalid_token")),
    ):
        resp = client.post("/api/v1/auth/facebook/verify",
                           json={"access_token": "test-fb-token-abc123"})
    assert resp.status_code == 401
    assert "Facebook sign-in failed" in resp.json()["detail"]


async def test_fb_verify_endpoint_400_on_missing_email(client):
    with (
        patch("app.modules.auth.router.rate_limit", new_callable=AsyncMock, return_value=True),
        patch("app.modules.auth.router.verify_facebook_token",
              side_effect=ValueError("unverified_email")),
    ):
        resp = client.post("/api/v1/auth/facebook/verify",
                           json={"access_token": "test-fb-token-abc123"})
    assert resp.status_code == 400


async def test_fb_verify_endpoint_503_without_config(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "META_LOGIN_APP_ID", "")
    monkeypatch.setattr(settings, "META_APP_ID", "")
    with patch("app.modules.auth.router.rate_limit",
               new_callable=AsyncMock, return_value=True):
        resp = client.post("/api/v1/auth/facebook/verify",
                           json={"access_token": "test-fb-token-abc123"})
    assert resp.status_code == 503
    assert "META_LOGIN_APP_ID" in resp.json()["detail"]

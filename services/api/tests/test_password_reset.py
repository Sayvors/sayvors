"""Password reset: endpoint completes, rotates credentials, emails security details."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.modules.auth.models import PasswordReset
from app.modules.auth.service import _describe_device
from app.modules.users.models import User
from app.security import (
    create_password_reset_token,
    hash_password,
    hash_token,
    verify_password,
)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


@pytest_asyncio.fixture
async def reset_setup(db, user_id):
    user = User(
        id=user_id,
        email="reset@sayvors.com",
        first_name="Reset",
        last_name="Tester",
        password_hash=hash_password("OldPassword1!"),
        onboarded=True,
    )
    db.add(user)
    raw = create_password_reset_token(user_id)
    db.add(
        PasswordReset(
            user_id=user_id,
            token_hash=hash_token(raw),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
    )
    await db.commit()
    return user, raw


async def test_reset_password_sends_security_email(client, db, reset_setup, user_id):
    _user, token = reset_setup
    with (
        patch(
            "app.modules.email.service.send_email", new_callable=AsyncMock
        ) as mock_send,
        patch(
            "app.modules.auth.service._geo_lookup",
            new_callable=AsyncMock,
            return_value="Riyadh, Saudi Arabia",
        ) as mock_geo,
        patch(
            "app.modules.auth.service.log_password_reset", new_callable=AsyncMock
        ) as mock_event,
        patch(
            "app.modules.auth.router.rate_limit",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        resp = client.post(
            "/api/v1/auth/reset-password",
            json={"token": token, "password": "NewPassword2!"},
            headers={"User-Agent": UA},
        )

    assert resp.status_code == 200, resp.text

    # Credentials rotated and lockout cleared.
    await db.refresh(_user)
    assert verify_password("NewPassword2!", _user.password_hash)
    assert _user.token_version == 1
    assert _user.failed_login_attempts == 0

    # Auth event ledger got the request context.
    mock_event.assert_awaited_once()
    _args, kwargs = mock_event.call_args
    assert kwargs.get("ua") == UA
    assert kwargs.get("ip")  # "testclient" from TestClient's peer

    # Geo looked up once; security email fired once with the details.
    mock_geo.assert_awaited_once_with(kwargs.get("ip"))
    mock_send.assert_awaited_once()
    send_args = mock_send.call_args.args
    subject, html = send_args[1], send_args[2]
    assert "password was changed" in subject.lower()
    assert "Riyadh, Saudi Arabia" in html
    assert "Chrome on Windows (Desktop)" in html
    assert kwargs.get("ip") in html
    assert "UTC" in html


async def test_reset_password_invalid_token_no_email(client, reset_setup):
    _user, token = reset_setup
    with (
        patch(
            "app.modules.email.service.send_email", new_callable=AsyncMock
        ) as mock_send,
        patch(
            "app.modules.auth.router.rate_limit",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        resp = client.post(
            "/api/v1/auth/reset-password",
            json={"token": token[:-4] + "AAAA", "password": "Whatever123!"},
            headers={"User-Agent": UA},
        )
    assert resp.status_code == 400
    mock_send.assert_not_awaited()


def test_describe_device_variants():
    assert _describe_device("") == "Unknown device"
    assert _describe_device(UA) == "Chrome on Windows (Desktop)"

    iphone = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
        "Mobile/15E148 Safari/604.1"
    )
    d = _describe_device(iphone)
    assert "Safari" in d and "iOS" in d and "Mobile" in d

    android = (
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
    )
    d = _describe_device(android)
    assert d == "Chrome on Android (Mobile)"

    firefox_mac = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) "
        "Gecko/20100101 Firefox/121.0"
    )
    assert _describe_device(firefox_mac) == "Firefox on macOS (Desktop)"

    # Edge ships Chrome in its UA — must win over the Chrome probe.
    edge = UA + " Edg/120.0.0.0"
    assert _describe_device(edge) == "Edge on Windows (Desktop)"


async def test_geo_lookup_falls_back():
    from app.modules.auth.service import _geo_lookup

    assert await _geo_lookup("") == "Unknown location"
    assert await _geo_lookup("testclient") == "Unknown location"
    with patch("httpx.AsyncClient", side_effect=Exception("network down")):
        assert await _geo_lookup("8.8.8.8") == "Unknown location"

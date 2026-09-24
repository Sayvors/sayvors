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

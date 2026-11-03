"""P1-B2: production startup config must fail closed."""
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.config import Settings, settings, validate_production_settings
from app import database

_PROD = {
    "JWT_SECRET": "x" * 40,
    "CHANNEL_ENCRYPTION_KEY": "k" * 32,
    "ADMIN_PASSWORD_HASH": "$2b$12$" + "a" * 53,
    "ALLOWED_HOSTS": ["api.sayvors.com"],
    "CORS_ORIGINS": ["https://app.sayvors.com"],
    "CORS_ORIGIN_REGEX": None,
    "FRONTEND_URL": "https://app.sayvors.com",
    "GOOGLE_REVIEWS_REDIRECT_URI": "https://api.sayvors.com/api/v1/channels/google/callback",
    "META_OAUTH_REDIRECT_URI": "https://api.sayvors.com/api/v1/meta/facebook/callback",
    "EMAIL_SEND_ALLOW_ANY_RECIPIENT": False,
    "RAG_DB_ALLOW_PRIVATE_HOSTS": False,
}


def test_valid_production_config_passes(monkeypatch):
    for k, v in _PROD.items():
        monkeypatch.setattr(settings, k, v)
    validate_production_settings()  # must not raise/exit


@pytest.mark.parametrize("attr,value", [
    ("JWT_SECRET", "short"),
    ("CHANNEL_ENCRYPTION_KEY", ""),
    ("ADMIN_PASSWORD_HASH", ""),
    ("ALLOWED_HOSTS", ["*"]),
    ("ALLOWED_HOSTS", []),
    ("CORS_ORIGINS", ["http://localhost:3000"]),
    ("CORS_ORIGIN_REGEX", "http://localhost:3000"),
    ("FRONTEND_URL", "http://localhost:3000"),
    ("GOOGLE_REVIEWS_REDIRECT_URI", "http://localhost:8000/api/v1/channels/google/callback"),
    ("META_OAUTH_REDIRECT_URI", "http://localhost:8000/api/v1/meta/facebook/callback"),
    ("EMAIL_SEND_ALLOW_ANY_RECIPIENT", True),
    ("RAG_DB_ALLOW_PRIVATE_HOSTS", True),
])
def test_each_permissive_default_fails_closed(monkeypatch, attr, value):
    for k, v in _PROD.items():
        monkeypatch.setattr(settings, k, v)
    monkeypatch.setattr(settings, attr, value)
    with pytest.raises(SystemExit) as exc:
        validate_production_settings()
    assert exc.value.code == 1


def test_db_pool_mode_is_normalized_and_validated():
    assert Settings(DB_POOL_MODE=" TRANSACTION ").DB_POOL_MODE == "transaction"

    with pytest.raises(ValidationError):
        Settings(DB_POOL_MODE="bogus")


def test_transaction_db_pool_mode_disables_asyncpg_statement_cache(monkeypatch):
    monkeypatch.setattr(settings, "DB_POOL_MODE", "transaction")
    args = database._connection_args(
        "postgresql+asyncpg://user:pass@db:6432/sayvors?ssl=require"
    )
    assert args["statement_cache_size"] == 0

    monkeypatch.setattr(settings, "DB_POOL_MODE", "session")
    args = database._connection_args(
        "postgresql+asyncpg://user:pass@db:5432/sayvors?ssl=require"
    )
    assert "statement_cache_size" not in args

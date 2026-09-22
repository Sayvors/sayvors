"""P1-B2: production startup config must fail closed."""
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.config import settings, validate_production_settings

_PROD = {
    "JWT_SECRET": "x" * 40,
    "CHANNEL_ENCRYPTION_KEY": "k" * 32,
    "ADMIN_PASSWORD_HASH": "$2b$12$" + "a" * 53,
    "ALLOWED_HOSTS": ["api.sayvors.com"],
    "CORS_ORIGINS": ["https://app.sayvors.com"],
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

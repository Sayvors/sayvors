"""P1-D: per-tenant Localith API keys (Fernet at rest, env fallback).

- api_key_encrypted decrypts to the tenant key; empty rows fall back.
- The per-connection key is threaded into sync/detail/reply calls.
- The API stores ciphertext only; removal restores the shared-key fallback.
"""
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

from app.modules.localith import service
from app.modules.localith.models import LocalithConnection

_HOST = {"host": "localhost"}


def _conn(api_key_encrypted=None):
    return LocalithConnection(
        id="conn-key-1", user_id="u-key-1", listing_id="loc-1",
        listing_name="T", listing_google_id="g1",
        api_key_encrypted=api_key_encrypted,
    )


def test_connection_api_key_empty_falls_back():
    assert service._connection_api_key(_conn(None)) is None
    assert service._connection_api_key(_conn("")) is None


def test_connection_api_key_round_trip():
    from app.modules.channels.service import encrypt_token

    conn = _conn(encrypt_token("tenant-secret-key"))
    assert service._connection_api_key(conn) == "tenant-secret-key"


def test_connection_api_key_garbage_falls_back():
    assert service._connection_api_key(_conn("not-fernet")) is None


@pytest.mark.asyncio
async def test_per_connection_key_reaches_provider(monkeypatch):
    """The connection key (not env) is passed to the Localith API call."""
    from app.modules.channels.service import encrypt_token

    seen = {}

    async def _fake_to_thread(fn, *args, **kwargs):
        seen["fn"] = fn.__name__
        seen["args"] = args
        return {"ok": True}

    monkeypatch.setattr(service.asyncio, "to_thread", _fake_to_thread)
    monkeypatch.setattr(
        service, "_connection_api_key", lambda conn: "tenant-key-9"
    )
    # Skip the env-key gate: an explicit key must be sufficient on its own.
    monkeypatch.setattr(service, "_key_present", lambda: False)

    detail = await service.get_listing_detail("loc-1", api_key="tenant-key-9")
    assert detail == {"ok": True}
    assert seen["args"] == ("loc-1", "tenant-key-9")


@pytest.mark.asyncio
async def test_shared_key_gate_still_requires_env(monkeypatch):
    """No connection key + no env key → clear error (unchanged behavior)."""
    monkeypatch.setattr(service, "_key_present", lambda: False)
    with pytest.raises(RuntimeError):
        await service.list_local_listings()


@pytest.mark.asyncio
async def test_api_key_set_remove_round_trip(client, db, user_id):
    """PUT stores ciphertext on all owned rows; DELETE restores fallback."""
    from sqlalchemy import select as _select

    for listing in ("loc-1", "loc-2"):
        r = client.put(
            "/api/v1/integrations/localith/connection",
            json={"listing_id": listing, "listing_name": f"Shop {listing}"},
            headers=_HOST,
        )
        assert r.status_code == 200, r.text[:160]

    r = client.put(
        "/api/v1/integrations/localith/connection/api-key",
        json={"api_key": "tenant-secret-key"},
        headers=_HOST,
    )
    assert r.status_code == 200, r.text[:160]
    assert r.json()["has_api_key"] is True

    rows = (
        await db.execute(
            _select(LocalithConnection).where(LocalithConnection.user_id == user_id)
        )
    ).scalars().all()
    assert len(rows) == 2
    for row in rows:
        assert row.api_key_encrypted
        assert "tenant-secret-key" not in row.api_key_encrypted

    r = client.delete(
        "/api/v1/integrations/localith/connection/api-key", headers=_HOST
    )
    assert r.status_code == 200, r.text[:160]
    assert r.json()["has_api_key"] is False
    await db.refresh(rows[0])
    assert rows[0].api_key_encrypted is None


@pytest.mark.asyncio
async def test_api_key_requires_connection(client):
    r = client.put(
        "/api/v1/integrations/localith/connection/api-key",
        json={"api_key": "tenant-secret-key"},
        headers=_HOST,
    )
    assert r.status_code == 400

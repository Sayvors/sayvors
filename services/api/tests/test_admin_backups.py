"""Admin console backup endpoints: config, run, list, delete, download.

S3 is never touched: ``app.modules.admin.backup`` is monkeypatched so the
routes either run against an unconfigured bucket (graceful empty/400) or a
fake run function. No real pg_dump / network is invoked.
"""
import pytest

import app.modules.admin.models  # noqa: F401 (registers tables)

TEST_ADMIN_HASH = "$2b$04$JYhUM7dKG7CjHsWtPoyNvuHgI.uZcJoMA8JruWs3DhtQxc2susyAy"
_HOST = {"host": "localhost"}


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    async def _allow(*args, **kwargs):
        return True

    monkeypatch.setattr("app.modules.auth.rate_limit.rate_limit", _allow)


@pytest.fixture
def admin_csrf(client, monkeypatch):
    monkeypatch.setattr("app.config.settings.ADMIN_PASSWORD_HASH", TEST_ADMIN_HASH)
    login = client.post(
        "/api/v1/admin/login", json={"username": "admin", "password": "test-admin-pass"}, headers=_HOST
    )
    assert login.status_code == 200
    return {**_HOST, "X-Requested-With": "XMLHttpRequest"}


@pytest.mark.asyncio
async def test_backup_config_default(client, admin_csrf):
    r = client.get("/api/v1/admin/backups/config", headers=admin_csrf)
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    assert body["interval_hours"] == 24
    assert "region" in body


@pytest.mark.asyncio
async def test_backup_config_update_roundtrip(client, admin_csrf, db):
    from sqlalchemy import select

    from app.modules.admin.models import AdminBackupConfig

    r = client.put(
        "/api/v1/admin/backups/config",
        json={"enabled": True, "interval_hours": 7, "bucket": "test-bucket", "region": "eu-north-1"},
        headers=admin_csrf,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert body["interval_hours"] == 7
    assert body["bucket"] == "test-bucket"

    row = (await db.execute(select(AdminBackupConfig))).scalar_one_or_none()
    assert row is not None
    assert row.enabled is True
    assert row.interval_hours == 7
    assert row.next_run_at is not None

    r2 = client.get("/api/v1/admin/backups/config", headers=admin_csrf)
    assert r2.json()["interval_hours"] == 7


@pytest.mark.asyncio
async def test_backup_config_rejects_zero_interval(client, admin_csrf):
    r = client.put(
        "/api/v1/admin/backups/config",
        json={"enabled": True, "interval_hours": 0},
        headers=admin_csrf,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_backup_run_starts_background(client, admin_csrf, monkeypatch):
    calls = []

    async def _fake_run(trigger):
        calls.append(trigger)
        return {"id": "fake", "status": "success", "backup_key": None, "size_bytes": None}

    monkeypatch.setattr("app.modules.admin.backup.run_backup_standalone", _fake_run)
    r = client.post("/api/v1/admin/backups/run", headers=admin_csrf)
    assert r.status_code == 200
    assert r.json()["status"] == "running"
    assert calls == ["manual"]


@pytest.mark.asyncio
async def test_backup_list_empty_without_bucket(client, admin_csrf):
    r = client.get("/api/v1/admin/backups", headers=admin_csrf)
    assert r.status_code == 200
    body = r.json()
    assert "config" in body
    assert body["objects"] == []


@pytest.mark.asyncio
async def test_backup_delete_requires_bucket(client, admin_csrf):
    r = client.delete("/api/v1/admin/backups?key=backups/x.sql.gz", headers=admin_csrf)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_backup_download_requires_bucket(client, admin_csrf):
    r = client.get("/api/v1/admin/backups/download?key=backups/x.sql.gz", headers=admin_csrf)
    assert r.status_code == 400

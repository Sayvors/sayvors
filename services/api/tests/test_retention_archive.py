"""Retention archive: training-ready shape, PII handling, fail-closed deletes.

The archive exists because review-generation rows carry the tool-call
trajectory — the exact format a tool-using model would need. It must also
never put a reviewer's name into cold storage, and a failed upload must stop
the deletion rather than losing unarchived data.
"""
import gzip
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import app.modules.admin.models  # noqa: F401 (register the new tables)

from app.config import settings
from app.modules.admin.models import RetentionRun
from app.modules.retention_archive import archive_key, archive_rows, format_archive

pytestmark = pytest.mark.asyncio

TEST_ADMIN_HASH = "$2b$04$JYhUM7dKG7CjHsWtPoyNvuHgI.uZcJoMA8JruWs3DhtQxc2susyAy"
_HOST = {"host": "localhost"}


def _row(**overrides):
    base = dict(
        id="log-1", tenant_id="tenant-1", channel_id="chan-1",
        review_id="rvw-1", review_text="القهوة حلوة بس غالية", rating=4,
        reviewer_name="Sensitive Name", channel="google_reviews",
        analysis={"intent": "price"}, selected_strategies=["price_answer"],
        tool_calls=[{"name": "facts_lookup", "arguments": {"key": "price"}}],
        retrieved_offers=[{"sku": "A"}], generated_response="85 SAR",
        validation_result={"ok": True}, status="posted", model="test-model",
        token_input=12, token_output=8, latency_ms=900,
        created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_archive_keeps_tool_trajectory_and_drops_pii():
    data, count = format_archive("review_generation", [_row()])
    assert count == 1
    record = json.loads(gzip.decompress(data).decode("utf-8"))
    assert "Sensitive Name" not in json.dumps(record)  # direct PII gone
    assert record["review_text"] == "القهوة حلوة بس غالية"
    assert record["tool_calls"][0]["name"] == "facts_lookup"
    assert record["selected_strategies"] == ["price_answer"]
    assert record["retrieved_offers"] == [{"sku": "A"}]
    assert record["model"] == "test-model"


def test_archive_key_is_categorised():
    key = archive_key("review_generation", now=datetime(2026, 3, 4, tzinfo=timezone.utc))
    assert key.startswith("retention/review_generation/2026/03/")
    assert key.endswith(".jsonl.gz")


async def test_archive_rows_records_success(db):
    calls = []

    def _put(kind, key, data, content_type):
        calls.append((kind, key, data, content_type))

    run = await archive_rows(
        db, kind="review_generation", rows=[_row()],
        trigger="manual", s3_put=_put,
    )
    assert run.status == "success"
    assert calls[0][0] == "archive"
    assert (await db.get(RetentionRun, run.id)).status == "success"


async def test_failed_upload_marks_run_failed_and_raises(db):
    def _boom(*args, **kwargs):
        raise RuntimeError("S3 down")

    with pytest.raises(RuntimeError):
        await archive_rows(
            db, kind="review_generation", rows=[_row()],
            trigger="manual", s3_put=_boom,
        )
    failed = (
        await db.execute(
            __import__("sqlalchemy").select(RetentionRun).where(
                RetentionRun.status == "failed"
            )
        )
    ).scalars().all()
    assert len(failed) == 1


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    async def _allow(*args, **kwargs):
        return True

    monkeypatch.setattr("app.modules.auth.rate_limit.rate_limit", _allow)


@pytest.fixture
def admin_headers(client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_PASSWORD_HASH", TEST_ADMIN_HASH)
    login = client.post(
        "/api/v1/admin/login",
        json={"username": "admin", "password": "test-admin-pass"},
        headers=_HOST,
    )
    assert login.status_code == 200
    return {**_HOST, "X-Requested-With": "XMLHttpRequest"}


def test_admin_can_set_and_read_retention_policy(client, admin_headers):
    r = client.put(
        "/api/v1/admin/retention/config",
        json={
            "review_log_days": 120, "connect_event_days": 45,
            "backup_lead_days": 5, "archive_enabled": True,
        },
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    got = client.get("/api/v1/admin/retention/config", headers=admin_headers)
    assert got.json()["review_log_days"] == 120
    assert got.json()["backup_lead_days"] == 5
    assert got.json()["archive_enabled"] is True


def test_admin_rejects_out_of_range_day_values(client, admin_headers):
    r = client.put(
        "/api/v1/admin/retention/config",
        json={
            "review_log_days": 0, "connect_event_days": 30,
            "backup_lead_days": 2, "archive_enabled": False,
        },
        headers=admin_headers,
    )
    assert r.status_code == 422

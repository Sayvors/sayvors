"""Plan bulk-edit CSV gate (§34 item 11): the `bulk_edit_csv` feature key.

The CSV upload write path (POST /api/v1/locations/bulk-upload) is gated;
the read-only helpers (bulk-data, bulk-template) stay open.
"""
import sys
from pathlib import Path

import pytest
from sqlalchemy import select

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.billing.models import Plan

pytestmark = pytest.mark.asyncio


async def _set_free_trial_bulk_edit(db, enabled: bool) -> None:
    plan = (
        await db.execute(select(Plan).where(Plan.slug == "free-trial"))
    ).scalar_one()
    features = dict(plan.features or {})
    features["bulk_edit_csv"] = enabled
    plan.features = features
    await db.flush()


async def test_bulk_upload_denied_without_feature(client, db, monkeypatch):
    await _set_free_trial_bulk_edit(db, False)
    called = False

    async def should_not_run(*a, **k):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr("app.modules.locations.bulk.apply_bulk_csv", should_not_run)
    resp = client.post(
        "/api/v1/locations/bulk-upload",
        files={"file": ("locations.csv", b"name,city\nA,Riyadh\n", "text/csv")},
    )
    assert resp.status_code == 403
    assert resp.headers.get("X-Entitlement-Denied") == "bulk_edit_csv"
    assert called is False


async def test_bulk_upload_allowed_with_feature(client, db, monkeypatch):
    await _set_free_trial_bulk_edit(db, True)

    async def fake_apply(db, tenant_id, csv_text):
        return {"updated": 1, "errors": [], "created": 0}

    monkeypatch.setattr("app.modules.locations.bulk.apply_bulk_csv", fake_apply)
    resp = client.post(
        "/api/v1/locations/bulk-upload",
        files={"file": ("locations.csv", b"name,city\nA,Riyadh\n", "text/csv")},
    )
    assert resp.status_code == 200
    assert resp.json()["updated"] == 1


async def test_bulk_data_read_not_gated(client, db):
    """Template/export reads stay open without the feature."""
    await _set_free_trial_bulk_edit(db, False)
    resp = client.get("/api/v1/locations/bulk-template")
    assert resp.status_code == 200

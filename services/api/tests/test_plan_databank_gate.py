"""Plan databank gate (§34 item 6): the `databank` feature key.

All databank *write* paths (create/delete bank, upload/delete documents,
scrape, process, reindex, retry, save/delete sources, ingest) are gated.
Reads (list/get/search/ask/preview/schema) stay open per the billing docs:
read-only data is never hidden by a feature gate.
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


async def _set_free_trial_databank(db, enabled: bool) -> None:
    plan = (
        await db.execute(select(Plan).where(Plan.slug == "free-trial"))
    ).scalar_one()
    features = dict(plan.features or {})
    features["databank"] = enabled
    plan.features = features
    await db.flush()


async def test_create_databank_denied_without_feature(client, db, monkeypatch):
    await _set_free_trial_databank(db, False)
    called = False

    async def should_not_run(*a, **k):
        nonlocal called
        called = True
        return None

    monkeypatch.setattr("app.modules.rag.router.create_databank", should_not_run)
    resp = client.post("/api/v1/rag/databanks", json={"name": "My KB"})
    assert resp.status_code == 403
    assert resp.headers.get("X-Entitlement-Denied") == "databank"
    assert called is False


async def test_create_databank_allowed_with_feature(client, db, monkeypatch):
    await _set_free_trial_databank(db, True)
    from datetime import datetime, timezone
    from types import SimpleNamespace

    async def fake_create(body, user, db):
        return SimpleNamespace(
            id="bank-1", name=body.name, description=None, accent_color=None,
            created_at=datetime.now(timezone.utc),
        )

    monkeypatch.setattr("app.modules.rag.router.create_databank", fake_create)
    resp = client.post("/api/v1/rag/databanks", json={"name": "My KB"})
    assert resp.status_code == 201
    assert resp.json()["name"] == "My KB"


async def test_list_databanks_not_gated(client, db):
    """Reads stay open even without the feature."""
    await _set_free_trial_databank(db, False)
    resp = client.get("/api/v1/rag/databanks")
    assert resp.status_code == 200
    assert resp.json()["databanks"] == []

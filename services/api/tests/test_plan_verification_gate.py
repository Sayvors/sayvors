"""Plan verification gate (§34 item 8): the `verifications` feature key.

Verification *requests* (POST /channels/{id}/verification) and *completion*
(POST /channels/{id}/verification/complete) are gated; the read snapshot
(GET) stays open. Denial happens before any Google provider work.
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

CHANNEL = "test-channel-0000-0000-0000-000000000001"  # conftest channel_id fixture value


async def _set_free_trial_verifications(db, enabled: bool) -> None:
    plan = (
        await db.execute(select(Plan).where(Plan.slug == "free-trial"))
    ).scalar_one()
    features = dict(plan.features or {})
    features["verifications"] = enabled
    plan.features = features
    await db.flush()


class _FakeVerificationClient:
    """Minimal stand-in for the Google verification client."""

    def __init__(self, state: dict | None = None):
        self.verify_calls = 0
        self.state = state or {}

    async def get_voice_of_merchant_state(self, location_id):
        return self.state

    async def fetch_verification_options(self, location_id, language_code):
        return []

    async def list_verifications(self, location_id):
        return []

    async def verify_location(self, *a, **k):
        self.verify_calls += 1
        return {"state": "PENDING", "name": "accounts/a/locations/l/verifications/v1"}

    async def close(self):
        pass


async def test_request_verification_denied_without_feature(client, db, monkeypatch):
    await _set_free_trial_verifications(db, False)
    fake = _FakeVerificationClient()

    async def fake_client(channel, db):
        return fake, "loc-1"

    monkeypatch.setattr("app.modules.channels.router._verification_client", fake_client)
    resp = client.post(f"/api/v1/channels/{CHANNEL}/verification", json={"method": "SMS"})
    assert resp.status_code == 403
    assert resp.headers.get("X-Entitlement-Denied") == "verifications"
    assert fake.verify_calls == 0


async def test_request_verification_allowed_with_feature(client, db, channel_id, monkeypatch):
    await _set_free_trial_verifications(db, True)
    fake = _FakeVerificationClient()

    async def fake_client(channel, db):
        return fake, "loc-1"

    monkeypatch.setattr("app.modules.channels.router._verification_client", fake_client)
    resp = client.post(f"/api/v1/channels/{CHANNEL}/verification", json={"method": "SMS"})
    assert resp.status_code == 200
    assert fake.verify_calls == 1


async def test_complete_verification_denied_without_feature(client, db, monkeypatch):
    await _set_free_trial_verifications(db, False)
    fake = _FakeVerificationClient()

    async def fake_client(channel, db):
        return fake, "loc-1"

    monkeypatch.setattr("app.modules.channels.router._verification_client", fake_client)
    resp = client.post(f"/api/v1/channels/{CHANNEL}/verification/complete", json={"pin": "123456"})
    assert resp.status_code == 403
    assert resp.headers.get("X-Entitlement-Denied") == "verifications"


async def test_get_verification_not_gated(client, db, channel_id, monkeypatch):
    """The read snapshot stays open without the feature."""
    await _set_free_trial_verifications(db, False)
    fake = _FakeVerificationClient()

    async def fake_client(channel, db):
        return fake, "loc-1"

    monkeypatch.setattr("app.modules.channels.router._verification_client", fake_client)
    resp = client.get(f"/api/v1/channels/{CHANNEL}/verification")
    assert resp.status_code == 200

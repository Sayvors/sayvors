"""Job handlers must never act on another tenant's row.

`POST /jobs` accepts a caller-controlled payload. Even though the endpoint is
now permission-gated, a handler that resolves its subject by bare id would
still let a crafted payload re-drive another workspace's work - sending their
customer a review request from their number, or re-billing their STT/TTS job.
These tests pin the tenant filter in each handler.
"""
from types import SimpleNamespace

import pytest

from app.modules.analytics.models import ReviewRequest
from app.modules.jobs.handlers.review_request_send import (
    handle_review_request_send,
)
from app.modules.jobs.handlers.stt_job import handle_stt_job
from app.modules.jobs.handlers.tts_job import handle_tts_job
from app.modules.stt.models import STTJob
from app.modules.tts.models import TTSJob
from app.modules.users.models import User

async def _seed_users(db, user_id: str, other_user_id: str) -> None:
    db.add_all(
        [
            User(
                id=user_id,
                email="tenant-a@example.com",
                first_name="Tenant",
                last_name="A",
                password_hash="x",
            ),
            User(
                id=other_user_id,
                email="tenant-b@example.com",
                first_name="Tenant",
                last_name="B",
                password_hash="x",
            ),
        ]
    )
    await db.commit()


@pytest.mark.asyncio
async def test_review_request_handler_rejects_another_tenants_request(
    db, user_id, other_user_id
):
    await _seed_users(db, user_id, other_user_id)
    db.add(
        ReviewRequest(
            id="req-other-tenant",
            user_id=other_user_id,
            contact="+966500000001",
            channel="whatsapp",
            trigger="manual",
            status="queued",
        )
    )
    await db.commit()

    job = SimpleNamespace(
        tenant_id=user_id,
        payload={"request_id": "req-other-tenant"},
        subject_id=None,
    )
    result = await handle_review_request_send(job, db)

    assert result == {
        "skipped": "request not found",
        "request_id": "req-other-tenant",
    }
    row = await db.get(ReviewRequest, "req-other-tenant")
    assert row.status == "queued"


@pytest.mark.asyncio
async def test_stt_handler_rejects_another_tenants_job(db, user_id, other_user_id):
    await _seed_users(db, user_id, other_user_id)
    db.add(
        STTJob(
            id="stt-other-tenant",
            user_id=other_user_id,
            audio_url="https://example.com/a.ogg",
        )
    )
    await db.commit()

    job = SimpleNamespace(tenant_id=user_id, payload={"stt_job_id": "stt-other-tenant"})
    with pytest.raises(ValueError, match="not found"):
        await handle_stt_job(job, db)


def test_submit_endpoint_rejects_types_without_a_handler(client):
    response = client.post(
        "/api/v1/jobs",
        json={"job_type": "meta.send_reply", "payload": {}},
    )
    assert response.status_code == 400
    assert "cannot be submitted" in response.json()["detail"]


def test_submit_endpoint_rejects_non_object_payload(client):
    response = client.post(
        "/api/v1/jobs",
        json={"job_type": "review_request.send", "payload": ["not", "an", "object"]},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "payload must be an object"


@pytest.mark.asyncio
async def test_tts_handler_rejects_another_tenants_job(db, user_id, other_user_id):
    await _seed_users(db, user_id, other_user_id)
    db.add(
        TTSJob(
            id="tts-other-tenant",
            user_id=other_user_id,
            text="hello",
        )
    )
    await db.commit()

    job = SimpleNamespace(tenant_id=user_id, payload={"tts_job_id": "tts-other-tenant"})
    with pytest.raises(ValueError, match="not found"):
        await handle_tts_job(job, db)

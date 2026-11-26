"""Job handlers must never act on another tenant's row.

`POST /jobs` accepts a caller-controlled payload. Even though the endpoint is
now permission-gated, a handler that resolves its subject by bare id would
still let a crafted payload re-drive another workspace's work - sending their
customer a review request from their number, or re-billing their STT/TTS job.
These tests pin the tenant filter in each handler.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.modules.analytics.models import ReviewRequest
from app.modules.jobs.handlers.review_request_send import (
    handle_review_request_send,
)
from app.modules.jobs.handlers.stt_job import handle_stt_job
from app.modules.jobs.handlers.tts_job import handle_tts_job
from app.modules.jobs.models import Job
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


def test_submit_endpoint_rejects_internal_ai_visibility_jobs(client):
    response = client.post(
        "/api/v1/jobs",
        json={
            "job_type": "ai_visibility.research",
            "payload": {"run_id": "run-1"},
            "idempotency_key": "ai-visibility:run-1",
        },
    )
    assert response.status_code == 400
    assert "cannot be submitted" in response.json()["detail"]


@pytest.mark.asyncio
async def test_generic_job_routes_do_not_expose_ai_visibility_jobs(
    client, db, user_id
):
    db.add(
        Job(
            id="ai-visibility-job",
            tenant_id=user_id,
            job_type="ai_visibility.research",
            lane="bulk",
            status="queued",
            payload={"run_id": "run-1"},
            lane_key="ai-visibility:prompt-1",
        )
    )
    await db.commit()

    assert client.get("/api/v1/jobs/ai-visibility-job").status_code == 404
    listed = client.get("/api/v1/jobs")
    assert listed.status_code == 200
    assert listed.json() == []
    assert (
        client.post("/api/v1/jobs/ai-visibility-job/cancel").status_code == 404
    )


@pytest.mark.asyncio
async def test_generic_job_list_filters_internal_jobs_before_limit(
    client, db, user_id
):
    old = datetime.now(timezone.utc) - timedelta(minutes=5)
    db.add_all(
        [
            Job(
                id="visible-job",
                tenant_id=user_id,
                job_type="review_request.send",
                lane="bulk",
                status="queued",
                payload={},
                lane_key="visible",
                created_at=old,
            ),
            Job(
                id="internal-job",
                tenant_id=user_id,
                job_type="ai_visibility.research",
                lane="bulk",
                status="queued",
                payload={"run_id": "run-1"},
                lane_key="internal",
            ),
        ]
    )
    await db.commit()

    response = client.get("/api/v1/jobs?limit=1")
    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == ["visible-job"]


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

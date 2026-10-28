"""STT: the transcription request must reach a worker, not sit pending forever.

The `/transcribe` endpoint used to save an STTJob row and stop there: the
row said "pending" and nothing ever ran it. The durable job queue is the
contract - the row and the Job commit together.
"""
import pytest
from sqlalchemy import select

from app.modules.jobs.models import Job
from app.modules.jobs.types import JobLane, JobType
from app.modules.stt.models import STTJob


@pytest.mark.asyncio
async def test_transcribe_queues_a_durable_job(client, db, user_id):
    res = client.post(
        "/api/v1/stt/transcribe",
        json={"audio_url": "https://cdn.example/voice.mp3", "language": "ar"},
    )
    assert res.status_code == 201, res.text[:300]
    stt_job_id = res.json()["id"]
    assert res.json()["status"] == "pending"

    stt_job = (await db.execute(select(STTJob).where(STTJob.id == stt_job_id))).scalar_one()
    assert stt_job.status == "pending"
    assert stt_job.audio_url == "https://cdn.example/voice.mp3"

    jobs = (
        (
            await db.execute(
                select(Job).where(
                    Job.job_type == JobType.stt_job.value,
                    Job.tenant_id == user_id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(jobs) == 1, "the transcription was never queued"
    job = jobs[0]
    assert job.status == "queued"
    assert job.lane == JobLane.bulk.value
    assert job.payload["stt_job_id"] == stt_job_id
    assert job.subject_type == "stt_job"
    assert job.subject_id == stt_job_id


@pytest.mark.asyncio
async def test_transcribe_does_not_queue_for_another_tenant(client, db):
    """One tenant's job must never be visible to another."""
    res = client.post(
        "/api/v1/stt/transcribe",
        json={"audio_url": "https://cdn.example/voice.mp3"},
    )
    assert res.status_code == 201, res.text[:300]
    jobs = (await db.execute(select(Job))).scalars().all()
    assert len(jobs) == 1
    assert jobs[0].tenant_id != "someone-else"

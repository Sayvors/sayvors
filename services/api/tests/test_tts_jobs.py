"""TTS HTTP job path: enqueue, render, store, serve, fail.

The old handler marked every job completed without synthesizing anything.
These tests pin the real contract: /convert leaves a pending row plus a
durable unified Job, the handler renders through the capability and stores a
private artifact, and playback is ownership-checked.
"""
import pytest
from sqlalchemy import select

from app.modules.jobs.handlers import tts_job as tts_job_handler
from app.modules.jobs.models import Job
from app.modules.tts import router as tts_router
from app.modules.tts.api import AudioFormat, SynthesisResult
from app.modules.tts.models import TTSJob


def _synthesis_result(audio: bytes = b"ID3fake-mp3") -> SynthesisResult:
    return SynthesisResult(
        audio=audio,
        mime_type="audio/mpeg",
        format=AudioFormat.MP3,
        provider="edge",
        model="voice:edge:simple",
        voice="en-US-AriaNeural",
        latency_ms=42,
    )


async def _create_and_load(db, client, **overrides) -> tuple[str, Job]:
    payload = {"text": "Hello there", "language": "en", **overrides}
    response = client.post("/api/v1/tts/convert", json=payload)
    assert response.status_code == 201, response.text
    job_id = response.json()["id"]
    run = (
        await db.execute(select(Job).where(Job.subject_id == job_id))
    ).scalar_one()
    return job_id, run


@pytest.mark.asyncio
async def test_convert_enqueues_a_pending_tts_job(db, client):
    job_id, run = await _create_and_load(db, client, speed=1.25)

    tts_job = await db.get(TTSJob, job_id)
    assert tts_job is not None
    assert tts_job.status == "pending"
    assert tts_job.speed == 1.25
    assert tts_job.audio_url is None

    assert run.job_type == "tts.job"
    assert run.status == "queued"
    assert run.payload == {"tts_job_id": job_id}
    assert run.idempotency_key == f"tts:{job_id}"

    # Nothing has been rendered yet, so playback is a clean 404.
    audio = client.get(f"/api/v1/tts/jobs/{job_id}/audio")
    assert audio.status_code == 404


@pytest.mark.asyncio
async def test_handler_renders_stores_and_serves_audio(db, client, monkeypatch):
    job_id, run = await _create_and_load(db, client, speed=1.25)

    seen = {}

    async def fake_synthesize(request, *, db=None):
        seen["request"] = request
        return _synthesis_result()

    stored = {}

    def fake_put_doc(user_id, filename, data):
        stored[(user_id, filename)] = data
        return {"key": f"{user_id}/{filename}"}

    monkeypatch.setattr(tts_job_handler, "synthesize", fake_synthesize)
    monkeypatch.setattr(tts_job_handler, "put_doc", fake_put_doc)

    result = await tts_job_handler.handle_tts_job(run, db)
    assert result["status"] == "completed"

    request = seen["request"]
    assert request.text == "Hello there"
    assert request.speed == 1.25
    assert request.format == AudioFormat.MP3
    assert request.purpose == "tts.job"
    assert request.tenant_id == "test-user-0000-0000-0000-000000000001"

    tts_job = await db.get(TTSJob, job_id)
    await db.refresh(tts_job)
    expected_key = f"tts/{job_id}.mp3"
    assert tts_job.status == "completed"
    assert tts_job.storage_key == expected_key
    assert tts_job.audio_mime == "audio/mpeg"
    assert tts_job.audio_url == f"/api/v1/tts/jobs/{job_id}/audio"
    assert tts_job.error is None
    assert tts_job.completed_at is not None
    assert stored[("test-user-0000-0000-0000-000000000001", expected_key)] == b"ID3fake-mp3"

    monkeypatch.setattr(
        tts_router, "get_doc",
        lambda user_id, key: stored[(user_id, key)],
    )
    audio = client.get(f"/api/v1/tts/jobs/{job_id}/audio")
    assert audio.status_code == 200
    assert audio.content == b"ID3fake-mp3"
    assert audio.headers["content-type"] == "audio/mpeg"
    assert audio.headers["cache-control"].startswith("private")


@pytest.mark.asyncio
async def test_handler_marks_failure_when_no_audio_is_rendered(db, client, monkeypatch):
    job_id, run = await _create_and_load(db, client)

    async def no_audio(request, *, db=None):
        return None

    monkeypatch.setattr(tts_job_handler, "synthesize", no_audio)

    result = await tts_job_handler.handle_tts_job(run, db)
    assert result["status"] == "failed"

    tts_job = await db.get(TTSJob, job_id)
    await db.refresh(tts_job)
    assert tts_job.status == "failed"
    assert "engine" in tts_job.error.lower()
    assert tts_job.storage_key is None
    assert tts_job.completed_at is not None


@pytest.mark.asyncio
async def test_handler_is_idempotent_once_audio_exists(db, client, monkeypatch):
    job_id, run = await _create_and_load(db, client)
    tts_job = await db.get(TTSJob, job_id)
    tts_job.status = "completed"
    tts_job.storage_key = f"tts/{job_id}.mp3"
    tts_job.audio_url = f"/api/v1/tts/jobs/{job_id}/audio"
    await db.commit()

    async def must_not_run(request, *, db=None):
        raise AssertionError("a completed job must not synthesize again")

    monkeypatch.setattr(tts_job_handler, "synthesize", must_not_run)
    result = await tts_job_handler.handle_tts_job(run, db)
    assert result["status"] == "already_completed"


@pytest.mark.asyncio
async def test_storage_failure_is_recorded_and_raised_for_retry(db, client, monkeypatch):
    job_id, run = await _create_and_load(db, client)

    async def fake_synthesize(request, *, db=None):
        return _synthesis_result()

    def failing_put_doc(user_id, filename, data):
        raise OSError("storage unavailable")

    monkeypatch.setattr(tts_job_handler, "synthesize", fake_synthesize)
    monkeypatch.setattr(tts_job_handler, "put_doc", failing_put_doc)

    with pytest.raises(OSError):
        await tts_job_handler.handle_tts_job(run, db)

    tts_job = await db.get(TTSJob, job_id)
    await db.refresh(tts_job)
    assert tts_job.status == "failed"
    assert "storage unavailable" in tts_job.error
    assert tts_job.completed_at is not None


@pytest.mark.asyncio
async def test_audio_route_refuses_a_foreign_or_tampered_key(db, client, monkeypatch):
    job_id, _run = await _create_and_load(db, client)
    tts_job = await db.get(TTSJob, job_id)
    tts_job.status = "completed"
    # A corrupted row must not turn the route into an arbitrary docs reader.
    tts_job.storage_key = "profile/secret.pdf"
    tts_job.audio_mime = "application/pdf"
    await db.commit()

    called = []
    monkeypatch.setattr(
        tts_router, "get_doc",
        lambda user_id, key: called.append(key) or b"secret",
    )
    response = client.get(f"/api/v1/tts/jobs/{job_id}/audio")
    assert response.status_code == 404
    assert called == []

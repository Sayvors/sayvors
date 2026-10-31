"""Admin-managed ASR engines, mirroring the embeddings/LLM config surface.

The STT key is expected to carry only the speech-to-text permission, so the
test probe and the client both go through the same endpoint real audio uses.
"""
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.config import settings

TEST_ADMIN_HASH = "$2b$04$JYhUM7dKG7CjHsWtPoyNvuHgI.uZcJoMA8JruWs3DhtQxc2susyAy"
_HOST = {"host": "localhost"}


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    async def _allow(*args, **kwargs):
        return True

    monkeypatch.setattr("app.modules.auth.rate_limit.rate_limit", _allow)


@pytest.fixture
def admin_headers(client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_PASSWORD_HASH", TEST_ADMIN_HASH)
    r = client.post(
        "/api/v1/admin/login",
        json={"username": "admin", "password": "test-admin-pass"},
        headers=_HOST,
    )
    assert r.status_code == 200, r.text
    return {**_HOST, "X-Requested-With": "XMLHttpRequest"}


# ── admin config ─────────────────────────────────────────────────────


def test_overview_lists_both_providers(client, admin_headers):
    r = client.get("/api/v1/admin/asr", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    names = {p["provider"] for p in body["providers"]}
    assert names == {"elevenlabs", "faster_whisper"}
    assert body["active_provider"] is None
    eleven = next(p for p in body["providers"] if p["provider"] == "elevenlabs")
    assert eleven["default_model"] == "scribe_v1"
    assert eleven["needs_key"] is True


async def test_saving_a_key_is_encrypted_and_never_returned(client, db, admin_headers):
    r = client.put(
        "/api/v1/admin/asr/elevenlabs",
        headers=admin_headers,
        json={"model": "scribe_v1", "languages": "*", "enabled": True, "active": True,
              "api_key": "sk-eleven-secret"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["has_key"] is True
    assert body["active"] is True
    assert "sk-eleven-secret" not in r.text

    from sqlalchemy import select

    from app.core.crypto import decrypt_secret
    from app.modules.stt.models import ASREngineConfig

    row = (
        await db.execute(
            select(ASREngineConfig).where(ASREngineConfig.provider == "elevenlabs")
        )
    ).scalar_one()
    assert row.key_encrypted
    assert row.key_encrypted != "sk-eleven-secret", "the column must not hold plaintext"
    assert decrypt_secret(row.key_encrypted) == "sk-eleven-secret"

    listed = client.get("/api/v1/admin/asr", headers=admin_headers).json()
    eleven = next(p for p in listed["providers"] if p["provider"] == "elevenlabs")
    assert eleven["has_key"] is True


def test_activating_one_provider_deactivates_the_other(client, admin_headers):
    client.put(
        "/api/v1/admin/asr/elevenlabs",
        headers=admin_headers,
        json={"languages": "*", "enabled": True, "active": True, "api_key": "sk-x"},
    )
    r = client.put(
        "/api/v1/admin/asr/faster_whisper",
        headers=admin_headers,
        json={"languages": "*", "enabled": True, "active": True},
    )
    assert r.status_code == 200, r.text

    listed = client.get("/api/v1/admin/asr", headers=admin_headers).json()
    by_name = {p["provider"]: p for p in listed["providers"]}
    assert by_name["faster_whisper"]["active"] is True
    assert by_name["elevenlabs"]["active"] is False
    assert listed["active_provider"] == "faster_whisper"


def test_activating_a_keyed_provider_without_a_key_is_rejected(client, admin_headers):
    r = client.put(
        "/api/v1/admin/asr/elevenlabs",
        headers=admin_headers,
        json={"languages": "*", "enabled": True, "active": True},
    )
    assert r.status_code == 400
    assert "API key" in r.json()["detail"]


def test_empty_key_clears_the_stored_one(client, admin_headers):
    client.put(
        "/api/v1/admin/asr/elevenlabs",
        headers=admin_headers,
        json={"languages": "*", "enabled": True, "active": False, "api_key": "sk-clear-me"},
    )
    r = client.put(
        "/api/v1/admin/asr/elevenlabs",
        headers=admin_headers,
        json={"languages": "*", "enabled": True, "active": False, "api_key": ""},
    )
    assert r.status_code == 200, r.text
    assert r.json()["has_key"] is False


def test_unknown_provider_is_a_404(client, admin_headers):
    r = client.put(
        "/api/v1/admin/asr/whisper_cloud",
        headers=admin_headers,
        json={"languages": "*", "enabled": True, "active": False},
    )
    assert r.status_code == 404


def test_test_endpoint_uses_the_stored_key(client, admin_headers, monkeypatch):
    client.put(
        "/api/v1/admin/asr/elevenlabs",
        headers=admin_headers,
        json={"languages": "*", "enabled": True, "active": True, "api_key": "sk-test"},
    )

    calls: dict = {}

    async def _fake(**kwargs):
        calls.update(kwargs)
        return {"text": "", "language": "en", "confidence": None,
                "duration_ms": 1000, "segments": []}

    monkeypatch.setattr("app.modules.stt.admin_router.transcribe_elevenlabs", _fake)

    r = client.post("/api/v1/admin/asr/elevenlabs/test", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert calls["api_key"] == "sk-test"
    assert calls["audio"][:4] == b"RIFF", "the probe is real audio, not a fake payload"


# ── provider client ──────────────────────────────────────────────────


def test_elevenlabs_payload_maps_onto_the_local_shape():
    from app.modules.stt.providers import normalize_elevenlabs

    out = normalize_elevenlabs({
        "text": "hello there",
        "language_code": "eng",
        "language_probability": 0.97,
        "words": [
            {"text": "hello", "start": 0.0, "end": 0.4, "type": "word", "logprob": -0.1},
            {"text": " ", "start": 0.4, "end": 0.4, "type": "spacing", "logprob": None},
            {"text": "there", "start": 0.4, "end": 0.9, "type": "word", "logprob": -0.2},
        ],
    })
    assert out["text"] == "hello there"
    assert out["language"] == "en", "ISO-639-3 is normalised to our ISO-639-1 codes"
    assert out["duration_ms"] == 900
    assert out["confidence"] == pytest.approx(0.8618, abs=1e-3)
    assert len(out["segments"]) == 2


def test_elevenlabs_confidence_is_none_without_words():
    from app.modules.stt.providers import normalize_elevenlabs

    out = normalize_elevenlabs({"text": "", "language_code": "urd"})
    assert out["confidence"] is None
    assert out["language"] == "ur"


@pytest.mark.asyncio
async def test_transcribe_audio_prefers_the_active_engine(monkeypatch):
    from app.modules.stt import provider

    config = {
        "provider": "elevenlabs", "api_key": "sk-live", "model": "scribe_v1",
        "base_url": None, "languages": "*", "enabled": True, "active": True,
    }

    async def _active(db, language):
        return config

    async def _download(url):
        return b"RIFFfake", ".ogg", "audio/ogg"

    seen: dict = {}

    async def _hosted(cfg, url, language, model):
        seen.update({"provider": cfg["provider"], "language": language})
        return {"text": "transcribed", "language": language or "en",
                "confidence": 0.9, "duration_ms": 100, "segments": []}

    monkeypatch.setattr(provider, "_active_hosted_engine", _active)
    monkeypatch.setattr(provider, "_download_audio_bytes", _download)
    monkeypatch.setattr(provider, "_transcribe_hosted", _hosted)

    result = await provider.transcribe_audio("https://media.example/a.ogg", language="ar")

    assert result["text"] == "transcribed"
    assert seen == {"provider": "elevenlabs", "language": "ar"}


@pytest.mark.asyncio
async def test_no_active_engine_means_local_whisper(db, monkeypatch):
    from app.modules.stt import config as asr_config

    async def _none(db=None):
        return None

    monkeypatch.setattr(asr_config, "get_active_asr_config", _none)
    from app.modules.stt import provider

    assert await provider._active_hosted_engine(None, "en") is None


@pytest.mark.asyncio
async def test_language_outside_the_engine_coverage_falls_back(db, monkeypatch):
    from app.modules.stt import config as asr_config
    from app.modules.stt import provider

    async def _arabic_only(db=None):
        return {
            "provider": "elevenlabs", "api_key": "sk", "model": "scribe_v1",
            "base_url": None, "languages": "ar", "enabled": True, "active": True,
        }

    monkeypatch.setattr(asr_config, "get_active_asr_config", _arabic_only)

    assert await provider._active_hosted_engine(None, "en") is None
    assert (await provider._active_hosted_engine(None, "ar"))["provider"] == "elevenlabs"

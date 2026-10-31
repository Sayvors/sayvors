"""Admin surface for speech-to-text engines.

Mounted by the admin router so it inherits admin auth + rate limiting, and
so the STT capability never imports the admin package (one-way dependency).

Key values are never returned: the response only says whether one is set.
"""

from __future__ import annotations

import io
import time
import wave

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_db
from .config import KEEP, get_asr_config, list_asr_configs, save_asr_config
from .providers import ASR_PROVIDERS, PROVIDER_META, transcribe_elevenlabs

router = APIRouter(prefix="/asr", tags=["admin"])


class ASRProviderStatus(BaseModel):
    provider: str
    label: str
    model: str | None = None
    base_url: str | None = None
    languages: str = "*"
    enabled: bool = False
    active: bool = False
    has_key: bool = False
    updated_at: str | None = None
    # Catalogue hints for the admin form.
    needs_key: bool = False
    default_model: str | None = None
    models: list[str] = []
    note: str | None = None
    docs: str | None = None


class ASROverview(BaseModel):
    providers: list[ASRProviderStatus]
    active_provider: str | None = None


class ASRConfigIn(BaseModel):
    model: str | None = Field(None, max_length=80)
    base_url: str | None = Field(None, max_length=300)
    languages: str = Field("*", max_length=200)
    enabled: bool = True
    active: bool = False
    # Omitted / null = keep the stored key; "" clears it.
    api_key: str | None = Field(None, max_length=500)


class ASRTestResult(BaseModel):
    ok: bool
    latency_ms: int
    detail: str


def _status(provider: str, row: dict | None) -> ASRProviderStatus:
    meta = PROVIDER_META.get(provider, {})
    row = row or {}
    return ASRProviderStatus(
        provider=provider,
        label=meta.get("label", provider),
        model=row.get("model") or meta.get("default_model"),
        base_url=row.get("base_url"),
        languages=row.get("languages") or "*",
        enabled=bool(row.get("enabled", False)),
        active=bool(row.get("active", False)),
        has_key=bool(row.get("has_key", False)),
        updated_at=row.get("updated_at"),
        needs_key=bool(meta.get("needs_key")),
        default_model=meta.get("default_model"),
        models=list(meta.get("models") or []),
        note=meta.get("note"),
        docs=meta.get("docs"),
    )


@router.get("", response_model=ASROverview)
async def admin_asr_overview(db: AsyncSession = Depends(get_db)):
    """Every known provider plus which one is serving transcription."""
    rows = {r["provider"]: r for r in await list_asr_configs(db)}
    providers = [_status(name, rows.get(name)) for name in ASR_PROVIDERS]
    active = next((p.provider for p in providers if p.active and p.enabled), None)
    return ASROverview(providers=providers, active_provider=active)


@router.put("/{provider}", response_model=ASRProviderStatus)
async def admin_asr_save(
    provider: str,
    body: ASRConfigIn,
    db: AsyncSession = Depends(get_db),
):
    """Create or update one provider.

    Activating a provider deactivates the others in the same transaction, so
    "exactly one active engine" cannot drift. A non-null api_key rotates the
    stored key (encrypted); an empty string clears it; null keeps it.
    """
    if provider not in ASR_PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown ASR provider {provider!r}")
    if PROVIDER_META.get(provider, {}).get("needs_key") and body.active:
        existing = {r["provider"]: r for r in await list_asr_configs(db)}.get(provider)
        if not body.api_key and not (existing or {}).get("has_key"):
            raise HTTPException(
                status_code=400,
                detail="Add an API key before activating this provider.",
            )
    try:
        saved = await save_asr_config(
            db,
            provider,
            model=body.model,
            base_url=body.base_url,
            languages=body.languages,
            enabled=body.enabled,
            active=body.active,
            api_key=body.api_key if body.api_key is not None else KEEP,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _status(provider, saved)


def _silent_probe_wav() -> bytes:
    """One second of a quiet tone, in memory.

    The STT key only carries the speech-to-text permission, so the probe has
    to go through the same endpoint real audio uses. A silent file would also
    work, but some APIs reject zero-signal audio; a low tone is unambiguously
    valid and transcribes to nothing.
    """
    import math
    import struct

    rate = 16000
    frames = bytearray()
    for i in range(rate):
        value = int(2000 * math.sin(2 * math.pi * 220 * i / rate))
        frames += struct.pack("<h", value)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(bytes(frames))
    return buffer.getvalue()


@router.post("/{provider}/test", response_model=ASRTestResult)
async def admin_asr_test(provider: str, db: AsyncSession = Depends(get_db)):
    """Probe this provider with real audio through the real endpoint.

    Uses the exact API key stored for the provider, so a permission problem
    (or an expired key) shows up here, before a customer's voice note does.
    """
    if provider not in ASR_PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown ASR provider {provider!r}")
    row = {r["provider"]: r for r in await list_asr_configs(db)}.get(provider) or {}
    if not row.get("has_key"):
        return ASRTestResult(ok=False, latency_ms=0, detail="No API key stored for this provider.")
    if provider == "faster_whisper":
        return ASRTestResult(ok=True, latency_ms=0, detail="Local engine — no key or network needed.")

    internal = await get_asr_config(provider, db)
    if not internal or not internal.get("api_key"):
        return ASRTestResult(ok=False, latency_ms=0, detail="Stored key could not be decrypted.")

    started = time.perf_counter()
    try:
        result = await transcribe_elevenlabs(
            api_key=internal["api_key"],
            audio=_silent_probe_wav(),
            filename="probe.wav",
            content_type="audio/wav",
            model=internal.get("model"),
            base_url=internal.get("base_url"),
            timeout_seconds=45.0,
        )
    except Exception as e:  # noqa: BLE001 - reported, not raised
        detail = f"{type(e).__name__}: {str(e)[:200]}"
        response = getattr(e, "response", None)
        if response is not None:
            detail = f"HTTP {response.status_code}: {response.text[:200]}"
        return ASRTestResult(
            ok=False,
            latency_ms=int((time.perf_counter() - started) * 1000),
            detail=detail,
        )
    latency = int((time.perf_counter() - started) * 1000)
    return ASRTestResult(
        ok=True,
        latency_ms=latency,
        detail=(
            f"Accepted the audio · model={internal.get('model') or 'default'} · "
            f"detected={result.get('language') or 'unknown'}"
        ),
    )

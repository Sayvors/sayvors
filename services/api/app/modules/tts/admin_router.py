"""Admin surface for TTS engine configuration.

The admin router mounts this router behind its own auth and rate-limit
dependencies, so the TTS capability never imports the admin package —
the dependency stays one-way: ``admin → tts``.

Tenants only ever see a tier ("simple" / "advanced"), never the provider
or key. Keys are stored Fernet-encrypted and NEVER returned; the response
only says whether one is set.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.crypto import decrypt_secret, encrypt_secret
from ...core.deps import get_db
from .models import VoiceModelConfig

router = APIRouter(prefix="/voice-engines", tags=["admin"])


class VoiceEngineStatus(BaseModel):
    id: str
    label: str
    provider: str
    tier: str
    api_url: str | None = None
    api_model: str | None = None
    # Voice identity pin (fish.audio reference_id) — keeps the same persona
    # in every voice note instead of Fish's per-request default roulette.
    reference_id: str | None = None
    # Optional per-language overrides, {"ur": "<id>"} — the customer's
    # language pin wins over the multilingual voice.
    language_references: dict[str, str] | None = None
    languages: str = "*"
    enabled: bool = True
    has_key: bool = False


class VoiceEngineUpsert(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    provider: str = Field(min_length=1, max_length=32)
    tier: str = Field(pattern="^(simple|advanced)$")
    api_url: str | None = Field(None, max_length=500)
    api_model: str | None = Field(None, max_length=200)
    reference_id: str | None = Field(None, max_length=200)
    language_references: dict[str, str] | None = None
    languages: str = Field("*", max_length=500)
    enabled: bool = True
    # Only applied when non-null — omitting it never clears the stored key;
    # empty string clears it.
    api_key: str | None = Field(None, max_length=500)

    @field_validator("language_references")
    @classmethod
    def _validate_language_pins(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        if v is None:
            return None
        cleaned = {
            str(k).strip().lower()[:8]: str(val).strip()[:200]
            for k, val in v.items()
            if str(k).strip() and str(val).strip()
        }
        if len(cleaned) > 8:
            raise ValueError("at most 8 language pins per engine")
        return cleaned or None


def _voice_engine_status(row) -> VoiceEngineStatus:
    return VoiceEngineStatus(
        id=row.id,
        label=row.label,
        provider=row.provider,
        tier=row.tier,
        api_url=row.api_url,
        api_model=row.api_model,
        reference_id=row.reference_id,
        language_references=row.language_references,
        languages=row.languages,
        enabled=row.enabled,
        has_key=bool(row.key_encrypted),
    )


@router.get("", response_model=list[VoiceEngineStatus])
async def admin_voice_engines_list(db: AsyncSession = Depends(get_db)):
    """All configured voice engines. Key VALUES are never returned."""
    rows = (await db.execute(select(VoiceModelConfig))).scalars().all()
    return [_voice_engine_status(r) for r in rows]


@router.get("/fish-voices")
async def admin_fish_voice_catalog(
    sort_by: str = "task_count",
    page: int = 1,
    db: AsyncSession = Depends(get_db),
):
    """Browse the fish.audio public voice library so the admin can pick a
    persona by name instead of pasting an opaque id. Uses the API key
    stored on any fish engine — add one first if this 400s."""
    from .engines.fish import voice_catalog as fish_voice_catalog

    row = (
        await db.execute(
            select(VoiceModelConfig)
            .where(
                VoiceModelConfig.provider == "fish",
                VoiceModelConfig.key_encrypted.is_not(None),
            )
            .order_by(VoiceModelConfig.updated_at.desc())
        )
    ).scalars().first()
    if row is None:
        raise HTTPException(
            status_code=400,
            detail="Add a Fish Audio engine with an API key first — the "
            "voice library is browsed with that key.",
        )
    try:
        return await fish_voice_catalog(
            decrypt_secret(row.key_encrypted), sort_by=sort_by, page=page
        )
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Could not reach fish.audio: {type(e).__name__}: {str(e)[:120]}",
        )


@router.post("", response_model=VoiceEngineStatus, status_code=201)
async def admin_voice_engine_create(
    body: VoiceEngineUpsert,
    db: AsyncSession = Depends(get_db),
):
    row = VoiceModelConfig(
        id=str(uuid.uuid4()),
        label=body.label,
        provider=body.provider,
        api_url=body.api_url,
        api_model=body.api_model,
        reference_id=body.reference_id,
        language_references=body.language_references,
        tier=body.tier,
        languages=body.languages,
        enabled=body.enabled,
    )
    if body.api_key is not None:
        row.key_encrypted = encrypt_secret(body.api_key) if body.api_key else None
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _voice_engine_status(row)


@router.delete("/{engine_id}", status_code=204)
async def admin_voice_engine_delete(
    engine_id: str,
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(VoiceModelConfig).where(VoiceModelConfig.id == engine_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Voice engine not found")
    await db.delete(row)
    await db.commit()
    return Response(status_code=204)


@router.post("/{engine_id}/test")
async def admin_voice_engine_test(
    engine_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Real synthesis probe through this exact engine — the admin hears the
    result of a good key, and a bad one shows here before any tenant does."""
    import time

    from .engines.edge import synthesize as _synthesize_edge
    from .engines.fish import synthesize as _synthesize_fish

    row = (
        await db.execute(
            select(VoiceModelConfig).where(VoiceModelConfig.id == engine_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Voice engine not found")

    text = "Hello! This is a Sayvors voice check."
    started = time.perf_counter()
    try:
        if row.provider == "fish":
            result = await _synthesize_fish(row, text, "en")
        elif row.provider == "edge":
            result = await _synthesize_edge(row.api_model, "en", text)
        else:
            return {
                "ok": False, "latency_ms": 0,
                "detail": f"provider {row.provider!r} has no client wired yet",
            }
    except Exception as e:
        return {
            "ok": False,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "detail": f"{type(e).__name__}: {str(e)[:160]}",
        }
    latency = int((time.perf_counter() - started) * 1000)
    if result is None:
        return {
            "ok": False, "latency_ms": latency,
            "detail": "no audio (missing API key, or language not covered)",
        }
    audio, mime = result
    return {"ok": True, "latency_ms": latency, "detail": f"{len(audio)} bytes {mime}"}


@router.put("/{engine_id}", response_model=VoiceEngineStatus)
async def admin_voice_engine_update(
    engine_id: str,
    body: VoiceEngineUpsert,
    db: AsyncSession = Depends(get_db),
):
    """Update an engine. A non-null api_key rotates the stored key
    (encrypted); an empty string clears it; omitting the field changes
    nothing."""
    row = (
        await db.execute(
            select(VoiceModelConfig).where(VoiceModelConfig.id == engine_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Voice engine not found")
    row.label = body.label
    row.provider = body.provider
    row.tier = body.tier
    row.api_url = body.api_url
    row.api_model = body.api_model
    row.reference_id = body.reference_id
    row.language_references = body.language_references
    row.languages = body.languages
    row.enabled = body.enabled
    if body.api_key is not None:
        row.key_encrypted = encrypt_secret(body.api_key) if body.api_key else None
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _voice_engine_status(row)

"""Read/write the admin-managed speech-to-text configuration.

The transcription path has no request session of its own (it runs inside a
job handler that does, but also inside one-shot scripts), so every helper
accepts an optional session and falls back to a fresh one — the same
contract `rag.embeddings` uses.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from .models import ASREngineConfig
from .providers import ASR_PROVIDERS, PROVIDER_META

logger = logging.getLogger(__name__)

# Tests point this at the in-memory engine; production leaves it None.
_session_factory = None

# "Field not supplied" marker. An omitted key must be distinguishable from
# an explicit empty string (which clears the stored key).
KEEP = object()


async def _session(db=None):
    if db is not None:
        yield db
        return
    if _session_factory is not None:
        async with _session_factory() as session:
            yield session
        return
    from ...database import async_session

    async with async_session() as session:
        yield session


def _decrypt(encrypted: str | None) -> str | None:
    if not encrypted:
        return None
    try:
        from ...core.crypto import decrypt_secret

        return decrypt_secret(encrypted)
    except Exception:  # noqa: BLE001 - a rotated key must not crash the worker
        logger.warning("ASR provider key could not be decrypted")
        return None


def row_to_config(row: ASREngineConfig) -> dict[str, Any]:
    """Public shape — never includes the key itself."""
    meta = PROVIDER_META.get(row.provider, {})
    return {
        "provider": row.provider,
        "label": meta.get("label", row.provider),
        "model": row.model,
        "base_url": row.base_url,
        "languages": row.languages or "*",
        "enabled": bool(row.enabled),
        "active": bool(row.active),
        "has_key": bool(row.key_encrypted),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _row_to_internal(row: ASREngineConfig) -> dict[str, Any]:
    return {
        "provider": row.provider,
        "model": row.model,
        "base_url": row.base_url,
        "languages": row.languages or "*",
        "enabled": bool(row.enabled),
        "active": bool(row.active),
        "api_key": _decrypt(row.key_encrypted),
    }


async def list_asr_configs(db=None) -> list[dict[str, Any]]:
    async for session in _session(db):
        rows = (await session.execute(select(ASREngineConfig))).scalars().all()
        return [row_to_config(r) for r in rows]
    return []


async def get_active_asr_config(db=None) -> dict[str, Any] | None:
    """The engine transcription should use, or None for local whisper.

    Only an enabled, activated row is returned. A provider that disables
    itself (bad key, quota) drops the system back to local transcription
    instead of failing every voice note.
    """
    async for session in _session(db):
        row = (
            await session.execute(
                select(ASREngineConfig)
                .where(
                    ASREngineConfig.active.is_(True),
                    ASREngineConfig.enabled.is_(True),
                )
                .order_by(ASREngineConfig.updated_at.desc())
            )
        ).scalars().first()
        return _row_to_internal(row) if row is not None else None
    return None


async def get_asr_config(provider: str, db=None) -> dict[str, Any] | None:
    async for session in _session(db):
        row = await session.get(ASREngineConfig, provider)
        return _row_to_internal(row) if row is not None else None
    return None


async def save_asr_config(
    db,
    provider: str,
    *,
    model: str | None | object = KEEP,
    base_url: str | None | object = KEEP,
    languages: str | None | object = KEEP,
    enabled: bool | None = None,
    active: bool | None = None,
    api_key: str | None | object = KEEP,
) -> dict[str, Any]:
    """Upsert one provider. Omitted fields are left untouched.

    `api_key=""` clears the stored key; `None` (or omitting it) keeps it.
    Activating a provider deactivates every other row in the same
    transaction, so "exactly one active" cannot drift.
    """
    if provider not in ASR_PROVIDERS:
        raise ValueError(f"unknown ASR provider: {provider}")
    from ...core.crypto import encrypt_secret

    row = await db.get(ASREngineConfig, provider)
    if row is None:
        row = ASREngineConfig(provider=provider, enabled=True, active=False)
        db.add(row)

    if model is not KEEP:
        row.model = (model or None)
    if base_url is not KEEP:
        row.base_url = (base_url or None)
    if languages is not KEEP:
        row.languages = (languages or "*")[:200]
    if enabled is not None:
        row.enabled = bool(enabled)
    if active is not None:
        row.active = bool(active)
        if row.active:
            others = (
                await db.execute(
                    select(ASREngineConfig).where(ASREngineConfig.provider != provider)
                )
            ).scalars().all()
            for other in others:
                other.active = False
    if api_key is not KEEP:
        row.key_encrypted = encrypt_secret(api_key) if api_key else None

    if row.model is None:
        row.model = PROVIDER_META.get(provider, {}).get("default_model")
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return row_to_config(row)

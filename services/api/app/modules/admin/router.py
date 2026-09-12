"""Platform admin API — separate password, no user record.

POST   /api/v1/admin/login   exchange the admin password for a short token
GET    /api/v1/admin/me      session check (also proves the gate works)
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from ...config import settings
from ...core.deps import get_db, require_admin
from ...security import create_admin_token, verify_password
from . import service as admin_service
from .schemas import (
    AdminHealth,
    AdminOverview,
    AdminTenantDetail,
    AdminTenantList,
    AdminUsageOverview,
    LlmModelCreate,
    LlmModelStatus,
    LlmModelTestResult,
    LlmModelUpdate,
    LlmProviderStatus,
    LlmProviderUpdate,
    LlmTestResult,
    RemoteModel,
    SavedModel,
)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


class AdminLoginRequest(BaseModel):
    password: str = Field(..., min_length=1, max_length=256)


class AdminLoginResponse(BaseModel):
    access_token: str
    expires_in_minutes: int


def _get_client_ip(request: Request) -> str:
    peer = request.client.host if request.client else ""
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[-1].strip()
    return peer or "unknown"


@router.post("/login", response_model=AdminLoginResponse)
async def admin_login(body: AdminLoginRequest, request: Request):
    if not settings.ADMIN_PASSWORD_HASH:
        raise HTTPException(status_code=503, detail="Admin access is not configured.")
    from ..auth.rate_limit import rate_limit

    ip = _get_client_ip(request)
    if not await rate_limit(f"admin-login:{ip}", 5, 300):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")
    if not verify_password(body.password, settings.ADMIN_PASSWORD_HASH):
        logger.warning("Failed admin login from %s", ip)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong password.")
    return AdminLoginResponse(
        access_token=create_admin_token(),
        expires_in_minutes=settings.ADMIN_SESSION_MINUTES,
    )


@router.get("/me")
async def admin_me(_admin: dict = Depends(require_admin)):
    return {"admin": True}


@router.get("/overview", response_model=AdminOverview)
async def admin_overview(
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return AdminOverview(**await admin_service.get_overview(db))


@router.get("/tenants", response_model=AdminTenantList)
async def admin_tenants(
    search: str | None = Query(None, max_length=200),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    items, total = await admin_service.list_tenants(db, search, limit, offset)
    return AdminTenantList(total=total, items=items)


@router.get("/tenants/{user_id}", response_model=AdminTenantDetail)
async def admin_tenant_detail(
    user_id: str,
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    detail = await admin_service.get_tenant(db, user_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Tenant not found.")
    return AdminTenantDetail(**detail)


@router.get("/health", response_model=AdminHealth)
async def admin_health(
    probe: bool = Query(False),
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Per-service status + recent failures.

    Fast metadata checks by default; probe=true also hits Localith and
    each configured AI provider live (free list-models calls, no tokens).
    """
    return AdminHealth(**await admin_service.get_health(db, probe))


@router.get("/usage/overview", response_model=AdminUsageOverview)
async def admin_usage_overview(
    days: int = Query(30, ge=1, le=365),
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Global token metering: totals + per-tenant + per-model tables."""
    from ..llm.usage import get_admin_overview

    return AdminUsageOverview(**await get_admin_overview(db, days))


@router.get("/llm", response_model=list[LlmProviderStatus])
async def admin_llm_list(
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Provider key status. Key VALUES are never returned."""
    from ..llm.models import ModelConfig
    from ..llm.providers import registry
    from ..llm.providers.catalog import MODELS, PROVIDERS

    model_rows: dict[str, ModelConfig] = {}
    for row in (await db.execute(select(ModelConfig))).scalars().all():
        model_rows[row.model_id] = row

    out = []
    for name in PROVIDERS:
        _key, source = registry.resolve_provider_key(name)
        enabled = True
        if registry._db_overlay is not None and name in registry._db_overlay:
            enabled = bool(registry._db_overlay[name].get("enabled", True))
        models = []
        for m in MODELS:
            if m.provider != name:
                continue
            row = model_rows.get(m.id)
            models.append(LlmModelStatus(
                id=m.id, name=m.name,
                enabled=row.enabled if row else True,
                tested_ok=row.tested_ok if row else None,
                tested_at=row.tested_at.isoformat() if row and row.tested_at else None,
                custom=False,
            ))
        for model_id, row in sorted(model_rows.items()):
            if not (row.provider and row.api_model) or row.provider != name:
                continue
            models.append(LlmModelStatus(
                id=model_id, name=row.display_name or model_id,
                enabled=row.enabled,
                tested_ok=row.tested_ok,
                tested_at=row.tested_at.isoformat() if row.tested_at else None,
                custom=True,
            ))
        out.append(LlmProviderStatus(
            provider=name,
            key_source=source,
            enabled=enabled,
            has_key=source == "database",
            models=models,
        ))
    return out


@router.put("/llm/{provider}", response_model=LlmProviderStatus)
async def admin_llm_update(
    provider: str,
    body: LlmProviderUpdate,
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Store/clear a provider key (Fernet-encrypted) or toggle enabled."""
    from ..llm.models import ProviderConfig
    from ..llm.providers import registry
    from ..llm.providers.catalog import PROVIDERS

    if provider not in PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")
    result = await db.execute(
        select(ProviderConfig).where(ProviderConfig.provider == provider)
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = ProviderConfig(provider=provider, enabled=True)
        db.add(row)
    if body.api_key is not None:
        key = body.api_key.strip()
        if key:
            from ..channels.service import encrypt_token

            row.key_encrypted = encrypt_token(key)
        else:
            row.key_encrypted = None  # clear -> env fallback
    if body.enabled is not None:
        row.enabled = body.enabled
    await db.commit()

    # Write-through to the live overlay (no restart needed).
    if registry._db_overlay is None:
        registry._db_overlay = {}
    registry._db_overlay[provider] = {
        "key_encrypted": row.key_encrypted,
        "enabled": row.enabled,
    }
    registry._providers.pop(provider, None)
    logger.info("Admin updated LLM provider %s (enabled=%s)", provider, row.enabled)

    _key, source = registry.resolve_provider_key(provider)
    return LlmProviderStatus(
        provider=provider, key_source=source, enabled=row.enabled,
        has_key=source in ("database", "env"),
    )


@router.post("/llm/{provider}/test", response_model=LlmTestResult)
async def admin_llm_test(
    provider: str,
    _admin: dict = Depends(require_admin),
):
    """Free liveness probe (model list, no tokens spent)."""
    import time as _time

    from ..llm.providers import registry
    from ..llm.providers.catalog import PROVIDERS

    if provider not in PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")
    from .service import _PROBE_URLS, _probe_ai_provider

    urls = _PROBE_URLS
    if registry.resolve_provider_key(provider)[0] is None and provider != "ollama":
        return LlmTestResult(provider=provider, ok=False, detail="no API key configured")
    start = _time.monotonic()
    try:
        detail = await _probe_ai_provider(provider, urls[provider])
        ms = round((_time.monotonic() - start) * 1000)
        return LlmTestResult(provider=provider, ok=True, latency_ms=ms, detail=detail)
    except Exception as e:
        ms = round((_time.monotonic() - start) * 1000)
        return LlmTestResult(provider=provider, ok=False, latency_ms=ms, detail=f"{type(e).__name__}: {str(e)[:160]}")


@router.put("/llm/{provider}/models/{model_id:path}", response_model=LlmModelStatus)
async def admin_llm_model_update(
    provider: str,
    model_id: str,
    body: LlmModelUpdate,
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Enable/disable one model for tenants. Creates the row on first touch."""
    from datetime import datetime, timezone

    from ..llm.models import ModelConfig
    from ..llm.providers import registry
    from ..llm.providers.registry import get_effective_model

    info = get_effective_model(model_id)
    if info is None or info.provider != provider:
        raise HTTPException(status_code=404, detail=f"Unknown model: {model_id}")
    result = await db.execute(
        select(ModelConfig).where(ModelConfig.model_id == model_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = ModelConfig(model_id=model_id, enabled=body.enabled)
        db.add(row)
    else:
        row.enabled = body.enabled
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()

    if registry._model_overlay is None:
        registry._model_overlay = {}
    registry._model_overlay[model_id] = bool(body.enabled)
    logger.info("Admin set model %s enabled=%s", model_id, body.enabled)
    await db.refresh(row)
    return LlmModelStatus(
        id=row.model_id, name=row.display_name or info.name, enabled=row.enabled,
        tested_ok=row.tested_ok,
        tested_at=row.tested_at.isoformat() if row.tested_at else None,
        custom=bool(row.provider and row.api_model),
    )


@router.post("/llm/{provider}/models/{model_id:path}/test", response_model=LlmModelTestResult)
async def admin_llm_model_test(
    provider: str,
    model_id: str,
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Live-test one exact model (tiny completion, ~20 tokens) and record it."""
    import time as _time2
    from datetime import datetime, timezone

    from ..llm.models import ModelConfig
    from ..llm.providers import registry
    from ..llm.providers.base import LLMMessage, LLMRequest
    from ..llm.providers.registry import get_effective_model

    info = get_effective_model(model_id)
    if info is None or info.provider != provider:
        raise HTTPException(status_code=404, detail=f"Unknown model: {model_id}")
    if registry.resolve_provider_key(provider)[0] is None:
        return LlmModelTestResult(model_id=model_id, ok=False, detail="no API key configured")

    start = _time2.monotonic()
    ok, detail, reply = False, "", ""
    try:
        provider_inst = registry.get_provider_for_model(model_id)
        from ..llm.service import _resolve_model

        api_model, _ = _resolve_model(model_id)
        resp = await provider_inst.complete(LLMRequest(
            model=api_model,
            messages=[LLMMessage(role="user", content="Reply with exactly: OK")],
            system_prompt="You are a connectivity probe. Reply with exactly: OK",
            temperature=0.1,
            max_tokens=20,
            stream=False,
            tenant_id=None,
            model_id=model_id,
            purpose="admin.test",
        ))
        reply = (resp.content or "").strip()[:200]
        ok, detail = True, "model generated a reply"
    except Exception as e:
        detail = f"{type(e).__name__}: {str(e)[:160]}"
    ms = round((_time2.monotonic() - start) * 1000)

    result = await db.execute(
        select(ModelConfig).where(ModelConfig.model_id == model_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = ModelConfig(model_id=model_id, enabled=True)
        db.add(row)
    row.tested_ok = ok
    row.tested_at = datetime.now(timezone.utc)
    await db.commit()
    return LlmModelTestResult(model_id=model_id, ok=ok, latency_ms=ms, detail=detail, reply=reply)


@router.post("/llm/models", response_model=LlmModelStatus, status_code=201)
async def admin_llm_model_create(
    body: LlmModelCreate,
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Add a model. Id must be unique in the database (not a duplicate row)."""
    from datetime import datetime, timezone

    from ..llm.models import ModelConfig
    from ..llm.providers import registry
    from ..llm.providers.catalog import PROVIDERS

    if body.provider not in PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {body.provider}")
    if ":" not in body.id:
        raise HTTPException(status_code=422, detail="Model id must look like 'provider:name'.")
    result = await db.execute(
        select(ModelConfig).where(ModelConfig.model_id == body.id)
    )
    if result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Model id already exists in the database.")
    row = ModelConfig(
        model_id=body.id,
        enabled=body.enabled,
        display_name=body.name,
        provider=body.provider,
        api_model=body.api_model,
        api_url=body.api_url,
        context_window=body.context_window,
        max_output=body.max_output,
        supports_stream=body.supports_stream,
    )
    db.add(row)
    await db.commit()

    if registry._model_overlay is None:
        registry._model_overlay = {}
    registry._model_overlay[body.id] = bool(body.enabled)
    if registry._custom_models is None:
        registry._custom_models = {}
    registry._custom_models[body.id] = {
        "name": body.name,
        "provider": body.provider,
        "api_model": body.api_model,
        "api_url": body.api_url,
        "context": body.context_window,
        "max_output": body.max_output,
        "supports_stream": body.supports_stream,
    }
    logger.info("Admin added custom model %s", body.id)
    await db.refresh(row)
    return LlmModelStatus(
        id=row.model_id, name=body.name, enabled=row.enabled,
        tested_ok=None, tested_at=None, custom=True,
    )


@router.delete("/llm/{provider}/models/{model_id:path}", status_code=204)
async def admin_llm_model_delete(
    provider: str,
    model_id: str,
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete an admin-saved model row (custom or catalog override).

    Pure catalog ids with no saved row can't be deleted — disable them instead.
    """
    from ..llm.models import ModelConfig
    from ..llm.providers import registry
    from ..llm.providers.catalog import get_model_by_id

    result = await db.execute(
        select(ModelConfig).where(ModelConfig.model_id == model_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        if get_model_by_id(model_id) is not None:
            raise HTTPException(
                status_code=400,
                detail="Catalog models can't be deleted — disable them instead.",
            )
        raise HTTPException(status_code=404, detail=f"Unknown custom model: {model_id}")
    if row.provider != provider:
        raise HTTPException(status_code=404, detail=f"Unknown custom model: {model_id}")
    await db.delete(row)
    await db.commit()
    if registry._model_overlay is not None:
        registry._model_overlay.pop(model_id, None)
    if registry._custom_models is not None:
        registry._custom_models.pop(model_id, None)
    logger.info("Admin deleted custom model %s", model_id)


@router.get("/models", response_model=list[SavedModel])
async def admin_models_list(
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Every explicitly saved model (toggles + customs) in one flat list."""
    from ..llm.models import ModelConfig
    from ..llm.providers.catalog import get_model_by_id

    rows = (await db.execute(select(ModelConfig))).scalars().all()
    out = []
    for row in sorted(rows, key=lambda r: r.model_id):
        info = get_model_by_id(row.model_id)
        custom = bool(row.provider and row.api_model)
        out.append(SavedModel(
            id=row.model_id,
            name=row.display_name or (info.name if info else row.model_id),
            provider=row.provider or (info.provider if info else ""),
            api_model=row.api_model or (info.api_model if info else ""),
            enabled=row.enabled,
            custom=custom,
            tested_ok=row.tested_ok,
            tested_at=row.tested_at.isoformat() if row.tested_at else None,
        ))
    return out


@router.get("/llm/{provider}/remote-models", response_model=list[RemoteModel])
async def admin_remote_models(
    provider: str,
    api_key: str | None = None,
    _admin: dict = Depends(require_admin),
):
    """Live model list straight from the provider's API.

    Uses the saved key by default. Pass ?api_key=... to use a key the admin
    typed inline (it gets saved to DB on model-add if provided).
    """
    import httpx

    from .service import _PROBE_URLS
    from ..llm.providers import registry
    from ..llm.providers.catalog import PROVIDERS

    if provider not in PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")
    key = api_key
    if not key:
        key, _source = registry.resolve_provider_key(provider)
    if not key:
        raise HTTPException(
            status_code=400,
            detail=f"No key available for {provider}.",
        )
    try:
        if provider == "gemini":
            resp = httpx.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                params={"key": key},
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("models", []) if isinstance(data, dict) else []
            return [
                RemoteModel(
                    id=f"gemini:{str(m.get('name', '')).split('/')[-1]}",
                    name=str(m.get("displayName", m.get("name", ""))),
                )
                for m in items
                if isinstance(m, dict) and m.get("name")
            ]
        if provider == "ollama":
            resp = httpx.get("http://localhost:11434/api/tags", timeout=20)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("models", []) if isinstance(data, dict) else []
            return [
                RemoteModel(id=f"ollama:{m.get('name', '')}", name=str(m.get("name", "")))
                for m in items
                if isinstance(m, dict) and m.get("name")
            ]
        base = _PROBE_URLS[provider].rstrip("/")
        # _PROBE_URLS entries for OpenAI-compatibles already end in /models.
        url = base if base.endswith("/models") else f"{base}/models"
        resp = httpx.get(
            url, headers={"Authorization": f"Bearer {key}"}, timeout=20
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data", []) if isinstance(data, dict) else []
        return [
            RemoteModel(id=f"{provider}:{m.get('id', '')}", name=str(m.get("id", "")))
            for m in items
            if isinstance(m, dict) and m.get("id")
        ]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Provider list failed: {type(e).__name__}: {str(e)[:160]}")

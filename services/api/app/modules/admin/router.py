"""Platform admin API — separate password, no user record.

POST   /api/v1/admin/login   exchange the admin password for a short token
GET    /api/v1/admin/me      session check (also proves the gate works)
"""
import logging
from datetime import datetime

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...core.deps import get_db, require_admin
from ...security import create_admin_token, verify_password
from ..auth.rate_limit import rate_limit
from ..auth.router import get_client_ip
from . import service as admin_service
from . import stats as admin_service_stats
from .schemas import (
    AdminHealth,
    AdminOverview,
    AdminOverviewStats,
    AdminTenantDetail,
    AdminTenantList,
    AdminUsageOverview,
    AdminVoiceUsageOverview,
    LiveStats,
    LlmModelCreate,
    LlmModelStatus,
    LlmModelTestResult,
    LlmModelUpdate,
    LlmProviderStatus,
    LlmProviderUpdate,
    LlmTestResult,
    OverviewLast24h,
    OverviewTotals,
    OverviewWindowDelta,
    PlatformStats,
    RemoteModel,
    SavedModel,
)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _stored_key_works(row) -> bool:
    """True only when the stored ciphertext decrypts with the current key.

    The admin views mirror the database, not the boot-time overlay: a process
    that failed to load its overlay must still show the keys an operator
    saved.
    """
    if row is None or not row.key_encrypted:
        return False
    try:
        from ...core.crypto import decrypt_secret

        return bool(decrypt_secret(row.key_encrypted))
    except Exception:
        return False


router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


class AdminLoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


class AdminLoginResponse(BaseModel):
    """No token in the body: the session lives in an httpOnly cookie so
    XSS cannot read it. The frontend only needs the TTL for its countdown."""

    expires_in_minutes: int


_ADMIN_FAIL_KEY = "admin-login:failures:global"


async def _register_admin_failure() -> int:
    """Increment the global failure counter; returns the new count.

    Keyed on the credential, not the source IP, so a distributed attacker
    rotating XFF addresses cannot reset their progress. Window: 15 minutes.
    """
    try:
        from ..redis.client import get_redis

        redis = await get_redis()
        count = await redis.incr(_ADMIN_FAIL_KEY)
        await redis.expire(_ADMIN_FAIL_KEY, 900)
        return int(count)
    except Exception:
        return 0


async def _admin_locked_out() -> bool:
    try:
        from ..redis.client import get_redis

        redis = await get_redis()
        count = int(await redis.get(_ADMIN_FAIL_KEY) or 0)
        return count >= settings.ADMIN_MAX_CONSECUTIVE_FAILURES
    except Exception:
        return False


async def _has_any_operator(db: AsyncSession | None = None) -> bool:
    """Whether any operator account exists.

    Uses the request session when one is available, so the admin endpoints
    honour the app's dependency injection (and the test overrides) instead of
    opening a second, unrelated connection.
    """
    try:
        from sqlalchemy import func, select

        from .models import PlatformOperator

        if db is None:
            from ...database import async_session

            async with async_session() as session:
                count = (
                    await session.execute(select(func.count()).select_from(PlatformOperator))
                ).scalar() or 0
                return count > 0
        count = (
            await db.execute(select(func.count()).select_from(PlatformOperator))
        ).scalar() or 0
        return count > 0
    except Exception:
        return False


@router.post("/login", response_model=AdminLoginResponse)
async def admin_login(
    body: AdminLoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from .models import PlatformOperator, AdminAuditLog

    ip = get_client_ip(request)
    # If no operators exist and no legacy password is configured, admin is
    # not set up at all.
    if not (await _has_any_operator(db)) and not settings.ADMIN_PASSWORD_HASH:
        raise HTTPException(status_code=503, detail="Admin access is not configured.")
    if not settings.TESTING:
        if not await rate_limit(f"admin-login:{ip}", 5, 300):
            raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")
    if await _admin_locked_out():
        logger.error("Admin login globally locked out (repeated failures), ip=%s", ip)
        raise HTTPException(status_code=429, detail="Admin access temporarily locked. Try again later.")

    row = (
        await db.execute(
            select(PlatformOperator).where(PlatformOperator.username == body.username)
        )
    ).scalar_one_or_none()

    # Backward-compat bootstrap: if no operators exist yet, fall back to the
    # legacy shared password (username "admin").
    if row is None and not (await _has_any_operator(db)) and settings.ADMIN_PASSWORD_HASH and body.username == "admin":
        if verify_password(body.password, settings.ADMIN_PASSWORD_HASH):
            import uuid as _uuid

            row = PlatformOperator(
                id=str(_uuid.uuid4()),
                username="admin",
                password_hash=settings.ADMIN_PASSWORD_HASH,
                role="superadmin",
                is_active=True,
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
            logger.warning("Bootstrapped legacy 'admin' operator from ADMIN_PASSWORD_HASH.")

    if row is None or not row.is_active:
        failures = await _register_admin_failure()
        logger.warning("Failed admin login (unknown/inactive operator) from %s (global failures=%d)", ip, failures)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong credentials.")
    now = datetime.now(timezone.utc)
    if row.locked_until is not None and row.locked_until > now:
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="Account is locked. Try again later.")
    if not verify_password(body.password, row.password_hash):
        r = await db.get(PlatformOperator, row.id)
        if r is not None:
            r.failed_login_count = (r.failed_login_count or 0) + 1
            if r.failed_login_count >= settings.ADMIN_MAX_CONSECUTIVE_FAILURES:
                r.locked_until = now + timedelta(minutes=15)
            await db.commit()
        failures = await _register_admin_failure()
        logger.warning("Failed admin login for operator %s from %s (global failures=%d)", body.username, ip, failures)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong credentials.")

    r = await db.get(PlatformOperator, row.id)
    if r is not None:
        r.failed_login_count = 0
        r.locked_until = None
        r.last_login_at = now
        await db.commit()

    try:
        from ..redis.client import get_redis

        redis = await get_redis()
        await redis.delete(_ADMIN_FAIL_KEY)
    except Exception:
        pass
    token = create_admin_token(subject=row.id)
    secure = (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto", "") == "https"
    )
    response.set_cookie(
        settings.ADMIN_COOKIE_NAME,
        token,
        max_age=settings.ADMIN_SESSION_MINUTES * 60,
        httponly=True,
        samesite="strict",
        secure=secure,
        path="/api/v1/admin",
    )
    try:
        db.add(AdminAuditLog(
            operator_id=row.id,
            operator_username=row.username,
            action="login",
            method="POST",
            path="/api/v1/admin/login",
            status_code=200,
            ip=ip,
            user_agent=request.headers.get("user-agent"),
        ))
        await db.commit()
    except Exception as e:
        logger.warning("Audit log write failed: %s", e)
        await db.rollback()
    return AdminLoginResponse(expires_in_minutes=settings.ADMIN_SESSION_MINUTES)


@router.post("/logout")
async def admin_logout(
    request: Request,
    response: Response,
    credentials: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False)),
):
    """Revoke the admin session: blacklist the token (Bearer or cookie) and
    clear the cookie. Fails open on decode errors — cookie is cleared anyway."""
    import time

    token = credentials.credentials if credentials else request.cookies.get(settings.ADMIN_COOKIE_NAME, "")
    if token:
        try:
            payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
            jti = payload.get("jti", "")
            if jti:
                from ..auth.rate_limit import blacklist_token

                ttl = int(payload.get("exp", 0) - time.time()) or settings.ADMIN_SESSION_MINUTES * 60
                await blacklist_token(jti, max(ttl, 60))
        except Exception:
            pass
    response.delete_cookie(settings.ADMIN_COOKIE_NAME, path="/api/v1/admin")
    return {"ok": True}


async def admin_rate_limit(request: Request):
    if settings.TESTING:
        return
    ip = get_client_ip(request)
    if not await rate_limit(f"admin:{ip}:{request.url.path}", 10000, 60):
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")


@router.get("/me")
async def admin_me(_admin: dict = Depends(require_admin), _rate_limit: None = Depends(admin_rate_limit)):
    return {"admin": True}


@router.get("/overview", response_model=AdminOverview)
async def admin_overview(
    _admin: dict = Depends(require_admin), _rate_limit: None = Depends(admin_rate_limit),
    db: AsyncSession = Depends(get_db),
):
    return AdminOverview(**await admin_service.get_overview(db))


@router.get("/overview/stats", response_model=AdminOverviewStats)
async def admin_overview_stats(
    window: str = Query("30d", pattern="^(24h|7d|30d|90d|1y)$"),
    _admin: dict = Depends(require_admin), _rate_limit: None = Depends(admin_rate_limit),
    db: AsyncSession = Depends(get_db),
):
    return AdminOverviewStats(**await admin_service_stats.get_stats(db, window))


@router.get("/overview/stats/live", response_model=LiveStats)
async def admin_overview_stats_live(
    minutes: int = Query(30, ge=15, le=120),
    _admin: dict = Depends(require_admin), _rate_limit: None = Depends(admin_rate_limit),
    db: AsyncSession = Depends(get_db),
):
    return LiveStats(**await admin_service_stats.get_live_stats(db, minutes))


@router.get("/tenants", response_model=AdminTenantList)
async def admin_tenants(
    search: str | None = Query(None, max_length=200),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _admin: dict = Depends(require_admin), _rate_limit: None = Depends(admin_rate_limit),
    db: AsyncSession = Depends(get_db),
):
    items, total = await admin_service.list_tenants(db, search, limit, offset)
    return AdminTenantList(items=items, total=total)


@router.get("/tenants/{user_id}/usage")
async def admin_tenant_usage(
    user_id: str,
    days: int = Query(30, ge=1, le=365),
    _admin: dict = Depends(require_admin), _rate_limit: None = Depends(admin_rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """Tenant-scoped LLM usage: totals + by_model + daily — for the tenant detail page."""
    from ..llm.usage import get_tenant_summary
    from ..users.models import User

    # ensure tenant exists so we return 404 not empty shape for unknown ids
    if await db.get(User, user_id) is None:
        raise HTTPException(status_code=404, detail="Tenant not found.")
    return await get_tenant_summary(db, user_id, days)


@router.get("/tenants/{user_id}", response_model=AdminTenantDetail)
async def admin_tenant_detail(
    user_id: str,
    _admin: dict = Depends(require_admin), _rate_limit: None = Depends(admin_rate_limit),
    db: AsyncSession = Depends(get_db),
):
    detail = await admin_service.get_tenant(db, user_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Tenant not found.")
    return AdminTenantDetail(**detail)


class PlanGrantRequest(BaseModel):
    plan: str = Field(..., pattern=r"^(free|pro)$")
    add_credit_cents: int = Field(default=0, ge=0, le=1_000_000)
    note: str | None = Field(default=None, max_length=500)


class PlanGrantResponse(BaseModel):
    plan: str
    balance_cents: int
    balance_dollars: float
    currency: str = "usd"


class WalletResyncRequest(BaseModel):
    """Preview by default; applying a repair requires dry_run=false."""

    dry_run: bool = True
    note: str | None = Field(default=None, max_length=500)


class WalletResyncResponse(BaseModel):
    tenant_id: str
    applied: bool
    balance_cents: int
    db_balance_cents: int
    redis_balance_cents: int | None = None
    previous_balance_cents: int | None = None
    delta_cents: int | None = None
    redis_synced: bool | None = None
    reliable: bool = True
    warning: str | None = None


@router.post("/tenants/{user_id}/plan", response_model=PlanGrantResponse)
async def admin_grant_plan(
    user_id: str,
    body: PlanGrantRequest,
    _admin: dict = Depends(require_admin), _rate_limit: None = Depends(admin_rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """Record a plan purchase: set plan, add AI credits, ledger + sync.

    A first-time Pro grant bundles $20 of AI credits automatically. This is
    the endpoint behind "when people buy a plan, the admin sees it and the
    DB updates the user to pro with $20 of AI tokens".
    """
    from ..billing import service as billing_service

    try:
        return await billing_service.grant_plan(
            user_id, body.plan, body.add_credit_cents, body.note, "admin", db
        )
    except ValueError as e:
        raise HTTPException(status_code=404 if "not found" in str(e) else 400, detail=str(e))


@router.post("/tenants/{user_id}/resync-balance", response_model=WalletResyncResponse)
async def admin_resync_balance(
    user_id: str,
    body: WalletResyncRequest | None = None,
    _admin: dict = Depends(require_admin),
    _rate_limit: None = Depends(admin_rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """Preview or repair Redis drift against the durable DB wallet.

    The DB is the source of truth: this endpoint never accepts a balance and
    never recomputes one from usage. Dry-run is the default. Applying writes a
    zero-amount ``balance_reconcile`` audit row only when the cache is missing
    or differs, then overwrites the cache with the DB value. Re-running with no
    drift is a no-op.
    """
    from ..billing.ledger import reconcile_wallet

    request = body or WalletResyncRequest()
    try:
        return await reconcile_wallet(
            user_id,
            db,
            dry_run=request.dry_run,
            note=request.note,
            created_by="admin",
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/billing/overview")
async def admin_billing_overview(
    _admin: dict = Depends(require_admin),
    _rate_limit: None = Depends(admin_rate_limit),
    db: AsyncSession = Depends(get_db),
):
    from .service import get_billing_overview

    return await get_billing_overview(db)


@router.get("/tenants/{user_id}/billing")
async def admin_tenant_billing(
    user_id: str,
    _admin: dict = Depends(require_admin),
    _rate_limit: None = Depends(admin_rate_limit),
    db: AsyncSession = Depends(get_db),
):
    from .service import get_tenant_billing

    result = await get_tenant_billing(db, user_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Tenant not found.")
    return result


@router.get("/health", response_model=AdminHealth)
async def admin_health(
    probe: bool = Query(False),
    _admin: dict = Depends(require_admin), _rate_limit: None = Depends(admin_rate_limit),
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
    _admin: dict = Depends(require_admin), _rate_limit: None = Depends(admin_rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """Global token metering: totals + per-tenant + per-model tables."""
    from ..llm.usage import get_admin_overview

    return AdminUsageOverview(**await get_admin_overview(db, days))


@router.get("/usage/voice", response_model=AdminVoiceUsageOverview)
async def admin_usage_voice(
    days: int = Query(30, ge=1, le=365),
    _admin: dict = Depends(require_admin), _rate_limit: None = Depends(admin_rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """Voice-model (TTS) metering: totals + per-engine bars + daily series."""
    from ..llm.usage import get_voice_overview

    return AdminVoiceUsageOverview(**await get_voice_overview(db, days))


@router.get("/llm", response_model=list[LlmProviderStatus])
async def admin_llm_list(
    _admin: dict = Depends(require_admin), _rate_limit: None = Depends(admin_rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """Provider key status. Key VALUES are never returned."""
    from ..llm.models import ModelConfig, ProviderConfig
    from ..llm.providers.catalog import MODELS, PROVIDERS

    model_rows: dict[str, ModelConfig] = {}
    for row in (await db.execute(select(ModelConfig))).scalars().all():
        model_rows[row.model_id] = row

    provider_rows: dict[str, ProviderConfig] = {
        row.provider: row
        for row in (await db.execute(select(ProviderConfig))).scalars().all()
    }

    out = []
    for name in PROVIDERS:
        row = provider_rows.get(name)
        enabled = row.enabled if row is not None else True
        has_key = _stored_key_works(row)
        source = "disabled" if row is not None and not row.enabled else (
            "database" if has_key else "none"
        )
        models = []
        for m in MODELS:
            if m.provider != name:
                continue
            model_row = model_rows.get(m.id)
            models.append(LlmModelStatus(
                id=m.id, name=m.name,
                enabled=model_row.enabled if model_row else True,
                tested_ok=model_row.tested_ok if model_row else None,
                tested_at=(
                    model_row.tested_at.isoformat()
                    if model_row and model_row.tested_at
                    else None
                ),
                custom=False,
            ))
        for model_id, model_row in sorted(model_rows.items()):
            if not (model_row.provider and model_row.api_model) or model_row.provider != name:
                continue
            models.append(LlmModelStatus(
                id=model_id, name=model_row.display_name or model_id,
                enabled=model_row.enabled,
                tested_ok=model_row.tested_ok,
                tested_at=model_row.tested_at.isoformat() if model_row.tested_at else None,
                custom=True,
            ))
        out.append(LlmProviderStatus(
            provider=name,
            key_source=source,
            enabled=enabled,
            has_key=has_key,
            models=models,
        ))
    return out


@router.put("/llm/{provider}", response_model=LlmProviderStatus)
async def admin_llm_update(
    provider: str,
    body: LlmProviderUpdate,
    _admin: dict = Depends(require_admin), _rate_limit: None = Depends(admin_rate_limit),
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
            row.key_encrypted = None  # clear -> no key
    if body.enabled is not None:
        row.enabled = body.enabled
    await db.commit()

    # Reload this worker's overlays from the committed row so the response
    # and the next generation see the key without a restart. Other workers
    # converge through the registry's TTL refresh.
    await registry.refresh_provider_keys_from_session(db)
    logger.info("Admin updated LLM provider %s (enabled=%s)", provider, row.enabled)

    _key, source = registry.resolve_provider_key(provider)
    return LlmProviderStatus(
        provider=provider, key_source=source, enabled=row.enabled,
        has_key=_stored_key_works(row),
    )


@router.post("/llm/{provider}/test", response_model=LlmTestResult)
async def admin_llm_test(
    provider: str,
    _admin: dict = Depends(require_admin), _rate_limit: None = Depends(admin_rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """Free liveness probe (model list, no tokens spent)."""
    import time as _time

    from ..llm.providers import registry
    from ..llm.providers.catalog import PROVIDERS

    if provider not in PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")
    from .service import _PROBE_URLS, _probe_ai_provider

    # Read the key from the request's database, not this worker's boot
    # overlay: a key saved by another worker must be testable here.
    await registry.refresh_provider_keys_from_session(db)
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


class EmbeddingProviderStatus(BaseModel):
    provider: str
    model: str | None = None
    has_key: bool = False
    enabled: bool = True
    active: bool = False
    base_url: str | None = None


class EmbeddingConfigOverview(BaseModel):
    providers: list[EmbeddingProviderStatus]
    active_provider: str | None = None
    canonical_dimensions: int
    chunks_total: int
    chunks_with_vector: int
    # "admin" when a provider is configured separately, "fallback" when the
    # embedding backend is still borrowing the text-generation keys.
    source: str


class EmbeddingProviderUpdate(BaseModel):
    model: str | None = None
    # None keeps the stored key, an empty string clears it.
    api_key: str | None = None
    base_url: str | None = None
    enabled: bool | None = None
    activate: bool = False


class EmbeddingTestRequest(BaseModel):
    provider: str | None = None


class EmbeddingTestResult(BaseModel):
    ok: bool
    provider: str | None = None
    model: str | None = None
    dimensions: int = 0
    latency_ms: int = 0
    detail: str = ""


@router.get("/embeddings", response_model=EmbeddingConfigOverview)
async def admin_embedding_config(
    _admin: dict = Depends(require_admin), _rate_limit: None = Depends(admin_rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """The embedding providers, configured apart from the text-generation ones."""
    from ..rag.embeddings import (
        CANONICAL_DIMENSIONS,
        EMBEDDING_PROVIDERS,
        corpus_stats,
        get_active_embedding_config,
        list_embedding_configs,
    )

    configs = {c["provider"]: c for c in await list_embedding_configs(db)}
    providers = []
    for name in EMBEDDING_PROVIDERS:
        config = configs.get(name, {})
        providers.append(
            EmbeddingProviderStatus(
                provider=name,
                model=config.get("model"),
                has_key=bool(config.get("has_key")),
                enabled=bool(config.get("enabled", True)),
                active=bool(config.get("active")),
                base_url=config.get("base_url"),
            )
        )

    active = await get_active_embedding_config(db)
    stats = await corpus_stats(db)
    return EmbeddingConfigOverview(
        providers=providers,
        active_provider=active["provider"] if active else None,
        canonical_dimensions=CANONICAL_DIMENSIONS,
        chunks_total=stats["chunks_total"],
        chunks_with_vector=stats["chunks_with_vector"],
        source="admin" if active else "fallback",
    )


@router.put("/embeddings/{provider}", response_model=EmbeddingProviderStatus)
async def admin_embedding_update(
    provider: str,
    body: EmbeddingProviderUpdate,
    _admin: dict = Depends(require_admin), _rate_limit: None = Depends(admin_rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """Store/clear the embedding key, pick the model, activate the provider."""
    from ..rag.embeddings import EMBEDDING_PROVIDERS, save_embedding_config

    if provider not in EMBEDDING_PROVIDERS:
        raise HTTPException(
            status_code=404, detail=f"Unknown embedding provider: {provider}"
        )
    try:
        result = await save_embedding_config(
            provider,
            model=body.model,
            api_key=body.api_key.strip() if body.api_key is not None else None,
            base_url=body.base_url,
            enabled=body.enabled,
            activate=body.activate,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    logger.info(
        "Admin updated embedding provider %s (model=%s active=%s)",
        provider,
        result["model"],
        result["active"],
    )
    return EmbeddingProviderStatus(
        provider=result["provider"],
        model=result["model"],
        has_key=result["has_key"],
        enabled=result["enabled"],
        active=result["active"],
        base_url=result["base_url"],
    )


@router.get("/embeddings/models")
async def admin_embedding_models(
    provider: str,
    api_key: str | None = None,
    base_url: str | None = None,
    _admin: dict = Depends(require_admin),
    _rate_limit: None = Depends(admin_rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """List the live model list from a provider's API.

    There is no built-in fallback: if the provider cannot answer, the admin
    sees the reason instead of a dropdown that looks legitimately empty.
    """
    from ..rag.embeddings import get_embedding_config, list_available_models

    # A refresh must work with the key already stored — asking the admin to
    # paste it again just to browse models is how the dropdown stayed empty.
    saved = await get_embedding_config(provider, db=db)
    effective_key = api_key or (saved or {}).get("key")
    effective_base = base_url or (saved or {}).get("base_url")

    try:
        models = await list_available_models(
            provider, api_key=effective_key, base_url=effective_base
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"provider": provider, "models": models}


@router.post("/embeddings/test", response_model=EmbeddingTestResult)
async def admin_embedding_test(
    body: EmbeddingTestRequest | None = None,
    _admin: dict = Depends(require_admin), _rate_limit: None = Depends(admin_rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """Embed one sample string and report the width that came back."""
    from ..rag.embeddings import EMBEDDING_PROVIDERS, test_embedding_provider

    request = body or EmbeddingTestRequest()
    if request.provider and request.provider not in EMBEDDING_PROVIDERS:
        raise HTTPException(
            status_code=404, detail=f"Unknown embedding provider: {request.provider}"
        )
    result = await test_embedding_provider(request.provider, db=db)
    return EmbeddingTestResult(**result)


@router.put("/llm/{provider}/models/{model_id:path}", response_model=LlmModelStatus)
async def admin_llm_model_update(
    provider: str,
    model_id: str,
    body: LlmModelUpdate,
    _admin: dict = Depends(require_admin), _rate_limit: None = Depends(admin_rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """Enable/disable one model for tenants. Creates the row on first touch."""
    from datetime import datetime, timezone

    from ..llm.models import ModelConfig
    from ..llm.providers import registry
    from ..llm.providers.registry import get_effective_model

    # A custom model may have been created by another worker since this
    # process booted; load the current rows before deciding it is unknown.
    await registry.refresh_provider_keys_from_session(db)
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
    _admin: dict = Depends(require_admin), _rate_limit: None = Depends(admin_rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """Live-test one exact model (tiny completion, ~20 tokens) and record it."""
    import time as _time2
    from datetime import datetime, timezone

    from ..llm.gateway import LLMMessage, complete
    from ..llm.models import ModelConfig
    from ..llm.providers import registry
    from ..llm.providers.registry import get_effective_model

    await registry.refresh_provider_keys_from_session(db)
    info = get_effective_model(model_id)
    if info is None or info.provider != provider:
        raise HTTPException(status_code=404, detail=f"Unknown model: {model_id}")
    if registry.resolve_provider_key(provider)[0] is None:
        return LlmModelTestResult(model_id=model_id, ok=False, detail="no API key configured")

    start = _time2.monotonic()
    ok, detail, reply = False, "", ""
    try:
        resp = await complete(
            model=model_id,
            messages=[LLMMessage(role="user", content="Reply with exactly: OK")],
            system_prompt="You are a connectivity probe. Reply with exactly: OK",
            temperature=0.1,
            max_tokens=20,
            tenant_id=None,
            purpose="admin.test",
        )
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
    _admin: dict = Depends(require_admin), _rate_limit: None = Depends(admin_rate_limit),
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

    await registry.refresh_provider_keys_from_session(db)
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
    _admin: dict = Depends(require_admin), _rate_limit: None = Depends(admin_rate_limit),
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
    await registry.refresh_provider_keys_from_session(db)
    logger.info("Admin deleted custom model %s", model_id)


class DialectCreate(BaseModel):
    code: str = Field(..., min_length=2, max_length=30, pattern="^[A-Za-z0-9-]+$")
    dialect_en: str = Field(..., min_length=2, max_length=120)
    dialect_ar: str = Field(..., min_length=2, max_length=120)
    examples: list[str] = Field(default_factory=list, max_length=10)


class DialectOut(BaseModel):
    code: str
    dialect_en: str
    dialect_ar: str
    examples: list[str]


@router.post("/dialects", response_model=DialectOut, status_code=201)
async def admin_dialect_create(
    body: DialectCreate,
    _admin: dict = Depends(require_admin), _rate_limit: None = Depends(admin_rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """Add a dialect to the catalog. Code must be unique ('auto' is reserved)."""
    from ..review_engine.models import Dialect

    code = body.code.strip().lower()
    if code == "auto":
        raise HTTPException(status_code=422, detail="'auto' is reserved.")
    existing = await db.execute(select(Dialect).where(Dialect.code == code))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"Dialect '{code}' already exists.")
    row = Dialect(
        code=code,
        dialect_en=body.dialect_en.strip(),
        dialect_ar=body.dialect_ar.strip(),
        examples=[e.strip() for e in body.examples if e and e.strip()][:10],
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    logger.info("Admin added dialect %s", code)
    return DialectOut(
        code=row.code, dialect_en=row.dialect_en,
        dialect_ar=row.dialect_ar, examples=list(row.examples or []),
    )


@router.delete("/dialects/{code}", status_code=204)
async def admin_dialect_delete(
    code: str,
    _admin: dict = Depends(require_admin), _rate_limit: None = Depends(admin_rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """Delete a dialect row. Channels still referencing the code fall back
    to 'auto' behavior — nothing breaks, generation just loses the dialect
    flavor until reconfigured."""
    from ..review_engine.models import Dialect

    row = await db.get(Dialect, code.strip().lower())
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown dialect: {code}")
    await db.delete(row)
    await db.commit()
    logger.info("Admin deleted dialect %s", code)


@router.get("/dialects")
async def admin_dialects_list(
    _admin: dict = Depends(require_admin), _rate_limit: None = Depends(admin_rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """Dialect catalog (admin view; 'auto' pseudo-row included)."""
    from ..review_engine.dialects import list_dialects as _list_dialects

    rows = await _list_dialects(db)
    return [
        {"code": "auto", "dialect_en": "Auto (match the review)", "dialect_ar": "تلقائي", "examples": []}
    ] + [
        {"code": r.code, "dialect_en": r.dialect_en, "dialect_ar": r.dialect_ar, "examples": list(r.examples or [])}
        for r in rows
    ]


@router.get("/tones")
async def admin_tones_list(
    _admin: dict = Depends(require_admin), _rate_limit: None = Depends(admin_rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """Tone catalog (admin view)."""
    from ..review_engine.models import Tone

    rows = (
        await db.execute(select(Tone).order_by(Tone.code))
    ).scalars().all()
    return [
        {"code": r.code, "label": r.label, "description": r.description or ""}
        for r in rows
    ]


class ToneCreate(BaseModel):
    code: str = Field(..., min_length=2, max_length=30, pattern="^[A-Za-z0-9-]+$")
    label: str = Field(..., min_length=2, max_length=120)
    description: str = Field(default="", max_length=255)


class ToneOut(BaseModel):
    code: str
    label: str
    description: str


@router.post("/tones", response_model=ToneOut, status_code=201)
async def admin_tone_create(
    body: ToneCreate,
    _admin: dict = Depends(require_admin), _rate_limit: None = Depends(admin_rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """Add a response tone to the catalog. Code must be unique."""
    from ..review_engine.models import Tone

    code = body.code.strip().lower()
    existing = await db.execute(select(Tone).where(Tone.code == code))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"Tone '{code}' already exists.")
    row = Tone(code=code, label=body.label.strip(), description=body.description.strip())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    logger.info("Admin added tone %s", code)
    return ToneOut(code=row.code, label=row.label, description=row.description or "")


class ToneUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=255)


@router.put("/tones/{code}", response_model=ToneOut)
async def admin_tone_update(
    code: str,
    body: ToneUpdate,
    _admin: dict = Depends(require_admin), _rate_limit: None = Depends(admin_rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """Edit a tone's label/description. The code itself is immutable —
    channels reference it, so renaming would orphan them; delete + recreate
    instead (channels on a deleted code keep working untouched)."""
    from ..review_engine.models import Tone

    row = await db.get(Tone, code.strip().lower())
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown tone: {code}")
    if body.label is not None:
        row.label = body.label.strip()
    if body.description is not None:
        row.description = body.description.strip()
    await db.commit()
    await db.refresh(row)
    logger.info("Admin updated tone %s", row.code)
    return ToneOut(code=row.code, label=row.label, description=row.description or "")


@router.delete("/tones/{code}", status_code=204)
async def admin_tone_delete(
    code: str,
    _admin: dict = Depends(require_admin), _rate_limit: None = Depends(admin_rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """Delete a tone row. Channels still referencing the code keep their
    stored string — generation reads it as-is."""
    from ..review_engine.models import Tone

    row = await db.get(Tone, code.strip().lower())
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown tone: {code}")
    await db.delete(row)
    await db.commit()
    logger.info("Admin deleted tone %s", code)


@router.get("/models", response_model=list[SavedModel])
async def admin_models_list(
    _admin: dict = Depends(require_admin), _rate_limit: None = Depends(admin_rate_limit),
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
    _admin: dict = Depends(require_admin), _rate_limit: None = Depends(admin_rate_limit),
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

# Voice-engine admin is part of the TTS capability. Mount it here so it
# shares this router's auth and rate limit without TTS importing admin.
from ..tts.admin_router import router as tts_admin_router

router.include_router(
    tts_admin_router,
    dependencies=[Depends(require_admin), Depends(admin_rate_limit)],
)


# ---------------------------------------------------------------------------
# Operator management + audit log
# ---------------------------------------------------------------------------

class OperatorOut(BaseModel):
    id: str
    username: str
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None


class OperatorCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=8, max_length=256)
    role: str = Field(default="operator", pattern="^(operator|superadmin)$")


class OperatorUpdate(BaseModel):
    is_active: bool | None = None
    role: str | None = Field(default=None, pattern="^(operator|superadmin)$")
    password: str | None = Field(default=None, min_length=8, max_length=256)


class AuditLogOut(BaseModel):
    id: str
    operator_id: str | None = None
    operator_username: str | None = None
    action: str
    method: str
    path: str
    status_code: int
    ip: str | None = None
    created_at: datetime


@router.get("/operators", response_model=list[OperatorOut])
async def list_operators(_admin=Depends(require_admin)):
    from sqlalchemy import select

    from ...database import async_session
    from .models import PlatformOperator

    async with async_session() as db:
        rows = (await db.execute(select(PlatformOperator).order_by(PlatformOperator.created_at))).scalars().all()
        return [
            OperatorOut(
                id=r.id, username=r.username, role=r.role, is_active=r.is_active,
                created_at=r.created_at, last_login_at=r.last_login_at,
            )
            for r in rows
        ]


@router.post("/operators", response_model=OperatorOut, status_code=status.HTTP_201_CREATED)
async def create_operator(body: OperatorCreate, _admin=Depends(require_admin)):
    from sqlalchemy import select

    from ...database import async_session
    from .models import AdminAuditLog, PlatformOperator

    async with async_session() as db:
        existing = (await db.execute(
            select(PlatformOperator).where(PlatformOperator.username == body.username)
        )).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(status_code=409, detail="Username already exists.")
        op_row = PlatformOperator(
            username=body.username,
            password_hash=hash_password(body.password),
            role=body.role,
            is_active=True,
        )
        db.add(op_row)
        await db.commit()
        await db.refresh(op_row)
        try:
            db.add(AdminAuditLog(
                operator_id=_admin.get("operator_id"),
                operator_username=_admin.get("username"),
                action="operator.create",
                method="POST",
                path="/api/v1/admin/operators",
                status_code=201,
                detail=f"created operator {body.username} role={body.role}",
            ))
            await db.commit()
        except Exception as e:
            logger.warning("Audit log write failed: %s", e)
        return OperatorOut(
            id=op_row.id, username=op_row.username, role=op_row.role,
            is_active=op_row.is_active, created_at=op_row.created_at,
            last_login_at=op_row.last_login_at,
        )


@router.patch("/operators/{operator_id}", response_model=OperatorOut)
async def update_operator(operator_id: str, body: OperatorUpdate, _admin=Depends(require_admin)):
    from ...database import async_session
    from .models import AdminAuditLog, PlatformOperator

    async with async_session() as db:
        row = await db.get(PlatformOperator, operator_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Operator not found.")
        if body.is_active is not None:
            row.is_active = body.is_active
        if body.role is not None:
            row.role = body.role
        if body.password is not None:
            row.password_hash = hash_password(body.password)
        await db.commit()
        await db.refresh(row)
        try:
            db.add(AdminAuditLog(
                operator_id=_admin.get("operator_id"),
                operator_username=_admin.get("username"),
                action="operator.update",
                method="PATCH",
                path=f"/api/v1/admin/operators/{operator_id}",
                status_code=200,
                detail=f"updated operator {row.username}",
            ))
            await db.commit()
        except Exception as e:
            logger.warning("Audit log write failed: %s", e)
        return OperatorOut(
            id=row.id, username=row.username, role=row.role,
            is_active=row.is_active, created_at=row.created_at,
            last_login_at=row.last_login_at,
        )


@router.get("/audit-log", response_model=list[AuditLogOut])
async def list_audit_log(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _admin=Depends(require_admin),
):
    from sqlalchemy import select

    from ...database import async_session
    from .models import AdminAuditLog

    async with async_session() as db:
        rows = (await db.execute(
            select(AdminAuditLog).order_by(AdminAuditLog.created_at.desc())
            .offset(offset).limit(limit)
        )).scalars().all()
        return [
            AuditLogOut(
                id=r.id, operator_id=r.operator_id, operator_username=r.operator_username,
                action=r.action, method=r.method, path=r.path, status_code=r.status_code,
                ip=r.ip, created_at=r.created_at,
            )
            for r in rows
        ]

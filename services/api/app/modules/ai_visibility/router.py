"""Tenant-scoped AI visibility prompt CRUD endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...core.deps import get_db
from ..auth.rate_limit import rate_limit
from ..team.context import TenantContext, require_perm
from . import service
from .models import AiVisibilityPrompt
from .schemas import PromptIn, PromptListOut, PromptOut, PromptPatch, RunIn, RunOut

router = APIRouter(prefix="/api/v1/ai-visibility", tags=["ai-visibility"])

# Prompt creation is cheap but writes durable rows; bound bursts per workspace.
PROMPT_CREATE_RATE_LIMIT = 60
PROMPT_CREATE_RATE_WINDOW_SECONDS = 60
RUN_CREATE_RATE_LIMIT = 30
RUN_CREATE_RATE_WINDOW_SECONDS = 60


def _out(row: AiVisibilityPrompt) -> PromptOut:
    return PromptOut(
        id=row.id,
        channel_id=row.channel_id,
        title=row.title,
        prompt_text=row.prompt_text,
        intent=row.intent,
        is_active=row.is_active,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


@router.get("/prompts", response_model=PromptListOut)
async def list_prompts(
    channel_id: str = Query(min_length=1, max_length=36),
    include_archived: bool = False,
    ctx: TenantContext = Depends(require_perm("analytics.view")),
    db: AsyncSession = Depends(get_db),
) -> PromptListOut:
    try:
        rows = await service.list_prompts(
            db, ctx.tenant_id, channel_id, include_archived
        )
    except service.OwnedChannelRequired as exc:
        raise HTTPException(404, "channel_not_found") from exc
    return PromptListOut(items=[_out(row) for row in rows])


@router.post("/prompts", response_model=PromptOut, status_code=201)
async def create_prompt(
    body: PromptIn,
    ctx: TenantContext = Depends(require_perm("ai.edit")),
    db: AsyncSession = Depends(get_db),
) -> PromptOut:
    if not settings.TESTING and not await rate_limit(
        f"ai-vis:prompt:{ctx.tenant_id}",
        PROMPT_CREATE_RATE_LIMIT,
        PROMPT_CREATE_RATE_WINDOW_SECONDS,
        fail_closed=True,
    ):
        raise HTTPException(429, "too_many_requests")
    try:
        row = await service.create_prompt(
            db,
            ctx.tenant_id,
            channel_id=body.channel_id,
            title=body.title,
            prompt_text=body.prompt_text,
            intent=body.intent,
            created_by=ctx.user.id,
        )
    except service.OwnedChannelRequired as exc:
        raise HTTPException(404, "channel_not_found") from exc
    except service.PromptLimitReached as exc:
        raise HTTPException(409, str(exc)) from exc
    except service.DuplicatePrompt as exc:
        raise HTTPException(409, str(exc)) from exc
    return _out(row)


@router.patch("/prompts/{prompt_id}", response_model=PromptOut)
async def patch_prompt(
    prompt_id: str,
    body: PromptPatch,
    ctx: TenantContext = Depends(require_perm("ai.edit")),
    db: AsyncSession = Depends(get_db),
) -> PromptOut:
    try:
        row = await service.update_prompt(db, ctx.tenant_id, prompt_id, body)
    except service.PromptLimitReached as exc:
        raise HTTPException(409, str(exc)) from exc
    except service.DuplicatePrompt as exc:
        raise HTTPException(409, str(exc)) from exc
    if row is None:
        raise HTTPException(404, "prompt_not_found")
    return _out(row)


@router.delete("/prompts/{prompt_id}", status_code=204)
async def remove_prompt(
    prompt_id: str,
    ctx: TenantContext = Depends(require_perm("ai.edit")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    if not await service.delete_prompt(db, ctx.tenant_id, prompt_id):
        raise HTTPException(404, "prompt_not_found")
    return Response(status_code=204)


def _run_out(row) -> RunOut:
    return RunOut(
        id=row.id,
        channel_id=row.channel_id,
        prompt_id=row.prompt_id,
        prompt_snapshot=row.prompt_snapshot,
        locale=row.locale,
        status=row.status,
        job_id=row.job_id,
        validation_status=row.validation_status,
        error=row.error,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


@router.post("/runs", response_model=RunOut, status_code=201)
async def create_run(
    body: RunIn,
    ctx: TenantContext = Depends(require_perm("ai.edit")),
    db: AsyncSession = Depends(get_db),
) -> RunOut:
    if not settings.TESTING and not await rate_limit(
        f"ai-vis:run:{ctx.tenant_id}",
        RUN_CREATE_RATE_LIMIT,
        RUN_CREATE_RATE_WINDOW_SECONDS,
        fail_closed=True,
    ):
        raise HTTPException(429, "too_many_requests")
    try:
        row = await service.create_run(
            db,
            ctx.tenant_id,
            body.channel_id,
            body.prompt_id,
            locale="ar" if getattr(ctx.user, "language", None) == "ar" else "en",
        )
    except service.OwnedChannelRequired as exc:
        raise HTTPException(404, "channel_not_found") from exc
    except service.PromptNotOwned as exc:
        raise HTTPException(404, "prompt_not_found") from exc
    except service.PromptInactive as exc:
        raise HTTPException(409, str(exc)) from exc
    return _run_out(row)

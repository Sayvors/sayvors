"""Tenant-scoped AI visibility prompt CRUD endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...core.deps import get_db
from ..auth.rate_limit import rate_limit
from ..billing.budget import get_balance
from ..billing.entitlements import check_feature, get_entitlements
from ..team.context import (
    CHANNEL_LEVEL_EDIT,
    CHANNEL_LEVEL_NONE,
    TenantContext,
    require_perm,
)
from . import service
from .models import AiVisibilityPrompt
from .schemas import (
    OverviewOut,
    PromptIn,
    PromptListOut,
    PromptOut,
    PromptPatch,
    RunDetailOut,
    RunIn,
    RunListItem,
    RunListOut,
    RunOut,
    SourceOut,
)

router = APIRouter(prefix="/api/v1/ai-visibility", tags=["ai-visibility"])

# Prompt creation is cheap but writes durable rows; bound bursts per workspace.
PROMPT_CREATE_RATE_LIMIT = 60
PROMPT_CREATE_RATE_WINDOW_SECONDS = 60
RUN_CREATE_RATE_LIMIT = 30
RUN_CREATE_RATE_WINDOW_SECONDS = 60


def _authorize_channel(ctx: TenantContext, channel_id: str, *, write: bool) -> None:
    level = ctx.channel_level(channel_id)
    if (write and level != CHANNEL_LEVEL_EDIT) or (
        not write and level == CHANNEL_LEVEL_NONE
    ):
        # Do not reveal whether an inaccessible branch exists.
        raise HTTPException(404, "channel_not_found")


async def _authorize_prompt(
    db: AsyncSession, ctx: TenantContext, prompt_id: str, *, write: bool
):
    prompt = await service.get_prompt(db, ctx.tenant_id, prompt_id)
    if prompt is None:
        raise HTTPException(404, "prompt_not_found")
    _authorize_channel(ctx, prompt.channel_id, write=write)
    return prompt


async def _authorize_run(
    db: AsyncSession, ctx: TenantContext, run_id: str, *, write: bool
):
    run, _sources = await service.get_run(db, ctx.tenant_id, run_id)
    if run is None:
        raise HTTPException(404, "run_not_found")
    _authorize_channel(ctx, run.channel_id, write=write)
    return run


async def _preflight_research(
    ctx: TenantContext, db: AsyncSession, depth: str
) -> None:
    await check_feature(ctx.tenant_id, "ai_replies")
    ent = await get_entitlements(ctx.tenant_id, db)
    limit = (
        ent.max_deep_research_month
        if depth == "deep"
        else ent.max_quick_research_month
    )
    if limit is not None:
        used = await service.monthly_research_count(db, ctx.tenant_id, depth)
        if used >= limit:
            raise HTTPException(
                403,
                (
                    f"Monthly {depth} research limit reached "
                    f"({used}/{limit}). Upgrade your plan or wait until next month."
                ),
                headers={"X-Entitlement-Denied": f"{depth}_research"},
            )
    balance = await get_balance(ctx.tenant_id)
    if balance is None:
        raise HTTPException(503, "credit_balance_unavailable")
    if balance <= 0:
        raise HTTPException(402, "insufficient_ai_credits")


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
    _authorize_channel(ctx, channel_id, write=False)
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
    _authorize_channel(ctx, body.channel_id, write=True)
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
    await _authorize_prompt(db, ctx, prompt_id, write=True)
    try:
        row = await service.update_prompt(db, ctx.tenant_id, prompt_id, body)
    except service.PromptLimitReached as exc:
        raise HTTPException(409, str(exc)) from exc
    except service.PromptTextLocked as exc:
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
    await _authorize_prompt(db, ctx, prompt_id, write=True)
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
        research_depth=row.research_depth or "quick",
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
    _authorize_channel(ctx, body.channel_id, write=True)
    if not settings.TESTING and not await rate_limit(
        f"ai-vis:run:{ctx.tenant_id}",
        RUN_CREATE_RATE_LIMIT,
        RUN_CREATE_RATE_WINDOW_SECONDS,
        fail_closed=True,
    ):
        raise HTTPException(429, "too_many_requests")
    existing = await service.get_active_run(
        db, ctx.tenant_id, body.prompt_id, body.channel_id
    )
    if existing is not None:
        return _run_out(existing)
    await _preflight_research(ctx, db, body.depth)
    try:
        row = await service.create_run(
            db,
            ctx.tenant_id,
            body.channel_id,
            body.prompt_id,
            locale="ar" if getattr(ctx.user, "language", None) == "ar" else "en",
            depth=body.depth,
        )
    except service.OwnedChannelRequired as exc:
        raise HTTPException(404, "channel_not_found") from exc
    except service.PromptNotOwned as exc:
        raise HTTPException(404, "prompt_not_found") from exc
    except service.PromptInactive as exc:
        raise HTTPException(409, str(exc)) from exc
    except service.RetryCooldown as exc:
        raise HTTPException(
            429, str(exc), headers={"Retry-After": "5"}
        ) from exc
    except service.RetryLimitReached as exc:
        raise HTTPException(
            409, str(exc), headers={"Retry-After": "3600"}
        ) from exc
    return _run_out(row)


@router.get("/overview", response_model=OverviewOut)
async def overview(
    channel_id: str = Query(min_length=1, max_length=36),
    days: int = Query(default=30, ge=0, le=3650),
    ctx: TenantContext = Depends(require_perm("analytics.view")),
    db: AsyncSession = Depends(get_db),
) -> OverviewOut:
    _authorize_channel(ctx, channel_id, write=False)
    try:
        return OverviewOut(
            **await service.overview(db, ctx.tenant_id, channel_id, days)
        )
    except service.OwnedChannelRequired as exc:
        raise HTTPException(404, "channel_not_found") from exc


@router.get("/runs", response_model=RunListOut)
async def list_runs(
    channel_id: str = Query(min_length=1, max_length=36),
    status: str | None = Query(default=None, max_length=24),
    prompt_id: str | None = Query(default=None, max_length=36),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    ctx: TenantContext = Depends(require_perm("analytics.view")),
    db: AsyncSession = Depends(get_db),
) -> RunListOut:
    _authorize_channel(ctx, channel_id, write=False)
    try:
        rows, total = await service.list_runs(
            db,
            ctx.tenant_id,
            channel_id,
            status=status,
            prompt_id=prompt_id,
            limit=limit,
            offset=offset,
        )
    except service.OwnedChannelRequired as exc:
        raise HTTPException(404, "channel_not_found") from exc
    return RunListOut(
        total=total,
        items=[
            RunListItem(
                id=run.id,
                channel_id=run.channel_id,
                prompt_id=run.prompt_id,
                prompt_title=title,
                status=run.status,
                mentioned=run.mentioned,
                cited=run.cited,
                recommended=run.recommended,
                incorrect=run.incorrect,
                source_count=run.source_count,
                validation_status=run.validation_status,
                created_at=run.created_at.isoformat(),
                completed_at=(
                    run.completed_at.isoformat() if run.completed_at else None
                ),
            )
            for run, title in rows
        ],
    )


@router.get("/runs/{run_id}", response_model=RunDetailOut)
async def run_detail(
    run_id: str,
    ctx: TenantContext = Depends(require_perm("analytics.view")),
    db: AsyncSession = Depends(get_db),
) -> RunDetailOut:
    await _authorize_run(db, ctx, run_id, write=False)
    run, source_rows = await service.get_run(db, ctx.tenant_id, run_id)
    if run is None:
        raise HTTPException(404, "run_not_found")
    return RunDetailOut(
        **_run_out(run).model_dump(),
        answer_text=run.answer_text,
        mentioned=run.mentioned,
        cited=run.cited,
        recommended=run.recommended,
        incorrect=run.incorrect,
        evidence_coverage=run.evidence_coverage,
        competitor_mentions=run.competitor_mentions,
        claims=run.claims_json,
        actions=run.actions_json,
        sources=[
            SourceOut(
                id=row.id,
                label=f"S{row.position + 1}",
                position=row.position,
                url=row.url,
                title=row.title,
                snippet=row.snippet,
                excerpt=row.excerpt,
                fetch_error=row.fetch_error,
            )
            for row in source_rows
        ],
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
    )


@router.post("/runs/{run_id}/retry", response_model=RunOut, status_code=201)
async def retry_run(
    run_id: str,
    ctx: TenantContext = Depends(require_perm("ai.edit")),
    db: AsyncSession = Depends(get_db),
) -> RunOut:
    run = await _authorize_run(db, ctx, run_id, write=True)
    if run.status in service.ACTIVE_RUN_STATUSES or run.status == "completed":
        return _run_out(run)
    if not settings.TESTING and not await rate_limit(
        f"ai-vis:run:{ctx.tenant_id}",
        RUN_CREATE_RATE_LIMIT,
        RUN_CREATE_RATE_WINDOW_SECONDS,
        fail_closed=True,
    ):
        raise HTTPException(429, "too_many_requests")
    await _preflight_research(ctx, db, run.research_depth or "quick")
    try:
        row = await service.retry_run(
            db,
            ctx.tenant_id,
            run_id,
            locale="ar" if getattr(ctx.user, "language", None) == "ar" else "en",
        )
    except service.PromptInactive as exc:
        raise HTTPException(409, str(exc)) from exc
    except service.RetryCooldown as exc:
        raise HTTPException(
            429, str(exc), headers={"Retry-After": "5"}
        ) from exc
    except service.RetryLimitReached as exc:
        raise HTTPException(
            409, str(exc), headers={"Retry-After": "3600"}
        ) from exc
    if row is None:
        raise HTTPException(404, "run_not_found")
    return _run_out(row)


@router.delete("/runs", status_code=204)
async def clear_runs(
    channel_id: str = Query(min_length=1, max_length=36),
    ctx: TenantContext = Depends(require_perm("ai.edit")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    _authorize_channel(ctx, channel_id, write=True)
    await service.clear_terminal_runs(db, ctx.tenant_id, channel_id)
    return Response(status_code=204)


@router.delete("/runs/{run_id}", status_code=204)
async def delete_run(
    run_id: str,
    ctx: TenantContext = Depends(require_perm("ai.edit")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await _authorize_run(db, ctx, run_id, write=True)
    try:
        deleted = await service.delete_run(db, ctx.tenant_id, run_id)
    except service.ActiveRunDeletion as exc:
        raise HTTPException(409, str(exc)) from exc
    if not deleted:
        raise HTTPException(404, "run_not_found")
    return Response(status_code=204)

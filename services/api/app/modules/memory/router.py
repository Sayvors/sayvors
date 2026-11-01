"""Review queue + toggle for cumulative conversation memory.

Access is `ai.edit`: this is a workspace-level knowledge surface, and an
approved memory changes what every future customer is told.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_db
from ..team.context import TenantContext, require_perm
from ..users.models import User
from .models import ConversationMemory
from .service import list_memories, memory_enabled, review_memory

router = APIRouter(prefix="/api/v1/memory", tags=["memory"])


class MemoryOut(BaseModel):
    id: str
    channel_id: str
    summary: str
    outcome: str | None = None
    facts: list[str] = []
    status: str
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    created_at: str
    updated_at: str


class MemoryListOut(BaseModel):
    memories: list[MemoryOut]
    total: int
    pending_count: int
    enabled: bool


class MemoryUpdate(BaseModel):
    status: str | None = Field(None, pattern="^(pending|approved|rejected)$")
    summary: str | None = Field(None, max_length=4000)
    outcome: str | None = Field(None, max_length=300)
    facts: list[str] | None = Field(None, max_length=8)


class MemorySettings(BaseModel):
    enabled: bool


def _to_out(row: ConversationMemory) -> MemoryOut:
    return MemoryOut(
        id=row.id,
        channel_id=row.channel_id,
        summary=row.summary,
        outcome=row.outcome,
        facts=row.facts or [],
        status=row.status,
        reviewed_by=row.reviewed_by,
        reviewed_at=(
            row.reviewed_at.isoformat() if row.reviewed_at else None
        ),
        created_at=row.created_at.isoformat() if row.created_at else "",
        updated_at=row.updated_at.isoformat() if row.updated_at else "",
    )


async def _enabled(db: AsyncSession, tenant_id: str) -> bool:
    return await memory_enabled(db, tenant_id)


@router.get("/settings", response_model=MemorySettings)
async def get_memory_settings(
    ctx: TenantContext = Depends(require_perm("ai.edit")),
    db: AsyncSession = Depends(get_db),
):
    return MemorySettings(enabled=await _enabled(db, ctx.tenant_id))


@router.patch("/settings", response_model=MemorySettings)
async def update_memory_settings(
    body: MemorySettings,
    ctx: TenantContext = Depends(require_perm("ai.edit")),
    db: AsyncSession = Depends(get_db),
):
    user = (
        await db.execute(select(User).where(User.id == ctx.tenant_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    user.ai_memory_enabled = bool(body.enabled)
    db.add(user)
    await db.commit()
    return MemorySettings(enabled=bool(user.ai_memory_enabled))


@router.get("", response_model=MemoryListOut)
async def list_memory_queue(
    status_filter: str | None = Query(
        None, alias="status", pattern="^(pending|approved|rejected)$"
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: TenantContext = Depends(require_perm("ai.edit")),
    db: AsyncSession = Depends(get_db),
):
    rows, total, pending = await list_memories(
        db,
        tenant_id=ctx.tenant_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return MemoryListOut(
        memories=[_to_out(row) for row in rows],
        total=total,
        pending_count=pending,
        enabled=await _enabled(db, ctx.tenant_id),
    )


@router.patch("/{memory_id}", response_model=MemoryOut)
async def update_memory(
    memory_id: str,
    body: MemoryUpdate,
    ctx: TenantContext = Depends(require_perm("ai.edit")),
    db: AsyncSession = Depends(get_db),
):
    try:
        row = await review_memory(
            db,
            tenant_id=ctx.tenant_id,
            memory_id=memory_id,
            actor_id=ctx.user.id,
            status=body.status,
            summary=body.summary,
            outcome=body.outcome,
            facts=body.facts,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found"
        )
    return _to_out(row)

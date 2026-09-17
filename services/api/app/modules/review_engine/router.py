"""Review engine API routes with SSE streaming progress."""
import json
import logging
from typing import Any, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_current_user, get_db
from ..users.models import User
from .models import ResponseStrategy, ReviewResponseLog
from .schemas import (
    ReviewEngineRequest,
    ReviewEngineResponse,
    ReviewStrategyOut,
    ReviewStrategyUpdate,
)
from .service import process_review, process_review_stream

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/review-engine", tags=["review-engine"])


@router.post("/generate", response_model=ReviewEngineResponse)
async def generate(
    req: ReviewEngineRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate an AI reply to a customer review using the strategy engine."""
    try:
        return await process_review(req, user.id, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/generate-stream")
async def generate_stream(
    req: ReviewEngineRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a review reply with real-time SSE progress events.

    Events emitted:
      - step: {step: "analyzing"|"strategies"|"tools"|"generating"|"validating"|"done", message: str}
      - tool_call: {tool: str, args: dict, result: str}
      - strategy: {id: str, name: str, reason: str}
      - response: {response_text: str, ...}
      - error: {message: str}
    """

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            async for event in process_review_stream(req, user.id, db):
                yield f"data: {json.dumps(event, default=str)}\n\n"
        except Exception as e:
            logger.exception("Review engine stream failed")
            yield f"data: {json.dumps({'step': 'error', 'message': str(e)[:300]})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class DialectOut(BaseModel):
    code: str
    dialect_en: str
    dialect_ar: str
    examples: list[str]


@router.get("/dialects", response_model=list[DialectOut])
async def list_dialects(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Arabic dialect catalog for reply localization (plus 'auto')."""
    from .dialects import list_dialects as _list_dialects

    rows = await _list_dialects(db)
    return [{"code": "auto", "dialect_en": "Auto (match the review)", "dialect_ar": "تلقائي", "examples": []}] + rows


@router.get("/strategies", response_model=list[ReviewStrategyOut])
async def list_strategies(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all response strategies."""
    result = await db.execute(select(ResponseStrategy).order_by(ResponseStrategy.priority.desc()))
    return result.scalars().all()


@router.get("/strategies/{strategy_id}", response_model=ReviewStrategyOut)
async def get_strategy(
    strategy_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single strategy by ID."""
    result = await db.execute(
        select(ResponseStrategy).where(ResponseStrategy.id == strategy_id)
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return strategy


@router.put("/strategies/{strategy_id}", response_model=ReviewStrategyOut)
async def update_strategy(
    strategy_id: str,
    body: ReviewStrategyUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update strategy settings (enable/disable, priority, instructions)."""
    result = await db.execute(
        select(ResponseStrategy).where(ResponseStrategy.id == strategy_id)
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    if body.enabled is not None:
        strategy.enabled = body.enabled
    if body.priority is not None:
        strategy.priority = body.priority
    if body.instructions is not None:
        strategy.instructions = body.instructions
    await db.commit()
    await db.refresh(strategy)
    return strategy


@router.get("/logs")
async def list_logs(
    limit: int = 20,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List recent response logs for this tenant."""
    result = await db.execute(
        select(ReviewResponseLog)
        .where(ReviewResponseLog.tenant_id == user.id)
        .order_by(ReviewResponseLog.created_at.desc())
        .limit(limit)
    )
    logs = result.scalars().all()
    return {"logs": logs, "total": len(logs)}

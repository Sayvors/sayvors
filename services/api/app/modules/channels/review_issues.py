
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_db
from ..review_engine.classification import (
    ISSUE_STATUSES,
    PRIMARY_CATEGORIES,
    PRIORITIES,
)
from ..team.context import TenantContext, require_perm
from .models import ReviewIssue
from .review_issue_events import notify_review_issue, publish_review_issue_event

router = APIRouter(prefix="/api/v1/reviews/issues", tags=["review-issues"])


class ReviewIssueOut(BaseModel):
    id: str
    tenant_id: str
    channel_id: str
    review_id: str
    ticket_number: str | None = None
    handoff_code: str | None = None
    rating: int
    primary_category: str
    subcategory: str
    subcategory_detail: str | None = None
    intent: str
    sentiment: str
    priority: str
    needs_attention: bool
    summary: str | None = None
    status: str
    reviewer_name: str | None = None
    review_text: str | None = None
    created_at: str
    resolved_at: str | None = None

    class Config:
        from_attributes = True


def _to_out(r) -> ReviewIssueOut:
    """Single serializer for both endpoints -- the two copies of this mapping
    had already drifted once (the list showed no ticket_number)."""
    return ReviewIssueOut(
        id=r.id,
        tenant_id=r.tenant_id,
        channel_id=r.channel_id,
        review_id=r.review_id,
        ticket_number=r.ticket_number,
        handoff_code=r.handoff_code,
        rating=r.rating,
        primary_category=r.primary_category,
        subcategory=r.subcategory,
        subcategory_detail=r.subcategory_detail,
        intent=r.intent,
        sentiment=r.sentiment,
        priority=r.priority,
        needs_attention=bool(r.needs_attention),
        summary=r.summary,
        status=r.status,
        reviewer_name=r.reviewer_name,
        review_text=r.review_text,
        created_at=r.created_at.isoformat() if r.created_at else "",
        resolved_at=r.resolved_at.isoformat() if r.resolved_at else None,
    )


class ReviewIssueListResponse(BaseModel):
    issues: list[ReviewIssueOut]
    total: int


@router.get("", response_model=ReviewIssueListResponse)
async def list_review_issues(
    status_filter: str | None = Query(None, alias="status"),
    priority_filter: str | None = Query(None, alias="priority"),
    channel_id: str | None = Query(None, alias="channel_id"),
    ticketed: bool = Query(True),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: TenantContext = Depends(require_perm("channels.view")),
    db: AsyncSession = Depends(get_db),
):
    conds = [ReviewIssue.tenant_id == ctx.tenant_id]
    if status_filter:
        conds.append(ReviewIssue.status == status_filter)
    if priority_filter:
        conds.append(ReviewIssue.priority == priority_filter)
    if channel_id:
        conds.append(ReviewIssue.channel_id == channel_id)
    if ticketed is True:
        conds.append(ReviewIssue.ticket_number.isnot(None))
    elif ticketed is False:
        conds.append(ReviewIssue.ticket_number.is_(None))

    total = (await db.execute(select(func.count()).select_from(ReviewIssue).where(*conds))).scalar_one()
    rows = (await db.execute(
        select(ReviewIssue).where(*conds)
        .order_by(ReviewIssue.created_at.desc())
        .offset(offset).limit(limit)
    )).scalars().all()

    return ReviewIssueListResponse(
        issues=[_to_out(r) for r in rows], total=total
    )


class IssueUpdate(BaseModel):
    status: str | None = None
    subcategory: str | None = None
    primary_category: str | None = None
    priority: str | None = None
    needs_attention: bool | None = None


# Validated against review_engine.classification's own tuples rather than a
# local copy -- a second literal list here would silently drift the day the
# taxonomy gains a status or priority.
VALID_STATUSES = set(ISSUE_STATUSES)
VALID_PRIORITIES = set(PRIORITIES)


@router.get("/by-ticket/{ticket_number}", response_model=ReviewIssueOut)
async def get_review_issue_by_ticket(
    ticket_number: str,
    ctx: TenantContext = Depends(require_perm("channels.view")),
    db: AsyncSession = Depends(get_db),
):
    """Resolve a customer-quoted ticket number to its issue.

    Always scoped to ctx.tenant_id -- ticket numbers are only unique within a
    tenant, so an unscoped lookup could surface another workspace's customer.
    """
    from ..review_engine.tickets import find_by_ticket

    row = await find_by_ticket(db, ctx.tenant_id, ticket_number)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue not found")
    return _to_out(row)


@router.post("/{issue_id}/handoff-code", response_model=ReviewIssueOut)
async def mint_handoff_code(
    issue_id: str,
    ctx: TenantContext = Depends(require_perm("channels.edit")),
    db: AsyncSession = Depends(get_db),
):
    """Mint (or return) the short code this customer quotes on WhatsApp.

    Idempotent — an issue that already has a code keeps it, because a code
    handed to a customer yesterday must not die overnight.

    Returns None-codes as a 422 rather than an error: praise and neutral
    chatter have nothing to hand off to, and a caller asking for a code on
    them is a bug worth surfacing loudly in the dashboard, not a crash.
    """
    from ..review_engine.handoff import ensure_handoff_code

    row = (await db.execute(
        select(ReviewIssue).where(
            ReviewIssue.id == issue_id,
            ReviewIssue.tenant_id == ctx.tenant_id,
        )
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue not found")

    code = await ensure_handoff_code(db, tenant_id=ctx.tenant_id, issue=row)
    if code is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This issue needs no attention, so it has nothing to hand off",
        )
    return _to_out(row)


@router.patch("/{issue_id}", response_model=ReviewIssueOut)
async def update_review_issue(
    issue_id: str,
    body: IssueUpdate,
    ctx: TenantContext = Depends(require_perm("channels.edit")),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        select(ReviewIssue).where(
            ReviewIssue.id == issue_id,
            ReviewIssue.tenant_id == ctx.tenant_id,
        )
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue not found")

    prev_status = row.status
    prev_attention = bool(row.needs_attention)

    if body.status is not None:
        if body.status not in VALID_STATUSES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bad status")
        row.status = body.status
        if body.status in {"resolved", "closed"}:
            from datetime import datetime, timezone
            row.resolved_at = datetime.now(timezone.utc)
    if body.primary_category is not None:
        if body.primary_category not in PRIMARY_CATEGORIES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bad category")
        row.primary_category = body.primary_category
    if body.priority is not None:
        if body.priority not in VALID_PRIORITIES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bad priority")
        row.priority = body.priority
    if body.subcategory is not None:
        row.subcategory = body.subcategory.strip() or "other"
    if body.needs_attention is not None:
        row.needs_attention = bool(body.needs_attention)
    db.add(row)
    await db.commit()
    await db.refresh(row)

    # Post-commit: a queue must never redraw from a change the database
    # rejected. Every edit is broadcast (the queue must stay honest), but
    # only a status or attention flip earns a bell entry — re-categorising a
    # ticket is bookkeeping, not news.
    await publish_review_issue_event(ctx.tenant_id, row, "updated")
    if row.status != prev_status or bool(row.needs_attention) != prev_attention:
        await notify_review_issue(
            db,
            tenant_id=ctx.tenant_id,
            issue=row,
            action="updated",
            actor_user_id=getattr(ctx.user, "id", None),
        )
    return _to_out(row)
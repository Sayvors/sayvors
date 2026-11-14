"""Staff registry API — employees per branch + per-employee review performance.

Endpoints (all owner/tenant-scoped via require_perm):
  GET    /api/v1/staff                     list employees (optional listing_id)
  POST   /api/v1/staff                     create employee (name, listing_id, aliases)
  PATCH  /api/v1/staff/{id}                rename / edit aliases / activate-deactivate
  DELETE /api/v1/staff/{id}                delete employee (mentions stay, NULL-linked)
  GET    /api/v1/staff/summary             per-employee performance for a window
  GET    /api/v1/staff/unmatched           grouped names that matched no employee
  POST   /api/v1/staff/unmatched/assign    retro-link one normalized name to an employee
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_db
from ..team.context import TenantContext, require_perm
from .models import ReviewStaffMention, StaffMember
from .staff_match import normalize_staff_name
from .staff_mentions import (
    link_unassigned_mentions,
    staff_summary,
    unmatched_names,
)

router = APIRouter(prefix="/api/v1/staff", tags=["staff"])


def _perm(ctx: TenantContext) -> None:
    """Team management permission guards every staff write; analytics read."""
    if not ctx.has("team.manage"):
        raise HTTPException(status_code=403, detail="You do not have permission to manage employees.")


class StaffIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    listing_id: str = Field(..., min_length=1, max_length=255)
    aliases: list[str] = Field(default_factory=list, max_length=20)


class StaffPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    listing_id: str | None = Field(None, min_length=1, max_length=255)
    aliases: list[str] | None = Field(None, max_length=20)
    active: bool | None = None


def _out(m: StaffMember) -> dict:
    return {
        "id": m.id,
        "listing_id": m.listing_id,
        "name": m.name,
        "aliases": m.aliases or [],
        "active": bool(m.active),
        "normalized_name": m.normalized_name,
    }


@router.get("")
async def list_staff(
    listing_id: str | None = Query(None, max_length=255),
    ctx: TenantContext = Depends(require_perm("team.manage")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(StaffMember).where(StaffMember.user_id == ctx.tenant_id)
    if listing_id:
        stmt = stmt.where(StaffMember.listing_id == listing_id)
    rows = (await db.execute(stmt.order_by(StaffMember.name))).scalars().all()
    return {"employees": [_out(m) for m in rows]}


@router.post("", status_code=201)
async def create_staff(
    body: StaffIn,
    ctx: TenantContext = Depends(require_perm("team.manage")),
    db: AsyncSession = Depends(get_db),
):
    key = normalize_staff_name(body.name)
    if not key:
        raise HTTPException(status_code=422, detail="That name has no usable characters.")
    existing = (
        await db.execute(
            select(StaffMember).where(
                StaffMember.user_id == ctx.tenant_id,
                StaffMember.listing_id == body.listing_id,
                StaffMember.normalized_name == key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="An employee with that name already exists at this branch.",
        )
    member = StaffMember(
        user_id=ctx.tenant_id,
        listing_id=body.listing_id,
        name=body.name.strip(),
        normalized_name=key,
        aliases=[a.strip() for a in body.aliases if a.strip()],
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return _out(member)


@router.patch("/{member_id}")
async def patch_staff(
    member_id: str,
    body: StaffPatch,
    ctx: TenantContext = Depends(require_perm("team.manage")),
    db: AsyncSession = Depends(get_db),
):
    member = (
        await db.execute(
            select(StaffMember).where(
                StaffMember.id == member_id, StaffMember.user_id == ctx.tenant_id
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=404, detail="Employee not found.")
    if body.name is not None:
        member.name = body.name.strip()
        member.normalized_name = normalize_staff_name(member.name)
    if body.listing_id is not None:
        member.listing_id = body.listing_id
    if body.aliases is not None:
        member.aliases = [a.strip() for a in body.aliases if a.strip()]
    if body.active is not None:
        member.active = body.active
    await db.commit()
    await db.refresh(member)
    return _out(member)


@router.delete("/{member_id}", status_code=204)
async def delete_staff(
    member_id: str,
    ctx: TenantContext = Depends(require_perm("team.manage")),
    db: AsyncSession = Depends(get_db),
):
    member = (
        await db.execute(
            select(StaffMember).where(
                StaffMember.id == member_id, StaffMember.user_id == ctx.tenant_id
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=404, detail="Employee not found.")
    await db.delete(member)
    # ON DELETE SET NULL moves their mentions to the unassigned bucket rather
    # than losing them — the owner can re-assign later.
    await db.commit()
    return None


@router.get("/summary")
async def get_summary(
    listing_id: str | None = Query(None, max_length=255),
    days: int = Query(30, ge=7, le=365),
    ctx: TenantContext = Depends(require_perm("team.view")),
    db: AsyncSession = Depends(get_db),
):
    rows = await staff_summary(
        db, user_id=ctx.tenant_id, listing_id=listing_id, days=days
    )
    return {"window_days": days, "employees": rows}


@router.get("/unmatched")
async def get_unmatched(
    ctx: TenantContext = Depends(require_perm("team.view")),
    db: AsyncSession = Depends(get_db),
):
    return {"names": await unmatched_names(db, user_id=ctx.tenant_id)}


@router.get("/{member_id}/mentions")
async def list_mentions(
    member_id: str,
    days: int = Query(90, ge=7, le=365),
    ctx: TenantContext = Depends(require_perm("team.view")),
    db: AsyncSession = Depends(get_db),
):
    """The reviews naming one employee — the details-page timeline."""
    member = (
        await db.execute(
            select(StaffMember).where(
                StaffMember.id == member_id, StaffMember.user_id == ctx.tenant_id
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=404, detail="Employee not found.")
    from datetime import datetime, timedelta, timezone

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        await db.execute(
            select(ReviewStaffMention)
            .where(
                ReviewStaffMention.user_id == ctx.tenant_id,
                ReviewStaffMention.staff_member_id == member_id,
                ReviewStaffMention.review_created_at >= cutoff,
            )
            .order_by(ReviewStaffMention.review_created_at.desc())
            .limit(200)
        )
    ).scalars().all()
    return {
        "employee": _out(member),
        "mentions": [
            {
                "review_id": m.review_id,
                "rating": m.rating,
                "sentiment": m.sentiment,
                "review_created_at": (
                    m.review_created_at.isoformat() if m.review_created_at else None
                ),
            }
            for m in rows
        ],
    }


class AssignIn(BaseModel):
    name_normalized: str = Field(..., min_length=1, max_length=120)
    staff_member_id: str = Field(..., min_length=1, max_length=36)


class BackfillIn(BaseModel):
    days: int = Field(90, ge=7, le=365)
    limit: int = Field(300, ge=1, le=1000)
    # Re-run meaning extraction (LLM) on stale rows — costs money, so it is
    # opt-in; the default backfill uses whatever meaning is already stored.
    reextract: bool = False


@router.post("/backfill")
async def run_backfill(
    body: BackfillIn,
    ctx: TenantContext = Depends(require_perm("team.manage")),
    db: AsyncSession = Depends(get_db),
):
    """Derive mentions from already-enriched reviews (last N days).

    Owner-triggered and bounded: idempotent, so re-running continues where
    the previous pass stopped (completed rows no longer qualify when
    reextract is on; with it off, rows are simply re-derived, which is
    idempotent by the unique constraint).
    """
    from .staff_mentions import backfill_staff_mentions

    result = await backfill_staff_mentions(
        db,
        user_id=ctx.tenant_id,
        days=body.days,
        limit=body.limit,
        reextract=body.reextract,
    )
    return result


@router.post("/unmatched/assign")
async def assign_unmatched(
    body: AssignIn,
    ctx: TenantContext = Depends(require_perm("team.manage")),
    db: AsyncSession = Depends(get_db),
):
    member = (
        await db.execute(
            select(StaffMember).where(
                StaffMember.id == body.staff_member_id,
                StaffMember.user_id == ctx.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=404, detail="Employee not found.")
    # Retro-link history, then record the unknown spelling as an alias so
    # future reviews using it keep matching (matching is keyed on the
    # normalized name; when the spelling normalizes differently from the
    # employee's stored name, only an alias bridges the gap).
    linked = await link_unassigned_mentions(
        db,
        user_id=ctx.tenant_id,
        name_normalized=body.name_normalized,
        staff_member_id=member.id,
    )
    display = (
        await db.execute(
            select(func.max(ReviewStaffMention.name_display)).where(
                ReviewStaffMention.user_id == ctx.tenant_id,
                ReviewStaffMention.name_normalized == body.name_normalized,
            )
        )
    ).scalar_one_or_none()
    display = str(display or "").strip()
    if display and normalize_staff_name(display) != member.normalized_name:
        aliases = [a.strip() for a in (member.aliases or [])]
        if display not in aliases:
            aliases.append(display[:120])
            member.aliases = aliases
    await db.commit()
    return {"linked": linked, "staff_member_id": member.id}

"""Staff registry API — employees per branch + per-employee review performance.

Endpoints (all owner/tenant-scoped via require_perm):
  GET    /api/v1/staff                     list employees (optional listing_id)
  POST   /api/v1/staff                     create employee (name, listing_id, aliases)
  PATCH  /api/v1/staff/{id}                rename / edit profile / activate-deactivate
  DELETE /api/v1/staff/{id}                delete employee (mentions stay, NULL-linked)
  GET    /api/v1/staff/{id}                profile: credit aggregate, AI analysis, reviews
  POST   /api/v1/staff/{id}/avatar         upload profile picture
  DELETE /api/v1/staff/{id}/avatar         remove profile picture
  GET    /api/v1/staff/summary             per-employee performance for a window
  GET    /api/v1/staff/unmatched           grouped names that matched no employee
  POST   /api/v1/staff/unmatched/assign    retro-link one normalized name to an employee
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_db
from ..profile.service import AVATAR_MAX_BYTES, _image_extension, _looks_like_image
from ..team.context import TenantContext, require_perm
from .models import ReviewInsight, ReviewStaffMention, StaffMember
from .staff_match import normalize_staff_name
from .staff_mentions import (
    link_unassigned_mentions,
    staff_summary,
    unmatched_names,
)
from .staff_profile import serialize_employee, staff_profile

router = APIRouter(prefix="/api/v1/staff", tags=["staff"])

logger = logging.getLogger(__name__)


def _perm(ctx: TenantContext) -> None:
    """Team management permission guards every staff write; analytics read."""
    if not ctx.has("team.manage"):
        raise HTTPException(status_code=403, detail="You do not have permission to manage employees.")


class StaffIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    listing_id: str = Field(..., min_length=1, max_length=255)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    job_title: str | None = Field(None, max_length=120)
    phone: str | None = Field(None, max_length=50)
    email: EmailStr | None = None
    bio: str | None = Field(None, max_length=2000)

    @field_validator("email", mode="before")
    @classmethod
    def _blank_email_is_none(cls, value):
        """A cleared contact field is absent, not an invalid address."""
        if isinstance(value, str) and not value.strip():
            return None
        return value


class StaffPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    listing_id: str | None = Field(None, min_length=1, max_length=255)
    aliases: list[str] | None = Field(None, max_length=20)
    job_title: str | None = Field(None, max_length=120)
    phone: str | None = Field(None, max_length=50)
    email: EmailStr | None = None
    bio: str | None = Field(None, max_length=2000)
    active: bool | None = None

    @field_validator("email", mode="before")
    @classmethod
    def _blank_email_is_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value


def _out(m: StaffMember) -> dict:
    return serialize_employee(m)


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
        job_title=(body.job_title or "").strip() or None,
        phone=(body.phone or "").strip() or None,
        email=str(body.email) if body.email else None,
        bio=(body.bio or "").strip() or None,
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
    if body.job_title is not None:
        member.job_title = body.job_title.strip() or None
    if body.phone is not None:
        member.phone = body.phone.strip() or None
    if "email" in body.model_fields_set:
        # An explicit null/blank clears the address; an omitted field is left
        # alone. The validator maps a blank string to None so both forms clear.
        member.email = str(body.email) if body.email else None
    if body.bio is not None:
        member.bio = body.bio.strip() or None
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


@router.get("/{member_id}")
async def get_staff_profile(
    member_id: str,
    days: int | None = Query(None, ge=7, le=365),
    ctx: TenantContext = Depends(require_perm("team.view")),
    db: AsyncSession = Depends(get_db),
):
    """One employee's profile: credit aggregate, AI analysis, credited reviews.

    ``days`` narrows the window (all-time when omitted). Reviews are only the
    ones that name this employee — the credit the review AI attributed to them.
    """
    data = await staff_profile(
        db, user_id=ctx.tenant_id, member_id=member_id, days=days
    )
    if data is None:
        raise HTTPException(status_code=404, detail="Employee not found.")
    return data


@router.get("/{member_id}/mentions")
async def list_mentions(
    member_id: str,
    days: int = Query(90, ge=7, le=365),
    ctx: TenantContext = Depends(require_perm("team.view")),
    db: AsyncSession = Depends(get_db),
):
    """The reviews naming one employee, with the AI's per-review read.

    Kept for callers that only need the timeline; the full profile
    (aggregate + analysis + reviews) is ``GET /{member_id}``.
    """
    member = (
        await db.execute(
            select(StaffMember).where(
                StaffMember.id == member_id, StaffMember.user_id == ctx.tenant_id
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=404, detail="Employee not found.")

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        await db.execute(
            select(ReviewStaffMention, ReviewInsight)
            .outerjoin(
                ReviewInsight,
                and_(
                    ReviewStaffMention.user_id == ReviewInsight.user_id,
                    ReviewStaffMention.channel_id == ReviewInsight.channel_id,
                    ReviewStaffMention.review_id == ReviewInsight.review_id,
                ),
            )
            .where(
                ReviewStaffMention.user_id == ctx.tenant_id,
                ReviewStaffMention.staff_member_id == member_id,
                ReviewStaffMention.review_created_at >= cutoff,
            )
            .order_by(ReviewStaffMention.review_created_at.desc())
            .limit(200)
        )
    ).all()

    def _ai(insight: ReviewInsight | None) -> dict | None:
        if insight is None or not isinstance(insight.meaning, dict):
            return None
        meaning = insight.meaning
        return {
            "intent": meaning.get("intent"),
            "subject": meaning.get("subject"),
            "problem": meaning.get("problem"),
            "asks": meaning.get("asks") or [],
            "evidence": meaning.get("evidence") or [],
            "confidence": meaning.get("confidence"),
            "needs_human": bool(meaning.get("needs_human")),
            "version": meaning.get("version"),
        }

    return {
        "employee": _out(member),
        "mentions": [
            {
                "review_id": m.review_id,
                "channel_id": m.channel_id,
                "rating": m.rating,
                "sentiment": m.sentiment,
                "review_created_at": (
                    m.review_created_at.isoformat() if m.review_created_at else None
                ),
                "matched_name": m.name_display,
                "reviewer_name": insight.reviewer_name if insight else None,
                "reviewer_photo_url": insight.reviewer_photo_url if insight else None,
                "review_text": insight.review_text if insight else None,
                "review_url": insight.review_url if insight else None,
                "ai": _ai(insight),
            }
            for m, insight in rows
        ],
    }


# ── Profile picture ──────────────────────────────────────────────────────

async def _owned_member(member_id: str, ctx: TenantContext, db: AsyncSession) -> StaffMember:
    member = (
        await db.execute(
            select(StaffMember).where(
                StaffMember.id == member_id, StaffMember.user_id == ctx.tenant_id
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=404, detail="Employee not found.")
    return member


@router.post("/{member_id}/avatar")
async def upload_staff_avatar(
    member_id: str,
    request: Request,
    file: UploadFile = File(...),
    ctx: TenantContext = Depends(require_perm("team.manage")),
    db: AsyncSession = Depends(get_db),
):
    """Upload a profile picture for one employee.

    Stored on the same public media backend as account avatars, under the
    workspace owner's prefix. The old object is deleted best-effort after the
    row points at the replacement.
    """
    member = await _owned_member(member_id, ctx, db)
    data = await file.read(AVATAR_MAX_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="Empty file.")
    if len(data) > AVATAR_MAX_BYTES:
        raise HTTPException(status_code=400, detail="File is too big — max 8MB.")
    try:
        ext, expected_type = _image_extension(file.filename or "avatar", file.content_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not _looks_like_image(ext, data):
        raise HTTPException(
            status_code=400,
            detail="File content doesn't look like the image type it claims.",
        )

    from ...core.storage import delete_media, local_media_url, put_media

    storage_key, public_url = put_media(
        ctx.tenant_id, file.filename or f"avatar{ext}", data, expected_type
    )
    if not public_url:
        public_url = local_media_url(str(request.base_url), ctx.tenant_id, storage_key)

    old_key = member.avatar_storage_key
    member.avatar_url = public_url[:1000]
    member.avatar_storage_key = storage_key[:500]
    await db.commit()
    await db.refresh(member)

    if old_key and old_key != storage_key:
        try:
            delete_media(ctx.tenant_id, old_key)
        except Exception:
            # The row already points at the replacement; a storage hiccup here
            # costs one orphaned object, not a broken profile. Log it so the
            # orphan can be found and cleaned up.
            logger.warning(
                "Could not delete superseded employee avatar %s for tenant %s",
                old_key,
                ctx.tenant_id,
                exc_info=True,
            )
    return _out(member)


@router.delete("/{member_id}/avatar")
async def delete_staff_avatar(
    member_id: str,
    ctx: TenantContext = Depends(require_perm("team.manage")),
    db: AsyncSession = Depends(get_db),
):
    """Remove the profile picture; the employee row and history stay."""
    member = await _owned_member(member_id, ctx, db)
    old_key = member.avatar_storage_key
    member.avatar_url = None
    member.avatar_storage_key = None
    await db.commit()

    if old_key:
        from ...core.storage import delete_media

        try:
            delete_media(ctx.tenant_id, old_key)
        except Exception:
            logger.warning(
                "Could not delete employee avatar %s for tenant %s",
                old_key,
                ctx.tenant_id,
                exc_info=True,
            )
    return {"ok": True}


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

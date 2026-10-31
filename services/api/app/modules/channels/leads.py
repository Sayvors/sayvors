"""Leads API: read + work the leads the messaging engine captures.

DB rows only — the messaging pipeline writes lead rows and schedules
follow-ups while chatting; this router never infers or scores. Ownership
is the tenant scope from the team context, never a client-passed id.
The Instagram hub's Leads tab is the first consumer: list, filter, move
a lead through new -> qualified -> follow_up -> converted/lost, and set
the tenant's follow-up knobs (clamped by the engine before storing).

`category` is the one human-facing lead label. The router returns it as
stored; the engine is the only classifier. An operator may correct it here,
which is recorded at confidence 1.0 so a later model extraction cannot
silently undo the correction.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_db
from ..team.context import TenantContext, require_perm
from ..users.models import User
from .models import ContactProfile, Lead
from .schemas import (
    LeadListResponse,
    LeadOut,
    LeadSettingsOut,
    LeadSettingsUpdate,
    LeadUpdate,
)
from .meta.lead_engine import normalize_lead_settings

router = APIRouter(prefix="/api/v1/leads", tags=["leads"])

_STAGES = ("new", "qualified", "follow_up", "converted", "lost")
_CATEGORY_PATTERN = "^(wholesale|retail|booking|quote|support|info)$"


async def _avatar_for(db: AsyncSession, tenant_id: str, platform: str, contact_id: str) -> str | None:
    """Best-effort cached avatar; a missing profile row is normal."""
    return (
        await db.execute(
            select(ContactProfile.avatar_url).where(
                ContactProfile.tenant_id == tenant_id,
                ContactProfile.platform == platform,
                ContactProfile.contact_id == contact_id,
            )
        )
    ).scalar_one_or_none()


def _lead_out(lead: Lead, avatar_url: str | None) -> LeadOut:
    return LeadOut(
        id=lead.id,
        channel_id=lead.channel_id,
        platform=lead.platform,
        contact_id=lead.contact_id,
        contact_name=lead.contact_name,
        contact_username=lead.contact_username,
        language=lead.language or "en",
        intent=lead.intent,
        category=lead.category,
        request=lead.request,
        avatar_url=avatar_url,
        # UI summary falls back to the captured request.
        summary=lead.summary or lead.request,
        stage=lead.stage,
        phone_number=lead.phone_number,
        phone_status=lead.phone_status,
        opt_out=bool(lead.opt_out),
        next_action_at=(
            lead.next_action_at.isoformat() if lead.next_action_at else None
        ),
        priority=lead.priority or "normal",
        ai_miss_count=int(lead.ai_miss_count or 0),
        priority_since=(
            lead.priority_since.isoformat() if lead.priority_since else None
        ),
        thread_key=lead.thread_key,
        last_message_at=(
            lead.last_message_at.isoformat() if lead.last_message_at else None
        ),
        created_at=lead.created_at.isoformat(),
        updated_at=lead.updated_at.isoformat(),
    )


@router.get("/settings", response_model=LeadSettingsOut)
async def get_lead_settings(
    ctx: TenantContext = Depends(require_perm("channels.view")),
    db: AsyncSession = Depends(get_db),
) -> LeadSettingsOut:
    row = (
        await db.execute(select(User.lead_settings).where(User.id == ctx.tenant_id))
    ).first()
    return LeadSettingsOut(**normalize_lead_settings(row.lead_settings if row else None))


@router.patch("/settings", response_model=LeadSettingsOut)
async def update_lead_settings(
    body: LeadSettingsUpdate,
    ctx: TenantContext = Depends(require_perm("channels.edit")),
    db: AsyncSession = Depends(get_db),
) -> LeadSettingsOut:
    # /settings must be declared before /{lead_id} or FastAPI would try to
    # parse "settings" as a lead id.
    user = (
        await db.execute(select(User).where(User.id == ctx.tenant_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

    current = normalize_lead_settings(user.lead_settings)
    provided = body.model_dump(exclude_unset=True, exclude_none=True)
    # Whitelist + clamp decide what a stored value may be — a client can
    # choose within the safe envelope, never outside it.
    merged = normalize_lead_settings({**current, **provided})
    user.lead_settings = merged
    db.add(user)
    await db.commit()
    return LeadSettingsOut(**merged)


@router.get("", response_model=LeadListResponse)
async def list_leads(
    platform: str | None = Query(None, max_length=20),
    stage_filter: str | None = Query(None, alias="stage", pattern="^(new|qualified|follow_up|converted|lost)$"),
    category_filter: str | None = Query(None, alias="category", pattern=_CATEGORY_PATTERN),
    priority_filter: str | None = Query(None, alias="priority", pattern="^(normal|important)$"),
    priority_first: bool = Query(
        False,
        alias="priority_first",
        description="Sort escalated leads to the top before recency.",
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: TenantContext = Depends(require_perm("channels.view")),
    db: AsyncSession = Depends(get_db),
) -> LeadListResponse:
    conds = [Lead.tenant_id == ctx.tenant_id, Lead.merged_into_id.is_(None)]
    if platform:
        conds.append(Lead.platform == platform)
    if stage_filter:
        conds.append(Lead.stage == stage_filter)
    if category_filter:
        conds.append(Lead.category == category_filter)
    if priority_filter:
        conds.append(Lead.priority == priority_filter)

    # Sorting by priority uses ix_leads_tenant_priority, so it stays an index
    # scan. Postgres orders enums by declaration, and 'important' is declared
    # second, so DESC puts escalated leads first.
    order = (
        (Lead.priority.desc(), Lead.updated_at.desc())
        if priority_first
        else (Lead.created_at.desc(),)
    )

    total = (
        await db.execute(select(func.count()).select_from(Lead).where(*conds))
    ).scalar_one()
    rows = (
        await db.execute(
            select(Lead, ContactProfile.avatar_url)
            .outerjoin(
                ContactProfile,
                (ContactProfile.tenant_id == Lead.tenant_id)
                & (ContactProfile.platform == Lead.platform)
                & (ContactProfile.contact_id == Lead.contact_id),
            )
            .where(*conds)
            .order_by(*order)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return LeadListResponse(
        leads=[_lead_out(lead, avatar) for lead, avatar in rows],
        total=total,
    )


@router.patch("/{lead_id}", response_model=LeadOut)
async def update_lead(
    lead_id: str,
    body: LeadUpdate,
    ctx: TenantContext = Depends(require_perm("channels.edit")),
    db: AsyncSession = Depends(get_db),
) -> LeadOut:
    lead = (
        await db.execute(
            select(Lead).where(Lead.id == lead_id, Lead.tenant_id == ctx.tenant_id)
        )
    ).scalar_one_or_none()
    if lead is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")

    # The tenant may close or reopen the pipeline manually; the engine
    # treats converted/lost as terminal for scheduled actions.
    if body.stage is not None:
        lead.stage = body.stage
    if body.category is not None:
        lead.category = body.category
        # A human correction outranks every model extraction. The engine's
        # category merge reads this confidence, so without the 1.0 a later
        # 0.9 "retail" guess would overwrite the operator's "wholesale".
        prov = dict(lead.field_provenance or {})
        prov["category"] = {
            "value": body.category,
            "confidence": 1.0,
            "source_message_id": None,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        lead.field_provenance = prov
    if body.summary is not None:
        lead.summary = body.summary.strip() or None
    db.add(lead)
    await db.commit()
    await db.refresh(lead)
    return _lead_out(
        lead,
        await _avatar_for(db, lead.tenant_id, lead.platform, lead.contact_id),
    )

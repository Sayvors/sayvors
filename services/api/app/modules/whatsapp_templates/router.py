"""WhatsApp template API: list, sync, send, and record consent."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_db
from ..channels.models import Channel, Lead
from ..team.context import TenantContext, require_perm
from . import service

router = APIRouter(prefix="/api/v1/whatsapp/templates", tags=["whatsapp-templates"])


class TemplateSendRequest(BaseModel):
    channel_id: str = Field(..., min_length=1)
    contact_phone: str = Field(..., min_length=5, max_length=32)
    template_id: str = Field(..., min_length=1)
    variables: list[str] = Field(default_factory=list)
    idempotency_key: str | None = Field(None, max_length=80)


class ConsentRequest(BaseModel):
    channel_id: str = Field(..., min_length=1)
    contact_phone: str = Field(..., min_length=5, max_length=32)
    source: str = Field("operator", max_length=32)


def _send_payload(row) -> dict:
    return {
        "id": row.id,
        "status": row.status,
        "template_name": row.template_name,
        "language": row.language,
        "contact_phone": row.contact_phone,
        "provider_message_id": row.provider_message_id,
        "error": row.error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("", response_model=dict)
async def list_templates(
    ctx: TenantContext = Depends(require_perm("channels.view")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rows = await service.list_templates(db, ctx.tenant_id)
    return {"templates": [service.serialize_template(r) for r in rows]}


@router.post("/sync", response_model=dict)
async def sync_templates(
    ctx: TenantContext = Depends(require_perm("channels.edit")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Pull the WABA's templates from Meta. Templates are created there."""
    try:
        result = await service.sync_templates(db, ctx.tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 - provider/network failure
        raise HTTPException(
            status_code=502,
            detail=f"Could not sync templates from Meta: {type(exc).__name__}",
        )
    rows = await service.list_templates(db, ctx.tenant_id)
    return {
        **result,
        "templates": [service.serialize_template(r) for r in rows],
    }


@router.post("/send", response_model=dict)
async def send_template(
    body: TemplateSendRequest,
    ctx: TenantContext = Depends(require_perm("channels.edit")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Send one approved template. Requires a recorded opt-in."""
    if not ctx.can_edit_channel(body.channel_id):
        raise HTTPException(status_code=403, detail="No edit access to this channel")
    try:
        row, created = await service.send_template(
            db,
            tenant_id=ctx.tenant_id,
            channel_id=body.channel_id,
            contact_phone=body.contact_phone,
            template_id=body.template_id,
            variables=body.variables,
            sent_by=ctx.user.id,
            idempotency_key=body.idempotency_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {**_send_payload(row), "created": created}


@router.get("/sends", response_model=dict)
async def list_sends(
    lead_id: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    ctx: TenantContext = Depends(require_perm("channels.view")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from .models import TemplateSend

    stmt = select(TemplateSend).where(TemplateSend.tenant_id == ctx.tenant_id)
    if lead_id:
        stmt = stmt.where(TemplateSend.lead_id == lead_id)
    rows = (
        await db.execute(
            stmt.order_by(TemplateSend.created_at.desc()).limit(limit)
        )
    ).scalars().all()
    return {"sends": [_send_payload(r) for r in rows]}


@router.post("/consent", response_model=dict)
async def record_consent(
    body: ConsentRequest,
    ctx: TenantContext = Depends(require_perm("channels.edit")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Record that the customer agreed to WhatsApp messages.

    The bridge records this automatically when the customer taps the link and
    writes; this endpoint covers an operator's own evidence (a phone call, a
    signed form). It never invents consent from a message.
    """
    if not ctx.can_edit_channel(body.channel_id):
        raise HTTPException(status_code=403, detail="No edit access to this channel")
    channel = (
        await db.execute(
            select(Channel).where(
                Channel.id == body.channel_id, Channel.user_id == ctx.tenant_id
            )
        )
    ).scalars().first()
    if channel is None or channel.platform != "whatsapp":
        raise HTTPException(status_code=404, detail="WhatsApp channel not found")
    lead = (
        await db.execute(
            select(Lead)
            .where(
                Lead.channel_id == body.channel_id,
                Lead.contact_id == body.contact_phone,
            )
            .order_by(Lead.created_at.asc())
            .limit(1)
        )
    ).scalars().first()
    if lead is None:
        raise HTTPException(
            status_code=404,
            detail="No lead for this contact yet — a customer message creates one.",
        )
    await service.record_opt_in(
        db, lead, source=body.source or "operator", message_id=None
    )
    await db.commit()
    return {
        "opt_in_at": lead.whatsapp_opt_in_at.isoformat()
        if lead.whatsapp_opt_in_at
        else None,
        "opt_in_source": lead.whatsapp_opt_in_source,
        "opt_out": bool(lead.opt_out),
    }


@router.delete("/consent", response_model=dict)
async def revoke_consent(
    channel_id: str = Query(..., min_length=1),
    contact_phone: str = Query(..., min_length=5, max_length=32),
    ctx: TenantContext = Depends(require_perm("channels.edit")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Withdraw the consent basis. Templates stop until it is recorded again."""
    lead = (
        await db.execute(
            select(Lead)
            .where(
                Lead.channel_id == channel_id,
                Lead.tenant_id == ctx.tenant_id,
                Lead.contact_id == contact_phone,
            )
            .order_by(Lead.created_at.asc())
            .limit(1)
        )
    ).scalars().first()
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    lead.whatsapp_opt_in_at = None
    lead.whatsapp_opt_in_source = None
    lead.whatsapp_opt_in_message_id = None
    await db.commit()
    return {"opt_in_at": None, "opt_in_source": None}

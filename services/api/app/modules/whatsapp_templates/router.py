"""WhatsApp template API: author, list, sync, send, and record consent."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_db
from ...core.upstream_errors import upstream_http_error
from ..billing.messaging_quota import ensure_messaging_quota
from ..channels.models import Channel, Lead
from ..team.context import TenantContext, require_perm
from . import service

router = APIRouter(prefix="/api/v1/whatsapp/templates", tags=["whatsapp-templates"])


class TemplateCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=512)
    language: str = Field("en", min_length=2, max_length=20)
    category: str = Field("utility", max_length=20)
    body: str = Field(..., min_length=1, max_length=1024)
    examples: list[str] = Field(default_factory=list, max_length=20)


class TemplateUpdateRequest(BaseModel):
    category: str | None = Field(None, max_length=20)
    body: str | None = Field(None, min_length=1, max_length=1024)
    examples: list[str] = Field(default_factory=list, max_length=20)


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
    return {
        "templates": await service.list_templates_with_stats(db, ctx.tenant_id),
        "waba": await service.waba_connection(db, ctx.tenant_id),
    }


@router.post("/sync", response_model=dict)
async def sync_templates(
    ctx: TenantContext = Depends(require_perm("channels.edit")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Reconcile the local mirror with Meta (status + templates made there)."""
    try:
        result = await service.sync_templates(db, ctx.tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 - provider/network failure
        raise upstream_http_error(
            exc,
            context="Meta template sync failed",
            detail="Could not sync templates from Meta. Try again shortly.",
        ) from None
    return {
        **result,
        "templates": await service.list_templates_with_stats(db, ctx.tenant_id),
        "waba": await service.waba_connection(db, ctx.tenant_id),
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
    # Templates are outbound WhatsApp messages: they share the monthly
    # allowance with manual sends and AI replies.
    await ensure_messaging_quota(ctx, db, body.channel_id)
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


# Authoring routes are declared after the static paths above: FastAPI matches
# in declaration order, so a dynamic "/{template_id}" DELETE placed earlier
# would swallow DELETE /consent.


@router.post("", response_model=dict, status_code=201)
async def create_template(
    body: TemplateCreateRequest,
    ctx: TenantContext = Depends(require_perm("channels.edit")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Submit a template to Meta and mirror its review status locally."""
    try:
        row = await service.create_template(
            db,
            ctx.tenant_id,
            name=body.name,
            language=body.language,
            category=body.category,
            body=body.body,
            examples=body.examples,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 - provider/network failure
        raise upstream_http_error(
            exc,
            context="Meta template create failed",
            detail="Could not create the template at Meta. Try again shortly.",
        ) from None
    return {"template": service.serialize_template(row)}


@router.patch("/{template_id}", response_model=dict)
async def update_template(
    template_id: str,
    body: TemplateUpdateRequest,
    ctx: TenantContext = Depends(require_perm("channels.edit")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Edit the body/category; Meta re-reviews an edited template."""
    try:
        row = await service.update_template(
            db,
            ctx.tenant_id,
            template_id,
            category=body.category,
            body=body.body,
            examples=body.examples,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 - provider/network failure
        raise upstream_http_error(
            exc,
            context="Meta template update failed",
            detail="Could not update the template at Meta. Try again shortly.",
        ) from None
    stats = (await service.send_stats(db, ctx.tenant_id)).get(row.id)
    return {"template": service.serialize_template(row, stats)}


@router.delete("/{template_id}", response_model=dict)
async def delete_template(
    template_id: str,
    ctx: TenantContext = Depends(require_perm("channels.edit")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete the template at Meta and locally; send history keeps its name."""
    try:
        await service.delete_template(db, ctx.tenant_id, template_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 - provider/network failure
        raise upstream_http_error(
            exc,
            context="Meta template delete failed",
            detail="Could not delete the template at Meta. Try again shortly.",
        ) from None
    return {"deleted": True, "id": template_id}


@router.get("/{template_id}/analytics", response_model=dict)
async def template_analytics(
    template_id: str,
    days: int = Query(30, ge=1, le=365),
    ctx: TenantContext = Depends(require_perm("channels.view")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Send outcomes for one template over a bounded window."""
    try:
        return await service.template_analytics(
            db, ctx.tenant_id, template_id, days=days
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

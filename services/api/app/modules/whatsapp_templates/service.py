"""Template sync, consent, and the idempotent send path."""
import logging
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from ..channels.meta.models import MetaAsset
from ..channels.models import Channel, ChannelMessage, Lead
from .models import TemplateSend, WhatsAppTemplate

logger = logging.getLogger(__name__)

_VARIABLE_RE = re.compile(r"\{\{\s*(\d+)\s*\}\}")

# Meta's "re-engagement" error: the 24h window closed between our check and
# the send, or no template was used. Surfaced verbatim so the UI can explain.
_WINDOW_ERROR = "131047"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def count_variables(body: str) -> int:
    return max((int(n) for n in _VARIABLE_RE.findall(body or "")), default=0)


def serialize_template(row: WhatsAppTemplate) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "language": row.language,
        "category": row.category,
        "status": row.status,
        "body": row.body,
        "variables": int(row.variables or 0),
        "meta_template_id": row.meta_template_id,
        "last_synced_at": row.last_synced_at.isoformat() if row.last_synced_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def list_templates(db, tenant_id: str) -> list[WhatsAppTemplate]:
    return list(
        (
            await db.execute(
                select(WhatsAppTemplate)
                .where(WhatsAppTemplate.tenant_id == tenant_id)
                .order_by(
                    WhatsAppTemplate.category.asc(),
                    WhatsAppTemplate.name.asc(),
                    WhatsAppTemplate.language.asc(),
                )
            )
        ).scalars().all()
    )


async def eligible_templates(db, tenant_id: str) -> list[WhatsAppTemplate]:
    """Approved utility templates — the only ones a follow-up may use."""
    return [
        row
        for row in await list_templates(db, tenant_id)
        if row.status == "approved" and row.category == "utility"
    ]


async def _waba_asset(db, tenant_id: str) -> MetaAsset | None:
    return (
        await db.execute(
            select(MetaAsset)
            .options(selectinload(MetaAsset.connection))
            .where(
                MetaAsset.tenant_id == tenant_id,
                MetaAsset.provider == "whatsapp",
                MetaAsset.asset_type == "waba",
                MetaAsset.active.is_(True),
            )
            .order_by(MetaAsset.created_at.asc())
            .limit(1)
        )
    ).scalars().first()


async def sync_templates(db, tenant_id: str) -> dict:
    """Pull the WABA's templates from Meta and upsert them locally.

    Meta owns template content and status; this table mirrors it. A template
    that disappears from Meta stays locally with its last status rather than
    being deleted — send history references it.
    """
    from ..channels.meta.credentials import decrypt_connection_token
    from ..channels.meta.service import get_adapter

    asset = await _waba_asset(db, tenant_id)
    if asset is None or asset.connection is None:
        raise ValueError("No WhatsApp Business Account is connected")
    token = decrypt_connection_token(asset.connection)
    if not token:
        raise ValueError("The WhatsApp connection has no usable access token")

    adapter = get_adapter("whatsapp")
    remote = await adapter.list_templates(asset.external_asset_id, token)

    existing = {
        (row.name, row.language): row
        for row in await list_templates(db, tenant_id)
    }
    now = _now()
    created = updated = 0
    for item in remote:
        name = (item.get("name") or "").strip()
        language = (item.get("language") or "en").strip()
        if not name:
            continue
        body = ""
        for component in item.get("components") or []:
            if (component.get("type") or "").lower() == "body":
                body = component.get("text") or ""
                break
        values = {
            "category": (item.get("category") or "utility").lower()[:20],
            "status": (item.get("status") or "pending").lower()[:20],
            "body": body,
            "variables": count_variables(body),
            "meta_template_id": str(item.get("id") or "")[:64] or None,
            "last_synced_at": now,
        }
        row = existing.get((name, language))
        if row is None:
            db.add(WhatsAppTemplate(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                name=name[:200],
                language=language[:20],
                **values,
            ))
            created += 1
        else:
            for key, value in values.items():
                setattr(row, key, value)
            updated += 1
    await db.commit()
    logger.info(
        "template sync tenant=%s created=%d updated=%d", tenant_id, created, updated
    )
    return {"created": created, "updated": updated, "remote": len(remote)}


async def record_opt_in(db, lead: Lead, *, source: str, message_id: str | None) -> None:
    """Record that the customer agreed to WhatsApp messages.

    Idempotent: the first evidence wins, so a later automated path cannot
    rewrite history. Clearing an explicit opt-out is deliberate and separate.
    """
    if lead.whatsapp_opt_in_at is not None:
        return
    lead.whatsapp_opt_in_at = _now()
    lead.whatsapp_opt_in_source = source[:32]
    lead.whatsapp_opt_in_message_id = (message_id or "")[:200] or None
    lead.opt_out = False
    lead.opt_out_at = None


async def send_template(
    db,
    *,
    tenant_id: str,
    channel_id: str,
    contact_phone: str,
    template_id: str,
    variables: list[str] | None = None,
    sent_by: str | None,
    idempotency_key: str | None = None,
) -> tuple[TemplateSend, bool]:
    """Send one approved template, guarded by consent and idempotency.

    Returns ``(row, created)``. ``created`` is False when the idempotency key
    already produced a send — the caller returns the original result instead of
    sending twice.

    Raises ValueError for preconditions the caller can act on (unknown or
    unapproved template, no consent, no connected number). A provider rejection
    is recorded on the row with status="failed" rather than raised: the caller
    shows the reason next to the send.
    """
    key = (idempotency_key or str(uuid.uuid4()))[:80]
    existing = (
        await db.execute(
            select(TemplateSend).where(
                TemplateSend.tenant_id == tenant_id,
                TemplateSend.idempotency_key == key,
            )
        )
    ).scalars().first()
    if existing is not None:
        return existing, False

    template = (
        await db.execute(
            select(WhatsAppTemplate).where(
                WhatsAppTemplate.id == template_id,
                WhatsAppTemplate.tenant_id == tenant_id,
            )
        )
    ).scalars().first()
    if template is None:
        raise ValueError("Template not found")
    if template.status != "approved":
        raise ValueError(
            f"Template '{template.name}' is {template.status}; only approved "
            "templates can be sent."
        )
    if template.meta_template_id is None:
        raise ValueError(
            "Template has not been synced from Meta; sync it before sending."
        )

    channel = (
        await db.execute(
            select(Channel).where(
                Channel.id == channel_id, Channel.user_id == tenant_id
            )
        )
    ).scalars().first()
    if channel is None or channel.platform != "whatsapp":
        raise ValueError("This conversation is not a WhatsApp channel")

    lead = (
        await db.execute(
            select(Lead)
            .where(Lead.channel_id == channel_id, Lead.contact_id == contact_phone)
            .order_by(Lead.created_at.asc())
            .limit(1)
        )
    ).scalars().first()
    if lead is None or lead.whatsapp_opt_in_at is None:
        raise ValueError(
            "No WhatsApp opt-in on record for this customer. Templates need a "
            "recorded consent basis."
        )
    if lead.opt_out:
        raise ValueError("This customer opted out of WhatsApp messages.")

    values = [str(v) for v in (variables or [])]
    if len(values) != int(template.variables or 0):
        raise ValueError(
            f"Template '{template.name}' needs {template.variables} variable(s), "
            f"got {len(values)}."
        )

    asset = (
        await db.execute(
            select(MetaAsset)
            .options(selectinload(MetaAsset.connection))
            .where(
                MetaAsset.tenant_id == tenant_id,
                MetaAsset.provider == "whatsapp",
                MetaAsset.external_asset_id == channel.platform_user_id,
                MetaAsset.active.is_(True),
            )
            .limit(1)
        )
    ).scalars().first()
    if asset is None or asset.connection is None:
        raise ValueError("This number is not connected to WhatsApp")

    row = TemplateSend(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        lead_id=lead.id,
        template_id=template.id,
        contact_phone=contact_phone[:32],
        template_name=template.name,
        language=template.language,
        variables={"values": values} if values else None,
        idempotency_key=key,
        status="blocked",
        consent_at=lead.whatsapp_opt_in_at,
        sent_by=sent_by,
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        # Lost the race to the same key: return the winner's row.
        await db.rollback()
        winner = (
            await db.execute(
                select(TemplateSend).where(
                    TemplateSend.tenant_id == tenant_id,
                    TemplateSend.idempotency_key == key,
                )
            )
        ).scalars().first()
        if winner is not None:
            return winner, False

    from ..channels.meta.credentials import decrypt_connection_token
    from ..channels.meta.providers.whatsapp import MetaAPIError
    from ..channels.meta.service import get_adapter

    token = decrypt_connection_token(asset.connection)
    if not token:
        row.status = "failed"
        row.error = "The WhatsApp connection has no usable access token"
        await db.commit()
        return row, True

    adapter = get_adapter("whatsapp")
    try:
        provider_id = await adapter.send_template_message(
            channel.platform_user_id, token, contact_phone,
            template.name, template.language, values,
        )
    except MetaAPIError as e:
        row.status = "failed"
        row.error = (
            f"The message window is closed and Meta rejected the template: {str(e)[:300]}"
            if _WINDOW_ERROR in str(e)
            else str(e)[:500]
        )
        await db.commit()
        logger.warning(
            "template send failed tenant=%s template=%s: %s",
            tenant_id, template.name, str(e)[:200],
        )
        return row, True
    except Exception as e:  # noqa: BLE001 - recorded, not raised
        row.status = "failed"
        row.error = f"{type(e).__name__}: {str(e)[:400]}"
        await db.commit()
        return row, True

    row.status = "sent"
    row.provider_message_id = (provider_id or "")[:200] or None
    # The template is now the thread's last outbound. is_ai stays False: a
    # template is a business action, not an AI answer, and the escalation
    # counter must not read it as one.
    db.add(ChannelMessage(
        id=str(uuid.uuid4()),
        channel_id=channel_id,
        platform_message_id=row.provider_message_id,
        direction="outbound",
        content=_encrypt(template.body or template.name),
        content_type="template",
        status="sent",
        contact_phone=_encrypt(contact_phone or None),
        contact_phone_hash=_hash(contact_phone),
        handled_by="system",
        is_ai=False,
    ))
    await db.commit()
    logger.info(
        "template sent tenant=%s template=%s to=+%s",
        tenant_id, template.name, (contact_phone or "")[-6:],
    )
    return row, True


def _encrypt(value: str | None):
    from ..channels.service import encrypt_message_content

    return encrypt_message_content(value)


def _hash(value: str | None):
    from ..channels.service import hash_contact_phone

    return hash_contact_phone(value) if value else None

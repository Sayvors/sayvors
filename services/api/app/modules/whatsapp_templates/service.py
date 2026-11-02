"""WhatsApp template authoring, sync, consent, and the idempotent send path.

Templates are created and edited here, then reviewed by Meta. The local table
mirrors Meta's status; "Sync" reconciles anything changed in WhatsApp Manager
and is still the source of truth for approval state.
"""
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from ..channels.meta.models import MetaAsset, MetaConnection
from ..channels.models import Channel, ChannelMessage, Lead
from .models import TemplateSend, WhatsAppTemplate

logger = logging.getLogger(__name__)

_VARIABLE_RE = re.compile(r"\{\{\s*(\d+)\s*\}\}")

# Meta's rules for template names and language codes. Enforced here so the
# tenant gets the reason before a round-trip that Meta would reject anyway.
_TEMPLATE_NAME_RE = re.compile(r"^[a-z0-9_]{1,512}$")
_LANGUAGE_RE = re.compile(r"^[a-z]{2,3}(?:_[A-Z]{2})?$")
_AUTHORABLE_CATEGORIES = frozenset({"utility", "marketing"})
_BODY_MAX = 1024

# Meta's "re-engagement" error: the 24h window closed between our check and
# the send, or no template was used. Surfaced verbatim so the UI can explain.
_WINDOW_ERROR = "131047"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def count_variables(body: str) -> int:
    return max((int(n) for n in _VARIABLE_RE.findall(body or "")), default=0)


def serialize_template(
    row: WhatsAppTemplate, stats: dict | None = None
) -> dict:
    stats = stats or {}
    return {
        "id": row.id,
        "name": row.name,
        "language": row.language,
        "category": row.category,
        "status": row.status,
        "body": row.body,
        "variables": int(row.variables or 0),
        "meta_template_id": row.meta_template_id,
        "send_count": int(stats.get("total", 0)),
        "sent_count": int(stats.get("sent", 0)),
        "failed_count": int(stats.get("failed", 0)),
        "last_sent_at": stats.get("last_sent_at"),
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


@dataclass(frozen=True)
class _WabaRef:
    """A WABA id recovered from the connection when no asset row exists.

    Older connections stored ``waba_id`` in connection metadata but never
    created the WABA asset. Templates only need the id and the token, so a
    lightweight reference avoids a migration/backfill just to list templates.
    """

    external_asset_id: str
    name: str | None
    connection_id: str
    tenant_id: str


async def _waba_asset(db, tenant_id: str) -> MetaAsset | _WabaRef | None:
    """The tenant's WABA, preferring an active one.

    Older connections have the phone number active but its parent WABA marked
    inactive: the selection UI only ever sent phone-number ids, so the replace
    sweep in ``select_assets`` deactivated the container. The parent of a live
    number is still the correct WABA for templates, so fall back to it rather
    than telling a connected tenant to connect again.
    """
    active = (
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
    if active is not None:
        return active

    phone = (
        await db.execute(
            select(MetaAsset)
            .where(
                MetaAsset.tenant_id == tenant_id,
                MetaAsset.provider == "whatsapp",
                MetaAsset.asset_type == "phone_number",
                MetaAsset.active.is_(True),
                MetaAsset.parent_asset_id.is_not(None),
            )
            .order_by(MetaAsset.created_at.asc())
            .limit(1)
        )
    ).scalars().first()
    if phone is not None and phone.parent_asset_id is not None:
        parent = await db.get(MetaAsset, phone.parent_asset_id)
        if (
            parent is not None
            and parent.tenant_id == tenant_id
            and parent.asset_type == "waba"
        ):
            return parent

    # Last resort: the connect flow always records the WABA id it was given,
    # even when asset discovery only persisted the phone number. Templates
    # need the id and token, not an asset row.
    connection = (
        await db.execute(
            select(MetaConnection)
            .where(
                MetaConnection.tenant_id == tenant_id,
                MetaConnection.provider == "whatsapp",
                MetaConnection.status != "revoked",
            )
            .order_by(MetaConnection.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if connection is None:
        return None
    waba_id = (connection.connection_metadata or {}).get("waba_id")
    if not waba_id:
        return None
    return _WabaRef(
        external_asset_id=str(waba_id)[:100],
        name=None,
        connection_id=connection.id,
        tenant_id=tenant_id,
    )


async def _connection_for(db, asset: MetaAsset | _WabaRef):
    """Load an asset's connection explicitly.

    The asset may have come from the identity map (created moments ago by the
    connect flow), where the lazy relationship is not loaded and touching it
    in async code raises MissingGreenlet. A direct get always works.
    """
    if asset.connection_id is None:
        return None
    return await db.get(MetaConnection, asset.connection_id)


async def waba_connection(db, tenant_id: str) -> dict:
    """Safe connection summary for the Templates panel — never the token."""
    asset = await _waba_asset(db, tenant_id)
    connection = await _connection_for(db, asset) if asset is not None else None
    return {
        "connected": connection is not None,
        "name": asset.name if asset is not None else None,
    }


async def _waba_and_token(
    db, tenant_id: str
) -> tuple[MetaAsset | _WabaRef, str]:
    """Resolve the WABA and a usable token, with actionable failures."""
    from ..channels.meta.credentials import decrypt_connection_token

    asset = await _waba_asset(db, tenant_id)
    connection = await _connection_for(db, asset) if asset is not None else None
    if asset is None or connection is None:
        raise ValueError(
            "No WhatsApp Business Account is connected. Connect a WhatsApp "
            "number under Channels first."
        )
    token = decrypt_connection_token(connection)
    if not token:
        raise ValueError(
            "The WhatsApp connection has no usable access token. Reconnect "
            "WhatsApp under Channels."
        )
    return asset, token


async def send_stats(
    db, tenant_id: str, *, since: datetime | None = None
) -> dict[str, dict]:
    """Per-template send totals in one grouped query (no N+1 on the list)."""
    stmt = (
        select(
            TemplateSend.template_id,
            TemplateSend.status,
            func.count(TemplateSend.id),
            func.max(TemplateSend.created_at),
        )
        .where(
            TemplateSend.tenant_id == tenant_id,
            TemplateSend.template_id.is_not(None),
        )
        .group_by(TemplateSend.template_id, TemplateSend.status)
    )
    if since is not None:
        stmt = stmt.where(TemplateSend.created_at >= since)

    out: dict[str, dict] = {}
    for template_id, status, count, last_at in (await db.execute(stmt)).all():
        item = out.setdefault(
            template_id,
            {
                "total": 0,
                "sent": 0,
                "failed": 0,
                "blocked": 0,
                "last_sent_at": None,
            },
        )
        item["total"] += int(count)
        if status in ("sent", "failed", "blocked"):
            item[status] += int(count)
        if last_at is not None:
            previous = item["last_sent_at"]
            if previous is None or last_at > previous:
                item["last_sent_at"] = last_at

    for item in out.values():
        if item["last_sent_at"] is not None:
            item["last_sent_at"] = item["last_sent_at"].isoformat()
    return out


async def list_templates_with_stats(
    db, tenant_id: str, *, since: datetime | None = None
) -> list[dict]:
    rows = await list_templates(db, tenant_id)
    stats = await send_stats(db, tenant_id, since=since)
    return [serialize_template(row, stats.get(row.id)) for row in rows]


async def template_analytics(
    db, tenant_id: str, template_id: str, *, days: int = 30
) -> dict:
    """Send outcomes for one template over a bounded window."""
    row = await _get_template(db, tenant_id, template_id)
    since = _now() - timedelta(days=days)
    stmt = (
        select(
            TemplateSend.status,
            func.count(TemplateSend.id),
            func.max(TemplateSend.created_at),
        )
        .where(
            TemplateSend.tenant_id == tenant_id,
            TemplateSend.template_id == template_id,
            TemplateSend.created_at >= since,
        )
        .group_by(TemplateSend.status)
    )
    result = {"sent": 0, "failed": 0, "blocked": 0, "last_sent_at": None}
    for status, count, last_at in (await db.execute(stmt)).all():
        if status in result:
            result[status] = int(count)
        if last_at is not None and (
            result["last_sent_at"] is None or last_at > result["last_sent_at"]
        ):
            result["last_sent_at"] = last_at
    if result["last_sent_at"] is not None:
        result["last_sent_at"] = result["last_sent_at"].isoformat()
    return {
        "template_id": row.id,
        "name": row.name,
        "language": row.language,
        "days": days,
        "total": result["sent"] + result["failed"] + result["blocked"],
        **result,
    }


async def _get_template(db, tenant_id: str, template_id: str) -> WhatsAppTemplate:
    row = (
        await db.execute(
            select(WhatsAppTemplate).where(
                WhatsAppTemplate.id == template_id,
                WhatsAppTemplate.tenant_id == tenant_id,
            )
        )
    ).scalars().first()
    if row is None:
        raise ValueError("Template not found")
    return row


def _clean_template_input(
    *,
    name: str,
    language: str,
    category: str,
    body: str,
    examples: list[str] | None,
) -> tuple[str, str, str, str, list[str]]:
    """Validate one template against Meta's rules before the round-trip."""
    clean_name = (name or "").strip().lower()
    if not _TEMPLATE_NAME_RE.fullmatch(clean_name):
        raise ValueError(
            "Template name must be 1-512 lowercase letters, numbers or "
            "underscores."
        )
    clean_language = (language or "en").strip()
    if not _LANGUAGE_RE.fullmatch(clean_language):
        raise ValueError(
            "Language must be a Meta code such as en, en_US, ar or ur."
        )
    clean_category = (category or "utility").strip().lower()
    if clean_category not in _AUTHORABLE_CATEGORIES:
        raise ValueError("Category must be utility or marketing.")

    clean_body = (body or "").strip()
    if not clean_body:
        raise ValueError("Template body is required.")
    if len(clean_body) > _BODY_MAX:
        raise ValueError(
            f"Template body must be {_BODY_MAX} characters or fewer."
        )
    variables = count_variables(clean_body)
    if variables:
        used = {int(n) for n in _VARIABLE_RE.findall(clean_body)}
        if used != set(range(1, variables + 1)):
            raise ValueError(
                "Template variables must be numbered {{1}}, {{2}}… without "
                "gaps."
            )
        samples = [str(v).strip() for v in (examples or [])]
        if len(samples) != variables or any(not v for v in samples):
            raise ValueError(
                f"This template has {variables} variable(s). Provide "
                f"{variables} sample value(s) so Meta can review it."
            )
        examples = samples
    else:
        examples = []
    return clean_name, clean_language, clean_category, clean_body, examples


def _provider_failure(action: str, exc: Exception) -> ValueError:
    return ValueError(
        f"Meta rejected the template {action}: {str(exc)[:400]}"
    )


async def create_template(
    db,
    tenant_id: str,
    *,
    name: str,
    language: str,
    category: str,
    body: str,
    examples: list[str] | None = None,
) -> WhatsAppTemplate:
    """Create a template and mirror Meta's initial review status locally."""
    from ..channels.meta.providers.base import MetaAPIError
    from ..channels.meta.service import get_adapter

    name, language, category, body, examples = _clean_template_input(
        name=name, language=language, category=category, body=body,
        examples=examples,
    )
    duplicate = (
        await db.execute(
            select(WhatsAppTemplate.id).where(
                WhatsAppTemplate.tenant_id == tenant_id,
                WhatsAppTemplate.name == name,
                WhatsAppTemplate.language == language,
            )
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise ValueError(
            "A template with this name and language already exists. Edit it "
            "instead."
        )

    asset, token = await _waba_and_token(db, tenant_id)
    adapter = get_adapter("whatsapp")
    try:
        remote = await adapter.create_template(
            asset.external_asset_id,
            token,
            name=name,
            language=language,
            category=category,
            body=body,
            examples=examples,
        )
    except MetaAPIError as exc:
        raise _provider_failure("creation", exc) from exc

    row = WhatsAppTemplate(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name=name,
        language=language,
        category=(remote.get("category") or category).lower()[:20],
        status=(remote.get("status") or "pending").lower()[:20],
        body=body,
        variables=count_variables(body),
        meta_template_id=str(remote.get("id") or "")[:64] or None,
        last_synced_at=_now(),
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ValueError(
            "A template with this name and language already exists."
        ) from exc
    await db.refresh(row)
    logger.info(
        "template created tenant=%s name=%s language=%s status=%s",
        tenant_id, name, language, row.status,
    )
    return row


async def update_template(
    db,
    tenant_id: str,
    template_id: str,
    *,
    category: str | None = None,
    body: str | None = None,
    examples: list[str] | None = None,
) -> WhatsAppTemplate:
    """Edit a template's body/category; Meta re-reviews it afterwards."""
    from ..channels.meta.providers.base import MetaAPIError
    from ..channels.meta.service import get_adapter

    row = await _get_template(db, tenant_id, template_id)
    if row.meta_template_id is None:
        raise ValueError(
            "This template has no Meta id yet. Press Sync from Meta, then edit."
        )

    new_category = (category or row.category).strip().lower()
    if new_category not in _AUTHORABLE_CATEGORIES:
        raise ValueError("Category must be utility or marketing.")
    new_body = row.body if body is None else body
    if body is not None:
        _, _, new_category, new_body, examples = _clean_template_input(
            name=row.name,
            language=row.language,
            category=new_category,
            body=new_body,
            examples=examples,
        )
    elif examples:
        # An empty list is the request model's default, not a caller trying to
        # send samples without a body.
        raise ValueError("Sample values can only be sent together with a body.")

    _asset, token = await _waba_and_token(db, tenant_id)
    adapter = get_adapter("whatsapp")
    try:
        remote = await adapter.update_template(
            row.meta_template_id,
            token,
            category=new_category,
            body=new_body if body is not None else None,
            examples=examples,
        )
    except MetaAPIError as exc:
        raise _provider_failure("update", exc) from exc

    row.category = (remote.get("category") or new_category).lower()[:20]
    if body is not None:
        row.body = new_body
        row.variables = count_variables(new_body)
    # Meta re-reviews an edited template before it can be sent again. Trust a
    # status in the response when present, otherwise return it to review rather
    # than leaving a stale APPROVED chip on content that changed.
    row.status = (remote.get("status") or "pending").lower()[:20]
    row.last_synced_at = _now()
    db.add(row)
    await db.commit()
    await db.refresh(row)
    logger.info(
        "template updated tenant=%s name=%s status=%s",
        tenant_id, row.name, row.status,
    )
    return row


async def delete_template(db, tenant_id: str, template_id: str) -> None:
    """Delete a template at Meta and locally; send history keeps its name."""
    from ..channels.meta.providers.base import MetaAPIError
    from ..channels.meta.service import get_adapter

    row = await _get_template(db, tenant_id, template_id)
    if row.meta_template_id is None:
        # Deleting by name would remove every language variant with that name,
        # including ones this row does not represent. Sync first so the exact
        # Meta id is known.
        raise ValueError(
            "This template has no Meta id yet. Press Sync from Meta, then delete."
        )
    # Capture before the delete: a committed delete expires the instance, and
    # the log below must not trigger a lazy refresh of a row that no longer
    # exists.
    name, language = row.name, row.language
    asset, token = await _waba_and_token(db, tenant_id)
    adapter = get_adapter("whatsapp")
    try:
        await adapter.delete_template(
            token,
            template_id=row.meta_template_id,
            waba_id=asset.external_asset_id,
            name=row.name,
        )
    except MetaAPIError as exc:
        raise _provider_failure("deletion", exc) from exc

    # TemplateSend has ON DELETE SET NULL, but the test SQLite engine does not
    # enforce it and production ordering should not depend on the FK action.
    # Null the link explicitly; template_name/language stay on each send row.
    await db.execute(
        update(TemplateSend)
        .where(
            TemplateSend.tenant_id == tenant_id,
            TemplateSend.template_id == template_id,
        )
        .values(template_id=None)
    )
    await db.delete(row)
    await db.commit()
    logger.info(
        "template deleted tenant=%s name=%s language=%s",
        tenant_id, name, language,
    )


async def sync_templates(db, tenant_id: str) -> dict:
    """Pull the WABA's templates from Meta and upsert them locally.

    Meta owns template content and status; this table mirrors it. A template
    that disappears from Meta stays locally with its last status rather than
    being deleted — send history references it.
    """
    from ..channels.meta.service import get_adapter

    asset, token = await _waba_and_token(db, tenant_id)
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

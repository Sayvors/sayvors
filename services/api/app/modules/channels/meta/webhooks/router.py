"""Central Meta webhook ingress: GET handshake + POST events.

Fast path only: verify -> persist raw -> enqueue -> 200. AI/automation
consumes the normalized events asynchronously (Phase 2).
"""
import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .....core.deps import get_db
from .....modules.outbox.models import EventOutbox
from ..models import MetaAsset, MetaConnection, MetaWebhookEvent
from . import parser as _parser
from .normalizer import normalize
from .verifier import MAX_BODY_BYTES, SIGNATURE_HEADER, verify_handshake, verify_signature

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/meta/webhooks", tags=["meta-webhooks"])

META_EVENTS_TOPIC = "meta-events"


@router.get("")
async def verify(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
):
    challenge = verify_handshake(hub_mode, hub_verify_token, hub_challenge)
    if challenge is None:
        logger.warning("Meta webhook handshake rejected")
        return Response(status_code=403, content="Forbidden")
    return Response(content=challenge, media_type="text/plain")


@router.post("")
async def ingress(request: Request, db: AsyncSession = Depends(get_db)):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_BODY_BYTES:
        return Response(status_code=413, content="Payload too large")
    raw_body = await request.body()
    if len(raw_body) > MAX_BODY_BYTES:
        return Response(status_code=413, content="Payload too large")

    if not verify_signature(raw_body, request.headers.get(SIGNATURE_HEADER)):
        logger.warning("Meta webhook signature rejected")
        return Response(status_code=403, content="Invalid signature")

    try:
        payload = json.loads(raw_body)
    except Exception:
        return Response(status_code=400, content="Invalid JSON")

    provider, raw_events = _parser.parse(payload)
    logger.info("Meta webhook provider=%s events=%d", provider, len(raw_events))

    for raw in raw_events:
        await _store_event(db, provider, payload, raw)
    return {"status": "ok", "events": len(raw_events)}


async def _store_event(
    db: AsyncSession, provider: str, payload: dict, raw: dict
) -> None:
    # ── Resolve tenant via our asset registry ──
    asset = (
        await db.execute(
            select(MetaAsset).where(
                MetaAsset.provider == provider,
                MetaAsset.external_asset_id == (raw.get("external_asset_id") or ""),
            )
        )
    ).scalar_one_or_none()

    tenant_id = asset.tenant_id if asset else None
    connection_id = asset.connection_id if asset else None
    status = "received" if asset else "unresolved"

    row = MetaWebhookEvent(
        id=str(uuid.uuid4()),
        provider=provider if provider != "unknown" else "unknown",
        external_event_id=str(raw.get("external_event_id") or "")[:255],
        event_type=str(raw.get("event_type") or "unknown"),
        tenant_id=tenant_id,
        connection_id=connection_id,
        raw_payload=payload,
        status=status,
        occurred_at=_parse_dt(raw.get("occurred_at")),
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError:
        # Replay / duplicate delivery: same (provider, event, type).
        await db.rollback()
        dup = (
            await db.execute(
                select(MetaWebhookEvent).where(
                    MetaWebhookEvent.provider == row.provider,
                    MetaWebhookEvent.external_event_id == row.external_event_id,
                    MetaWebhookEvent.event_type == row.event_type,
                )
            )
        ).scalar_one_or_none()
        if dup is not None and dup.status not in ("processed", "duplicate"):
            dup.status = "duplicate"
            db.add(dup)
            await db.commit()
        logger.info(
            "Meta webhook duplicate provider=%s event=%s",
            provider, row.external_event_id,
        )
        return

    if asset is not None:
        # Touch connection health + enqueue the normalized event for
        # async consumers. Request-scoped session: single local INSERT.
        conn = (
            await db.execute(
                select(MetaConnection).where(MetaConnection.id == connection_id)
            )
        ).scalar_one_or_none()
        if conn is not None:
            conn.last_webhook_received_at = datetime.now(timezone.utc)
            db.add(conn)
        normalized = normalize(raw, provider, tenant_id, connection_id)
        db.add(
            EventOutbox(
                id=str(uuid.uuid4()),
                event_type=f"meta.{normalized['event_type']}",
                payload=normalized,
                topic=META_EVENTS_TOPIC,
            )
        )
    else:
        logger.warning(
            "Meta webhook unresolved asset provider=%s external=%s",
            provider, raw.get("external_asset_id"),
        )
    await db.commit()


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None

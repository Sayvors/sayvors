import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_db, get_current_user
from ..team.context import TenantContext, get_context, require_perm
from ...database import async_session as _async_session
from ...config import settings
from ..auth.rate_limit import rate_limit
from ..users.models import User
from .models import (
    AutoReplyConfig,
    BusinessService,
    Channel,
    ChannelMessage,
    ChannelThread,
    ReviewIssue,
    ReviewReply,
    VerificationRecord,
)
from .schemas import (
    AutoReplyConfigResponse,
    AutoReplyConfigUpdate,
    ChannelCreate,
    ChannelListResponse,
    ChannelMessageListResponse,
    ChannelMessageResponse,
    ChannelMessageSend,
    ChannelResponse,
    InboxSendRequest,
    InteractiveSend,    InboxSendResponse,
    InboxThread,
    InboxThreadListResponse,
    ReviewReplyEdit,
    ReviewReplyGenerate,
    ReviewReplyListResponse,
    ReviewReplyResponse,
    ServiceCreate,
    ServiceResponse,
    ServiceUpdate,
    ThreadStateOut,
    VerificationRequest,
    VerificationResponse,
)
from .service import (
    UNKNOWN_THREAD_KEY,
    create_channel,
    decrypt_contact_phone,
    decrypt_message_content,
    delete_channel,
    get_channel,
    handle_webhook,
    hash_contact_phone,
    list_channels,
    list_inbox_threads,
    list_messages,
    list_thread_messages,
    send_message,
    send_interactive_message,
    verify_webhook_signature,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/channels", tags=["channels"])

MAX_WEBHOOK_BODY_BYTES = 1_000_000  # 1 MB


def _channel_source_info(channel: Channel) -> tuple[str | None, str | None]:
    """(source, listing_id) for a channel.

    "localith" = mirrored from a Localith listing sync (managed on the
    Localith card); "google" = native Google OAuth channel. parsed from
    metadata_json so the UI can show each branch exactly once.
    """
    import json as _json

    try:
        meta = _json.loads(channel.metadata_json or "{}")
    except (ValueError, TypeError):
        meta = {}
    if not isinstance(meta, dict):
        return None, None
    provider = str(meta.get("provider") or "").lower()
    if provider == "localith" or "listing_id" in meta:
        return "localith", str(meta.get("listing_id") or meta.get("location_id") or "")
    if channel.platform == "google_reviews":
        loc = meta.get("location_id")
        return "google", str(loc) if loc else None
    return None, None


def _channel_response(channel: Channel) -> ChannelResponse:
    source, listing_id = _channel_source_info(channel)
    return ChannelResponse(
        id=channel.id,
        platform=channel.platform,
        platform_user_id=channel.platform_user_id,
        display_name=channel.display_name,
        status=channel.status,
        avatar_url=channel.avatar_url,
        created_at=channel.created_at.isoformat(),
        source=source,
        listing_id=listing_id or None,
    )


@router.post("/", response_model=ChannelResponse, status_code=status.HTTP_201_CREATED)
async def connect_channel(
    body: ChannelCreate,
    ctx: TenantContext = Depends(require_perm("channels.connect")),
    db: AsyncSession = Depends(get_db),
):
    from ..billing.entitlements import get_entitlements
    from ..team.context import tenant_id_of

    tid = tenant_id_of(ctx.user)
    ent = await get_entitlements(tid, db)
    from ...channels.service import list_channels

    existing, _ = await list_channels(ctx.user, db, limit=100, offset=0)
    from ..billing.entitlements import entitlement_403

    if not ent.channel_quota_ok(len(existing)):
        raise entitlement_403(
            f"Channel limit reached for plan '{ent.plan_slug}' (max {ent.max_channels}). Upgrade to add more.",
            "quota",
        )
    if not ent.has_feature("channels"):
        raise entitlement_403("Channels are not included in your plan.", "channels")

    try:
        channel = await create_channel(body, ctx.user, db)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _channel_response(channel)


@router.get("", response_model=ChannelListResponse)
async def get_channels(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    ctx: TenantContext = Depends(require_perm("channels.view")),
    db: AsyncSession = Depends(get_db),
):
    channels, total = await list_channels(ctx.user, db, limit, offset)
    # A member with no role-wide channel default only sees channels they
    # were explicitly granted (per-channel overrides), never the rest.
    visible = ctx.visible_channel_ids()
    if visible is not None:
        channels = [c for c in channels if c.id in visible]
        total = len(channels)
    return ChannelListResponse(
        channels=[_channel_response(c) for c in channels],
        total=total,
    )


@router.get("/{channel_id}", response_model=ChannelResponse)
async def get_channel_by_id(
    channel_id: str,
    ctx: TenantContext = Depends(require_perm("channels.view")),
    db: AsyncSession = Depends(get_db),
):
    if ctx.channel_level(channel_id) == "none":
        raise HTTPException(status_code=404, detail="Channel not found")
    channel = await get_channel(channel_id, ctx.user, db)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return _channel_response(channel)


@router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_channel(
    channel_id: str,
    ctx: TenantContext = Depends(require_perm("channels.remove")),
    db: AsyncSession = Depends(get_db),
):
    if not ctx.can_edit_channel(channel_id):
        raise HTTPException(status_code=404, detail="Channel not found")
    deleted = await delete_channel(channel_id, ctx.user, db)
    if not deleted:
        raise HTTPException(status_code=404, detail="Channel not found")


async def _google_channel(channel_id: str, user: User, db: AsyncSession) -> Channel:
    channel = await get_channel(channel_id, user, db)
    if not channel or channel.platform != "google_reviews":
        raise HTTPException(status_code=404, detail="Google channel not found")
    return channel


def _verification_response(record: VerificationRecord | None, channel_id: str) -> VerificationResponse:
    return VerificationResponse(
        channel_id=channel_id,
        status=record.status if record else "unstarted",
        method=record.method if record else None,
        contact_target=record.contact_target if record else None,
        attempts=record.attempts if record else 0,
        requested_at=record.requested_at.isoformat() if record and record.requested_at else None,
        verified_at=record.verified_at.isoformat() if record and record.verified_at else None,
    )


@router.get("/{channel_id}/verification", response_model=VerificationResponse)
async def get_verification(
    channel_id: str,
    ctx: TenantContext = Depends(require_perm("channels.view")),
    db: AsyncSession = Depends(get_db),
):
    if ctx.channel_level(channel_id) == "none":
        raise HTTPException(status_code=404, detail="Channel not found")
    await _google_channel(channel_id, ctx.user, db)
    result = await db.execute(select(VerificationRecord).where(VerificationRecord.channel_id == channel_id))
    return _verification_response(result.scalar_one_or_none(), channel_id)


@router.post("/{channel_id}/verification", response_model=VerificationResponse)
async def request_verification(
    channel_id: str,
    body: VerificationRequest,
    ctx: TenantContext = Depends(require_perm("channels.edit")),
    db: AsyncSession = Depends(get_db),
):
    if not ctx.can_edit_channel(channel_id):
        raise HTTPException(status_code=403, detail="No edit access to this channel")
    channel = await _google_channel(channel_id, ctx.user, db)
    result = await db.execute(select(VerificationRecord).where(VerificationRecord.channel_id == channel_id))
    record = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if record is None:
        record = VerificationRecord(channel_id=channel_id)
        db.add(record)
    record.status = "requested"
    record.method = body.method
    record.contact_target = body.contact_target
    record.attempts += 1
    record.requested_at = now
    from ..outbox.service import enqueue_event_in

    await enqueue_event_in(db, "google.verification.requested", {"channel_id": channel.id, "method": body.method}, "google-business-events")
    await db.commit()
    await db.refresh(record)
    return _verification_response(record, channel_id)


def _service_response(service: BusinessService) -> ServiceResponse:
    return ServiceResponse(
        id=service.id,
        channel_id=service.channel_id,
        name=service.name,
        category=service.category,
        description=service.description,
        is_offered=service.is_offered,
        source=service.source,
    )


@router.get("/{channel_id}/services")
async def list_services(
    channel_id: str,
    ctx: TenantContext = Depends(require_perm("channels.view")),
    db: AsyncSession = Depends(get_db),
):
    if ctx.channel_level(channel_id) == "none":
        raise HTTPException(status_code=404, detail="Channel not found")
    await _google_channel(channel_id, ctx.user, db)
    result = await db.execute(
        select(BusinessService).where(BusinessService.channel_id == channel_id).order_by(BusinessService.created_at)
    )
    return {"services": [_service_response(item) for item in result.scalars().all()], "predefined": []}


@router.post("/{channel_id}/services", response_model=ServiceResponse, status_code=status.HTTP_201_CREATED)
async def create_service(
    channel_id: str,
    body: ServiceCreate,
    ctx: TenantContext = Depends(require_perm("channels.edit")),
    db: AsyncSession = Depends(get_db),
):
    if not ctx.can_edit_channel(channel_id):
        raise HTTPException(status_code=403, detail="No edit access to this channel")
    await _google_channel(channel_id, ctx.user, db)
    service = BusinessService(channel_id=channel_id, **body.model_dump())
    db.add(service)
    from ..outbox.service import enqueue_event_in

    await enqueue_event_in(db, "google.service.created", {"channel_id": channel_id, "service_id": service.id}, "google-business-events")
    await db.commit()
    await db.refresh(service)
    return _service_response(service)


@router.put("/{channel_id}/services/{service_id}", response_model=ServiceResponse)
async def update_service(
    channel_id: str,
    service_id: str,
    body: ServiceUpdate,
    ctx: TenantContext = Depends(require_perm("channels.edit")),
    db: AsyncSession = Depends(get_db),
):
    if not ctx.can_edit_channel(channel_id):
        raise HTTPException(status_code=403, detail="No edit access to this channel")
    await _google_channel(channel_id, ctx.user, db)
    result = await db.execute(select(BusinessService).where(BusinessService.id == service_id, BusinessService.channel_id == channel_id))
    service = result.scalar_one_or_none()
    if service is None:
        raise HTTPException(status_code=404, detail="Service not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(service, key, value)
    from ..outbox.service import enqueue_event_in

    await enqueue_event_in(db, "google.service.updated", {"channel_id": channel_id, "service_id": service.id}, "google-business-events")
    await db.commit()
    await db.refresh(service)
    return _service_response(service)


@router.delete("/{channel_id}/services/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_service(
    channel_id: str,
    service_id: str,
    ctx: TenantContext = Depends(require_perm("channels.edit")),
    db: AsyncSession = Depends(get_db),
):
    if not ctx.can_edit_channel(channel_id):
        raise HTTPException(status_code=403, detail="No edit access to this channel")
    await _google_channel(channel_id, ctx.user, db)
    result = await db.execute(select(BusinessService).where(BusinessService.id == service_id, BusinessService.channel_id == channel_id))
    service = result.scalar_one_or_none()
    if service is None:
        raise HTTPException(status_code=404, detail="Service not found")
    await db.delete(service)
    from ..outbox.service import enqueue_event_in

    await enqueue_event_in(db, "google.service.deleted", {"channel_id": channel_id, "service_id": service_id}, "google-business-events")
    await db.commit()


@router.post("/{channel_id}/messages", response_model=ChannelMessageResponse, status_code=status.HTTP_201_CREATED)
async def send_to_channel(
    channel_id: str,
    body: ChannelMessageSend,
    ctx: TenantContext = Depends(require_perm("inbox.reply")),
    db: AsyncSession = Depends(get_db),
):
    if not ctx.can_edit_channel(channel_id):
        raise HTTPException(status_code=403, detail="No edit access to this channel")
    try:
        msg = await send_message(channel_id, body, ctx.user, db)
    except ValueError as exc:
        message = str(exc)
        if message == "Channel not found":
            raise HTTPException(status_code=404, detail=message)
        # A missing recipient is a bad request, not a missing channel.
        raise HTTPException(status_code=422, detail=message)
    return ChannelMessageResponse(
        id=msg.id,
        channel_id=msg.channel_id,
        platform_message_id=msg.platform_message_id,
        direction=msg.direction,
        content=decrypt_message_content(msg.content),
        content_type=msg.content_type,
        status=msg.status,
        error=msg.error,
        contact_phone=decrypt_contact_phone(msg.contact_phone),
        contact_name=msg.contact_name,
        created_at=msg.created_at.isoformat(),
    )


@router.post(
    "/{channel_id}/interactive",
    response_model=ChannelMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def send_interactive_to_channel(
    channel_id: str,
    body: InteractiveSend,
    ctx: TenantContext = Depends(require_perm("inbox.reply")),
    db: AsyncSession = Depends(get_db),
):
    """Send WhatsApp reply buttons, a list menu, or a CTA link.

    The tap arrives back as an ordinary inbound text message carrying the
    button/row title, so the AI and the inbox handle it with no special case.
    """
    if not ctx.can_edit_channel(channel_id):
        raise HTTPException(status_code=403, detail="No edit access to this channel")

    payload: dict = {
        "body": body.body,
        "header": body.header,
        "footer": body.footer,
    }
    if body.kind == "buttons":
        if not body.buttons:
            raise HTTPException(status_code=422, detail="buttons are required")
        payload["buttons"] = body.buttons
    elif body.kind == "list":
        if not body.button_text or not body.sections:
            raise HTTPException(
                status_code=422, detail="button_text and sections are required"
            )
        payload["button_text"] = body.button_text
        payload["sections"] = body.sections
    else:
        if not body.display_text or not body.url:
            raise HTTPException(
                status_code=422, detail="display_text and url are required"
            )
        payload["display_text"] = body.display_text
        payload["url"] = body.url

    try:
        msg = await send_interactive_message(
            channel_id,
            contact_phone=body.contact_phone,
            kind=body.kind,
            payload=payload,
            user=ctx.user,
            db=db,
            contact_name=body.contact_name,
        )
    except ValueError as exc:
        message = str(exc)
        if message == "Channel not found":
            raise HTTPException(status_code=404, detail=message)
        raise HTTPException(status_code=422, detail=message)

    return ChannelMessageResponse(
        id=msg.id,
        channel_id=msg.channel_id,
        platform_message_id=msg.platform_message_id,
        direction=msg.direction,
        content=decrypt_message_content(msg.content),
        content_type=msg.content_type,
        status=msg.status,
        error=msg.error,
        contact_phone=decrypt_contact_phone(msg.contact_phone),
        contact_name=msg.contact_name,
        created_at=msg.created_at.isoformat(),
    )


@router.get("/{channel_id}/messages", response_model=ChannelMessageListResponse)
async def get_channel_messages(
    channel_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: TenantContext = Depends(require_perm("inbox.view")),
    db: AsyncSession = Depends(get_db),
):
    if ctx.channel_level(channel_id) == "none":
        raise HTTPException(status_code=404, detail="Channel not found")
    msgs, total = await list_messages(channel_id, ctx.user, db, limit, offset)
    return ChannelMessageListResponse(
        messages=[
            ChannelMessageResponse(
                id=m.id,
                channel_id=m.channel_id,
                platform_message_id=m.platform_message_id,
                direction=m.direction,
                content=decrypt_message_content(m.content),
                content_type=m.content_type,
                status=m.status,
                error=m.error,
                contact_phone=decrypt_contact_phone(m.contact_phone),
                contact_name=m.contact_name,
                created_at=m.created_at.isoformat(),
            )
            for m in msgs
        ],
        total=total,
    )


# ── Inbox ───────────────────────────────────────────────────────────────
#
# Declared before /{channel_id} so "inbox" is not read as a channel ID.

_inbox_router = APIRouter(prefix="/api/v1/inbox", tags=["inbox"])


@_inbox_router.post("/ws-ticket")
async def create_ws_ticket(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Issue a short-lived (30s) one-time ticket for WebSocket auth.

    SEC-H3: moves the access token off the URL (access logs) by exchanging
    it for a single-use ticket that can be passed as ?ticket= to /ws.
    """
    import secrets
    ticket = secrets.token_urlsafe(32)
    try:
        from ..redis.client import get_redis
        redis = await get_redis()
        await redis.setex(f"ws:ticket:{ticket}", 30, user.id)
    except Exception:
        # Redis down — fall back to allowing the full token (degraded mode)
        pass
    return {"ticket": ticket}


@_inbox_router.websocket("/ws")
async def inbox_ws(websocket: WebSocket):
    """Live inbox events for the authenticated user.

    G2: access token travels as an httpOnly cookie. Browsers send cookies
    with same-origin WebSocket connections, so we read it from
    ``websocket.cookies`` first, falling back to the ``?token=`` query
    param for non-browser clients.
    """
    token = websocket.cookies.get(settings.ACCESS_COOKIE_NAME, "")
    ticket = websocket.query_params.get("ticket") or ""
    if not token and not ticket:
        token = websocket.query_params.get("token") or ""

    user_id = None
    payload = None
    try:
        if ticket:
            # SEC-H3: one-time ticket (moves token off URL). Single-use:
            # delete from Redis after validation so it can't be replayed.
            try:
                from ..redis.client import get_redis
                redis = await get_redis()
                user_id = await redis.get(f"ws:ticket:{ticket}")
                if user_id:
                    await redis.delete(f"ws:ticket:{ticket}")
                user_id = user_id.decode() if isinstance(user_id, bytes) else user_id
            except Exception:
                user_id = None
            if not user_id:
                raise ValueError("invalid or expired ticket")
        else:
            import jwt as pyjwt

            payload = pyjwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
            user_id = payload.get("sub")
            if not user_id or payload.get("type") != "access":
                raise ValueError("bad token")
            # SEC-H3: enforce revocation — blacklist (logout/reuse) and
            # token_version (password change / logout-all). Mirrors get_current_user.
            from ..auth.rate_limit import is_token_blacklisted
            if await is_token_blacklisted(payload.get("jti", "")):
                raise ValueError("token revoked")
            from sqlalchemy import select
            from ..users.models import User
            from ..team.models import TeamMember
            async with _async_session() as _chk:
                _tv = (await _chk.execute(
                    select(User.token_version).where(User.id == user_id)
                )).scalar_one_or_none()
                if payload.get("ver", 0) != (_tv or 0):
                    raise ValueError("token revoked")
                # Suspension check (mirrors get_current_user)
                _user = (await _chk.execute(
                    select(User).where(User.id == user_id)
                )).scalar_one_or_none()
                if _user and _user.tenant_id and _user.tenant_id != _user.id:
                    _member = (await _chk.execute(
                        select(TeamMember.status).where(
                            TeamMember.user_id == _user.id,
                            TeamMember.tenant_id == _user.tenant_id,
                        )
                    )).scalar_one_or_none()
                    if _member == "suspended":
                        raise ValueError("account suspended")
    except Exception:
        await websocket.close(code=4401)
        return

    await websocket.accept()

    # Resolve user to get tenant for workspace-level realtime
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession
    async with _async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user_row = result.scalar_one_or_none()
        tenant_key = (getattr(user_row, 'tenant_id', None) or user_row.id) if user_row else user_id
    from .realtime import subscribe_inbox
    try:
        client, pubsub = await subscribe_inbox(tenant_key)
    except Exception:
        await websocket.close(code=1013)
        return

    import asyncio

    async def _heartbeat():
        try:
            while True:
                await asyncio.sleep(25)
                # Periodic revocation check: only for token-based auth
                # (ticket-based auth is single-use and already consumed).
                if payload is not None:
                    try:
                        from ..auth.rate_limit import is_token_blacklisted
                        if await is_token_blacklisted(payload.get("jti", "")):
                            await websocket.close(code=4401)
                            return
                        async with _async_session() as _chk:
                            _tv = (await _chk.execute(
                                select(User.token_version).where(User.id == user_id)
                            )).scalar_one_or_none()
                            if payload.get("ver", 0) != (_tv or 0):
                                await websocket.close(code=4401)
                                return
                    except Exception:
                        pass
                await websocket.send_json({"type": "ping"})
        except Exception:
            pass

    beat = asyncio.create_task(_heartbeat())
    try:
        async for msg in pubsub.listen():
            if msg.get("type") != "message" or not msg.get("data"):
                continue
            try:
                await websocket.send_text(msg["data"])
            except Exception:
                break
    except WebSocketDisconnect:
        pass
    finally:
        beat.cancel()
        try:
            from .realtime import unsubscribe_inbox
            await unsubscribe_inbox(tenant_key, pubsub._queue)
        except Exception:
            pass


@_inbox_router.get("/threads", response_model=InboxThreadListResponse)
async def inbox_threads(
    search: str | None = Query(None, max_length=200),
    category: str | None = Query(None, max_length=32),
    priority: str | None = Query(None, max_length=16),
    important: bool | None = Query(None),
    include_archived: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    ctx: TenantContext = Depends(require_perm("inbox.view")),
    db: AsyncSession = Depends(get_db),
):
    """List inbox threads, optionally filtered by category, priority or
    the derived `important` flag."""
    threads = await list_inbox_threads(ctx.user, db, search=search, limit=limit, include_archived=include_archived)
    if category:
        threads = [t for t in threads if t.get("category") == category]
    if priority:
        threads = [t for t in threads if t.get("priority") == priority]
    if important is not None:
        threads = [t for t in threads if bool(t.get("important")) is important]
    visible = ctx.visible_channel_ids()
    if visible is not None:
        threads = [t for t in threads if t.get("channel_id") in visible]
    return InboxThreadListResponse(threads=[InboxThread(**t) for t in threads], total=len(threads))


@_inbox_router.get("/threads/{channel_id}/{contact_phone}", response_model=ChannelMessageListResponse)
async def inbox_thread_messages(
    channel_id: str,
    contact_phone: str,
    limit: int = Query(200, ge=1, le=500),
    ctx: TenantContext = Depends(require_perm("inbox.view")),
    db: AsyncSession = Depends(get_db),
):
    """Messages in one thread, oldest first.

    `contact_phone` is the literal string "unknown" for the catch-all thread
    holding pre-migration rows with no sender.
    """
    if ctx.channel_level(channel_id) == "none":
        raise HTTPException(status_code=404, detail="Channel not found")
    phone = None if contact_phone == UNKNOWN_THREAD_KEY else contact_phone
    msgs = await list_thread_messages(ctx.user, db, channel_id, phone, limit=limit)
    if not msgs:
        # Distinguish "no such channel" (404) from "empty thread" (200, empty).
        channel = await get_channel(channel_id, ctx.user, db)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")
    thread_state = None
    if phone is not None:
        thread_state = await _thread_state(db, ctx.tenant_id, channel_id, phone)
    return ChannelMessageListResponse(
        messages=[
            ChannelMessageResponse(
                id=m.id,
                channel_id=m.channel_id,
                platform_message_id=m.platform_message_id,
                direction=m.direction,
                content=decrypt_message_content(m.content),
                content_type=m.content_type,
                status=m.status,
                error=m.error,
                contact_phone=decrypt_contact_phone(m.contact_phone),
                contact_name=m.contact_name,
                created_at=m.created_at.isoformat(),
            )
            for m in msgs
        ],
        total=len(msgs),
        thread=thread_state,
    )


async def _thread_state(db, tenant_id: str, channel_id: str, phone: str) -> ThreadStateOut:
    """Mode, newest summary, window and consent for one thread.

    Both reads are indexed and bounded; a read failure degrades to the safe
    default (AI owns) rather than failing the whole thread view.
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import func

    from .conversation_context import latest
    from .conversation_mode import get_state
    from .models import ChannelMessage, Lead

    state = await get_state(db, channel_id, phone)
    context = None
    try:
        row = await latest(db, channel_id=channel_id, contact_phone=phone)
        if row is not None:
            summary = decrypt_message_content(row.summary) or ""
            if summary.strip():
                context = {
                    "summary": summary,
                    "message_count": int(row.message_count or 0),
                    "reason": row.reason or "manual",
                    "created_at": row.created_at.isoformat(),
                }
    except Exception as e:  # noqa: BLE001 - the card is an enhancement
        logger.warning(
            "thread context read failed channel=%s: %s", channel_id, e
        )

    # Meta's window and the template consent basis. A failure here must not
    # hide the thread: the fields simply read as "closed / no consent", which
    # is the safe side for a send.
    window_open = False
    opt_in_at = opt_in_source = None
    opted_out = False
    try:
        last_inbound = (
            await db.execute(
                select(func.max(ChannelMessage.created_at)).where(
                    ChannelMessage.channel_id == channel_id,
                    ChannelMessage.contact_phone_hash == hash_contact_phone(phone),
                    ChannelMessage.direction == "inbound",
                )
            )
        ).scalar()
        if last_inbound is not None:
            if last_inbound.tzinfo is None:
                last_inbound = last_inbound.replace(tzinfo=timezone.utc)
            window_open = (
                datetime.now(timezone.utc) - last_inbound
            ) < timedelta(hours=24)

        lead = (
            await db.execute(
                select(Lead)
                .where(Lead.channel_id == channel_id, Lead.contact_id == phone)
                .order_by(Lead.created_at.asc())
                .limit(1)
            )
        ).scalars().first()
        if lead is not None:
            opt_in_at = (
                lead.whatsapp_opt_in_at.isoformat()
                if lead.whatsapp_opt_in_at
                else None
            )
            opt_in_source = lead.whatsapp_opt_in_source
            opted_out = bool(lead.opt_out)
    except Exception as e:  # noqa: BLE001 - see above
        logger.warning("thread window/consent read failed channel=%s: %s", channel_id, e)

    return ThreadStateOut(
        **state,
        context=context,
        reply_window_open=window_open,
        opt_in_at=opt_in_at,
        opt_in_source=opt_in_source,
        opted_out=opted_out,
    )


class ThreadModeUpdate(BaseModel):
    mode: str = Field(..., pattern="^(ai|human)$")
    reason: str | None = Field(None, max_length=200)


@_inbox_router.patch(
    "/threads/{channel_id}/{contact_phone}/mode",
    response_model=ThreadStateOut,
)
async def inbox_thread_set_mode(
    channel_id: str,
    contact_phone: str,
    body: ThreadModeUpdate,
    ctx: TenantContext = Depends(require_perm("inbox.reply")),
    db: AsyncSession = Depends(get_db),
):
    """Switch the conversation between AI and human ownership.

    This is the explicit control behind the inbox switch. "human" mutes the
    AI immediately and cancels queued follow-ups; "ai" hands the thread back
    with a fresh escalation clock. Both directions write a context snapshot,
    so whoever answers next — model or person — starts oriented.
    """
    if not ctx.can_edit_channel(channel_id):
        raise HTTPException(status_code=403, detail="No edit access to this channel")
    # can_edit_channel is a role-level check; it does not verify the channel
    # belongs to this tenant. Resolve ownership explicitly or this endpoint
    # would switch another tenant's thread.
    if await get_channel(channel_id, ctx.user, db) is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    phone = None if contact_phone == UNKNOWN_THREAD_KEY else contact_phone
    if phone is None:
        raise HTTPException(
            status_code=422,
            detail="An unattributed thread has nobody to switch.",
        )

    from .conversation_context import generate
    from .conversation_mode import set_mode

    try:
        thread = await set_mode(
            db,
            tenant_id=ctx.tenant_id,
            channel_id=channel_id,
            contact_phone=phone,
            mode=body.mode,
            by=ctx.user.id,
            reason=(body.reason or "manual")[:200],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if thread is None:
        raise HTTPException(
            status_code=409, detail="Could not open this conversation thread."
        )

    await generate(
        db,
        tenant_id=ctx.tenant_id,
        channel_id=channel_id,
        contact_phone=phone,
        reason="mode_change",
    )

    from .realtime import publish_inbox_event

    await publish_inbox_event(ctx.tenant_id, {
        "type": "mode",
        "channel_id": channel_id,
        "contact_phone": phone,
        "mode": body.mode,
        "mode_changed_by": ctx.user.id,
    })
    return await _thread_state(db, ctx.tenant_id, channel_id, phone)


@_inbox_router.post(
    "/threads/{channel_id}/{contact_phone}/resolve",
    response_model=ThreadStateOut,
)
async def inbox_thread_resolve(
    channel_id: str,
    contact_phone: str,
    ctx: TenantContext = Depends(require_perm("inbox.reply")),
    db: AsyncSession = Depends(get_db),
):
    """Close the human session and hand the thread back to the AI.

    The summary written here is what the AI resumes with, so the customer does
    not have to repeat the conversation to a different responder.
    """
    if not ctx.can_edit_channel(channel_id):
        raise HTTPException(status_code=403, detail="No edit access to this channel")
    # Ownership, not just role permission — see the mode endpoint.
    if await get_channel(channel_id, ctx.user, db) is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    phone = None if contact_phone == UNKNOWN_THREAD_KEY else contact_phone
    if phone is None:
        raise HTTPException(
            status_code=422,
            detail="An unattributed thread has nobody to switch.",
        )

    from .conversation_context import generate
    from .conversation_mode import resolve as resolve_thread

    thread = await resolve_thread(
        db,
        tenant_id=ctx.tenant_id,
        channel_id=channel_id,
        contact_phone=phone,
        user_id=ctx.user.id,
    )
    if thread is None:
        raise HTTPException(
            status_code=409, detail="Could not open this conversation thread."
        )

    await generate(
        db,
        tenant_id=ctx.tenant_id,
        channel_id=channel_id,
        contact_phone=phone,
        reason="resolve",
    )

    from .realtime import publish_inbox_event

    await publish_inbox_event(ctx.tenant_id, {
        "type": "mode",
        "channel_id": channel_id,
        "contact_phone": phone,
        "mode": "ai",
        "mode_changed_by": ctx.user.id,
    })
    return await _thread_state(db, ctx.tenant_id, channel_id, phone)


class ThreadCategoryUpdate(BaseModel):
    category: str = Field(..., min_length=1, max_length=32)
    priority: str | None = Field(None, max_length=16)


@_inbox_router.patch("/threads/{channel_id}/{contact_phone}/category", response_model=dict)
async def inbox_thread_update_category(
    channel_id: str,
    contact_phone: str,
    body: ThreadCategoryUpdate,
    ctx: TenantContext = Depends(require_perm("inbox.view")),
    db: AsyncSession = Depends(get_db),
):
    """Update the category/priority of all messages in a thread.

    The tenant can override the auto-assigned category. Updates every message
    in the thread so the inbox filter reflects the change immediately.
    """
    if ctx.channel_level(channel_id) == "none":
        raise HTTPException(status_code=404, detail="Channel not found")
    phone = None if contact_phone == UNKNOWN_THREAD_KEY else contact_phone
    from sqlalchemy import update

    phone_hash = hash_contact_phone(phone) if phone else None
    conditions = [ChannelMessage.channel_id == channel_id]
    if phone_hash is None:
        conditions.append(ChannelMessage.contact_phone_hash.is_(None))
    else:
        conditions.append(ChannelMessage.contact_phone_hash == phone_hash)

    await db.execute(
        update(ChannelMessage)
        .where(*conditions)
        .values(category=body.category, priority=body.priority)
    )
    await db.commit()
    return {"channel_id": channel_id, "contact_phone": phone, "category": body.category, "priority": body.priority}


@_inbox_router.patch("/threads/{channel_id}/{contact_phone}/archive", response_model=dict)
async def inbox_thread_archive(
    channel_id: str,
    contact_phone: str,
    body: dict,
    ctx: TenantContext = Depends(require_perm("inbox.view")),
    db: AsyncSession = Depends(get_db),
):
    """Archive or unarchive a thread. Body: {\"archived\": true|false}.

    Soft delete: sets archived_at on the ChannelThread row. The thread and
    its messages are preserved and reappear when unarchived.
    """
    if ctx.channel_level(channel_id) == "none":
        raise HTTPException(status_code=404, detail="Channel not found")
    phone = None if contact_phone == UNKNOWN_THREAD_KEY else contact_phone
    from sqlalchemy import update

    phone_hash = hash_contact_phone(phone) if phone else None
    conditions = [ChannelThread.channel_id == channel_id]
    if phone_hash is None:
        conditions.append(ChannelThread.contact_phone_hash.is_(None))
    else:
        conditions.append(ChannelThread.contact_phone_hash == phone_hash)

    archived = bool(body.get("archived", True))
    await db.execute(
        update(ChannelThread)
        .where(*conditions)
        .values(archived_at=datetime.now(timezone.utc) if archived else None)
    )
    await db.commit()
    return {"channel_id": channel_id, "contact_phone": phone, "archived": archived}


@_inbox_router.delete("/threads/{channel_id}/{contact_phone}", status_code=status.HTTP_204_NO_CONTENT)
async def inbox_thread_delete(
    channel_id: str,
    contact_phone: str,
    ctx: TenantContext = Depends(require_perm("inbox.view")),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete a thread and all its messages.

    Destructive: removes every channel_messages row for this (channel,
    contact) and the channel_threads summary row. Cannot be undone.
    """
    if ctx.channel_level(channel_id) == "none":
        raise HTTPException(status_code=404, detail="Channel not found")
    # channel_level is a role default, not an ownership check — without this a
    # member of one tenant could delete another tenant's conversation by id.
    if await get_channel(channel_id, ctx.user, db) is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    phone = None if contact_phone == UNKNOWN_THREAD_KEY else contact_phone
    phone_hash = hash_contact_phone(phone) if phone else None
    from sqlalchemy import delete

    msg_conditions = [ChannelMessage.channel_id == channel_id]
    if phone_hash is None:
        msg_conditions.append(ChannelMessage.contact_phone_hash.is_(None))
    else:
        msg_conditions.append(ChannelMessage.contact_phone_hash == phone_hash)

    await db.execute(delete(ChannelMessage).where(*msg_conditions))

    # The stored summaries paraphrase those messages: deleting the thread
    # without them would leave PII behind and a stale card on a future thread
    # for the same contact.
    from .models import ConversationContext

    ctx_conditions = [ConversationContext.channel_id == channel_id]
    if phone_hash is None:
        ctx_conditions.append(ConversationContext.contact_phone_hash.is_(None))
    else:
        ctx_conditions.append(
            ConversationContext.contact_phone_hash == phone_hash
        )
    await db.execute(delete(ConversationContext).where(*ctx_conditions))

    thread_conditions = [ChannelThread.channel_id == channel_id]
    if phone_hash is None:
        thread_conditions.append(ChannelThread.contact_phone_hash.is_(None))
    else:
        thread_conditions.append(ChannelThread.contact_phone_hash == phone_hash)
    await db.execute(delete(ChannelThread).where(*thread_conditions))
    await db.commit()
    return None


@_inbox_router.patch("/threads/{channel_id}/{contact_phone}/pin", response_model=dict)
async def inbox_thread_pin(
    channel_id: str,
    contact_phone: str,
    body: dict,
    ctx: TenantContext = Depends(require_perm("inbox.view")),
    db: AsyncSession = Depends(get_db),
):
    """Pin or unpin a thread. Body: {"pinned": true|false}."""
    if ctx.channel_level(channel_id) == "none":
        raise HTTPException(status_code=404, detail="Channel not found")
    phone = None if contact_phone == UNKNOWN_THREAD_KEY else contact_phone
    phone_hash = hash_contact_phone(phone) if phone else None
    from sqlalchemy import update

    conditions = [ChannelThread.channel_id == channel_id]
    if phone_hash is None:
        conditions.append(ChannelThread.contact_phone_hash.is_(None))
    else:
        conditions.append(ChannelThread.contact_phone_hash == phone_hash)

    pinned = bool(body.get("pinned", True))
    await db.execute(
        update(ChannelThread)
        .where(*conditions)
        .values(pinned_at=datetime.now(timezone.utc) if pinned else None)
    )
    await db.commit()
    return {"channel_id": channel_id, "contact_phone": phone, "pinned": pinned}


@_inbox_router.post("/send", response_model=InboxSendResponse)
async def inbox_send(
    body: InboxSendRequest,
    ctx: TenantContext = Depends(require_perm("inbox.reply")),
    db: AsyncSession = Depends(get_db),
):
    """Send a message to a contact.

    Always 200 with `sent: false` and the provider's reason when WhatsApp
    rejects it — an out-of-window send is a normal outcome, not a server fault,
    and the thread shows it as failed rather than pretending it went out.
    """
    if not ctx.can_edit_channel(body.channel_id):
        raise HTTPException(status_code=403, detail="No edit access to this channel")
    # Plan entitlements: feature gate + monthly message cap (fail closed).
    from ..billing.entitlements import count_messages_this_month, get_entitlements
    from ..team.context import tenant_id_of

    tid = tenant_id_of(ctx.user)
    ent = await get_entitlements(tid, db)
    from ..billing.entitlements import entitlement_403

    if not ent.has_feature("messaging"):
        raise entitlement_403("Messaging is not included in your plan.", "messaging")
    used = await count_messages_this_month(tid, db)
    if not ent.message_quota_ok(used):
        from ..billing.entitlements import ENTITLEMENT_DENIED_HEADER

        raise HTTPException(
            status_code=429,
            detail=f"Monthly message limit reached for plan '{ent.plan_slug}'. Upgrade to send more.",
            headers={ENTITLEMENT_DENIED_HEADER: "quota"},
        )
    try:
        msg = await send_message(
            body.channel_id,
            ChannelMessageSend(
                content=body.content,
                content_type="text",
                contact_phone=body.contact_phone,
                contact_name=body.contact_name,
            ),
            ctx.user,
            db,
        )
    except ValueError as exc:
        message = str(exc)
        if message == "Channel not found":
            raise HTTPException(status_code=404, detail=message)
        raise HTTPException(status_code=422, detail=message)

    failed = msg.status == "failed"

    from .realtime import publish_inbox_event

    await publish_inbox_event(ctx.tenant_id, {
        "type": "message",
        "id": msg.id,
        "channel_id": msg.channel_id,
        "platform": None,
        "direction": "outbound",
        "content": decrypt_message_content(msg.content),
        "content_type": msg.content_type,
        "status": msg.status,
        "contact_phone": decrypt_contact_phone(msg.contact_phone),
        "contact_name": msg.contact_name,
        "created_at": msg.created_at,
    })

    return InboxSendResponse(
        message=ChannelMessageResponse(
            id=msg.id,
            channel_id=msg.channel_id,
            platform_message_id=msg.platform_message_id,
            direction=msg.direction,
            content=decrypt_message_content(msg.content),
            content_type=msg.content_type,
            status=msg.status,
            error=msg.error,
            contact_phone=decrypt_contact_phone(msg.contact_phone),
            contact_name=msg.contact_name,
            created_at=msg.created_at.isoformat(),
        ),
        sent=not failed,
        error=msg.error,
    )


# ── Webhooks (no auth — platform sends these) ──────────────────────────

# Platform → header that carries the HMAC signature
_SIGNATURE_HEADERS = {
    "facebook": "x-hub-signature-256",
    "instagram": "x-hub-signature-256",
    "x": "x-twitter-webhooks-signature",
    "telegram": "x-telegram-bot-api-secret-token",
    "whatsapp": "x-hub-signature-256",
    "linkedin": "x-linkedin-signature",
}


@router.post("/webhook/{platform}")
async def channel_webhook(
    platform: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    # ── Enforce body size limit ──
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_WEBHOOK_BODY_BYTES:
        return Response(status_code=413, content="Payload too large")

    raw_body = await request.body()
    if len(raw_body) > MAX_WEBHOOK_BODY_BYTES:
        return Response(status_code=413, content="Payload too large")

    # ── Signature verification (FAIL CLOSED) ──
    # Every branch below rejects: an unsigned/forged payload must never reach
    # dispatch. If no channel/secret is configured we cannot verify anything,
    # so the correct answer is 503, not "process anyway".
    sig_header = _SIGNATURE_HEADERS.get(platform)
    if not sig_header:
        return Response(status_code=404, content="Unknown platform")

    signature = request.headers.get(sig_header)
    channels = (
        await db.execute(
            select(Channel).where(
                Channel.platform == platform,
                Channel.status == "active",
            )
        )
    ).scalars().all()

    if not channels:
        logger.warning(
            "Webhook rejected for platform=%s: no active channel configured", platform
        )
        return Response(status_code=503, content="Channel not configured")

    secret_channels = [c for c in channels if c.webhook_secret]
    if not secret_channels:
        # A channel without a webhook secret cannot be authenticated.
        logger.warning(
            "Webhook rejected for platform=%s: no channel secret configured", platform
        )
        return Response(status_code=503, content="Webhook secret not configured")

    verified_channel = None
    for channel in secret_channels:
        if await verify_webhook_signature(platform, raw_body, signature or "", channel):
            verified_channel = channel
            break
    if verified_channel is None:
        # Unverified traffic (forged/unsigned): apply a per-IP rate limit
        # to prevent brute-force signature probing.
        if not settings.TESTING:
            client_ip = request.client.host if request.client else "unknown"
            if not await rate_limit(f"webhook:unverified:{platform}:{client_ip}", 20, 60):
                return Response(status_code=429, content="Too many requests")
        logger.warning("Webhook signature verification failed for platform=%s", platform)
        return Response(status_code=403, content="Invalid signature")

    # ── Rate limit (per verified channel, not global per platform) ──
    if not settings.TESTING and not await rate_limit(
        f"webhook:{platform}:{verified_channel.id}", 100, 60
    ):
        return Response(status_code=429, content="Too many requests")

    # ── Parse and dispatch ──
    try:
        import json
        payload = json.loads(raw_body)
    except Exception:
        return Response(status_code=400, content="Invalid JSON")

    msg = await handle_webhook(platform, payload, db)
    return {"status": "ok"}


# ── Google Reviews OAuth connect (REAL flow) ────────────


async def get_current_user_or_query_token(
    request: Request, db: AsyncSession = Depends(get_db)
):
    """Auth for browser-navigable endpoints: Authorization header OR ?ticket=.

    Browser navigations cannot send headers, but raw access JWTs in query
    strings leak via history, proxy logs, and Referer. Instead the SPA mints
    a 120-second single-use `google_connect` ticket (POST /google/connect-ticket)
    and passes THAT in the query — a leaked ticket is worthless after first
    use or two minutes, and never grants any other endpoint.
    """
    from ...core.deps import get_current_user

    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        # Reuse the standard dependency logic
        from fastapi.security import HTTPAuthorizationCredentials
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=auth_header[7:])
        return await get_current_user(creds, db)

    ticket = request.query_params.get("ticket")
    if not ticket:
        raise HTTPException(status_code=401, detail="Not authenticated")
    import jwt as pyjwt
    try:
        payload = pyjwt.decode(ticket, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
    if payload.get("type") != "google_connect":
        raise HTTPException(status_code=401, detail="Invalid token type")

    # Single-use: burn the jti. If Redis is down, degrade to TTL-only
    # (a 2-minute replay window beats bricking the connect flow).
    jti = payload.get("jti") or ""
    if jti:
        try:
            from ..redis.client import get_redis

            redis = await get_redis()
            burned = await redis.getdel(f"gct:{jti}")
            if not burned:
                raise HTTPException(status_code=401, detail="Ticket already used")
        except HTTPException:
            raise
        except Exception:
            logger.warning("Connect-ticket burn unavailable (Redis); accepting TTL-only")

    from ..users.models import User
    result = await db.execute(select(User).where(User.id == payload.get("sub")))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def _google_oauth_state(user_id: str, next_path: str | None = None) -> str:
    """Short-lived signed state binding the OAuth round-trip to the user."""
    import jwt as pyjwt
    import secrets
    from datetime import datetime, timedelta, timezone
    from ...config import settings as cfg

    payload = {
        "sub": user_id,
        "type": "google_oauth",
        "jti": secrets.token_hex(8),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
    }
    if next_path:
        payload["next"] = next_path
    return pyjwt.encode(payload, cfg.JWT_SECRET, algorithm=cfg.JWT_ALGORITHM)


def _verify_google_oauth_state(state: str) -> tuple[str | None, str | None]:
    """Returns (user_id, next_path) from a valid state token, else (None, None)."""
    import re
    import jwt as pyjwt
    from ...config import settings as cfg

    try:
        payload = pyjwt.decode(state, cfg.JWT_SECRET, algorithms=[cfg.JWT_ALGORITHM])
    except Exception:
        return None, None
    if payload.get("type") != "google_oauth":
        return None, None
    next_path = payload.get("next")
    if next_path and not re.fullmatch(r"/[A-Za-z0-9\-/_]*", next_path):
        next_path = None
    return payload.get("sub"), next_path


GOOGLE_CONNECT_TICKET_TTL_SECONDS = 120


class _ConnectTicketOut(BaseModel):
    ticket: str
    expires_in: int


@router.post("/google/connect-ticket", response_model=_ConnectTicketOut)
async def create_google_connect_ticket(
    user: User = Depends(get_current_user),
):
    """Mint a 120-second single-use ticket for the browser-navigable
    /google/connect endpoint, so long-lived access JWTs never appear in URLs.
    """
    import secrets
    from datetime import datetime, timedelta

    import jwt as pyjwt

    payload = {
        "sub": user.id,
        "type": "google_connect",
        "jti": secrets.token_hex(16),
        "exp": datetime.now(timezone.utc)
        + timedelta(seconds=GOOGLE_CONNECT_TICKET_TTL_SECONDS),
    }
    ticket = pyjwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    try:
        from ..redis.client import get_redis

        redis = await get_redis()
        await redis.setex(
            f"gct:{payload['jti']}",
            GOOGLE_CONNECT_TICKET_TTL_SECONDS,
            "1",
        )
    except Exception:
        # Without Redis the ticket is TTL-only — still a strict improvement
        # over a 15-minute access token in a URL.
        logger.warning("Connect-ticket jti not registered (Redis unavailable)")
    return _ConnectTicketOut(ticket=ticket, expires_in=GOOGLE_CONNECT_TICKET_TTL_SECONDS)


@router.get("/google/connect")
async def google_connect(
    request: Request,
    ticket: str | None = Query(None, description="Single-use connect ticket from POST /google/connect-ticket"),
    next: str | None = Query(None, description="Frontend path to return to after connect (e.g. /onboarding)"),
    user: User = Depends(get_current_user_or_query_token),
):
    """Start the Google OAuth flow. Open this URL in the browser.

    Works both with an Authorization header (API clients) and with
    `?ticket=<connect ticket>` (browser button navigations, which cannot
    send headers). The state is a signed, 10-min, one-flow token.
    """
    import re
    from .google_reviews import build_auth_url

    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=503,
            detail="Google OAuth app not configured. Set GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET in .env",
        )
    # Only allow safe relative frontend paths in the return-to
    safe_next = next if (next and re.fullmatch(r"/[A-Za-z0-9\-/_]*", next)) else None
    state = _google_oauth_state(user.id, safe_next)
    url = build_auth_url(state, settings.GOOGLE_REVIEWS_REDIRECT_URI)
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url)


_GOOGLE_ERROR_CODES = {
    "access_denied", "missing_code", "invalid_state", "token_exchange_failed",
    "accounts_unavailable", "no_business_account", "server_error",
}


def _safe_google_error(error: str | None) -> str:
    """Echo only known error codes back to the frontend — never raw input."""
    return error if error in _GOOGLE_ERROR_CODES else "oauth_error"


@router.get("/google/callback")
async def google_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Google OAuth redirect target: exchanges the code and creates channels
    for every Business Profile location found."""
    import uuid as _uuid
    from fastapi.responses import RedirectResponse
    from .google_reviews import exchange_code, list_accounts, GoogleReviewsClient, GoogleReviewsError
    from .service import encrypt_token
    from ...config import settings as cfg

    base = cfg.FRONTEND_URL.rstrip("/") + "/dashboard/channels"

    if error:
        return RedirectResponse(f"{base}?google_error={_safe_google_error(error)}")
    if not code or not state:
        return RedirectResponse(f"{base}?google_error=missing_code")

    user_id, next_path = _verify_google_oauth_state(state)
    if not user_id:
        return RedirectResponse(f"{base}?google_error=invalid_state")
    if next_path:
        base = cfg.FRONTEND_URL.rstrip("/") + next_path

    try:
        tokens = await exchange_code(code, cfg.GOOGLE_REVIEWS_REDIRECT_URI)
    except GoogleReviewsError as e:
        logger.error("Google OAuth exchange failed: %s", e)
        return RedirectResponse(f"{base}?google_error=token_exchange_failed")

    access_token = tokens.get("access_token", "")
    refresh_token = tokens.get("refresh_token")

    try:
        accounts = await list_accounts(access_token)
    except GoogleReviewsError as e:
        logger.error("Google accounts fetch failed: %s", e)
        # Don't lie to the user: surface the real cause (quota, auth, etc.)
        # instead of the misleading "no_business_account" error.
        return RedirectResponse(f"{base}?google_error=accounts_unavailable&detail={e.status_code}")

    if not accounts:
        return RedirectResponse(f"{base}?google_error=no_business_account")

    created = 0
    for account in accounts:
        account_id = account.get("name", "accounts/").split("/")[-1]
        account_name = account.get("accountName") or account.get("name", "")

        client = GoogleReviewsClient(access_token, refresh_token)
        try:
            locations = await client.list_locations(account_id)
        except GoogleReviewsError as e:
            logger.warning("No locations for account %s: %s", account_id, e)
            continue
        finally:
            await client.close()

        if not locations:
            continue

        for loc in locations:
            # locations/{account}/locations/{id}
            location_id = loc.get("name", "locations/").split("/")[-1]
            title = loc.get("title") or location_id

            # Google access tokens typically expire in 3600s. Default if missing
            # so we still know to refresh proactively.
            from datetime import datetime, timedelta, timezone
            expires_in = int(tokens.get("expires_in") or 3600)
            token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

            # Get-or-create on the indexed listing key: rapid callbacks
            # (double consent, retries, racing workers) can never twin a row.
            # The unique index admits one winner; the loser reuses that row.
            # The insert runs in a SAVEPOINT so losing the race never
            # disturbs the loop's surrounding transaction.
            from sqlalchemy.exc import IntegrityError as _IntegrityError

            from .service import find_channel_by_key as _find_by_key

            import json as _json

            key = location_id
            matching = await _find_by_key(db, user_id, "google_reviews", key)
            if matching is None:
                # Legacy rows predate listing_key: fall back to a metadata
                # scan once, and heal the row so next time hits the index.
                legacy = await db.execute(
                    select(Channel).where(
                        Channel.user_id == user_id,
                        Channel.platform == "google_reviews",
                        Channel.status == "active",
                    )
                )
                for c in legacy.scalars().all():
                    if _channel_meta_meta(c).get("location_id") == location_id:
                        matching = c
                        if c.listing_key is None:
                            c.listing_key = key
                        break
            if matching is not None:
                # Re-consent heals tokens: a fresh refresh_token repairs
                # channels that can't publish ("No refresh token available").
                # Never overwrite a stored refresh token with nothing —
                # Google only sends one on fresh consent.
                if refresh_token:
                    matching.access_token = encrypt_token(access_token)
                    matching.refresh_token = encrypt_token(refresh_token)
                    matching.token_expires_at = token_expires_at
                continue

            channel = Channel(
                id=str(_uuid.uuid4()),
                user_id=user_id,
                platform="google_reviews",
                platform_user_id=account_id,
                display_name=title,
                access_token=encrypt_token(access_token),
                refresh_token=encrypt_token(refresh_token) if refresh_token else None,
                token_expires_at=token_expires_at,
                status="active",
                metadata_json=_json.dumps({"location_id": location_id, "account_name": account_name}),
                listing_key=key,
            )
            db.add(channel)
            try:
                async with db.begin_nested():
                    await db.flush()
            except _IntegrityError:
                # Lost the race to a parallel callback: discard our copy
                # and reuse the winner's row (healing tokens as usual).
                db.expunge(channel)
                matching = await _find_by_key(db, user_id, "google_reviews", key)
                if matching is not None and refresh_token:
                    matching.access_token = encrypt_token(access_token)
                    matching.refresh_token = encrypt_token(refresh_token)
                    matching.token_expires_at = token_expires_at
                continue
            created += 1

    await db.commit()
    logger.info("Google Reviews connect: created %d channels for user %s", created, user_id)
    return RedirectResponse(f"{base}?google_connected={created}")


def _channel_meta_meta(channel: Channel) -> dict:
    import json as _json
    try:
        return _json.loads(channel.metadata_json or "{}")
    except (ValueError, TypeError):
        return {}


# ── Auto-Reply config (Phase 1: Google Reviews) ─────────


async def _get_owned_channel(channel_id: str, user: User, db: AsyncSession) -> Channel:
    channel = await get_channel(channel_id, user, db)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return channel


@router.get("/{channel_id}/autoreply", response_model=AutoReplyConfigResponse)
async def get_autoreply_config(
    channel_id: str,
    ctx: TenantContext = Depends(require_perm("channels.view")),
    db: AsyncSession = Depends(get_db),
):
    if ctx.channel_level(channel_id) == "none":
        raise HTTPException(status_code=404, detail="Channel not found")
    channel = await _get_owned_channel(channel_id, ctx.user, db)
    result = await db.execute(
        select(AutoReplyConfig).where(AutoReplyConfig.channel_id == channel_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        # Messaging channels answer by default — that is what the number is
        # for, and simply opening this screen must not silently switch the AI
        # off. Review channels keep the historical opt-in default.
        enabled = channel.platform in ("whatsapp", "instagram")
        config = AutoReplyConfig(channel_id=channel_id, enabled=enabled)
        db.add(config)
        await db.commit()
        await db.refresh(config)
    return _config_response(config)


def _config_response(config: AutoReplyConfig) -> AutoReplyConfigResponse:
    return AutoReplyConfigResponse(
        channel_id=config.channel_id,
        enabled=config.enabled,
        tone=config.tone,
        databank_id=config.databank_id,
        databank_grounding=bool(getattr(config, "databank_grounding", True)),
        min_rating_auto=config.min_rating_auto,
        model=config.model,
        approval_mode=config.approval_mode,
        edited_review_autopost=bool(config.edited_review_autopost),
        custom_instructions=config.custom_instructions,
        dialect=config.dialect or "auto",
        reply_language=config.reply_language or "match",
        promo_product_mentions=bool(config.promo_product_mentions),
        promo_links=bool(config.promo_links),
        promo_only_relevant=config.promo_only_relevant
        if config.promo_only_relevant is not None else True,
        promo_max_ctas=config.promo_max_ctas
        if config.promo_max_ctas is not None else 1,
        handoff_link_enabled=bool(getattr(config, "handoff_link_enabled", True)),
        handoff_code_ttl_days=max(
            1, min(30, int(getattr(config, "handoff_code_ttl_days", 1) or 1))
        ),
    )


@router.put("/{channel_id}/autoreply", response_model=AutoReplyConfigResponse)
async def update_autoreply_config(
    channel_id: str,
    body: AutoReplyConfigUpdate,
    ctx: TenantContext = Depends(require_perm("channels.edit")),
    db: AsyncSession = Depends(get_db),
):
    if not ctx.can_edit_channel(channel_id):
        raise HTTPException(status_code=403, detail="No edit access to this channel")
    channel = await _get_owned_channel(channel_id, ctx.user, db)

    # If a databank is being linked, verify it belongs to this workspace
    if body.databank_id:
        from ..rag.models import Databank
        from ..team.context import tenant_id_of

        owned = await db.execute(
            select(Databank.id).where(
                Databank.id == body.databank_id, Databank.user_id == tenant_id_of(ctx.user)
            )
        )
        if not owned.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Databank not found")

    result = await db.execute(
        select(AutoReplyConfig).where(AutoReplyConfig.channel_id == channel.id)
    )
    config = result.scalar_one_or_none()
    if not config:
        config = AutoReplyConfig(channel_id=channel.id)
        db.add(config)

    if body.enabled is not None:
        config.enabled = body.enabled
    if body.tone is not None:
        from ..review_engine.tones import is_valid_tone_db

        if not await is_valid_tone_db(body.tone, db):
            raise HTTPException(
                status_code=422,
                detail=f"Unknown tone '{body.tone}'. See GET /api/v1/review-engine/tones.",
            )
        config.tone = body.tone[:50]
    if body.databank_id is not None:
        config.databank_id = body.databank_id or None
    if body.databank_grounding is not None:
        config.databank_grounding = body.databank_grounding
    if body.min_rating_auto is not None:
        config.min_rating_auto = body.min_rating_auto
    if body.model is not None:
        from ..llm.providers.registry import list_tenant_models

        # Empty string resets to tenant default (NULL) — the model then
        # resolves from the admin-managed enabled list at generation time.
        if not body.model.strip():
            config.model = None
        else:
            # Only models the admin saved + enabled (with a usable provider
            # key) may be assigned — the same set tenants see in the picker.
            visible = {m.id for m, _ in await list_tenant_models(db)}
            if body.model not in visible:
                raise HTTPException(
                    status_code=422,
                    detail=f"Model {body.model} is not enabled by your administrator.",
                )
            config.model = body.model[:100]
    if body.approval_mode is not None:
        config.approval_mode = body.approval_mode
    if body.edited_review_autopost is not None:
        config.edited_review_autopost = body.edited_review_autopost
    if body.custom_instructions is not None:
        config.custom_instructions = body.custom_instructions.strip()[:2000] or None
    if body.dialect is not None:
        from ..review_engine.dialects import is_valid_dialect_db

        if not await is_valid_dialect_db(body.dialect, db):
            raise HTTPException(
                status_code=422,
                detail=f"Unknown dialect '{body.dialect}'. See GET /api/v1/review-engine/dialects.",
            )
        config.dialect = body.dialect
    if body.reply_language is not None:
        config.reply_language = body.reply_language
    if body.promo_product_mentions is not None:
        config.promo_product_mentions = body.promo_product_mentions
    if body.promo_links is not None:
        config.promo_links = body.promo_links
    if body.promo_only_relevant is not None:
        config.promo_only_relevant = body.promo_only_relevant
    if body.promo_max_ctas is not None:
        config.promo_max_ctas = body.promo_max_ctas
    if body.handoff_link_enabled is not None:
        config.handoff_link_enabled = body.handoff_link_enabled
    if body.handoff_code_ttl_days is not None:
        config.handoff_code_ttl_days = body.handoff_code_ttl_days

    await db.commit()
    await db.refresh(config)
    return _config_response(config)


# ── Review replies ──────────────────────────────────────


@router.get("/{channel_id}/reviews", response_model=ReviewReplyListResponse)
async def list_review_replies(
    channel_id: str,
    status_filter: str | None = Query(None, alias="status", pattern="^(posted|pending_approval|failed|approved)$"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    ctx: TenantContext = Depends(require_perm("reviews.view")),
    db: AsyncSession = Depends(get_db),
):
    if ctx.channel_level(channel_id) == "none":
        raise HTTPException(status_code=404, detail="Channel not found")
    await _get_owned_channel(channel_id, ctx.user, db)

    from ..analytics.models import ReviewInsight

    # Reviews the merchant flagged as deleted/removed on Google —
    # never surface them in the approval queue or anywhere else.
    skipped_result = await db.execute(
        select(ReviewInsight.review_id).where(
            ReviewInsight.channel_id == channel_id,
            ReviewInsight.skipped == True,  # noqa: E712
        )
    )
    skipped_ids = {r[0] for r in skipped_result.scalars().all()}

    query = select(ReviewReply).where(ReviewReply.channel_id == channel_id)
    if skipped_ids:
        query = query.where(~ReviewReply.review_id.in_(skipped_ids))
    if status_filter:
        query = query.where(ReviewReply.status == status_filter)
    result = await db.execute(query.order_by(ReviewReply.created_at.desc()).limit(limit).offset(offset))
    rows = result.scalars().all()

    pending_result = await db.execute(
        select(ReviewReply.id)
        .where(ReviewReply.channel_id == channel_id, ReviewReply.status == "pending_approval")
        .where(~ReviewReply.review_id.in_(skipped_ids))
        .limit(1000)
    )
    pending = len(pending_result.scalars().all())

    # Live Google review links (synced into analytics insights) so the
    # merchant can eyeball each review — and its reply — on Google.
    review_urls: dict[str, str] = {}
    review_ids = [r.review_id for r in rows]
    if review_ids:
        from ..analytics.models import ReviewInsight

        url_rows = await db.execute(
            select(ReviewInsight.review_id, ReviewInsight.review_url).where(
                ReviewInsight.channel_id == channel_id,
                ReviewInsight.review_id.in_(review_ids),
                ReviewInsight.review_url.is_not(None),
            )
        )
        review_urls = {rid: url for rid, url in url_rows.all()}

    return ReviewReplyListResponse(
        replies=[
            ReviewReplyResponse(
                id=r.id,
                channel_id=r.channel_id,
                review_id=r.review_id,
                rating=r.rating,
                review_text=r.review_text,
                reviewer_name=r.reviewer_name,
                reply_text=r.reply_text,
                status=r.status,
                generation_attempt=r.generation_attempt,
                error=r.error,
                created_at=r.created_at.isoformat(),
                review_url=review_urls.get(r.review_id),
            )
            for r in rows
        ],
        pending=pending,
    )


@router.post("/{channel_id}/reviews/verify-posted", response_model=dict)
async def verify_posted_replies(
    channel_id: str,
    ctx: TenantContext = Depends(require_perm("reviews.view")),
    db: AsyncSession = Depends(get_db),
):
    """Re-check every `posted` reply against live Google data.

    Rows with no reply actually showing are flipped to `failed` with a
    clear reason. "Posted" must mean live — this is the enforcement.
    Read failures (auth/network) abort without touching anything: we
    only correct on definitive absence, never on our own errors.
    """
    from .google_reviews import GoogleReviewsClient, GoogleReviewsError
    from .service import decrypt_token

    if ctx.channel_level(channel_id) == "none":
        raise HTTPException(status_code=404, detail="Channel not found")
    channel = await _get_owned_channel(channel_id, ctx.user, db)
    all_posted = (
        await db.execute(
            select(ReviewReply)
            .where(
                ReviewReply.channel_id == channel.id,
                ReviewReply.status == "posted",
            )
            .order_by(ReviewReply.created_at.desc())
            .limit(500)
        )
    ).scalars().all()

    # Localith rows were confirmed at approve time by the Localith API —
    # they can't (and must not) be re-verified against Google directly.
    rows = [r for r in all_posted if not r.review_id.startswith("localith:")]
    skipped_localith = len(all_posted) - len(rows)
    if not rows:
        return {
            "channel_id": channel.id,
            "checked": 0,
            "confirmed": 0,
            "corrected": 0,
            "skipped_localith": skipped_localith,
        }

    access_token = decrypt_token(channel.access_token) if channel.access_token else None
    refresh_token = decrypt_token(channel.refresh_token) if channel.refresh_token else None
    if not access_token and not refresh_token:
        raise HTTPException(
            status_code=401,
            detail="Google account not connected. Reconnect Google on the Connect page, then verify again.",
        )
    client = GoogleReviewsClient(access_token or "", refresh_token)
    confirmed = 0
    corrected = 0
    try:
        for reply in rows:
            try:
                live = await client.confirm_reply_live(reply.review_id, attempts=1)
            except GoogleReviewsError as e:
                raise HTTPException(
                    status_code=e.status_code,
                    detail=f"Could not read Google to verify: {e}",
                )
            if live:
                confirmed += 1
            else:
                reply.status = "failed"
                reply.error = (
                    "Not found on Google when verified. "
                    "Reconnect Google if needed, remake the draft, approve again."
                )
                corrected += 1
    finally:
        await client.close()
    await db.commit()
    return {
        "channel_id": channel.id,
        "checked": len(rows),
        "confirmed": confirmed,
        "corrected": corrected,
        "skipped_localith": skipped_localith,
    }


async def _notify_reply_posted(db, user_id: str, channel, reply) -> None:
    """User-facing receipt for a published reply (never raises)."""
    from ..notifications.service import notify

    await notify(
        db, user_id, "reply_posted",
        f"Published reply to ★{reply.rating} review from {reply.reviewer_name or 'a customer'}",
        (reply.reply_text or "")[:160],
        data={"review_id": reply.review_id, "channel_id": channel.id,
              "location": getattr(channel, "display_name", None)},
        href="/dashboard/reviews",
    )


async def _notify_reply_failed(db, user_id: str, channel, reply, reason: str) -> None:
    """User-facing receipt for a failed publish (never raises)."""
    from ..notifications.service import notify

    await notify(
        db, user_id, "reply_failed",
        f"Reply failed for ★{reply.rating} review",
        (reason or "")[:160],
        data={"review_id": reply.review_id, "channel_id": channel.id,
              "location": getattr(channel, "display_name", None)},
        href="/dashboard/outbox",
    )


async def _clear_edited_flag(db, channel_id: str, review_id: str) -> None:
    """Posting an updated reply answers the edit: clear the flag so the
    'edited' card stops lingering (the dismiss endpoint promises this).
    Snapshots are kept as history of what was answered. Never raises."""
    try:
        from ..analytics.models import ReviewInsight

        ins = (
            await db.execute(
                select(ReviewInsight).where(
                    ReviewInsight.channel_id == channel_id,
                    ReviewInsight.review_id == review_id,
                )
            )
        ).scalar_one_or_none()
        if ins is not None and ins.edited:
            ins.edited = False
            ins.edited_at = None
            db.add(ins)
    except Exception:
        pass


@router.post("/{channel_id}/reviews/{reply_id}/approve", response_model=ReviewReplyResponse)
async def approve_review_reply(
    channel_id: str,
    reply_id: str,
    ctx: TenantContext = Depends(require_perm("reviews.publish")),
    db: AsyncSession = Depends(get_db),
):
    """Approve a pending (low-rating) reply and post it to Google."""
    if not ctx.can_edit_channel(channel_id):
        raise HTTPException(status_code=403, detail="No edit access to this channel")
    channel = await _get_owned_channel(channel_id, ctx.user, db)
    result = await db.execute(
        select(ReviewReply).where(
            ReviewReply.id == reply_id, ReviewReply.channel_id == channel.id
        )
    )
    reply = result.scalar_one_or_none()
    if not reply:
        raise HTTPException(status_code=404, detail="Reply not found")
    if reply.status != "pending_approval":
        raise HTTPException(status_code=400, detail=f"Reply is not pending approval (status={reply.status})")

    from .google_reviews import GoogleReviewsClient, GoogleReviewsError
    from .service import decrypt_token

    if settings.GOOGLE_REVIEWS_MOCK:
        # Dev mode has no real GBP location: publishing is impossible, so
        # refuse instead of fabricating a "posted" row nobody can verify.
        raise HTTPException(
            status_code=503,
            detail="Mock mode: connect a real Google Business Profile to publish replies.",
        )

    if reply.review_id.startswith("localith:"):
        # Localith-sourced review: publish through Localith's
        # POST /items/{id}/replies — as a GBP partner they post it live
        # on the connected listing, no per-tenant Google OAuth needed.
        from ..localith.service import post_reply as localith_post_reply

        item_id = reply.review_id.split(":", 1)[1]
        try:
            await localith_post_reply(item_id, reply.reply_text)
        except Exception as e:
            logger.warning("Localith reply publish failed review=%s item=%s: %s", reply.review_id, item_id, e)
            reply.status = "failed"
            reply.error = str(e)[:2000]
            await db.commit()
            await _notify_reply_failed(db, ctx.user.id, channel, reply, str(e))
            raise HTTPException(
                status_code=502,
                detail=f"Failed to post reply via Localith: {e}",
            )
        reply.status = "posted"
        reply.error = None
        await db.commit()
        await _clear_edited_flag(db, channel.id, reply.review_id)
        await db.commit()
        await _notify_reply_posted(db, ctx.user.id, channel, reply)
    else:
        access_token = decrypt_token(channel.access_token) if channel.access_token else None
        refresh_token = decrypt_token(channel.refresh_token) if channel.refresh_token else None
        if not access_token and not refresh_token:
            # No Google tokens: nothing can reach Google. Leave the draft
            # pending and tell the merchant the only fix is re-consent.
            raise HTTPException(
                status_code=401,
                detail="Google account not connected. Reconnect Google on the Connect page, then approve again.",
            )
        client = GoogleReviewsClient(access_token or "", refresh_token)
        try:
            if not access_token:
                await client.refresh_access_token()
            await client.reply_to_review(reply.review_id, reply.reply_text)
            # "posted" must mean live on Google: confirm by reading the
            # review back before stamping the status.
            if not await client.confirm_reply_live(reply.review_id):
                reply.status = "failed"
                reply.error = (
                    "Google accepted the reply but it is not showing on the "
                    "listing. Approve again to retry."
                )
                await db.commit()
                await _notify_reply_failed(db, ctx.user.id, channel, reply, reply.error)
                raise HTTPException(status_code=502, detail=reply.error)
            reply.status = "posted"
            reply.error = None
            await db.commit()
            await _clear_edited_flag(db, channel.id, reply.review_id)
            await db.commit()
            await _notify_reply_posted(db, ctx.user.id, channel, reply)
        except GoogleReviewsError as e:
            reply.status = "failed"
            reply.error = str(e)[:2000]
            await db.commit()
            await _notify_reply_failed(db, ctx.user.id, channel, reply, str(e))
            # Surface the real reason (e.g. "No refresh token available") —
            # a generic message hides that re-consent is the only fix.
            raise HTTPException(
                status_code=e.status_code, detail=f"Failed to post reply to Google: {e}"
            )
        finally:
            await client.close()

    # Collapse duplicate drafts for the same review: approving one
    # withdraws its siblings (pending or failed) so the same review can
    # never be posted twice (the poll worker used to queue one draft
    # per pass).
    sibling_result = await db.execute(
        select(ReviewReply).where(
            ReviewReply.channel_id == channel.id,
            ReviewReply.review_id == reply.review_id,
            ReviewReply.status.in_(["pending_approval", "failed"]),
            ReviewReply.id != reply.id,
        )
    )
    for sibling in sibling_result.scalars().all():
        sibling.status = "rejected"
        sibling.error = None
    # Keep analytics response-rate/response-time accurate
    try:
        from ..outbox.service import enqueue_event_in

        await enqueue_event_in(
            db,
            "review.replied",
            {
                "user_id": ctx.user.id,
                "channel_id": channel.id,
                "review_id": reply.review_id,
                "status": "posted",
                "replied_at": datetime.now(timezone.utc).isoformat(),
            },
            topic="review-events",
        )
        await db.commit()
    except Exception:
        logger.warning("review.replied enqueue failed for %s", reply.review_id)

    await db.refresh(reply)
    return ReviewReplyResponse(
        id=reply.id,
        channel_id=reply.channel_id,
        review_id=reply.review_id,
        rating=reply.rating,
        review_text=reply.review_text,
        reviewer_name=reply.reviewer_name,
        reply_text=reply.reply_text,
        status=reply.status,
        generation_attempt=reply.generation_attempt,
        error=reply.error,
        created_at=reply.created_at.isoformat(),
    )


@router.post("/{channel_id}/reviews/generate", response_model=ReviewReplyResponse, status_code=status.HTTP_201_CREATED)
async def generate_reply_for_review(
    channel_id: str,
    body: ReviewReplyGenerate,
    ctx: TenantContext = Depends(require_perm("reviews.reply")),
    db: AsyncSession = Depends(get_db),
):
    """Draft an AI reply for a review that has no reply row yet (inbox flow)."""
    if not settings.TESTING and not await rate_limit(f"gen:{channel_id}", 100, 60):
        raise HTTPException(status_code=429, detail="Too many requests")
    if not ctx.can_edit_channel(channel_id):
        raise HTTPException(status_code=403, detail="No edit access to this channel")
    channel = await _get_owned_channel(channel_id, ctx.user, db)
    config = (
        await db.execute(select(AutoReplyConfig).where(AutoReplyConfig.channel_id == channel.id))
    ).scalar_one_or_none()
    if not config:
        config = AutoReplyConfig(channel_id=channel.id)
        db.add(config)

    existing = await db.execute(
        select(ReviewReply).where(
            ReviewReply.channel_id == channel.id,
            ReviewReply.review_id == body.review_id,
        ).limit(1)
    )
    existing_reply = existing.scalar_one_or_none()
    if existing_reply is not None and existing_reply.status == "pending_approval":
        # Idempotent: the queued draft IS the response — hand it back so
        # callers (e.g. the dashboard's edit-follow-up cards) can never
        # create duplicate drafts for the same review.
        return _reply_response(existing_reply)
    if existing_reply is not None and existing_reply.status == "posted":
        # A reply is already live on Google. A new draft is only legitimate
        # as an edit follow-up — the reviewer changed the review after we
        # answered it.
        from ..analytics.models import ReviewInsight

        insight = (
            await db.execute(
                select(ReviewInsight).where(
                    ReviewInsight.channel_id == channel.id,
                    ReviewInsight.review_id == body.review_id,
                )
            )
        ).scalar_one_or_none()
        if not (insight is not None and insight.edited):
            raise HTTPException(status_code=409, detail="A reply already exists for this review")
    if existing_reply is not None:
        # Dead draft (rejected/failed) — clear it so a fresh one can be made.
        await db.delete(existing_reply)
        await db.flush()

    from .review_reply import generate_auto_reply

    custom_text = (body.custom_text or "").strip()
    if custom_text:
        # Merchant typed the reply themselves — skip the LLM entirely.
        reply_text = custom_text
    else:
        try:
            reply_text, _ = await generate_auto_reply(
                config, channel, body.rating, body.review_text,
                body.reviewer_name, db, review_id=body.review_id,
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Reply generation failed: {e}")

    reply = ReviewReply(
        id=str(uuid.uuid4()),
        channel_id=channel.id,
        review_id=body.review_id,
        rating=body.rating,
        review_text=body.review_text,
        reviewer_name=body.reviewer_name,
        reply_text=reply_text,
        status="pending_approval",
        generation_attempt=1,
    )
    db.add(reply)
    await db.commit()
    await db.refresh(reply)
    return _reply_response(reply)

@router.put("/{channel_id}/reviews/{reply_id}", response_model=ReviewReplyResponse)
async def edit_pending_reply(
    channel_id: str,
    reply_id: str,
    body: ReviewReplyEdit,
    ctx: TenantContext = Depends(require_perm("reviews.reply")),
    db: AsyncSession = Depends(get_db),
):
    """Edit any live response to a review.

    Pending drafts are edited in place. Failed drafts are edited and
    re-queued for approval. Posted replies can be corrected too: the edit
    sends them back to pending_approval (generation_attempt+1), so the
    update only goes live after a fresh approval — nothing edits Google
    behind the merchant's back.
    """
    if not ctx.can_edit_channel(channel_id):
        raise HTTPException(status_code=403, detail="No edit access to this channel")
    reply = await _get_owned_reply(channel_id, reply_id, ctx.user, db)
    if reply.status not in ("pending_approval", "failed", "posted"):
        raise HTTPException(
            status_code=400,
            detail="Only pending, failed or posted replies can be edited",
        )
    reply.reply_text = body.reply_text.strip()
    if reply.status == "failed":
        reply.status = "pending_approval"
        reply.error = None
    elif reply.status == "posted":
        reply.status = "pending_approval"
        reply.generation_attempt = (reply.generation_attempt or 1) + 1
    await db.commit()
    await db.refresh(reply)
    return _reply_response(reply)


@router.post("/{channel_id}/reviews/{reply_id}/regenerate", response_model=ReviewReplyResponse)
async def regenerate_reply(
    channel_id: str,
    reply_id: str,
    ctx: TenantContext = Depends(require_perm("reviews.reply")),
    db: AsyncSession = Depends(get_db),
):
    """Re-generate a pending reply through the review engine.

    Single production path (the legacy `?engine=` flag is accepted but
    ignored — every regeneration runs the full pipeline). The rejected
    draft is passed along so the engine writes a fresh variation.
    """
    if not settings.TESTING and not await rate_limit(f"regen:{channel_id}", 100, 60):
        raise HTTPException(status_code=429, detail="Too many requests")
    if not ctx.can_edit_channel(channel_id):
        raise HTTPException(status_code=403, detail="No edit access to this channel")
    reply = await _get_owned_reply(channel_id, reply_id, ctx.user, db)
    if reply.status != "pending_approval":
        raise HTTPException(status_code=400, detail="Only pending replies can be regenerated")
    attempt = (reply.generation_attempt or 1) + 1

    config = (
        await db.execute(select(AutoReplyConfig).where(AutoReplyConfig.channel_id == channel_id))
    ).scalar_one_or_none()
    if not config:
        config = AutoReplyConfig(channel_id=channel_id)
        db.add(config)

    from types import SimpleNamespace

    from .review_reply import generate_auto_reply

    # The model knows this is a rejected draft so it writes a fresh variation.
    try:
        reply.reply_text, _ = await generate_auto_reply(
            config, SimpleNamespace(id=channel_id, user_id=ctx.user.id),
            reply.rating, reply.review_text, reply.reviewer_name, db,
            review_id=(reply.review_id or "")[:120] or None,
            attempt=attempt, previous_draft=reply.reply_text,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Reply generation failed: {e}")

    refreshed = await db.get(ReviewReply, reply_id)
    refreshed.reply_text = reply.reply_text
    refreshed.generation_attempt = attempt
    await db.commit()
    await db.refresh(refreshed)
    return _reply_response(refreshed)


@router.post("/{channel_id}/reviews/{reply_id}/retry", response_model=ReviewReplyResponse)
async def retry_failed_reply(
    channel_id: str,
    reply_id: str,
    ctx: TenantContext = Depends(require_perm("reviews.reply")),
    db: AsyncSession = Depends(get_db),
):
    """Retry a failed reply: regenerate the text if generation failed, then
    return it to the approval queue with the error cleared."""
    if not ctx.can_edit_channel(channel_id):
        raise HTTPException(status_code=403, detail="No edit access to this channel")
    reply = await _get_owned_reply(channel_id, reply_id, ctx.user, db)
    if reply.status != "failed":
        raise HTTPException(status_code=400, detail="Only failed replies can be retried")
    # Generation attempt: only counts real generations. A retry with text
    # already in hand just re-queues; an empty failed row regenerates (+1).
    attempt = reply.generation_attempt or 1
    if not (reply.reply_text or "").strip():
        config = (
            await db.execute(
                select(AutoReplyConfig).where(AutoReplyConfig.channel_id == channel_id)
            )
        ).scalar_one_or_none()
        if not config:
            config = AutoReplyConfig(channel_id=channel_id)
            db.add(config)
        from types import SimpleNamespace

        from .review_reply import generate_auto_reply

        attempt += 1
        try:
            reply.reply_text, _ = await generate_auto_reply(
                config, SimpleNamespace(id=channel_id, user_id=ctx.user.id),
                reply.rating, reply.review_text, reply.reviewer_name, db,
                review_id=(reply.review_id or "")[:120] or None,
                attempt=attempt,
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Reply generation failed: {e}")

    refreshed = await db.get(ReviewReply, reply_id)
    refreshed.status = "pending_approval"
    refreshed.error = None
    refreshed.generation_attempt = attempt
    if reply.reply_text:
        refreshed.reply_text = reply.reply_text
    await db.commit()
    await db.refresh(refreshed)
    return _reply_response(refreshed)


@router.delete("/{channel_id}/reviews/{reply_id}", response_model=ReviewReplyResponse)
async def reject_reply(
    channel_id: str,
    reply_id: str,
    ctx: TenantContext = Depends(require_perm("reviews.reply")),
    db: AsyncSession = Depends(get_db),
):
    """Discard a reply draft without posting anything to Google.

    Failed drafts can be discarded too — e.g. when the review was
    deleted on Google and no retry can ever succeed.
    """
    if not ctx.can_edit_channel(channel_id):
        raise HTTPException(status_code=403, detail="No edit access to this channel")
    reply = await _get_owned_reply(channel_id, reply_id, ctx.user, db)
    if reply.status not in ("pending_approval", "failed"):
        raise HTTPException(status_code=400, detail="Only pending or failed replies can be rejected")
    reply.status = "rejected"
    reply.error = None
    # Dismissal sticks: auto-pipelines must not draft again for this review
    # until the reviewer edits it or the merchant regenerates manually.
    try:
        from ..analytics.models import ReviewInsight

        insight = (
            await db.execute(
                select(ReviewInsight).where(
                    ReviewInsight.channel_id == reply.channel_id,
                    ReviewInsight.review_id == reply.review_id,
                )
            )
        ).scalar_one_or_none()
        if insight is not None and not insight.draft_dismissed:
            insight.draft_dismissed = True
            db.add(insight)
    except Exception as e:
        logger.debug("Draft-dismissal marker not set for %s: %s", reply_id, e)
    await db.commit()
    await db.refresh(reply)
    return _reply_response(reply)


def _reply_response(reply: ReviewReply) -> ReviewReplyResponse:
    return ReviewReplyResponse(
        id=reply.id,
        channel_id=reply.channel_id,
        review_id=reply.review_id,
        rating=reply.rating,
        review_text=reply.review_text,
        reviewer_name=reply.reviewer_name,
        reply_text=reply.reply_text,
        status=reply.status,
        generation_attempt=getattr(reply, "generation_attempt", 1) or 1,
        error=reply.error,
        created_at=reply.created_at.isoformat(),
    )


async def _get_owned_reply(
    channel_id: str, reply_id: str, user: User, db: AsyncSession
) -> ReviewReply:
    channel = await _get_owned_channel(channel_id, user, db)
    result = await db.execute(
        select(ReviewReply).where(ReviewReply.id == reply_id, ReviewReply.channel_id == channel.id)
    )
    reply = result.scalar_one_or_none()
    if not reply:
        raise HTTPException(status_code=404, detail="Reply not found")
    return reply


class TestReviewPipelineInput(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    review_text: str = Field(..., min_length=1, max_length=5000)
    reviewer_name: str | None = Field(None, max_length=255)


class TestReviewPipelineResult(BaseModel):
    review_id: str
    issue_id: str | None = None
    issue_created: bool = False
    skipped_reason: str | None = None
    classification_error: str | None = None
    ticket_number: str | None = None
    handoff_code: str | None = None
    handoff_eligible: bool = False
    handoff_link: str | None = None
    sales_link: str | None = None
    reply_preview: str | None = None
    reply_error: str | None = None
    published: bool = False
    status: str | None = None
    primary_category: str | None = None
    subcategory: str | None = None
    subcategory_detail: str | None = None
    intent: str | None = None
    sentiment: str | None = None
    priority: str | None = None
    needs_attention: bool | None = None
    summary: str | None = None
    reviewer_name: str | None = None
    review_text: str | None = None


@router.post("/{channel_id}/test-review", response_model=TestReviewPipelineResult)
async def test_review_pipeline(
    channel_id: str,
    body: TestReviewPipelineInput,
    ctx: TenantContext = Depends(require_perm("channels.edit")),
    db: AsyncSession = Depends(get_db),
):
    """Run a review through the local review/ticket/handoff pipeline.

    This is a development/testing helper. It never calls Google Business
    Profile, never posts a reply, and never sends a WhatsApp message. It
    generates the same public reply preview the live worker would publish so
    the reviewer-facing WhatsApp handoff link can be inspected before any
    external side effect.
    """
    channel = await db.get(Channel, channel_id)
    if channel is None or channel.user_id != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="Channel not found.")
    if not ctx.can_edit_channel(channel_id):
        raise HTTPException(status_code=403, detail="No edit access to this channel.")
    if channel.platform != "google_reviews":
        raise HTTPException(
            status_code=422, detail="Test reviews require a Google reviews channel."
        )

    review_id = f"test-review-{uuid.uuid4().hex}"

    config = None
    model: str | None = None
    try:
        from ..review_engine.schemas import ReviewEngineRequest
        from ..review_engine.service import _resolve_engine_model

        config = (
            await db.execute(
                select(AutoReplyConfig).where(
                    AutoReplyConfig.channel_id == channel_id
                )
            )
        ).scalars().first()
        configured_model = getattr(config, "model", None)
        req = ReviewEngineRequest(
            rating=body.rating, channel_id=channel_id, model=configured_model
        )
        model, _ = await _resolve_engine_model(req, ctx.tenant_id, db)
    except Exception:
        model = None

    subcats: list[str] = []
    try:
        account = (
            await db.execute(
                select(User.lead_settings).where(User.id == ctx.tenant_id)
            )
        ).scalar_one_or_none()
        from ..channels.meta.lead_engine import normalize_lead_settings

        subcats = normalize_lead_settings(account).get(
            "review_issue_subcategories"
        ) or []
    except Exception:
        subcats = []

    try:
        from ..review_engine.graph import run_review_pipeline

        outcome = await run_review_pipeline(
            db,
            tenant_id=ctx.tenant_id,
            channel_id=channel_id,
            review_id=review_id,
            rating=body.rating,
            review_text=body.review_text,
            reviewer_name=body.reviewer_name,
            model=model,
            tenant_subcategories=subcats,
        )
    except Exception as e:
        outcome = {
            "skipped_reason": f"pipeline failed: {type(e).__name__}: {str(e)[:200]}"
        }

    issue = (
        await db.execute(
            select(ReviewIssue).where(
                ReviewIssue.tenant_id == ctx.tenant_id,
                ReviewIssue.channel_id == channel_id,
                ReviewIssue.review_id == review_id,
            )
        )
    ).scalar_one_or_none()

    # Same generation path as the live worker, but the returned text is a
    # preview only: no ReviewReply row, no Google API call, no WhatsApp send.
    reply_preview: str | None = None
    reply_error: str | None = None
    try:
        from .review_reply import generate_auto_reply

        reply_preview, _ = await generate_auto_reply(
            config,
            channel,
            body.rating,
            body.review_text,
            body.reviewer_name,
            db,
            review_id=review_id,
        )
    except Exception as e:
        reply_error = f"{type(e).__name__}: {str(e)[:300]}"

    handoff_link: str | None = None
    sales_link: str | None = None
    try:
        from ..review_engine.handoff import tenant_whatsapp_number, wa_me_link

        number = await tenant_whatsapp_number(db, tenant_id=ctx.tenant_id)
        if number:
            sales_link = f"https://wa.me/{number}"
            if issue is not None and issue.handoff_code:
                handoff_link = wa_me_link(number, issue.handoff_code) or None
    except Exception:
        handoff_link = None
        sales_link = None

    return TestReviewPipelineResult(
        review_id=review_id,
        issue_id=getattr(issue, "id", None)
        if issue is not None
        else outcome.get("issue_id"),
        issue_created=bool(outcome.get("issue_created")),
        skipped_reason=outcome.get("skipped_reason"),
        classification_error=outcome.get("classification_error"),
        ticket_number=getattr(issue, "ticket_number", None)
        if issue is not None
        else outcome.get("ticket_number"),
        handoff_code=getattr(issue, "handoff_code", None)
        if issue is not None
        else outcome.get("handoff_code"),
        handoff_eligible=bool(outcome.get("handoff_eligible")),
        handoff_link=handoff_link,
        sales_link=sales_link,
        reply_preview=reply_preview,
        reply_error=reply_error,
        published=False,
        status=getattr(issue, "status", None),
        primary_category=getattr(issue, "primary_category", None),
        subcategory=getattr(issue, "subcategory", None),
        subcategory_detail=getattr(issue, "subcategory_detail", None),
        intent=getattr(issue, "intent", None),
        sentiment=getattr(issue, "sentiment", None),
        priority=getattr(issue, "priority", None),
        needs_attention=getattr(issue, "needs_attention", None),
        summary=getattr(issue, "summary", None),
        reviewer_name=getattr(issue, "reviewer_name", body.reviewer_name),
        review_text=getattr(issue, "review_text", body.review_text),
    )

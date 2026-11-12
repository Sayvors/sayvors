import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_db, get_current_user
from ...core.upstream_errors import upstream_http_error
from ..team.context import TenantContext, get_context, require_perm, tenant_id_of
from ...database import async_session as _async_session
from ...config import settings
from ..auth.rate_limit import rate_limit
from ..billing.messaging_quota import ensure_messaging_quota
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
    ConnectImportLatestOut,
    ConnectImportLocationOut,
    ConnectImportItemOut,
    ConnectImportProgressOut,
    ConnectImportPublish,
    ConnectImportSessionOut,
    ConnectImportStart,
    InboxSendRequest,
    InboxLocationSendRequest,
    InboxContactSendRequest,
    InboxReactionRequest,
    InteractiveSend,
    QrCodeCreate,    InboxSendResponse,
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
    VerificationCompleteRequest,
    VerificationRequest,
    VerificationResponse,
)
from .service import (
    UNKNOWN_THREAD_KEY,
    MAX_OUTBOUND_DOCUMENT_BYTES,
    MAX_OUTBOUND_STICKER_BYTES,
    create_channel,
    decrypt_contact_phone,
    decrypt_message_content,
    delete_channel,
    get_channel,
    hash_contact_phone,
    list_channels,
    list_inbox_threads_page,
    list_messages,
    list_thread_messages,
    react_to_message,
    send_message,
    send_interactive_message,
    send_location_message,
    send_contact_message,
    send_document_message,
    send_sticker_message,
    set_contact_blocked,
    soft_delete_message,
    whatsapp_number_health,
    list_whatsapp_qr_codes,
    create_whatsapp_qr_code,
    delete_whatsapp_qr_code,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/channels", tags=["channels"])


def _channel_source_info(channel: Channel) -> tuple[str | None, str | None]:
    """(source, listing_id) for a channel.

    Google OAuth channels are the only source. Parsed from metadata_json so
    the UI can show each branch exactly once.
    """
    import json as _json

    try:
        meta = _json.loads(channel.metadata_json or "{}")
    except (ValueError, TypeError):
        meta = {}
    if not isinstance(meta, dict):
        return None, None
    if channel.platform == "google_reviews":
        loc = meta.get("location_id")
        return "google", str(loc) if loc else None
    return None, None


def _channel_response(channel: Channel) -> ChannelResponse:
    import json as _json

    source, listing_id = _channel_source_info(channel)
    try:
        meta = _json.loads(channel.metadata_json or "{}")
    except (ValueError, TypeError):
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
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
        place_id=(
            str(meta.get("place_id")).strip()
            if meta.get("place_id")
            else None
        ),
        maps_url=(
            str(meta.get("maps_url")).strip()
            if meta.get("maps_url")
            else None
        ),
        phone=(
            str(meta.get("phone")).strip()
            if meta.get("phone")
            else None
        ),
        website=(
            str(meta.get("website")).strip()
            if meta.get("website")
            else None
        ),
        profile_fields_checked=meta.get("profile_fields_checked") is True,
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
    include_disconnected: bool = Query(False),
    ctx: TenantContext = Depends(require_perm("channels.view")),
    db: AsyncSession = Depends(get_db),
):
    channels, total = await list_channels(
        ctx.user, db, limit, offset, include_disconnected=include_disconnected
    )
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


@router.post("/google/disconnect")
async def disconnect_google(
    ctx: TenantContext = Depends(require_perm("channels.remove")),
    db: AsyncSession = Depends(get_db),
):
    """Soft-disconnect every Google channel for the tenant.

    The rows, reviews, metrics, drafts and profile data are kept. Only the
    OAuth tokens and status change, so reconnecting restores the same data
    instead of re-importing it. Best-effort token revocation at Google too.
    """
    import httpx

    from .service import decrypt_token

    uid = tenant_id_of(ctx.user)
    channels = (
        await db.execute(
            select(Channel).where(
                Channel.user_id == uid,
                Channel.platform == "google_reviews",
                Channel.status != "disconnected",
            )
        )
    ).scalars().all()

    for channel in channels:
        token = decrypt_token(channel.refresh_token) if channel.refresh_token else None
        if token:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    await client.post(
                        "https://oauth2.googleapis.com/revoke",
                        params={"token": token},
                    )
            except Exception as e:  # noqa: BLE001
                logger.warning("Google token revoke failed for %s: %s", channel.id, e)
        channel.status = "disconnected"
        channel.access_token = None
        channel.refresh_token = None
        channel.token_expires_at = None
    await db.commit()

    # The assistant's facts must stop including disconnected locations.
    from ..profile.facts_store import rebuild_facts_safe

    await rebuild_facts_safe(db, uid)
    return {"disconnected": len(channels)}


@router.post("/google/sync-now")
async def sync_google_reviews_now(
    ctx: TenantContext = Depends(require_perm("channels.view")),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger a Google Reviews sync pass immediately.

    Normally reviews are polled every minute by the background worker.
    This endpoint runs one polling pass right now over all active
    Google Reviews channels for the tenant, pulling any new or updated
    reviews from Google.

    Returns the poll totals: channels polled, reviews found, replies
    posted/queued, skipped, adopted, and errors.
    """
    from .reviews_worker import poll_once

    totals = await poll_once()
    return {
        "triggered": True,
        "interval_seconds": settings.GOOGLE_REVIEWS_POLL_INTERVAL_SECONDS,
        "totals": totals,
    }


@router.post("/google/pubsub")
async def google_pubsub_push(request: Request, db: AsyncSession = Depends(get_db)):
    """Google Business Profile Pub/Sub push ingress (NEW_REVIEW etc.).

    The realtime layer of the review-pull design: a push triggers a
    targeted pull of that location's channel within seconds instead of
    waiting for the next poll pass. Fail-closed: unconfigured audience
    ⇒ 503, anything that fails OIDC verification ⇒ 403. Always acks 200
    once verified — delivery is best-effort on Google's side and the
    60s poll + daily sweep heal are the correctness guarantee, so a pull
    that fails here must never turn into a Pub/Sub retry storm.
    """
    from ..auth.router import get_client_ip
    from . import google_push

    if not settings.TESTING:
        client_ip = get_client_ip(request)
        if not await rate_limit(
            f"google-push:{client_ip}",
            google_push.PUSH_RATE_MAX,
            google_push.PUSH_RATE_WINDOW_SECONDS,
        ):
            logger.warning("Google push rate limited ip=%s", client_ip)
            return Response(
                status_code=429,
                content="Too many requests",
                headers={"Retry-After": str(google_push.PUSH_RATE_WINDOW_SECONDS)},
            )

    if not google_push.push_configured():
        # Fail-closed: no audience configured means this deployment has no
        # push subscription whose tokens we could trust.
        return Response(status_code=503, content="Google push ingress not configured")

    content_length = request.headers.get("content-length")
    if (
        content_length
        and content_length.isdigit()
        and int(content_length) > google_push.PUSH_MAX_BODY_BYTES
    ):
        return Response(status_code=413, content="Payload too large")
    raw_body = await request.body()
    if len(raw_body) > google_push.PUSH_MAX_BODY_BYTES:
        return Response(status_code=413, content="Payload too large")

    if not google_push.verify_push_oidc(request):
        logger.warning("Google push OIDC rejected")
        return Response(status_code=403, content="Invalid push token")

    message_id, notification = google_push.parse_push_envelope(raw_body)
    if notification is None:
        # Not a shape we can act on. Ack anyway: Pub/Sub would retry the
        # same bytes forever, and the poll layer is the correctness net.
        return {"status": "ignored"}

    location_ids = google_push.extract_location_ids(notification)
    if not location_ids:
        logger.info(
            "Google push %s has no usable location reference — ignoring (%.300s)",
            message_id, notification,
        )
        return {"status": "ignored"}

    spawned = await google_push.trigger_pulls_for_locations(db, location_ids)
    logger.info(
        "Google push %s type=%s locations=%s spawned_pulls=%d",
        message_id,
        notification.get("notificationType"),
        ",".join(location_ids),
        spawned,
    )
    return {"status": "ok", "triggered": spawned}


@router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_channel(
    channel_id: str,
    ctx: TenantContext = Depends(require_perm("channels.remove")),
    db: AsyncSession = Depends(get_db),
):
    if not ctx.can_edit_channel(channel_id):
        raise HTTPException(status_code=404, detail="Channel not found")
    channel = await get_channel(channel_id, ctx.user, db)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    if channel.platform == "google_reviews":
        # Google disconnects are always soft: rows, reviews and metrics are
        # kept so reconnecting restores the same data.
        channel.status = "disconnected"
        channel.access_token = None
        channel.refresh_token = None
        channel.token_expires_at = None
        await db.commit()
        return
    deleted = await delete_channel(channel_id, ctx.user, db)
    if not deleted:
        raise HTTPException(status_code=404, detail="Channel not found")


async def _google_channel(channel_id: str, user: User, db: AsyncSession) -> Channel:
    channel = await get_channel(channel_id, user, db)
    if not channel or channel.platform != "google_reviews":
        raise HTTPException(status_code=404, detail="Google channel not found")
    return channel


def _import_location_status(session_status: str, items: list) -> str:
    if session_status in ("queued", "fetching"):
        return "fetching"
    if session_status == "awaiting_scope":
        return "awaiting_scope"
    if session_status == "completed":
        return "completed"
    if session_status == "publishing":
        return "publishing"
    if any(item.status in ("generating", "pending") for item in items):
        return "generating"
    if any(item.status in ("failed", "publish_failed") for item in items):
        return "attention"
    if items and all(
        item.status in ("draft_ready", "already_replied", "published", "outside_scope")
        for item in items
    ):
        return "ready"
    return session_status


async def _import_session_out(
    db: AsyncSession, session, include_items: bool = True
) -> ConnectImportSessionOut:
    from .connect_import import session_events, session_items

    items = await session_items(db, session.id) if include_items else []
    events = await session_events(db, session.id)
    channel_ids = sorted({item.channel_id for item in items})
    channels = {}
    if channel_ids:
        channels = {
            channel.id: channel
            for channel in (
                await db.execute(
                    select(Channel).where(Channel.id.in_(channel_ids))
                )
            ).scalars().all()
        }
    grouped: dict[str, list] = {}
    for item in items:
        grouped.setdefault(item.channel_id, []).append(item)
    reply_ids = [item.reply_id for item in items if item.reply_id]
    replies = {}
    if reply_ids:
        replies = {
            reply.id: reply
            for reply in (
                await db.execute(
                    select(ReviewReply).where(ReviewReply.id.in_(reply_ids))
                )
            ).scalars().all()
        }
    locations: list[ConnectImportLocationOut] = []
    for channel_id in channel_ids:
        channel = channels.get(channel_id)
        location_items = grouped.get(channel_id, [])
        meta = {}
        if channel is not None:
            try:
                import json as _json

                meta = _json.loads(channel.metadata_json or "{}")
            except (TypeError, ValueError):
                meta = {}
        locations.append(
            ConnectImportLocationOut(
                channel_id=channel_id,
                name=(channel.display_name if channel else None) or "Google location",
                address=str(meta.get("address") or "") or None,
                status=_import_location_status(session.status, location_items),
                items=[
                    ConnectImportItemOut(
                        id=item.id,
                        channel_id=item.channel_id,
                        review_id=item.review_id,
                        location_name=item.location_name,
                        reviewer_name=item.reviewer_name,
                        rating=item.rating,
                        review_text=item.review_text,
                        review_time=(
                            item.review_time.isoformat() if item.review_time else None
                        ),
                        status=item.status,
                        reply_id=item.reply_id,
                        draft_text=(
                            replies[item.reply_id].reply_text
                            if item.reply_id and item.reply_id in replies
                            else None
                        ),
                        selected=bool(item.selected),
                        error=item.error,
                    )
                    for item in location_items
                ],
            )
        )
    return ConnectImportSessionOut(
        id=session.id,
        status=session.status,
        scope_days=session.scope_days,
        progress=ConnectImportProgressOut(
            total_locations=session.total_locations,
            fetched_locations=session.fetched_locations,
            total_reviews=session.total_reviews,
            fetched_reviews=session.fetched_reviews,
            total_drafts=session.total_drafts,
            drafts_ready=session.drafts_ready,
            drafts_failed=session.drafts_failed,
        ),
        locations=locations,
        events=[
            {
                "id": event.id,
                "level": event.level,
                "message": event.message,
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
            for event in events
        ],
        summary=session.summary,
        error=session.error,
        created_at=session.created_at.isoformat() if session.created_at else None,
        updated_at=session.updated_at.isoformat() if session.updated_at else None,
    )


@router.get(
    "/google/import-sessions/latest",
    response_model=ConnectImportLatestOut,
)
async def latest_google_import_session(
    ctx: TenantContext = Depends(require_perm("channels.view")),
    db: AsyncSession = Depends(get_db),
):
    from .connect_import import latest_active_session

    session = await latest_active_session(db, tenant_id_of(ctx.user))
    if session is None:
        return ConnectImportLatestOut(session=None)
    return ConnectImportLatestOut(
        session=await _import_session_out(db, session, include_items=False)
    )


@router.get(
    "/google/import-sessions/{session_id}",
    response_model=ConnectImportSessionOut,
)
async def get_google_import_session(
    session_id: str,
    ctx: TenantContext = Depends(require_perm("channels.view")),
    db: AsyncSession = Depends(get_db),
):
    from .connect_import import get_session

    session = await get_session(db, tenant_id_of(ctx.user), session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Import session not found")
    return await _import_session_out(db, session)


@router.post(
    "/google/import-sessions/{session_id}/start",
    response_model=ConnectImportSessionOut,
)
async def start_google_import_session(
    session_id: str,
    body: ConnectImportStart,
    ctx: TenantContext = Depends(require_perm("channels.edit")),
    db: AsyncSession = Depends(get_db),
):
    from .connect_import import get_session, start_generation

    session = await get_session(db, tenant_id_of(ctx.user), session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Import session not found")
    try:
        session = await start_generation(db, session, int(body.scope_days))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return await _import_session_out(db, session)


@router.post(
    "/google/import-sessions/{session_id}/items/{item_id}/generate",
    response_model=ConnectImportSessionOut,
)
async def generate_google_import_item(
    session_id: str,
    item_id: str,
    ctx: TenantContext = Depends(require_perm("channels.edit")),
    db: AsyncSession = Depends(get_db),
):
    from .connect_import import get_session, request_item_generation

    session = await get_session(db, tenant_id_of(ctx.user), session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Import session not found")
    try:
        session = await request_item_generation(db, session, item_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return await _import_session_out(db, session)


@router.post(
    "/google/import-sessions/{session_id}/publish",
    response_model=ConnectImportSessionOut,
)
async def publish_google_import_session(
    session_id: str,
    body: ConnectImportPublish,
    ctx: TenantContext = Depends(require_perm("channels.edit")),
    db: AsyncSession = Depends(get_db),
):
    from .connect_import import get_session, request_publish

    session = await get_session(db, tenant_id_of(ctx.user), session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Import session not found")
    try:
        session = await request_publish(
            db,
            session,
            item_ids=body.item_ids,
            publish_all=bool(body.all),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return await _import_session_out(db, session)


def _verification_status(
    state: dict, verifications: list[dict]
) -> tuple[str, dict | None, str | None]:
    """Derive a UI status from Google's merchant state and verification list."""
    latest = None
    if verifications:
        latest = max(
            verifications,
            key=lambda item: str(item.get("createTime") or ""),
        )
    if state.get("hasVoiceOfMerchant"):
        return "verified", latest, None
    if state.get("complyWithGuidelines") is not None:
        return "guidelines", latest, None
    if state.get("resolveOwnershipConflict") is not None:
        return "ownership_conflict", latest, None
    if state.get("waitForVoiceOfMerchant") is not None:
        return "under_review", latest, None
    if latest:
        provider_state = str(latest.get("state") or "").upper()
        if provider_state == "COMPLETED":
            return "verified", latest, None
        if provider_state == "PENDING":
            return "pending", latest, None
        if provider_state == "FAILED":
            return "failed", latest, None
    if state.get("verify") is not None:
        return "required", latest, None
    return "unstarted", latest, None


def _verification_contact(latest: dict | None, options: list[dict]) -> tuple[str | None, str | None]:
    """(method, contact target) from the latest request or eligible option."""
    if latest:
        method = latest.get("method")
        if method:
            return str(method), None
    if options:
        first = options[0]
        method = str(first.get("verificationMethod") or "") or None
        target = first.get("phoneNumber")
        if not target:
            email = first.get("emailData") or {}
            user = str(email.get("user") or "")
            domain = str(email.get("domain") or "")
            target = f"{user}@{domain}" if user and domain else None
        return method, str(target) if target else None
    return None, None


async def _verification_snapshot(
    db: AsyncSession,
    channel: Channel,
    client,
    location_id: str,
    language_code: str = "en",
) -> VerificationResponse:
    """Read Google's live verification state and mirror it into our row."""
    from .google_reviews import GoogleReviewsError

    state = await client.get_voice_of_merchant_state(location_id)
    options: list[dict] = []
    verifications: list[dict] = []
    provider_error: str | None = None
    try:
        options = await client.fetch_verification_options(location_id, language_code)
    except GoogleReviewsError:
        provider_error = "Google did not return verification options."
    try:
        verifications = await client.list_verifications(location_id)
    except GoogleReviewsError:
        provider_error = provider_error or "Google did not return verification history."

    # Google sometimes returns a placeholder option (`{}`) when the caller is
    # not eligible to verify. It is not a method and must never reach the UI as
    # a blank card.
    options = [
        option for option in options if option.get("verificationMethod")
    ]

    status, latest, _ = _verification_status(state, verifications)
    method, contact = _verification_contact(latest, options)

    if provider_error is None and not options and status != "verified":
        if state.get("hasBusinessAuthority") is False:
            provider_error = (
                "Google reports this account does not have business authority "
                "for this location yet, so the API cannot offer a verification "
                "method. Some locations require video verification, which Google "
                "only exposes in Google Business Profile. Complete verification "
                "there, then refresh. If Google says you do not have access, ask "
                "the profile owner to grant owner or manager access."
            )
        elif latest and str(latest.get("state") or "").upper() == "FAILED":
            provider_error = (
                "Google's last verification attempt failed and no new method is "
                "currently eligible through the API. Try again from Google "
                "Business Profile or contact Google support."
            )
        else:
            provider_error = (
                "Google did not return an eligible verification method for this "
                "location."
            )

    result = await db.execute(
        select(VerificationRecord).where(VerificationRecord.channel_id == channel.id)
    )
    record = result.scalar_one_or_none()
    if record is None and (verifications or "verify" in state or status == "verified"):
        record = VerificationRecord(channel_id=channel.id)
        db.add(record)

    if record is not None:
        record.status = status
        record.method = method or record.method
        record.contact_target = contact or record.contact_target
        record.provider_name = (
            str(latest.get("name"))
            if latest and str(latest.get("state") or "").upper() == "PENDING"
            else None
        )
        record.attempts = max(record.attempts or 0, len(verifications))
        if latest and latest.get("createTime") and record.requested_at is None:
            try:
                record.requested_at = datetime.fromisoformat(
                    str(latest["createTime"]).replace("Z", "+00:00")
                )
            except ValueError:
                pass
        if status == "verified":
            if record.verified_at is None:
                completed_at = None
                if latest and latest.get("createTime"):
                    try:
                        completed_at = datetime.fromisoformat(
                            str(latest["createTime"]).replace("Z", "+00:00")
                        )
                    except ValueError:
                        completed_at = None
                record.verified_at = completed_at or datetime.now(timezone.utc)
        else:
            record.verified_at = None
        await db.commit()
        await db.refresh(record)

    from ..locations.service import channel_meta

    meta = channel_meta(channel)
    if not meta.get("country"):
        # Show the country Google actually has; a wrong country is one of the
        # most common reasons verification has no eligible method.
        try:
            from .google_business import GBP_BIZINFO_API

            loc = await client._authed_request(
                "GET",
                f"{GBP_BIZINFO_API}/locations/{location_id}",
                params={"readMask": "storefrontAddress"},
            )
            if loc.status_code == 200:
                code = (
                    ((loc.json().get("storefrontAddress") or {}).get("regionCode") or "")
                    .strip()
                    .upper()[:2]
                )
                if code:
                    meta["country"] = code
                    channel.metadata_json = json.dumps(meta)
                    await db.commit()
        except Exception:  # noqa: BLE001 - diagnostics are best effort
            pass
    return VerificationResponse(
        channel_id=channel.id,
        status=status,
        location_address=meta.get("address"),
        location_country=meta.get("country"),
        location_phone=meta.get("phone"),
        location_website=meta.get("website"),
        account_name=meta.get("account_name"),
        method=method or (record.method if record else None),
        contact_target=contact or (record.contact_target if record else None),
        attempts=record.attempts if record else len(verifications),
        requested_at=(
            record.requested_at.isoformat() if record and record.requested_at else None
        ),
        verified_at=(
            record.verified_at.isoformat() if record and record.verified_at else None
        ),
        has_voice_of_merchant=bool(state.get("hasVoiceOfMerchant")),
        has_business_authority=bool(state.get("hasBusinessAuthority")),
        options=options,
        verifications=verifications,
        provider_name=record.provider_name if record else None,
        provider_error=provider_error,
    )


async def _verification_client(channel: Channel, db: AsyncSession):
    """Google client + location id for a connected channel."""
    from ..locations.service import listing_id_of
    from .google_reviews import GoogleReviewsClient
    from .service import decrypt_token, encrypt_token

    access_token = decrypt_token(channel.access_token) if channel.access_token else None
    refresh_token = decrypt_token(channel.refresh_token) if channel.refresh_token else None
    if not access_token and not refresh_token:
        raise HTTPException(
            status_code=409,
            detail="Google is disconnected. Reconnect it to manage verification.",
        )
    client = GoogleReviewsClient(access_token or "", refresh_token)
    client.set_known_expiry(channel.token_expires_at)

    async def _persist(new_access_token: str, new_expires_at) -> None:
        channel.access_token = encrypt_token(new_access_token)
        channel.token_expires_at = new_expires_at
        db.add(channel)
        await db.commit()

    client.set_token_persister(_persist)
    return client, listing_id_of(channel)


@router.get("/{channel_id}/verification", response_model=VerificationResponse)
async def get_verification(
    channel_id: str,
    language: str = Query("en", min_length=2, max_length=20),
    ctx: TenantContext = Depends(require_perm("channels.view")),
    db: AsyncSession = Depends(get_db),
):
    if ctx.channel_level(channel_id) == "none":
        raise HTTPException(status_code=404, detail="Channel not found")
    channel = await _google_channel(channel_id, ctx.user, db)
    client, location_id = await _verification_client(channel, db)
    try:
        return await _verification_snapshot(db, channel, client, location_id, language)
    except Exception as e:  # noqa: BLE001
        raise upstream_http_error(
            e, context=f"Google verification read failed for {channel_id}",
            detail="Google could not return verification details for this location.",
        ) from None
    finally:
        await client.close()


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
    client, location_id = await _verification_client(channel, db)
    try:
        verification = await client.verify_location(
            location_id,
            method=body.method,
            language_code=body.language_code,
            phone_number=body.phone_number,
            email_address=body.email_address,
            mailer_contact=body.mailer_contact,
            trusted_partner_token=body.trusted_partner_token,
        )
        result = await db.execute(
            select(VerificationRecord).where(VerificationRecord.channel_id == channel_id)
        )
        record = result.scalar_one_or_none()
        if record is None:
            record = VerificationRecord(channel_id=channel_id)
            db.add(record)
        provider_state = str(verification.get("state") or "").upper()
        record.status = {
            "COMPLETED": "verified",
            "FAILED": "failed",
            "PENDING": "pending",
        }.get(provider_state, "requested")
        record.method = body.method
        record.contact_target = (
            body.phone_number or body.email_address or body.mailer_contact
        )
        record.provider_name = (
            str(verification.get("name")) if verification.get("name") else None
        )
        record.attempts = (record.attempts or 0) + 1
        record.requested_at = datetime.now(timezone.utc)
        if record.status == "verified":
            record.verified_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(record)
        return await _verification_snapshot(
            db, channel, client, location_id, body.language_code
        )
    except Exception as e:  # noqa: BLE001
        status_code = getattr(e, "status_code", 502)
        raise upstream_http_error(
            e,
            context=f"Google verification request failed for {channel_id}",
            status_code=400 if status_code in (400, 422) else 502,
            detail=(
                "Google rejected the verification request. Check the method and "
                "contact details and try again."
                if status_code in (400, 422)
                else "Google could not start verification for this location."
            ),
        ) from None
    finally:
        await client.close()


@router.post("/{channel_id}/verification/complete", response_model=VerificationResponse)
async def complete_verification(
    channel_id: str,
    body: VerificationCompleteRequest,
    ctx: TenantContext = Depends(require_perm("channels.edit")),
    db: AsyncSession = Depends(get_db),
):
    if not ctx.can_edit_channel(channel_id):
        raise HTTPException(status_code=403, detail="No edit access to this channel")
    channel = await _google_channel(channel_id, ctx.user, db)
    result = await db.execute(
        select(VerificationRecord).where(VerificationRecord.channel_id == channel_id)
    )
    record = result.scalar_one_or_none()
    if record is None or not record.provider_name:
        raise HTTPException(
            status_code=409,
            detail="Start a verification request before submitting a PIN.",
        )
    client, location_id = await _verification_client(channel, db)
    try:
        verification = await client.complete_verification(record.provider_name, body.pin)
        provider_state = str(verification.get("state") or "").upper()
        record.status = "verified" if provider_state == "COMPLETED" else "pending"
        if record.status == "verified":
            record.verified_at = datetime.now(timezone.utc)
            record.provider_name = None
        await db.commit()
        await db.refresh(record)
        return await _verification_snapshot(db, channel, client, location_id)
    except Exception as e:  # noqa: BLE001
        status_code = getattr(e, "status_code", 502)
        raise upstream_http_error(
            e,
            context=f"Google verification complete failed for {channel_id}",
            status_code=400 if status_code in (400, 422) else 502,
            detail=(
                "The PIN is not valid or has expired. Request a new verification "
                "code and try again."
                if status_code in (400, 422)
                else "Google could not complete verification for this location."
            ),
        ) from None
    finally:
        await client.close()


def _service_response(
    service: BusinessService,
    *,
    google_pushed: bool | None = None,
    google_error: str | None = None,
) -> ServiceResponse:
    return ServiceResponse(
        id=service.id,
        channel_id=service.channel_id,
        name=service.name,
        category=service.category,
        description=service.description,
        is_offered=service.is_offered,
        source=service.source,
        declared=service.declared,
        google_pushed=google_pushed,
        google_error=google_error,
    )


async def _push_services(db, channel_id: str) -> dict:
    """Push the channel's service list to Google and report the outcome.

    Best-effort: the local rows stay either way, so a rejected push never
    loses the merchant's work.
    """
    from .google_services import push_services
    from .models import Channel

    channel = await db.get(Channel, channel_id)
    if channel is None:
        return {"pushed": False, "error": "channel not found", "skipped": []}
    return await push_services(db, channel)


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
    from ..profile.facts_store import rebuild_facts_safe

    await rebuild_facts_safe(db, tenant_id_of(ctx.user))
    push = await _push_services(db, channel_id)
    return _service_response(
        service,
        google_pushed=push.get("pushed"),
        google_error=push.get("error"),
    )


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
    if body.declared is True:
        # Declaring a service means the business offers it.
        service.is_offered = True
    from ..outbox.service import enqueue_event_in

    await enqueue_event_in(db, "google.service.updated", {"channel_id": channel_id, "service_id": service.id}, "google-business-events")
    await db.commit()
    await db.refresh(service)
    from ..profile.facts_store import rebuild_facts_safe

    await rebuild_facts_safe(db, tenant_id_of(ctx.user))
    push = await _push_services(db, channel_id)
    return _service_response(
        service,
        google_pushed=push.get("pushed"),
        google_error=push.get("error"),
    )


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
    from ..profile.facts_store import rebuild_facts_safe

    await rebuild_facts_safe(db, tenant_id_of(ctx.user))
    # Rebuild Google's list so the deleted service leaves it too. The row is
    # already gone, so the rebuild drops the entry.
    await _push_services(db, channel_id)


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
    return _message_out(msg)


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

    return _message_out(msg)


@router.get("/{channel_id}/whatsapp/health", response_model=dict)
async def get_whatsapp_health(
    channel_id: str,
    ctx: TenantContext = Depends(require_perm("inbox.view")),
    db: AsyncSession = Depends(get_db),
):
    """Meta's quality rating and messaging limit for this number.

    Shown in the channel settings so a sudden send failure has a visible
    cause instead of a support ticket.
    """
    if ctx.channel_level(channel_id) == "none":
        raise HTTPException(status_code=404, detail="Channel not found")
    try:
        return await whatsapp_number_health(channel_id, ctx.user, db)
    except ValueError as exc:
        message = str(exc)
        raise HTTPException(
            status_code=404 if message == "Channel not found" else 422,
            detail=message,
        )


@router.get("/{channel_id}/whatsapp/qr-codes", response_model=list[dict])
async def get_whatsapp_qr_codes(
    channel_id: str,
    ctx: TenantContext = Depends(require_perm("inbox.view")),
    db: AsyncSession = Depends(get_db),
):
    if ctx.channel_level(channel_id) == "none":
        raise HTTPException(status_code=404, detail="Channel not found")
    try:
        return await list_whatsapp_qr_codes(channel_id, ctx.user, db)
    except ValueError as exc:
        message = str(exc)
        raise HTTPException(
            status_code=404 if message == "Channel not found" else 422,
            detail=message,
        )


@router.post("/{channel_id}/whatsapp/qr-codes", response_model=dict)
async def post_whatsapp_qr_code(
    channel_id: str,
    body: QrCodeCreate,
    ctx: TenantContext = Depends(require_perm("inbox.reply")),
    db: AsyncSession = Depends(get_db),
):
    if not ctx.can_edit_channel(channel_id):
        raise HTTPException(status_code=403, detail="No edit access to this channel")
    try:
        return await create_whatsapp_qr_code(
            channel_id, body.prefilled_message, ctx.user, db,
            image_format=body.image_format,
        )
    except ValueError as exc:
        message = str(exc)
        raise HTTPException(
            status_code=404 if message == "Channel not found" else 422,
            detail=message,
        )


@router.delete("/{channel_id}/whatsapp/qr-codes/{code}", response_model=dict)
async def remove_whatsapp_qr_code(
    channel_id: str,
    code: str,
    ctx: TenantContext = Depends(require_perm("inbox.reply")),
    db: AsyncSession = Depends(get_db),
):
    if not ctx.can_edit_channel(channel_id):
        raise HTTPException(status_code=403, detail="No edit access to this channel")
    try:
        deleted = await delete_whatsapp_qr_code(channel_id, code, ctx.user, db)
    except ValueError as exc:
        message = str(exc)
        raise HTTPException(
            status_code=404 if message == "Channel not found" else 422,
            detail=message,
        )
    if not deleted:
        raise HTTPException(status_code=404, detail="QR code not found")
    return {"deleted": True, "code": code}


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
            _message_out(m)
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
    cursor: str | None = Query(None, max_length=512),
    ctx: TenantContext = Depends(require_perm("inbox.view")),
    db: AsyncSession = Depends(get_db),
):
    """One filtered, RBAC-scoped page of inbox threads.

    Filters and channel visibility are applied in SQL before LIMIT. `cursor`
    from a previous response walks to the next page; `total` counts the
    filtered result set, not the page.
    """
    try:
        threads, total, next_cursor = await list_inbox_threads_page(
            ctx.user,
            db,
            search=search,
            limit=limit,
            cursor=cursor,
            include_archived=include_archived,
            category=category,
            priority=priority,
            important=important,
            visible_channel_ids=ctx.visible_channel_ids(),
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid cursor") from None
    return InboxThreadListResponse(
        threads=[InboxThread(**t) for t in threads],
        total=total,
        next_cursor=next_cursor,
    )


@_inbox_router.get("/threads/{channel_id}/{contact_phone}", response_model=ChannelMessageListResponse)
async def inbox_thread_messages(
    channel_id: str,
    contact_phone: str,
    limit: int = Query(200, ge=1, le=500),
    before: str | None = Query(None, min_length=1, max_length=64),
    ctx: TenantContext = Depends(require_perm("inbox.view")),
    db: AsyncSession = Depends(get_db),
):
    """One page of messages in a thread, oldest first.

    `contact_phone` is the literal string "unknown" for the catch-all thread
    holding pre-migration rows with no sender.

    `before` is the id of the oldest message the client already has; the
    response's `next_cursor` walks further back until null. Fetch one extra
    row to tell whether an older page exists without a second query.
    """
    if ctx.channel_level(channel_id) == "none":
        raise HTTPException(status_code=404, detail="Channel not found")
    phone = None if contact_phone == UNKNOWN_THREAD_KEY else contact_phone
    try:
        msgs = await list_thread_messages(
            ctx.user, db, channel_id, phone, limit=limit + 1, before=before
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid message cursor") from None
    has_more = len(msgs) > limit
    if has_more:
        msgs = msgs[-limit:]
    next_cursor = msgs[0].id if has_more and msgs else None
    if not msgs and not before:
        # Distinguish "no such channel" (404) from "empty thread" (200, empty).
        channel = await get_channel(channel_id, ctx.user, db)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")
    thread_state = None
    if phone is not None:
        thread_state = await _thread_state(db, ctx.tenant_id, channel_id, phone)
    return ChannelMessageListResponse(
        messages=[
            _message_out(m)
            for m in msgs
        ],
        total=len(msgs),
        next_cursor=next_cursor,
        thread=thread_state,
    )


@_inbox_router.post("/threads/{channel_id}/{contact_phone}/read")
async def mark_thread_read(
    channel_id: str,
    contact_phone: str,
    ctx: TenantContext = Depends(require_perm("inbox.view")),
    db: AsyncSession = Depends(get_db),
):
    """Clear the unread badge for one thread.

    Opening a conversation is the read event; before this endpoint the badge
    only went away when a new outbound message was written, so a thread the
    agent had read kept its counter forever. Idempotent and tenant-scoped via
    ``channel_level``.
    """
    if ctx.channel_level(channel_id) == "none":
        raise HTTPException(status_code=404, detail="Channel not found")
    phone = None if contact_phone == UNKNOWN_THREAD_KEY else contact_phone
    contact_hash = hash_contact_phone(phone) if phone is not None else None
    await db.execute(
        update(ChannelThread)
        .where(
            ChannelThread.channel_id == channel_id,
            ChannelThread.contact_phone_hash.is_(None)
            if contact_hash is None
            else ChannelThread.contact_phone_hash == contact_hash,
        )
        .values(unread_count=0)
    )
    await db.commit()
    return {"unread": 0}


def _as_utc(value):
    """Naive timestamps are UTC (SQLite drops tzinfo); make that explicit.

    The resume clock subtracts from an aware `now` in the sweep, so a naive
    value read back from SQLite would raise if used directly here too.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def _thread_state(db, tenant_id: str, channel_id: str, phone: str) -> ThreadStateOut:
    """Mode, newest summary, window, consent and escalation clock for one thread.

    The reads are indexed and bounded; a read failure degrades to the safe
    default (AI owns, no escalation) rather than failing the whole thread view.
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import func

    from .conversation_context import latest
    from .conversation_mode import get_state
    from .meta.lead_escalation import load_settings
    from .models import ChannelMessage, Lead

    state = await get_state(db, channel_id, phone)
    assignee_name = None
    if state.get("assigned_to"):
        try:
            assignee = (
                await db.execute(
                    select(User).where(User.id == state["assigned_to"])
                )
            ).scalar_one_or_none()
            if assignee is not None:
                assignee_name = (
                    f"{assignee.first_name or ''} {assignee.last_name or ''}".strip()
                    or assignee.email
                )
        except Exception as e:  # noqa: BLE001 - the card is an enhancement
            logger.warning(
                "thread assignee read failed channel=%s: %s", channel_id, e
            )
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

    # The escalation clock. Defaults describe "not escalated", which is the
    # safe side: the UI shows no countdown and no reminder state.
    escalation: dict = {
        "priority": "normal",
        "ai_miss_count": 0,
        "lead_category": None,
        "priority_since": None,
        "escalated_at": None,
        "escalation_reminder_at": None,
        "handover_sent_at": None,
        "resume_at": None,
        "escalation_resume_hours": 24,
    }

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
                .where(
                    Lead.tenant_id == tenant_id,
                    Lead.channel_id == channel_id,
                    Lead.contact_id == phone,
                )
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

            # Window length is a tenant setting; read it through the same
            # loader the resume sweep uses so the UI cannot promise a
            # different resume time than the sweep will act on. Bypass the
            # sweep cache so a just-edited setting is reflected immediately.
            resume_hours = int(
                (await load_settings(db, tenant_id, use_cache=False)).get(
                    "escalation_resume_hours", 24
                )
            )
            priority_since = _as_utc(lead.priority_since)
            escalation = {
                "priority": lead.priority or "normal",
                "ai_miss_count": int(lead.ai_miss_count or 0),
                "lead_category": lead.category,
                "priority_since": (
                    priority_since.isoformat() if priority_since else None
                ),
                "escalated_at": (
                    _as_utc(lead.escalated_at).isoformat()
                    if lead.escalated_at
                    else None
                ),
                "escalation_reminder_at": (
                    _as_utc(lead.escalation_reminder_at).isoformat()
                    if lead.escalation_reminder_at
                    else None
                ),
                "handover_sent_at": (
                    _as_utc(lead.handover_sent_at).isoformat()
                    if lead.handover_sent_at
                    else None
                ),
                "escalation_resume_hours": resume_hours,
                "resume_at": None,
            }
            # Same arithmetic as run_resume_sweep: the clock only runs while
            # the lead is actually escalated and has a start time.
            if escalation["priority"] == "important" and priority_since:
                escalation["resume_at"] = (
                    priority_since + timedelta(hours=resume_hours)
                ).isoformat()
    except Exception as e:  # noqa: BLE001 - see above
        logger.warning("thread window/consent read failed channel=%s: %s", channel_id, e)

    return ThreadStateOut(
        **state,
        assignee_name=assignee_name,
        context=context,
        reply_window_open=window_open,
        opt_in_at=opt_in_at,
        opt_in_source=opt_in_source,
        opted_out=opted_out,
        **escalation,
    )


class ThreadAssigneeUpdate(BaseModel):
    # None (or omitted) unassigns. The service validates that the id belongs
    # to an active teammate who can actually work this channel.
    assigned_to: str | None = Field(None, max_length=36)


@_inbox_router.get("/assignees")
async def inbox_assignees(
    channel_id: str = Query(..., max_length=36),
    ctx: TenantContext = Depends(require_perm("channels.view")),
    db: AsyncSession = Depends(get_db),
):
    """People who can own a conversation on this channel.

    The picker needs names and ids; computing the eligible set server-side
    keeps tenant scope and channel access in one place instead of trusting
    whatever the browser sends back.
    """
    from .assignment import AssignmentError, assignable_users

    if ctx.channel_level(channel_id) == "none":
        raise HTTPException(status_code=404, detail="Channel not found")
    try:
        people = await assignable_users(db, ctx.tenant_id, channel_id)
    except AssignmentError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"assignees": people}


@_inbox_router.patch(
    "/threads/{channel_id}/{contact_phone}/assignee",
    response_model=ThreadStateOut,
)
async def inbox_thread_set_assignee(
    channel_id: str,
    contact_phone: str,
    body: ThreadAssigneeUpdate,
    ctx: TenantContext = Depends(require_perm("inbox.reply")),
    db: AsyncSession = Depends(get_db),
):
    """Claim a conversation for a teammate, or clear the owner.

    Assignment is independent of `conversation_mode`: claiming an escalated
    thread does not silently hand the AI back, and handing the AI back does
    not erase who was working it.
    """
    from .assignment import AssignmentError, assign_thread

    if ctx.channel_level(channel_id) == "none":
        raise HTTPException(status_code=404, detail="Channel not found")
    phone = None if contact_phone == UNKNOWN_THREAD_KEY else contact_phone
    if phone is None:
        raise HTTPException(
            status_code=422,
            detail="An unattributed thread has nobody to assign.",
        )
    try:
        await assign_thread(
            db,
            tenant_id=ctx.tenant_id,
            channel_id=channel_id,
            contact_phone=phone,
            assignee_id=body.assigned_to or None,
            actor=ctx.user,
        )
    except AssignmentError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await _thread_state(db, ctx.tenant_id, channel_id, phone)


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
    "/threads/{channel_id}/{contact_phone}/block",
    response_model=ThreadStateOut,
)
async def inbox_thread_block(
    channel_id: str,
    contact_phone: str,
    ctx: TenantContext = Depends(require_perm("inbox.reply")),
    db: AsyncSession = Depends(get_db),
):
    """Block this customer on the WhatsApp number."""
    if not ctx.can_edit_channel(channel_id):
        raise HTTPException(status_code=403, detail="No edit access to this channel")
    if await get_channel(channel_id, ctx.user, db) is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    phone = None if contact_phone == UNKNOWN_THREAD_KEY else contact_phone
    if phone is None:
        raise HTTPException(
            status_code=422, detail="An unattributed thread has nobody to block."
        )
    try:
        thread = await set_contact_blocked(
            channel_id, phone, True, ctx.user, db
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    from .realtime import publish_inbox_event

    await publish_inbox_event(ctx.tenant_id, {
        "type": "blocked",
        "channel_id": channel_id,
        "contact_phone": phone,
        "blocked_at": (
            thread.blocked_at.isoformat() if thread.blocked_at else None
        ),
        "blocked_by": thread.blocked_by,
    })
    return await _thread_state(db, ctx.tenant_id, channel_id, phone)


@_inbox_router.delete(
    "/threads/{channel_id}/{contact_phone}/block",
    response_model=ThreadStateOut,
)
async def inbox_thread_unblock(
    channel_id: str,
    contact_phone: str,
    ctx: TenantContext = Depends(require_perm("inbox.reply")),
    db: AsyncSession = Depends(get_db),
):
    """Remove a WhatsApp block for this customer."""
    if not ctx.can_edit_channel(channel_id):
        raise HTTPException(status_code=403, detail="No edit access to this channel")
    if await get_channel(channel_id, ctx.user, db) is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    phone = None if contact_phone == UNKNOWN_THREAD_KEY else contact_phone
    if phone is None:
        raise HTTPException(
            status_code=422, detail="An unattributed thread has nobody to unblock."
        )
    try:
        thread = await set_contact_blocked(
            channel_id, phone, False, ctx.user, db
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    from .realtime import publish_inbox_event

    await publish_inbox_event(ctx.tenant_id, {
        "type": "blocked",
        "channel_id": channel_id,
        "contact_phone": phone,
        "blocked_at": None,
        "blocked_by": None,
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

    context_row = await generate(
        db,
        tenant_id=ctx.tenant_id,
        channel_id=channel_id,
        contact_phone=phone,
        reason="resolve",
    )

    # Cumulative memory: the resolved thread's summary becomes a pending,
    # scrubbed lesson. Nothing reaches the AI until a human approves it in
    # the review queue, so this cannot silently change future answers.
    if context_row is not None:
        from ..memory.service import capture_from_resolution

        await capture_from_resolution(
            db,
            tenant_id=ctx.tenant_id,
            channel_id=channel_id,
            contact_phone=phone,
            context=context_row,
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


def _message_out(m: ChannelMessage) -> ChannelMessageResponse:
    """One message shape for every inbox endpoint.

    A locally removed message keeps its row but never returns its text: the
    browser is told `deleted` and shows the removal marker instead.
    """
    deleted = m.deleted_at is not None
    return ChannelMessageResponse(
        id=m.id,
        channel_id=m.channel_id,
        platform_message_id=m.platform_message_id,
        direction=m.direction,
        content="" if deleted else (decrypt_message_content(m.content) or ""),
        content_type=m.content_type,
        status=m.status,
        error=m.error,
        contact_phone=decrypt_contact_phone(m.contact_phone),
        contact_name=m.contact_name,
        reply_to_message_id=m.reply_to_message_id,
        deleted_at=m.deleted_at.isoformat() if m.deleted_at else None,
        deleted=deleted,
        media_url=(
            f"/api/v1/inbox/media/{m.id}" if m.media_key and not deleted else None
        ),
        media_mime_type=m.media_mime_type,
        media_filename=m.media_filename,
        created_at=m.created_at.isoformat(),
    )


async def _publish_outbound_message(tenant_id: str, msg: ChannelMessage) -> None:
    from .realtime import publish_inbox_event

    await publish_inbox_event(tenant_id, {
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
        "reply_to_message_id": msg.reply_to_message_id,
        "media_url": (
            f"/api/v1/inbox/media/{msg.id}"
            if msg.media_key and msg.deleted_at is None else None
        ),
        "media_mime_type": msg.media_mime_type,
        "media_filename": msg.media_filename,
        "created_at": msg.created_at,
    })


@_inbox_router.get("/media/{message_id}")
async def inbox_message_media(
    message_id: str,
    ctx: TenantContext = Depends(require_perm("inbox.view")),
    db: AsyncSession = Depends(get_db),
):
    """Serve one stored attachment to an authorized inbox viewer.

    The bytes live in the private document store; this route is the only way
    to read them. A message outside the caller's channels is a 404, not a 403,
    so an id cannot be probed for existence.
    """
    from pathlib import Path
    from urllib.parse import quote

    from ...core.storage import get_doc

    row = (
        await db.execute(
            select(ChannelMessage).where(ChannelMessage.id == message_id)
        )
    ).scalar_one_or_none()
    if (
        row is None
        or not row.media_key
        or row.deleted_at is not None
        or ctx.channel_level(row.channel_id) == "none"
    ):
        raise HTTPException(status_code=404, detail="Attachment not found")
    # The message id is global; ownership and per-member channel access both
    # have to agree before a byte is served.
    if await get_channel(row.channel_id, ctx.user, db) is None:
        raise HTTPException(status_code=404, detail="Attachment not found")

    try:
        blob = get_doc(f"inbox-{ctx.tenant_id}", row.media_key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Attachment is no longer available") from None

    mime = (row.media_mime_type or "application/octet-stream").lower()
    # Only raster images are rendered in place. PDFs and every other document
    # download, so an untrusted file is never handed to a browser viewer on the
    # API origin. SVG is excluded on purpose (it can carry script).
    inline = mime.startswith("image/") and mime != "image/svg+xml"
    if not inline:
        mime = "application/octet-stream"

    name = row.media_filename or f"attachment{Path(row.media_key).suffix}"
    ascii_name = "".join(
        ch if (ch.isascii() and (ch.isalnum() or ch in "._-")) else "_"
        for ch in name
    )[:120] or "attachment"
    disposition = "inline" if inline else "attachment"
    return Response(
        content=blob,
        media_type=mime,
        headers={
            "Content-Disposition": (
                f"{disposition}; filename=\"{ascii_name}\"; "
                f"filename*=UTF-8''{quote(name)}"
            ),
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )



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
    await ensure_messaging_quota(ctx, db, body.channel_id)
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
            reply_to_message_id=body.reply_to_message_id,
        )
    except ValueError as exc:
        message = str(exc)
        if message == "Channel not found":
            raise HTTPException(status_code=404, detail=message)
        raise HTTPException(status_code=422, detail=message)

    failed = msg.status == "failed"
    await _publish_outbound_message(ctx.tenant_id, msg)

    return InboxSendResponse(
        message=_message_out(msg),
        sent=not failed,
        error=msg.error,
    )


@_inbox_router.post("/send-document", response_model=InboxSendResponse)
async def inbox_send_document(
    channel_id: str = Form(...),
    contact_phone: str = Form(...),
    caption: str = Form(""),
    file: UploadFile = File(...),
    ctx: TenantContext = Depends(require_perm("inbox.reply")),
    db: AsyncSession = Depends(get_db),
):
    """Send a PDF, invoice, menu or other document as a native attachment."""
    if not ctx.can_edit_channel(channel_id):
        raise HTTPException(status_code=403, detail="No edit access to this channel")
    await ensure_messaging_quota(ctx, db, channel_id)

    # Read one byte past the ceiling so an oversized upload is rejected without
    # buffering the whole file first.
    data = await file.read(MAX_OUTBOUND_DOCUMENT_BYTES + 1)
    await file.close()
    if not data:
        raise HTTPException(status_code=422, detail="The document is empty")
    if len(data) > MAX_OUTBOUND_DOCUMENT_BYTES:
        raise HTTPException(status_code=413, detail="Documents must be under 32 MB")

    try:
        msg = await send_document_message(
            channel_id,
            contact_phone,
            data=data,
            filename=file.filename or "document",
            mime_type=file.content_type or "application/octet-stream",
            caption=caption,
            user=ctx.user,
            db=db,
        )
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(
            status_code=404 if detail == "Channel not found" else 422,
            detail=detail,
        ) from exc
    await _publish_outbound_message(ctx.tenant_id, msg)
    return InboxSendResponse(
        message=_message_out(msg),
        sent=msg.status != "failed",
        error=msg.error,
    )


@_inbox_router.post("/send-sticker", response_model=InboxSendResponse)
async def inbox_send_sticker(
    channel_id: str = Form(...),
    contact_phone: str = Form(...),
    file: UploadFile = File(...),
    ctx: TenantContext = Depends(require_perm("inbox.reply")),
    db: AsyncSession = Depends(get_db),
):
    """Send a WebP sticker (WhatsApp's only sticker format)."""
    if not ctx.can_edit_channel(channel_id):
        raise HTTPException(status_code=403, detail="No edit access to this channel")
    await ensure_messaging_quota(ctx, db, channel_id)

    data = await file.read(MAX_OUTBOUND_STICKER_BYTES + 1)
    await file.close()
    if not data:
        raise HTTPException(status_code=422, detail="The sticker is empty")
    if len(data) > MAX_OUTBOUND_STICKER_BYTES:
        raise HTTPException(status_code=413, detail="Stickers must be under 500 KB")

    try:
        msg = await send_sticker_message(
            channel_id,
            contact_phone,
            data=data,
            filename=file.filename or "sticker.webp",
            mime_type=file.content_type or "image/webp",
            user=ctx.user,
            db=db,
        )
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(
            status_code=404 if detail == "Channel not found" else 422,
            detail=detail,
        ) from exc
    await _publish_outbound_message(ctx.tenant_id, msg)
    return InboxSendResponse(
        message=_message_out(msg),
        sent=msg.status != "failed",
        error=msg.error,
    )


@_inbox_router.post("/send-location", response_model=InboxSendResponse)
async def inbox_send_location(
    body: InboxLocationSendRequest,
    ctx: TenantContext = Depends(require_perm("inbox.reply")),
    db: AsyncSession = Depends(get_db),
):
    """Send a native WhatsApp location card (lat/lng, name and address)."""
    if not ctx.can_edit_channel(body.channel_id):
        raise HTTPException(status_code=403, detail="No edit access to this channel")
    await ensure_messaging_quota(ctx, db, body.channel_id)
    try:
        msg = await send_location_message(
            body.channel_id,
            body.contact_phone,
            body.latitude,
            body.longitude,
            name=body.name,
            address=body.address,
            user=ctx.user,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    await _publish_outbound_message(ctx.tenant_id, msg)
    return InboxSendResponse(
        message=_message_out(msg),
        sent=msg.status != "failed",
        error=msg.error,
    )


@_inbox_router.post("/send-contact", response_model=InboxSendResponse)
async def inbox_send_contact(
    body: InboxContactSendRequest,
    ctx: TenantContext = Depends(require_perm("inbox.reply")),
    db: AsyncSession = Depends(get_db),
):
    """Send a native WhatsApp contact card."""
    if not ctx.can_edit_channel(body.channel_id):
        raise HTTPException(status_code=403, detail="No edit access to this channel")
    await ensure_messaging_quota(ctx, db, body.channel_id)
    try:
        msg = await send_contact_message(
            body.channel_id,
            body.contact_phone,
            name=body.name,
            phone=body.phone,
            email=body.email,
            user=ctx.user,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    await _publish_outbound_message(ctx.tenant_id, msg)
    return InboxSendResponse(
        message=_message_out(msg),
        sent=msg.status != "failed",
        error=msg.error,
    )


@_inbox_router.post(
    "/messages/{message_id}/reaction", response_model=InboxSendResponse
)
async def inbox_react_to_message(
    message_id: str,
    body: InboxReactionRequest,
    ctx: TenantContext = Depends(require_perm("inbox.reply")),
    db: AsyncSession = Depends(get_db),
):
    """React to one message (empty emoji removes the reaction)."""
    target = (
        await db.execute(
            select(ChannelMessage).where(ChannelMessage.id == message_id)
        )
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="Message not found")
    if not ctx.can_edit_channel(target.channel_id):
        raise HTTPException(status_code=403, detail="No edit access to this channel")
    try:
        msg = await react_to_message(
            target.channel_id, message_id, body.emoji, ctx.user, db
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return InboxSendResponse(
        message=_message_out(msg),
        sent=msg.status != "failed",
        error=msg.error,
    )


@_inbox_router.delete(
    "/messages/{message_id}", response_model=ChannelMessageResponse
)
async def inbox_remove_message(
    message_id: str,
    ctx: TenantContext = Depends(require_perm("inbox.reply")),
    db: AsyncSession = Depends(get_db),
):
    """Remove a message from this inbox. Not a WhatsApp retraction.

    Meta's Cloud API has no delete-for-everyone endpoint for business
    messages, so the row is kept for audit and the UI labels it as removed.
    """
    target = (
        await db.execute(
            select(ChannelMessage).where(ChannelMessage.id == message_id)
        )
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="Message not found")
    if not ctx.can_edit_channel(target.channel_id):
        raise HTTPException(status_code=403, detail="No edit access to this channel")
    try:
        msg = await soft_delete_message(
            target.channel_id, message_id, ctx.user, db
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _message_out(msg)


# ── Retired legacy webhooks ─────────────────────────────────────────────
#
# The real Meta ingress is POST /api/v1/meta/webhooks (signature-verified,
# rate-limited, persisted, enqueued). This older path scanned every active
# channel's secret and then called handle_webhook(), a stub that silently
# dropped the payload. It now fails loudly so no caller believes an event was
# accepted; the route stays mounted to give existing integrations a clear 410
# instead of a confusing 404 or CSRF rejection.

@router.post("/webhook/{platform}")
async def channel_webhook(platform: str):
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "Legacy webhook endpoint retired. Use the platform-specific "
            "ingress at POST /api/v1/meta/webhooks."
        ),
    )


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
    from .google_reviews import (
        exchange_code,
        list_accounts,
        location_address,
        location_category,
        location_phone,
        location_website,
        location_description,
        location_hours,
        location_categories,
        location_attributes,
        location_service_area,
        location_service_types,
        GoogleReviewsClient,
        GoogleReviewsError,
    )
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
        attributes_by_location: dict[str, list[dict]] = {}
        try:
            locations = await client.list_locations(account_id)
            for loc in locations:
                lid = loc.get("name", "locations/").split("/")[-1]
                try:
                    attributes_by_location[lid] = await client.get_attributes(lid)
                except GoogleReviewsError as e:
                    logger.debug("attributes unavailable for %s: %s", lid, e)
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
                    )
                )
                for c in legacy.scalars().all():
                    if _channel_meta_meta(c).get("location_id") == location_id:
                        matching = c
                        if c.listing_key is None:
                            c.listing_key = key
                        break
            if matching is not None:
                # Re-consent heals tokens and reactivates a soft-disconnected
                # channel: the same row, reviews, metrics and drafts return.
                # Never overwrite a stored refresh token with nothing —
                # Google only sends one on fresh consent.
                matching.status = "active"
                if access_token:
                    matching.access_token = encrypt_token(access_token)
                if refresh_token:
                    matching.refresh_token = encrypt_token(refresh_token)
                matching.token_expires_at = token_expires_at
                matching.display_name = title
                matching.listing_key = key
                existing_meta = _channel_meta_meta(matching)
                existing_meta.update({
                    "location_id": location_id,
                    "account_name": account_name,
                    "place_id": loc.get("metadata", {}).get("placeId"),
                    # v1 Location.Metadata uses mapsUri (v4 used mapsUrl).
                    "maps_url": loc.get("metadata", {}).get("mapsUri"),
                    "country": (
                        ((loc.get("storefrontAddress") or {}).get("regionCode") or "")
                        .strip()
                        .upper()[:2]
                    ) or None,
                    "address": location_address(loc),
                    "category": location_category(loc),
                    "phone": location_phone(loc),
                    "website": location_website(loc),
                    "description": location_description(loc),
                    "hours": location_hours(loc),
                    "categories": location_categories(loc),
                    "attributes": location_attributes(attributes_by_location.get(location_id)),
                    "service_area": location_service_area(loc),
                    "services": location_service_types(loc),
                    "profile_fields_checked": True,
                })
                matching.metadata_json = _json.dumps(existing_meta)
                from .service import sync_google_services

                await sync_google_services(
                    db, matching, location_service_types(loc),
                    location_category(loc),
                )
                continue

            loc_meta = loc.get("metadata") or {}
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
                metadata_json=_json.dumps({
                    "location_id": location_id,
                    "account_name": account_name,
                    "place_id": loc_meta.get("placeId"),
                    "maps_url": loc_meta.get("mapsUrl"),
                    "address": location_address(loc),
                    "category": location_category(loc),
                    "phone": location_phone(loc),
                    "website": location_website(loc),
                    "description": location_description(loc),
                    "hours": location_hours(loc),
                    "categories": location_categories(loc),
                    "attributes": location_attributes(attributes_by_location.get(location_id)),
                    "service_area": location_service_area(loc),
                    "services": location_service_types(loc),
                    "profile_fields_checked": True,
                }),
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
            from .service import sync_google_services

            await sync_google_services(
                db, channel, location_service_types(loc), location_category(loc)
            )
            created += 1

    await db.commit()
    # Reconnect restores the same rows; rebuild the assistant's location facts.
    from ..profile.facts_store import rebuild_facts_safe

    await rebuild_facts_safe(db, user_id)
    logger.info("Google Reviews connect: created %d channels for user %s", created, user_id)
    import_session = None
    try:
        from .connect_import import create_session

        connector = await db.get(User, user_id)
        tenant_id = tenant_id_of(connector) if connector is not None else user_id
        import_session = await create_session(db, tenant_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not create connect import session: %s", e)
    redirect = f"{base}?google_connected={created}"
    if import_session is not None:
        redirect = f"{redirect}&import_session={import_session.id}"
    return RedirectResponse(redirect)


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
                google_reply_state=r.google_reply_state,
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
    """Re-check stale reply rows against live Google data, both directions.

    Google now moderates replies (`ReviewReplyState`, 2026-04-01), so a write
    Sayvors accepted can stay unreadable far longer than any read-back window.
    Verification is therefore conservative:

      - `failed` + Google shows the reply  -> healed to `posted` (the reply was
        accepted all along; the old read-back gate produced false failures).
      - `posted` + the review is gone      -> `rejected` (nothing to reply to).
      - `posted` + reply showing           -> confirmed.
      - reply absent either way            -> left untouched. Absence is not
        proof of failure under moderation, so it must never flip a row.

    Read failures (auth/network) abort without touching anything: we only
    correct on definitive evidence, never on our own errors.
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
                ReviewReply.status.in_(["posted", "failed"]),
            )
            .order_by(ReviewReply.created_at.desc())
            .limit(500)
        )
    ).scalars().all()

    # Only native Google review resource names can be verified against Google.
    rows = [r for r in all_posted if r.review_id.startswith("accounts/")]
    skipped_non_google = len(all_posted) - len(rows)
    if not rows:
        return {
            "channel_id": channel.id,
            "checked": 0,
            "confirmed": 0,
            "corrected": 0,
            "skipped_non_google": skipped_non_google,
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
    healed = 0
    removed = 0
    try:
        for reply in rows:
            payload: dict = {}
            try:
                # Read the review itself first so a deleted review can be told
                # apart from a reply that never made it live. read_reply_state
                # folds both into "absent", which is why a review the customer
                # deleted surfaced as "publishing failed".
                for attempt in range(2):
                    payload = await client.get_review(reply.review_id)
                    if payload or attempt == 1:
                        break
                    await asyncio.sleep(2)
            except GoogleReviewsError as e:
                raise HTTPException(
                    status_code=e.status_code,
                    detail=f"Could not read Google to verify: {e}",
                )
            live_reply = payload.get("reviewReply") if payload else None
            if live_reply:
                # Same default as read_reply_state: a reply Google shows without
                # a state is treated as live (legacy rows predate the field).
                reply.google_reply_state = (
                    (live_reply.get("reviewReplyState") or "APPROVED").lower()
                )
                if reply.status == "failed":
                    # Google shows the reply: the earlier failure was a
                    # read-back false negative (moderation lag). Adopt the
                    # live text/timestamps so the row matches Google.
                    reply.status = "posted"
                    reply.error = None
                    reply.reply_text = (live_reply.get("comment") or "").strip() or reply.reply_text
                    updated = live_reply.get("updateTime")
                    if updated:
                        try:
                            reply.replied_at = datetime.fromisoformat(
                                updated.replace("Z", "+00:00")
                            )
                        except ValueError:
                            pass
                    reply.reply_external_id = f"google:{updated}" if updated else None
                    healed += 1
                else:
                    confirmed += 1
            elif not payload:
                # Google no longer has this review (deleted by the reviewer or
                # removed by Google). There is nothing to reply to: this is not
                # a publish failure and must never ask for a reconnect.
                # Withdrawing the draft keeps it out of the failed queue.
                reply.status = "rejected"
                reply.error = (
                    "This review was deleted on Google, so there is nothing to reply to."
                )
                removed += 1
            # else: the review exists but shows no reply. Under Google's
            # moderation that is not proof of failure (a PENDING reply can be
            # unreadable), so the row is left exactly as it was.
    finally:
        await client.close()
    await db.commit()
    return {
        "channel_id": channel.id,
        "checked": len(rows),
        "confirmed": confirmed,
        "corrected": corrected,
        "healed": healed,
        "removed": removed,
        "skipped_non_google": skipped_non_google,
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
        # "posted" must mean Google accepted the reply. Moderation
        # (PENDING) and replication lag are not failures — only an
        # explicit REJECTED state means the reply is not on Google.
        state = await client.read_reply_state(reply.review_id)
        if state["state"] == "rejected":
            reply.status = "failed"
            reply.error = (
                "Google rejected the reply"
                + (f": {state['policy_violation']}" if state["policy_violation"] else "")
                + ". Edit the draft and approve again."
            )
            reply.google_reply_state = state["state"]
            await db.commit()
            await _notify_reply_failed(db, ctx.user.id, channel, reply, reply.error)
            raise HTTPException(status_code=502, detail=reply.error)
        reply.google_reply_state = state["state"]
        reply.status = "posted"
        reply.error = None
        from .reviews_worker import _store_reply_message

        await _store_reply_message(
            db, channel, reply.review_id, reply.reviewer_name, reply,
            status="sent", handled_by="ai",
        )
        await db.commit()
        await _clear_edited_flag(db, channel.id, reply.review_id)
        await db.commit()
        await _notify_reply_posted(db, ctx.user.id, channel, reply)
    except GoogleReviewsError as e:
        if e.status_code == 404:
            # The review is gone from Google (deleted by the reviewer, or
            # removed). Republishing can never succeed, so keep it out of the
            # failed queue and stop telling the merchant to retry.
            reply.status = "rejected"
            reply.error = (
                "This review was deleted on Google, so there is nothing to reply to."
            )
            await db.commit()
            raise HTTPException(
                status_code=404,
                detail="This review no longer exists on Google, so there is nothing to reply to.",
            ) from e
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
            raise upstream_http_error(
                e,
                context="Review reply generation failed",
                detail="Reply generation is temporarily unavailable. Try again shortly.",
            ) from None

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
        raise upstream_http_error(
            e,
            context="Review reply regeneration failed",
            detail="Reply generation is temporarily unavailable. Try again shortly.",
        ) from None

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
            raise upstream_http_error(
                e,
                context="Review reply generation failed",
                detail="Reply generation is temporarily unavailable. Try again shortly.",
            ) from None

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

# -- Google Business Profile location media (gallery) -------------

@router.get("/{channel_id}/google-media")
async def list_google_media(
    channel_id: str,
    page_size: int = Query(2500, ge=1, le=2500),
    page_token: str | None = Query(None, max_length=2000),
    category: str | None = Query(None, max_length=40),
    ctx: TenantContext = Depends(require_perm("channels.view")),
    db: AsyncSession = Depends(get_db),
):
    """List photos/videos in the connected Google Business Profile gallery."""
    if ctx.channel_level(channel_id) == "none":
        raise HTTPException(status_code=404, detail="Channel not found")
    if category:
        allowed = {
            "COVER", "PROFILE", "LOGO", "EXTERIOR", "INTERIOR", "PRODUCT",
            "AT_WORK", "FOOD_AND_DRINK", "MENU", "COMMON_AREA", "ROOMS", "TEAMS", "ADDITIONAL",
        }
        cat = category.strip().upper()
        if cat not in allowed:
            raise HTTPException(status_code=400, detail=f"Invalid category: {category}")
        category = cat
    channel = await _google_channel(channel_id, ctx.user, db)
    client, location_id = await _verification_client(channel, db)
    try:
        data = await client.list_media(
            channel.platform_user_id or "",
            location_id,
            page_size=page_size,
            page_token=page_token,
            category=category,
        )
        items = []
        for m in (data.get("mediaItems") or []):
            if not isinstance(m, dict):
                continue
            assoc = m.get("locationAssociation") or {}
            items.append(
                {
                    "name": m.get("name") or "",
                    "mediaFormat": m.get("mediaFormat"),
                    "category": assoc.get("category"),
                    "googleUrl": m.get("googleUrl"),
                    "thumbnailUrl": m.get("thumbnailUrl"),
                    "sourceUrl": m.get("sourceUrl"),
                    "description": m.get("description"),
                    "createTime": m.get("createTime"),
                    "dimensions": m.get("dimensions"),
                    "insights": m.get("insights"),
                }
            )
        return {
            "media": items,
            "nextPageToken": data.get("nextPageToken"),
            "totalMediaItemCount": data.get("totalMediaItemCount"),
        }
    except Exception as e:  # noqa: BLE001
        from .google_reviews import GoogleReviewsError
        import logging

        if isinstance(e, GoogleReviewsError):
            logging.getLogger(__name__).error(
                "Google media list failed for %s: %s", channel_id, e, exc_info=True
            )
            msg = str(e)
            google_raw = msg[msg.index("{") :] if "{" in msg else msg
            status = int(getattr(e, "status_code", 502) or 502)
            if status < 400 or status > 599:
                status = 502
            raise HTTPException(status_code=status, detail=google_raw) from None
        raise upstream_http_error(
            e,
            context=f"Google media list failed for {channel_id}",
            detail="Google could not return the location gallery.",
        ) from None
    finally:
        await client.close()


@router.post("/{channel_id}/google-media", status_code=status.HTTP_201_CREATED)
async def upload_google_media(
    channel_id: str,
    file: UploadFile | None = File(None),
    source_url: str | None = Form(None),
    category: str = Form("ADDITIONAL"),
    description: str | None = Form(None),
    ctx: TenantContext = Depends(require_perm("channels.edit")),
    db: AsyncSession = Depends(get_db),
):
    """Upload a photo to the connected Google Business Profile gallery.

    Provide either a file upload or ``source_url`` (publicly accessible).
    """
    if not ctx.can_edit_channel(channel_id):
        raise HTTPException(status_code=403, detail="No edit access to this channel")
    cat = (category or "ADDITIONAL").strip().upper()
    allowed = {
        "COVER", "PROFILE", "LOGO", "EXTERIOR", "INTERIOR", "PRODUCT",
        "AT_WORK", "FOOD_AND_DRINK", "MENU", "COMMON_AREA", "ROOMS", "TEAMS", "ADDITIONAL",
    }
    if cat not in allowed:
        raise HTTPException(status_code=400, detail=f"Invalid category: {category}")
    if file is None and not (source_url or "").strip():
        raise HTTPException(status_code=400, detail="Provide a file or source_url.")

    channel = await _google_channel(channel_id, ctx.user, db)
    client, location_id = await _verification_client(channel, db)
    try:
        if file is not None:
            data = await file.read()
            if not data:
                raise HTTPException(status_code=400, detail="Empty file.")
            ctype = file.content_type or "image/jpeg"
            if not ctype.startswith("image/"):
                raise HTTPException(status_code=400, detail="Only image files are supported.")
            # Basic size guard; Google enforces its own limits too.
            if len(data) > 5 * 1024 * 1024:
                raise HTTPException(status_code=400, detail="Image is too large (max 5MB).")
            ref = await client.start_media_upload(channel.platform_user_id or "", location_id)
            await client.upload_media_bytes(ref, data, ctype)
            created = await client.create_location_media(
                channel.platform_user_id or "",
                location_id,
                category=cat,
                data_ref=ref,
                description=description,
            )
        else:
            # Direct byte upload to Google: fetch source bytes and upload via
            # startUpload/dataRef instead of passing sourceUrl to GBP.
            url = (source_url or "").strip()
            if not url.lower().startswith(("http://", "https://")):
                raise HTTPException(status_code=400, detail="source_url must be an http(s) URL.")
            import httpx
            try:
                async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as hc:
                    resp = await hc.get(url)
                    resp.raise_for_status()
                    data = resp.content
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Could not fetch source_url: {exc}") from None
            if not data:
                raise HTTPException(status_code=400, detail="Fetched image is empty.")
            if len(data) > 5 * 1024 * 1024:
                raise HTTPException(status_code=400, detail="Image is too large (max 5MB).")
            ctype = (resp.headers.get("content-type") or "image/jpeg").split(";", 1)[0].strip()
            if not ctype.startswith("image/"):
                ctype = "image/jpeg"
            ref = await client.start_media_upload(channel.platform_user_id or "", location_id)
            await client.upload_media_bytes(ref, data, ctype)
            created = await client.create_location_media(
                channel.platform_user_id or "",
                location_id,
                category=cat,
                data_ref=ref,
                description=description,
            )
        assoc = created.get("locationAssociation") or {}
        return {
            "created": True,
            "media": {
                "name": created.get("name") or "",
                "mediaFormat": created.get("mediaFormat"),
                "category": assoc.get("category"),
                "googleUrl": created.get("googleUrl"),
                "thumbnailUrl": created.get("thumbnailUrl"),
                "sourceUrl": created.get("sourceUrl"),
                "description": created.get("description"),
                "createTime": created.get("createTime"),
                "dimensions": created.get("dimensions"),
                "insights": created.get("insights"),
            },
        }
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        from .google_reviews import GoogleReviewsError
        import logging

        if isinstance(e, GoogleReviewsError):
            # Surface original Google status/body to the user as requested.
            logging.getLogger(__name__).error(
                "Google media upload failed for %s: %s", channel_id, e, exc_info=True
            )
            msg = str(e)
            if "{" in msg:
                try:
                    google_raw = msg[msg.index("{") :]
                except Exception:
                    google_raw = msg
            else:
                google_raw = msg
            status = int(getattr(e, "status_code", 502) or 502)
            if status < 400 or status > 599:
                status = 502
            raise HTTPException(status_code=status, detail=google_raw) from None
        raise upstream_http_error(
            e,
            context=f"Google media upload failed for {channel_id}",
            detail="Google could not add the photo to the location gallery.",
        ) from None
    finally:
        await client.close()


@router.delete("/{channel_id}/google-media")
async def delete_google_media(
    channel_id: str,
    name: str = Query(..., min_length=1, max_length=500, description="Full media resource name"),
    ctx: TenantContext = Depends(require_perm("channels.edit")),
    db: AsyncSession = Depends(get_db),
):
    """Delete a photo/video from the connected Google Business Profile gallery."""
    if not ctx.can_edit_channel(channel_id):
        raise HTTPException(status_code=403, detail="No edit access to this channel")
    channel = await _google_channel(channel_id, ctx.user, db)
    client, location_id = await _verification_client(channel, db)
    try:
        # Safety: only allow deleting media belonging to this location.
        _, _, parent = client._normalize_parent(channel.platform_user_id or "", location_id)
        if not name.startswith(parent + "/media/"):
            raise HTTPException(status_code=403, detail="Media does not belong to this location.")
        await client.delete_media(name)
        return {"deleted": True, "name": name}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        from .google_reviews import GoogleReviewsError
        import logging

        if isinstance(e, GoogleReviewsError):
            logging.getLogger(__name__).error(
                "Google media delete failed for %s: %s", channel_id, e, exc_info=True
            )
            msg = str(e)
            google_raw = msg[msg.index("{") :] if "{" in msg else msg
            status = int(getattr(e, "status_code", 502) or 502)
            if status < 400 or status > 599:
                status = 502
            raise HTTPException(status_code=status, detail=google_raw) from None
        raise upstream_http_error(
            e,
            context=f"Google media delete failed for {channel_id}",
            detail="Google could not remove the photo from the location gallery.",
        ) from None
    finally:
        await client.close()

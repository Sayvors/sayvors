import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_db, get_current_user
from ...config import settings
from ..users.models import User
from .models import BusinessService, Channel, ReviewReply, AutoReplyConfig, VerificationRecord
from .schemas import (
    AutoReplyConfigResponse,
    AutoReplyConfigUpdate,
    ChannelCreate,
    ChannelListResponse,
    ChannelMessageListResponse,
    ChannelMessageResponse,
    ChannelMessageSend,
    ChannelResponse,
    ReviewReplyEdit,
    ReviewReplyGenerate,
    ReviewReplyListResponse,
    ReviewReplyResponse,
    ServiceCreate,
    ServiceResponse,
    ServiceUpdate,
    VerificationRequest,
    VerificationResponse,
)
from .service import (
    create_channel,
    delete_channel,
    get_channel,
    handle_webhook,
    list_channels,
    list_messages,
    send_message,
    verify_webhook_signature,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/channels", tags=["channels"])

MAX_WEBHOOK_BODY_BYTES = 1_000_000  # 1 MB


@router.post("/", response_model=ChannelResponse, status_code=status.HTTP_201_CREATED)
async def connect_channel(
    body: ChannelCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    channel = await create_channel(body, user, db)
    return ChannelResponse(
        id=channel.id,
        platform=channel.platform,
        platform_user_id=channel.platform_user_id,
        display_name=channel.display_name,
        status=channel.status,
        avatar_url=channel.avatar_url,
        created_at=channel.created_at.isoformat(),
    )


@router.get("/", response_model=ChannelListResponse)
async def get_channels(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    channels, total = await list_channels(user, db, limit, offset)
    return ChannelListResponse(
        channels=[
            ChannelResponse(
                id=c.id,
                platform=c.platform,
                platform_user_id=c.platform_user_id,
                display_name=c.display_name,
                status=c.status,
                avatar_url=c.avatar_url,
                created_at=c.created_at.isoformat(),
            )
            for c in channels
        ],
        total=total,
    )


@router.get("/{channel_id}", response_model=ChannelResponse)
async def get_channel_by_id(
    channel_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    channel = await get_channel(channel_id, user, db)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return ChannelResponse(
        id=channel.id,
        platform=channel.platform,
        platform_user_id=channel.platform_user_id,
        display_name=channel.display_name,
        status=channel.status,
        avatar_url=channel.avatar_url,
        created_at=channel.created_at.isoformat(),
    )


@router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_channel(
    channel_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    deleted = await delete_channel(channel_id, user, db)
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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _google_channel(channel_id, user, db)
    result = await db.execute(select(VerificationRecord).where(VerificationRecord.channel_id == channel_id))
    return _verification_response(result.scalar_one_or_none(), channel_id)


@router.post("/{channel_id}/verification", response_model=VerificationResponse)
async def request_verification(
    channel_id: str,
    body: VerificationRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    channel = await _google_channel(channel_id, user, db)
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
    await db.commit()
    await db.refresh(record)
    from ..outbox.service import enqueue_event
    await enqueue_event("google.verification.requested", {"channel_id": channel.id, "method": body.method}, "google-business-events")
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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _google_channel(channel_id, user, db)
    result = await db.execute(
        select(BusinessService).where(BusinessService.channel_id == channel_id).order_by(BusinessService.created_at)
    )
    return {"services": [_service_response(item) for item in result.scalars().all()], "predefined": []}


@router.post("/{channel_id}/services", response_model=ServiceResponse, status_code=status.HTTP_201_CREATED)
async def create_service(
    channel_id: str,
    body: ServiceCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _google_channel(channel_id, user, db)
    service = BusinessService(channel_id=channel_id, **body.model_dump())
    db.add(service)
    await db.commit()
    await db.refresh(service)
    from ..outbox.service import enqueue_event
    await enqueue_event("google.service.created", {"channel_id": channel_id, "service_id": service.id}, "google-business-events")
    return _service_response(service)


@router.put("/{channel_id}/services/{service_id}", response_model=ServiceResponse)
async def update_service(
    channel_id: str,
    service_id: str,
    body: ServiceUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _google_channel(channel_id, user, db)
    result = await db.execute(select(BusinessService).where(BusinessService.id == service_id, BusinessService.channel_id == channel_id))
    service = result.scalar_one_or_none()
    if service is None:
        raise HTTPException(status_code=404, detail="Service not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(service, key, value)
    await db.commit()
    await db.refresh(service)
    from ..outbox.service import enqueue_event
    await enqueue_event("google.service.updated", {"channel_id": channel_id, "service_id": service.id}, "google-business-events")
    return _service_response(service)


@router.delete("/{channel_id}/services/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_service(
    channel_id: str,
    service_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _google_channel(channel_id, user, db)
    result = await db.execute(select(BusinessService).where(BusinessService.id == service_id, BusinessService.channel_id == channel_id))
    service = result.scalar_one_or_none()
    if service is None:
        raise HTTPException(status_code=404, detail="Service not found")
    await db.delete(service)
    await db.commit()
    from ..outbox.service import enqueue_event
    await enqueue_event("google.service.deleted", {"channel_id": channel_id, "service_id": service_id}, "google-business-events")


@router.post("/{channel_id}/messages", response_model=ChannelMessageResponse, status_code=status.HTTP_201_CREATED)
async def send_to_channel(
    channel_id: str,
    body: ChannelMessageSend,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        msg = await send_message(channel_id, body, user, db)
    except ValueError:
        raise HTTPException(status_code=404, detail="Channel not found")
    return ChannelMessageResponse(
        id=msg.id,
        channel_id=msg.channel_id,
        platform_message_id=msg.platform_message_id,
        direction=msg.direction,
        content=msg.content,
        content_type=msg.content_type,
        status=msg.status,
        error=msg.error,
        created_at=msg.created_at.isoformat(),
    )


@router.get("/{channel_id}/messages", response_model=ChannelMessageListResponse)
async def get_channel_messages(
    channel_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    msgs, total = await list_messages(channel_id, user, db, limit, offset)
    return ChannelMessageListResponse(
        messages=[
            ChannelMessageResponse(
                id=m.id,
                channel_id=m.channel_id,
                platform_message_id=m.platform_message_id,
                direction=m.direction,
                content=m.content,
                content_type=m.content_type,
                status=m.status,
                error=m.error,
                created_at=m.created_at.isoformat(),
            )
            for m in msgs
        ],
        total=total,
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

    # ── Signature verification ──
    sig_header = _SIGNATURE_HEADERS.get(platform)
    if sig_header:
        signature = request.headers.get(sig_header)
        # Look up the channel for this platform to get the webhook_secret
        result = await db.execute(
            select(Channel).where(
                Channel.platform == platform,
                Channel.status == "active",
            )
        )
        channel = result.scalar_one_or_none()

        if channel and channel.webhook_secret:
            body_bytes = raw_body
            verified = await verify_webhook_signature(platform, body_bytes, signature or "", channel)
            if not verified:
                logger.warning("Webhook signature verification failed for platform=%s", platform)
                return Response(status_code=403, content="Invalid signature")
        elif not channel:
            # No channel found — might be a verify request or misconfiguration
            logger.warning("Webhook received for platform=%s with no active channel", platform)

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
    """Auth for browser-navigable endpoints: Authorization header OR ?token=."""
    from ...core.deps import get_current_user

    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        # Reuse the standard dependency logic
        from fastapi.security import HTTPAuthorizationCredentials
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=auth_header[7:])
        return await get_current_user(creds, db)

    token = request.query_params.get("token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    import jwt as pyjwt
    try:
        payload = pyjwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")
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


@router.get("/google/connect")
async def google_connect(
    request: Request,
    token: str | None = Query(None, description="Access token (query param) — lets the browser open this URL directly"),
    next: str | None = Query(None, description="Frontend path to return to after connect (e.g. /onboarding)"),
    user: User = Depends(get_current_user_or_query_token),
):
    """Start the Google OAuth flow. Open this URL in the browser.

    Works both with an Authorization header (API clients) and with
    `?token=<access_token>` (browser button navigations, which cannot
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
        return RedirectResponse(f"{base}?google_error={error}")
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

            # Skip if this location is already connected for this user
            import json as _json
            existing = await db.execute(
                select(Channel).where(
                    Channel.user_id == user_id,
                    Channel.platform == "google_reviews",
                    Channel.status == "active",
                )
            )
            matching = [
                c
                for c in existing.scalars().all()
                if _channel_meta_meta(c).get("location_id") == location_id
            ]
            if matching:
                # Re-consent heals tokens: a fresh refresh_token repairs
                # channels that can't publish ("No refresh token available").
                # Never overwrite a stored refresh token with nothing —
                # Google only sends one on fresh consent.
                if refresh_token:
                    for c in matching:
                        c.access_token = encrypt_token(access_token)
                        c.refresh_token = encrypt_token(refresh_token)
                        c.token_expires_at = token_expires_at
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
            )
            db.add(channel)
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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_channel(channel_id, user, db)
    result = await db.execute(
        select(AutoReplyConfig).where(AutoReplyConfig.channel_id == channel_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        # Implicit default config; enabled=False until the merchant turns it on
        config = AutoReplyConfig(channel_id=channel_id)
        db.add(config)
        await db.commit()
        await db.refresh(config)
    return AutoReplyConfigResponse(
        channel_id=config.channel_id,
        enabled=config.enabled,
        tone=config.tone,
        databank_id=config.databank_id,
        min_rating_auto=config.min_rating_auto,
        model=config.model,
        approval_mode=config.approval_mode,
        custom_instructions=config.custom_instructions,
    )


@router.put("/{channel_id}/autoreply", response_model=AutoReplyConfigResponse)
async def update_autoreply_config(
    channel_id: str,
    body: AutoReplyConfigUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    channel = await _get_owned_channel(channel_id, user, db)

    # If a databank is being linked, verify it belongs to this user
    if body.databank_id:
        from ..rag.models import Databank
        owned = await db.execute(
            select(Databank.id).where(
                Databank.id == body.databank_id, Databank.user_id == user.id
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
        config.tone = body.tone[:50]
    if body.databank_id is not None:
        config.databank_id = body.databank_id or None
    if body.min_rating_auto is not None:
        config.min_rating_auto = body.min_rating_auto
    if body.model is not None:
        from ..llm.providers.registry import list_tenant_models

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
    if body.custom_instructions is not None:
        config.custom_instructions = body.custom_instructions.strip()[:2000] or None

    await db.commit()
    await db.refresh(config)
    return AutoReplyConfigResponse(
        channel_id=config.channel_id,
        enabled=config.enabled,
        tone=config.tone,
        databank_id=config.databank_id,
        min_rating_auto=config.min_rating_auto,
        model=config.model,
        approval_mode=config.approval_mode,
        custom_instructions=config.custom_instructions,
    )


# ── Review replies ──────────────────────────────────────


@router.get("/{channel_id}/reviews", response_model=ReviewReplyListResponse)
async def list_review_replies(
    channel_id: str,
    status_filter: str | None = Query(None, alias="status", pattern="^(posted|pending_approval|failed|approved)$"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_channel(channel_id, user, db)

    query = select(ReviewReply).where(ReviewReply.channel_id == channel_id)
    if status_filter:
        query = query.where(ReviewReply.status == status_filter)
    result = await db.execute(query.order_by(ReviewReply.created_at.desc()).limit(limit).offset(offset))
    rows = result.scalars().all()

    pending_result = await db.execute(
        select(ReviewReply.id)
        .where(ReviewReply.channel_id == channel_id, ReviewReply.status == "pending_approval")
        .limit(1000)
    )
    pending = len(pending_result.scalars().all())

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
                error=r.error,
                created_at=r.created_at.isoformat(),
            )
            for r in rows
        ],
        pending=pending,
    )


@router.post("/{channel_id}/reviews/{reply_id}/approve", response_model=ReviewReplyResponse)
async def approve_review_reply(
    channel_id: str,
    reply_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Approve a pending (low-rating) reply and post it to Google."""
    channel = await _get_owned_channel(channel_id, user, db)
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
        # Dev mode: no real GBP location behind the demo channel
        reply.status = "posted"
        reply.error = None
        await db.commit()
    else:
        access_token = decrypt_token(channel.access_token) if channel.access_token else None
        refresh_token = decrypt_token(channel.refresh_token) if channel.refresh_token else None
        if not access_token and not refresh_token:
            # Localith middleware channel: reviews sync through Localith and
            # there is no Google token to post with. The merchant publishes
            # the reply from their Localith/GBP dashboard — approval marks
            # it "approved" (NOT "posted": nothing reached Google).
            reply.status = "approved"
            reply.error = None
            await db.commit()
        else:
            client = GoogleReviewsClient(access_token or "", refresh_token)
            try:
                if not access_token:
                    await client.refresh_access_token()
                await client.reply_to_review(reply.review_id, reply.reply_text)
                reply.status = "posted"
                reply.error = None
                await db.commit()
            except GoogleReviewsError as e:
                reply.status = "failed"
                reply.error = str(e)[:2000]
                await db.commit()
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
    await db.commit()

    # Keep analytics response-rate/response-time accurate
    try:
        from ..outbox.service import enqueue_event

        await enqueue_event(
            "review.replied",
            {
                "user_id": user.id,
                "channel_id": channel.id,
                "review_id": reply.review_id,
                "status": "posted",
                "replied_at": datetime.now(timezone.utc).isoformat(),
            },
            topic="review-events",
        )
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
        error=reply.error,
        created_at=reply.created_at.isoformat(),
    )


@router.post("/{channel_id}/reviews/generate", response_model=ReviewReplyResponse, status_code=status.HTTP_201_CREATED)
async def generate_reply_for_review(
    channel_id: str,
    body: ReviewReplyGenerate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Draft an AI reply for a review that has no reply row yet (inbox flow)."""
    channel = await _get_owned_channel(channel_id, user, db)
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
    if existing_reply is not None and existing_reply.status in ("pending_approval", "posted"):
        raise HTTPException(status_code=409, detail="A reply already exists for this review")
    if existing_reply is not None:
        # Dead draft (rejected/failed) — clear it so a fresh one can be made.
        await db.delete(existing_reply)
        await db.flush()

    from .review_reply import generate_review_reply

    custom_text = (body.custom_text or "").strip()
    if custom_text:
        # Merchant typed the reply themselves — skip the LLM entirely.
        reply_text = custom_text
    else:
        try:
            reply_text = await generate_review_reply(
                config, body.rating, body.review_text, body.reviewer_name, db
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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Edit a reply draft before publishing."""
    reply = await _get_owned_reply(channel_id, reply_id, user, db)
    if reply.status != "pending_approval":
        raise HTTPException(status_code=400, detail="Only pending replies can be edited")
    reply.reply_text = body.reply_text.strip()
    await db.commit()
    await db.refresh(reply)
    return _reply_response(reply)


@router.post("/{channel_id}/reviews/{reply_id}/regenerate", response_model=ReviewReplyResponse)
async def regenerate_reply(
    channel_id: str,
    reply_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Re-generate a pending reply with the channel's current model/tone/voice."""
    reply = await _get_owned_reply(channel_id, reply_id, user, db)
    if reply.status != "pending_approval":
        raise HTTPException(status_code=400, detail="Only pending replies can be regenerated")
    config = (
        await db.execute(select(AutoReplyConfig).where(AutoReplyConfig.channel_id == channel_id))
    ).scalar_one_or_none()
    if not config:
        config = AutoReplyConfig(channel_id=channel_id)
        db.add(config)

    from .review_reply import generate_review_reply

    try:
        reply.reply_text = await generate_review_reply(
            config, reply.rating, reply.review_text, reply.reviewer_name, db
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Reply generation failed: {e}")
    await db.commit()
    await db.refresh(reply)
    return _reply_response(reply)


@router.post("/{channel_id}/reviews/{reply_id}/retry", response_model=ReviewReplyResponse)
async def retry_failed_reply(
    channel_id: str,
    reply_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retry a failed reply: regenerate the text if generation failed, then
    return it to the approval queue with the error cleared."""
    reply = await _get_owned_reply(channel_id, reply_id, user, db)
    if reply.status != "failed":
        raise HTTPException(status_code=400, detail="Only failed replies can be retried")
    if not (reply.reply_text or "").strip():
        config = (
            await db.execute(
                select(AutoReplyConfig).where(AutoReplyConfig.channel_id == channel_id)
            )
        ).scalar_one_or_none()
        if not config:
            config = AutoReplyConfig(channel_id=channel_id)
            db.add(config)
        from .review_reply import generate_review_reply

        try:
            reply.reply_text = await generate_review_reply(
                config, reply.rating, reply.review_text, reply.reviewer_name, db
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Reply generation failed: {e}")
    reply.status = "pending_approval"
    reply.error = None
    await db.commit()
    await db.refresh(reply)
    return _reply_response(reply)


@router.delete("/{channel_id}/reviews/{reply_id}", response_model=ReviewReplyResponse)
async def reject_reply(
    channel_id: str,
    reply_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Discard a pending reply draft without posting anything to Google."""
    reply = await _get_owned_reply(channel_id, reply_id, user, db)
    if reply.status != "pending_approval":
        raise HTTPException(status_code=400, detail="Only pending replies can be rejected")
    reply.status = "rejected"
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

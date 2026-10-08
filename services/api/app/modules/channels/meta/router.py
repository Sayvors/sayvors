"""Meta connections API: connect, callback, assets, validate, disconnect."""
import logging
import re
import time

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ....config import settings
from ....core.deps import get_current_user, get_db
from ....modules.team.context import TenantContext, require_perm, tenant_id_of
from ...auth.rate_limit import rate_limit
from ...users.models import User
from . import oauth as _oauth
from . import service as _service
from .providers.base import MetaAPIError
from .schemas import (
    InstagramAudienceOut,
    InstagramDemographics,
    InstagramPerson,
    InstagramPostOut,
    InstagramPostsOut,
    InstagramProfileOut,
    MetaAssetListResponse,
    MetaAssetOut,
    MetaAssetSelect,
    MetaConnectionListResponse,
    MetaConnectionOut,
    MetaRegisterNumberRequest,
    MetaValidateResponse,
    MetaWhatsAppSession,
    WhatsAppProfileOut,
    WhatsAppProfileUpdate,
    WhatsAppUsageOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/meta", tags=["meta"])

_SAFE_NEXT = re.compile(r"/[A-Za-z0-9\-/_]*")


def _remember_pin(asset, pin: str | None) -> None:
    """Persist the tenant's 2-step PIN (encrypted) on the number asset.

    The PIN is per phone number in Meta's model, and re-registering is only
    allowed for 14 days — so it has to survive a page reload. Fernet at rest,
    same scheme as the access token. Never returned by any endpoint.
    """
    if not pin:
        return
    from .credentials import encrypt_credential

    meta = dict(getattr(asset, "asset_metadata", None) or {})
    meta["pin_encrypted"] = encrypt_credential(pin)
    asset.asset_metadata = meta


def discovered_has_number(discovered) -> bool:
    return any(getattr(d, "asset_type", "") == "phone_number" for d in discovered or [])


# Meta's whatsapp_business_profile vertical enum. Anything else is a 400 (#100).
WA_VERTICALS = frozenset({
    "OTHER", "AUTO", "BEAUTY", "APPAREL", "EDU", "ENTERTAIN", "EVENT_PLAN",
    "FINANCE", "GROCERY", "GOVT", "HOTEL", "HEALTH", "NONPROFIT",
    "PROF_SERVICES", "RETAIL", "TRAVEL", "RESTAURANT", "ALCOHOL",
    "ONLINE_GAMBLING", "PHYSICAL_GAMBLING", "OTC_DRUGS",
})
_VERTICAL_ALIASES = {
    "SERVICES": "PROF_SERVICES", "REAL_ESTATE": "OTHER", "REALTY": "OTHER",
    "MEDICAL": "HEALTH", "SCHOOL": "EDU", "AUTOMOTIVE": "AUTO",
    "RESTAURANTS": "RESTAURANT", "RETAILS": "RETAIL",
}


def _normalize_vertical(value: str) -> str:
    """Map legacy label-style values (\"Restaurant\") to Meta's enum."""
    v = value.strip().upper().replace(" ", "_").replace("-", "_")
    if v in WA_VERTICALS:
        return v
    if v in _VERTICAL_ALIASES:
        return _VERTICAL_ALIASES[v]
    raise HTTPException(
        status_code=400,
        detail=f"Invalid category '{value}' — allowed: {', '.join(sorted(WA_VERTICALS))}",
    )


def _persist_profile(asset, data: dict) -> str:
    """Store the profile snapshot on the number asset (DB copy).

    A NEW dict must be assigned — SQLAlchemy only detects JSON-column
    changes on reassignment. Merging keeps siblings like pin_encrypted.
    """
    from datetime import datetime, timezone

    synced_at = datetime.now(timezone.utc).isoformat()
    asset.asset_metadata = {
        **(asset.asset_metadata or {}),
        "business_profile": data,
        "business_profile_synced_at": synced_at,
    }
    return synced_at


def _profile_out(
    data: dict, synced_at: str | None = None, stale: bool = False
) -> WhatsAppProfileOut:
    return WhatsAppProfileOut(
        about=data.get("about"),
        address=data.get("address"),
        description=data.get("description"),
        email=data.get("email"),
        websites=data.get("websites") or [],
        vertical=data.get("vertical"),
        profile_picture_url=data.get("profile_picture_url"),
        hours=data.get("hours"),
        synced_at=synced_at,
        stale=stale,
    )


def _conn_out(c) -> MetaConnectionOut:
    return MetaConnectionOut(
        id=c.id,
        provider=c.provider,
        connection_type=c.connection_type,
        meta_business_id=c.meta_business_id,
        scopes=list(c.scopes or []),
        status=c.status,
        last_validated_at=c.last_validated_at.isoformat() if c.last_validated_at else None,
        last_successful_api_call_at=c.last_successful_api_call_at.isoformat()
        if c.last_successful_api_call_at
        else None,
        last_webhook_received_at=c.last_webhook_received_at.isoformat()
        if c.last_webhook_received_at
        else None,
        created_at=c.created_at.isoformat(),
    )


def _asset_out(a) -> MetaAssetOut:
    return MetaAssetOut(
        id=a.id,
        provider=a.provider,
        asset_type=a.asset_type,
        external_asset_id=a.external_asset_id,
        parent_asset_id=a.parent_asset_id,
        name=a.name,
        username=a.username,
        phone=a.phone,
        active=bool(a.active),
        status=a.status,
    )


@router.get("/connections", response_model=MetaConnectionListResponse)
async def list_connections(
    ctx: TenantContext = Depends(require_perm("channels.view")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await _service.list_connections(db, tenant_id_of(user))
    return MetaConnectionListResponse(connections=[_conn_out(c) for c in rows])


@router.post("/{provider}/connect")
async def start_connect(
    provider: str,
    request: Request,
    ctx: TenantContext = Depends(require_perm("channels.connect")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create an OAuth transaction; return the provider auth entry."""
    origin = _request_origin(request)
    try:
        return await _service.start_connect(
            db, tenant_id_of(user), provider, {"frontend_origin": origin} if origin else None
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Unknown Meta provider")
    except MetaAPIError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


def _frontend_base(next_path: str | None, origin: str | None = None) -> str:
    """Where the browser that started this flow should land after the OAuth.

    The tenant may browse the app from any origin that proxies the API
    (localhost in dev, a tunnel, the deployed domain) — FRONTEND_URL only
    names one of them, so the connect call records the origin it was made
    from and the callback returns the tenant to THAT origin.
    """
    base_url = (origin or settings.FRONTEND_URL).rstrip("/")
    base = f"{base_url}/dashboard/channels"
    if next_path and _SAFE_NEXT.fullmatch(next_path):
        base = f"{base_url}{next_path}"
    return base


def _request_origin(request: Request) -> str | None:
    """The web origin behind this request, when it looks sane.

    Same-origin POSTs carry Origin; proxied hops carry x-forwarded-host.
    Only a bare scheme://host is ever accepted — no path, query or fragment —
    so a crafted header cannot turn the OAuth return into a redirect
    anywhere but a site root (and only for the tenant's own transaction).
    """
    from urllib.parse import urlsplit

    candidate = request.headers.get("origin")
    if not candidate:
        forwarded_host = (request.headers.get("x-forwarded-host") or "").split(",")[0].strip()
        if forwarded_host:
            scheme = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip() or "https"
            candidate = f"{scheme}://{forwarded_host}"
    if not candidate:
        return None
    parts = urlsplit(candidate)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        return None
    return f"{parts.scheme}://{parts.netloc}"


_FB_SDK_URL = "https://connect.facebook.net/en_US/sdk.js"
# sdk.js is a 12KB bootstrap: it defines a stub window.FB and then loads
# this real 272KB bundle from connect.facebook.net. We proxy the bundle
# too (and rewrite the bootstrap's hardcoded URL to this proxy) so the
# whole SDK loads same-origin — no facebook.net fetch for the core SDK.
_FB_BUNDLE_URL = "https://connect.facebook.net/en_US/bundle/sdk.js/"
_FB_BUNDLE_URL_ESCAPED = _FB_BUNDLE_URL.replace("/", "\\/")
_FB_SDK_TTL_SECONDS = 3600
_sdk_cache: dict = {"body": None, "at": 0.0}
_bundle_cache: dict = {"body": None, "at": 0.0}


async def _fetch_cached_js(url: str, cache: dict) -> str | None:
    """Fetch public Meta JS into the in-memory cache; None on failure."""
    now = time.monotonic()
    if cache["body"] and now - cache["at"] < _FB_SDK_TTL_SECONDS:
        return cache["body"]
    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.get(url, headers={"User-Agent": "SayvorsMetaSDKProxy/1.0"})
        if resp.status_code != 200:
            raise ValueError(f"upstream status {resp.status_code}")
        cache.update(body=resp.text, at=now)
        return cache["body"]
    except Exception as e:
        logger.warning("Meta SDK proxy fetch failed: %s", type(e).__name__)
        return None


def _js_response(body: str | None) -> Response:
    if body is None:
        return Response(
            "/* Meta SDK temporarily unavailable */",
            media_type="application/javascript",
            status_code=200,
        )
    return Response(
        body,
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/connect-sdk")
async def meta_sdk(request: Request):
    """Same-origin proxy for the Meta JS SDK (ad-blocker mitigation).

    Blockers match the facebook.net domain AND common SDK filenames, so
    this route carries neither. The SDK is public static JS — no auth,
    no tenant data. Cached in memory for an hour; upstream failures
    return an inert stub (never secrets, never the error body) so the
    frontend falls into its retry messaging.

    The bundle URL is rewritten to /connect-sdk-bundle below so the
    browser never has to fetch facebook.net for the core SDK either.
    """
    body = await _fetch_cached_js(_FB_SDK_URL, _sdk_cache)
    if body is not None:
        # No trailing slash — the route is registered without one, and the
        # rewrite replaces the full escaped URL (including its trailing \/).
        #
        # The rewritten URL must be one the BROWSER can reach, not one this
        # server can reach. Behind a proxy (ngrok -> Next /api rewrite -> us)
        # every header points at the hop before us, so prefer the forwarded
        # origin the client actually used. Falling back to `request.url` yields
        # http://localhost:8000, which the tunnel page cannot load — the bundle
        # fails, fbAsyncInit never fires, and Facebook sign-in silently
        # disables itself.
        scheme = (
            request.headers.get("x-forwarded-proto")
            or request.url.scheme
        ).split(",")[0].strip()
        netloc = (
            request.headers.get("x-forwarded-host")
            or request.headers.get("host")
            or request.url.netloc
        ).split(",")[0].strip()
        # An https page can only load an https script, and a loopback API is
        # not reachable from a tunnel anyway — so a forwarded origin wins, but
        # a bare loopback host falls back to http rather than https (we serve no
        # TLS locally, so https://localhost:8000 would be refused).
        if netloc.startswith(("localhost", "127.0.0.1")):
            scheme = "http"
        proxy_base = f"{scheme}://{netloc}/api/v1/meta/connect-sdk-bundle"
        body = body.replace(
            _FB_BUNDLE_URL_ESCAPED, proxy_base.replace("/", "\\/")
        )
    return _js_response(body)


@router.get("/connect-sdk-bundle")
async def meta_sdk_bundle():
    """Same-origin proxy for the real Meta SDK bundle (see /connect-sdk)."""
    body = await _fetch_cached_js(_FB_BUNDLE_URL, _bundle_cache)
    return _js_response(body)


_META_ERROR_CODES = {
    "access_denied", "missing_code", "invalid_state", "token_exchange_failed",
    "unknown_provider", "account_blocked", "server_error",
}


def _safe_meta_error(error: str | None) -> str:
    """Echo only known error codes back to the frontend — never raw input
    (an attacker-crafted callback URL must not control the redirect query)."""
    return error if error in _META_ERROR_CODES else "oauth_error"


@router.get("/{provider}/callback")
async def oauth_callback(
    provider: str,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Provider redirect target (Facebook/Instagram Login flows)."""
    base = _frontend_base(None)
    if provider not in ("facebook", "instagram"):
        return RedirectResponse(f"{base}?meta_error=unknown_provider")
    if error:
        return RedirectResponse(f"{base}?meta_error={_safe_meta_error(error)}")

    txn = await _oauth.consume_transaction(db, state, provider)
    if txn is None and provider in ("facebook", "instagram"):
        # Both Login dialogs share one registered redirect URI (the facebook
        # callback), so an Instagram transaction arrives here with
        # provider="facebook". The transaction row — not the URL — owns the
        # provider; resolve it from the state instead of rejecting it.
        sibling = "instagram" if provider == "facebook" else "facebook"
        txn = await _oauth.consume_transaction(db, state, sibling)
        if txn is not None:
            provider = sibling
            logger.info(
                "Meta OAuth callback provider resolved from state: %s", provider
            )
    if txn is None:
        return RedirectResponse(f"{base}?meta_error=invalid_state")
    tenant_id = txn.tenant_id
    # Return the tenant to the origin their own connect call came from.
    base = _frontend_base(
        (txn.transaction_metadata or {}).get("next"),
        (txn.transaction_metadata or {}).get("frontend_origin"),
    )

    adapter = _service.get_adapter(provider)
    try:
        credentials = await adapter.exchange_code(
            code or "", settings.META_OAUTH_REDIRECT_URI
        )
    except MetaAPIError as e:
        logger.error("Meta OAuth exchange failed provider=%s: %s", provider, e.status_code)
        await _oauth.fail_transaction(db, txn.id)
        return RedirectResponse(f"{base}?meta_error=token_exchange_failed")

    if provider == "instagram":
        # IG messaging rides the parent Page's token, so the Facebook row
        # holds the working credential. The instagram row is the marker the
        # channels page reads — without it the IG card offers Connect forever.
        conn = await _service.store_connection(
            db, tenant_id, "facebook", credentials
        )
        await _service.store_connection(
            db,
            tenant_id,
            "instagram",
            {
                "access_token": credentials.get("access_token", ""),
                "connection_type": "via_facebook",
                "business_id": credentials.get("business_id"),
            },
            scopes=list(credentials.get("scopes", []) or []),
        )
        return RedirectResponse(
            f"{base}?meta_connected=facebook&next=instagram_select"
        )

    conn = await _service.store_connection(db, tenant_id, provider, credentials)
    try:
        discovered = await adapter.discover_assets(
            {"access_token": credentials.get("access_token", "")}
        )
        await _service.save_discovered_assets(db, tenant_id, provider, conn, discovered)
    except MetaAPIError as e:
        logger.warning("Meta asset discovery failed provider=%s: %s", provider, e.status_code)
        # Surface the Graph status to the tenant (no secrets) instead of a
        # silent success with zero assets.
        return RedirectResponse(
            f"{base}?meta_connected={provider}&discovery_error={e.status_code}"
        )
    return RedirectResponse(f"{base}?meta_connected={provider}")


@router.get("/whatsapp/smb-sync-status")
async def smb_sync_status(
    ctx: TenantContext = Depends(require_perm("channels.view")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Check SMB App Data sync status for a coexistence connection."""
    conn = await _service.get_connection(db, tenant_id_of(user), "whatsapp")
    if conn is None or conn.connection_type != "coexistence":
        raise HTTPException(status_code=404, detail="No coexistence connection")
    meta = conn.connection_metadata or {}
    return {
        "status": meta.get("smb_sync_status", "unknown"),
        "deadline": meta.get("smb_sync_deadline"),
    }


@router.get("/whatsapp/usage", response_model=WhatsAppUsageOut)
async def whatsapp_usage(
    ctx: TenantContext = Depends(require_perm("channels.view")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Sayvors messaging quota: outbound messages this calendar month against
    the plan's monthly limit. Deliberately NOT Meta's messaging tier — tenants
    see our quota, never Meta's."""
    from datetime import datetime, timezone

    from sqlalchemy import func, select

    from ..models import Channel, ChannelMessage

    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    # Outbound only: inbound customer messages are unbounded and must never
    # spend the quota. Failed sends count — the Graph call was attempted.
    used = (
        await db.execute(
            select(func.count())
            .select_from(ChannelMessage)
            .join(Channel, ChannelMessage.channel_id == Channel.id)
            .where(
                Channel.user_id == tenant_id_of(user),
                Channel.platform == "whatsapp",
                ChannelMessage.direction == "outbound",
                ChannelMessage.created_at >= month_start,
            )
        )
    ).scalar() or 0
    # DI-provided stub users carry no flushed column default.
    plan = getattr(user, "plan", None) or "free"
    monthly_limit = settings.PLAN_MESSAGE_LIMITS.get(
        plan, settings.PLAN_MESSAGE_LIMITS["free"]
    )
    return WhatsAppUsageOut(used_this_month=int(used), monthly_limit=monthly_limit, plan=plan)


@router.post("/whatsapp/session")
async def whatsapp_session(
    body: MetaWhatsAppSession,
    ctx: TenantContext = Depends(require_perm("channels.connect")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Complete WhatsApp Embedded Signup: session payload from FB.login."""
    txn = await _oauth.consume_transaction(db, body.state, "whatsapp")
    if txn is None:
        raise HTTPException(status_code=400, detail="Invalid or expired state")
    # The authenticated tenant MUST own the session row. State entropy alone
    # is strong, but this guarantees a cross-tenant state can never be used
    # (defense-in-depth for the tenant-owned connection model).
    if tenant_id_of(user) != txn.tenant_id:
        logger.warning(
            "Meta WhatsApp session rejected: authenticated tenant %s != txn tenant %s",
            user.id, txn.tenant_id,
        )
        raise HTTPException(
            status_code=403, detail="Session belongs to another tenant"
        )
    tenant_id = txn.tenant_id

    adapter = _service.get_adapter("whatsapp")
    credentials: dict = {
        "business_id": body.business_id,
        "waba_id": body.waba_id,
        "phone_number_id": body.phone_number_id,
    }
    is_coexistence = body.mode == "coexistence"
    if is_coexistence:
        credentials["connection_type"] = "coexistence"
    try:
        if body.code:
            exchanged = await adapter.exchange_code(body.code)
            credentials["access_token"] = exchanged.get("access_token", "")
        conn = await _service.store_connection(db, tenant_id, "whatsapp", credentials)
        discovered = await adapter.discover_assets(credentials)
        assets = await _service.save_discovered_assets(
            db, tenant_id, "whatsapp", conn, discovered
        )
        # Webhook subscription + number registration. These are best-effort —
        # a failure must not lose the connection the tenant just completed — but
        # the outcome is REPORTED, not swallowed: an unregistered number cannot
        # send, and Meta only allows registration for 14 days after signup.
        token = credentials.get("access_token", "")
        registered: list[str] = []
        failed: list[dict] = []
        if token:
            for asset in assets:
                try:
                    if asset.asset_type == "waba":
                        await adapter.subscribe_app(asset.external_asset_id, token)
                    elif asset.asset_type == "phone_number":
                        if not is_coexistence:
                            await adapter.register_number(
                                asset.external_asset_id, token, pin=body.pin
                            )
                            _remember_pin(asset, body.pin)
                        # In coexistence, the number is already registered
                        asset.status = "registered"
                        registered.append(asset.external_asset_id)
                except MetaAPIError as e:
                    logger.warning(
                        "WhatsApp post-connect step failed asset=%s: %s",
                        asset.external_asset_id, e.status_code,
                    )
                    failed.append({
                        "asset_id": asset.external_asset_id,
                        "asset_type": asset.asset_type,
                        "status": e.status_code,
                    })
            # In coexistence mode, trigger SMB App Data sync after webhook subscription
            if is_coexistence and token:
                from datetime import datetime, timedelta, timezone
                for asset in assets:
                    if asset.asset_type == "phone_number":
                        try:
                            await adapter.sync_smb_app_data(
                                asset.external_asset_id, token, "smb_app_state_sync"
                            )
                            await adapter.sync_smb_app_data(
                                asset.external_asset_id, token, "history"
                            )
                        except MetaAPIError as e:
                            logger.warning(
                                "WhatsApp SMB sync trigger failed phone=%s: %s",
                                asset.external_asset_id, e.status_code,
                            )
                        break  # first phone number only
                # Record the 24h deadline in connection_metadata
                conn.connection_metadata = {
                    **(conn.connection_metadata or {}),
                    "smb_sync_status": "triggered",
                    "smb_sync_deadline": (
                        datetime.now(timezone.utc) + timedelta(hours=24)
                    ).isoformat(),
                }
                db.add(conn)
            # Commit unconditionally: this persists the encrypted PIN and the
            # registered status set above. Skipping it on the happy path would
            # silently discard the PIN the tenant just supplied.
            await db.commit()
    except MetaAPIError as e:
        await _oauth.fail_transaction(db, txn.id)
        raise HTTPException(status_code=e.status_code, detail=str(e))

    needs_pin = (not is_coexistence) and (
        any(
            a["asset_type"] == "phone_number" and a["asset_id"] in
            {r["asset_id"] for r in failed}
            for a in failed
        ) or (
            bool(body.phone_number_id or discovered_has_number(discovered))
            and not body.pin
        )
    )
    return {
        "connected": True,
        "provider": "whatsapp",
        "assets_found": len(assets),
        "registered": registered,
        "registration_failed": failed,
        # The single most important signal for the frontend: the number is live
        # but cannot send until a PIN is supplied.
        "needs_pin": needs_pin,
    }


@router.post("/whatsapp/{phone_number_id}/register")
async def register_whatsapp_number(
    phone_number_id: str,
    body: MetaRegisterNumberRequest,
    ctx: TenantContext = Depends(require_perm("channels.edit")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Register (or re-register) a number with the tenant's 2-step PIN.

    Meta only accepts registration for 14 days after Embedded Signup, and a
    wrong PIN must be recoverable — so this exists as a first-class retry
    instead of forcing a full reconnect."""
    # The PIN is the only secret protecting registration — throttle guesses
    # at entry (even malformed bodies burn an attempt). Fail-closed default:
    # a Redis outage must not disable brute-force protection.
    if not settings.TESTING and not await rate_limit(
        f"wa:register:{user.id}:{phone_number_id}", 5, 600
    ):
        raise HTTPException(
            status_code=429, detail="Too many attempts — try again in a few minutes"
    )
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from .credentials import decrypt_connection_token
    from .models import MetaAsset
    from .providers.base import MetaAPIError as _MetaAPIError

    asset = (
        await db.execute(
            select(MetaAsset)
            .options(selectinload(MetaAsset.connection))
            .where(
                MetaAsset.tenant_id == tenant_id_of(user),
                MetaAsset.provider == "whatsapp",
                MetaAsset.asset_type == "phone_number",
                MetaAsset.external_asset_id == phone_number_id,
            )
        )
    ).scalar_one_or_none()
    if asset is None:
        raise HTTPException(status_code=404, detail="Number not found for this account")

    token = decrypt_connection_token(asset.connection) if asset.connection else None
    if not token:
        raise HTTPException(
            status_code=409, detail="Reconnect WhatsApp — the access token is missing"
        )

    adapter = _service.get_adapter("whatsapp")
    try:
        await adapter.register_number(phone_number_id, token, pin=body.pin)
    except _MetaAPIError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))

    _remember_pin(asset, body.pin)
    asset.status = "registered"
    await db.commit()
    return {"registered": True, "phone_number_id": phone_number_id}


@router.get("/whatsapp/{phone_number_id}/profile", response_model=WhatsAppProfileOut)
async def get_whatsapp_profile(
    phone_number_id: str,
    ctx: TenantContext = Depends(require_perm("channels.view")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch the live WhatsApp business profile from Meta (not cached)."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from .credentials import decrypt_connection_token
    from .models import MetaAsset
    from .providers.base import MetaAPIError as _MetaAPIError

    asset = (
        await db.execute(
            select(MetaAsset)
            .options(selectinload(MetaAsset.connection))
            .where(
                MetaAsset.tenant_id == tenant_id_of(user),
                MetaAsset.provider == "whatsapp",
                MetaAsset.asset_type == "phone_number",
                MetaAsset.external_asset_id == phone_number_id,
            )
        )
    ).scalar_one_or_none()
    if asset is None:
        raise HTTPException(status_code=404, detail="Number not found for this account")
    token = decrypt_connection_token(asset.connection) if asset.connection else None
    if not token:
        raise HTTPException(status_code=409, detail="Reconnect WhatsApp — the access token is missing")
    adapter = _service.get_adapter("whatsapp")
    stored_profile = (asset.asset_metadata or {}).get("business_profile") or {}
    try:
        data = await adapter.get_business_profile(phone_number_id, token)
    except _MetaAPIError as e:
        # Graph being unreachable is not a reason to blank the editor: fall
        # back to the persisted copy so the tenant still sees their profile
        # (flagged stale). 404/5xx only when there is nothing stored.
        if stored_profile:
            return _profile_out(
                stored_profile,
                (asset.asset_metadata or {}).get("business_profile_synced_at"),
                stale=True,
            )
        raise HTTPException(status_code=e.status_code, detail=str(e))
    # `hours` never comes back from Graph — keep the locally persisted copy.
    if stored_profile.get("hours"):
        data["hours"] = stored_profile["hours"]
    # An empty live read must never blank the editor (or wipe storage):
    # fall back to the last persisted copy.
    if not data and stored_profile:
        return _profile_out(
            stored_profile,
            (asset.asset_metadata or {}).get("business_profile_synced_at"),
        )
    synced_at = _persist_profile(asset, data)
    db.add(asset)
    await db.commit()
    return _profile_out(data, synced_at)


@router.patch("/whatsapp/{phone_number_id}/profile", response_model=WhatsAppProfileOut)
async def update_whatsapp_profile(
    phone_number_id: str,
    body: WhatsAppProfileUpdate,
    ctx: TenantContext = Depends(require_perm("channels.edit")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update allowlisted business profile fields on Meta."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from .credentials import decrypt_connection_token
    from .models import MetaAsset
    from .providers.base import MetaAPIError as _MetaAPIError

    # Convenience surface, not a brute-force target: fail-open on a Redis
    # blip so an outage never blocks profile editing.
    if not settings.TESTING and not await rate_limit(
        f"wa:profile:{user.id}:{phone_number_id}", 10, 60, fail_closed=False
    ):
        raise HTTPException(status_code=429, detail="Too many updates — slow down for a moment")

    asset = (
        await db.execute(
            select(MetaAsset)
            .options(selectinload(MetaAsset.connection))
            .where(
                MetaAsset.tenant_id == tenant_id_of(user),
                MetaAsset.provider == "whatsapp",
                MetaAsset.asset_type == "phone_number",
                MetaAsset.external_asset_id == phone_number_id,
            )
        )
    ).scalar_one_or_none()
    if asset is None:
        raise HTTPException(status_code=404, detail="Number not found for this account")
    token = decrypt_connection_token(asset.connection) if asset.connection else None
    if not token:
        raise HTTPException(status_code=409, detail="Reconnect WhatsApp — the access token is missing")
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    hours = fields.pop("hours", None)  # not a Graph param — persist locally
    if "vertical" in fields and fields["vertical"]:
        fields["vertical"] = _normalize_vertical(fields["vertical"])
    if "websites" in fields:
        fields["websites"] = [w if w.startswith("http") else f"https://{w}" for w in fields["websites"]][:2]
    adapter = _service.get_adapter("whatsapp")
    try:
        data = await adapter.set_business_profile(phone_number_id, token, fields)
    except _MetaAPIError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    stored_profile = (asset.asset_metadata or {}).get("business_profile") or {}
    # Graph acknowledged the write but the re-read came back empty — keep the
    # stored copy and overlay what we just saved instead of blanking it.
    if not data:
        data = {**stored_profile, **fields}
    data["hours"] = hours if hours is not None else stored_profile.get("hours")
    synced_at = _persist_profile(asset, data)
    db.add(asset)
    await db.commit()
    return _profile_out(data, synced_at)


@router.get("/instagram/{ig_id}/profile", response_model=InstagramProfileOut)
async def get_instagram_profile(
    ig_id: str,
    ctx: TenantContext = Depends(require_perm("channels.view")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch the live Instagram business profile from Meta (not cached).

    Read-only by Meta's design: the IG User reference states updating is not
    supported, so there is no sibling PATCH. A failed Graph read falls back to
    the persisted snapshot (flagged stale) rather than blanking the page.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from .credentials import decrypt_connection_token
    from .models import MetaAsset
    from .providers.base import MetaAPIError as _MetaAPIError

    asset = (
        await db.execute(
            select(MetaAsset)
            .options(selectinload(MetaAsset.connection))
            .where(
                MetaAsset.tenant_id == tenant_id_of(user),
                MetaAsset.provider == "instagram",
                MetaAsset.asset_type == "ig_account",
                MetaAsset.external_asset_id == ig_id,
            )
        )
    ).scalar_one_or_none()
    if asset is None:
        raise HTTPException(status_code=404, detail="Instagram account not found for this workspace")

    meta = asset.asset_metadata or {}
    stored = meta.get("business_profile") or {}
    page_name = meta.get("parent_page_name")

    def _out(data: dict, synced_at: str | None, stale: bool) -> InstagramProfileOut:
        return InstagramProfileOut(
            username=data.get("username"),
            name=data.get("name"),
            biography=data.get("biography"),
            website=data.get("website"),
            profile_picture_url=data.get("profile_picture_url"),
            followers_count=int(data.get("followers_count") or 0),
            follows_count=int(data.get("follows_count") or 0),
            media_count=int(data.get("media_count") or 0),
            status=asset.status,
            eligibility=meta.get("eligibility"),
            parent_page_id=asset.parent_asset_id,
            parent_page_name=page_name,
            synced_at=synced_at,
            stale=stale,
        )

    token = decrypt_connection_token(asset.connection) if asset.connection else None
    if not token:
        if stored:
            return _out(stored, meta.get("business_profile_synced_at"), stale=True)
        raise HTTPException(
            status_code=409, detail="Reconnect Instagram — the access token is missing"
        )

    adapter = _service.get_adapter("instagram")
    try:
        data = await adapter.get_business_profile(ig_id, token)
    except _MetaAPIError as e:
        if stored:
            return _out(stored, meta.get("business_profile_synced_at"), stale=True)
        raise HTTPException(status_code=e.status_code, detail=str(e))

    # An empty live read must never blank the page or wipe the snapshot.
    if not data or not data.get("username"):
        return _out(stored or data, meta.get("business_profile_synced_at"), stale=True)

    synced_at = _persist_profile(asset, data)
    db.add(asset)
    await db.commit()
    return _out(data, synced_at, stale=False)


@router.get("/instagram/{ig_id}/audience", response_model=InstagramAudienceOut)
async def get_instagram_audience(
    ig_id: str,
    ctx: TenantContext = Depends(require_perm("channels.view")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """People who engaged with the account, plus aggregate follower demographics.

    There is no follower roster anywhere in this response on purpose: Meta does
    not expose follower/following lists. Commenters are read live from Graph
    (our webhooks parse comment events but the consumer drops them), and DM
    contacts come from our own inbox, so both sides hold real usernames and
    therefore real profile links.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from ..models import ContactProfile
    from .credentials import decrypt_connection_token
    from .models import MetaAsset
    from .providers.base import MetaAPIError as _MetaAPIError

    tenant = tenant_id_of(user)
    asset = (
        await db.execute(
            select(MetaAsset)
            # The token lives on the connection; lazy-loading it here would
            # touch the DB outside the async context.
            .options(selectinload(MetaAsset.connection))
            .where(
                MetaAsset.tenant_id == tenant,
                MetaAsset.provider == "instagram",
                MetaAsset.asset_type == "ig_account",
                MetaAsset.external_asset_id == ig_id,
            )
        )
    ).scalar_one_or_none()
    if asset is None:
        raise HTTPException(
            status_code=404, detail="Instagram account not found for this workspace"
        )

    people: list[InstagramPerson] = []

    # 1. DM contacts — people who actually wrote to us.
    contacts = (
        await db.execute(
            select(ContactProfile)
            .where(
                ContactProfile.tenant_id == tenant,
                ContactProfile.platform == "instagram",
            )
            .order_by(ContactProfile.profile_fetched_at.desc().nullslast())
        )
    ).scalars().all()
    for c in contacts:
        people.append(
            InstagramPerson(
                source="dm",
                ig_id=c.contact_id,
                username=c.username,
                name=c.name or c.username,
                occurred_at=c.profile_fetched_at.isoformat() if c.profile_fetched_at else None,
                profile_url=f"https://instagram.com/{c.username}" if c.username else None,
            )
        )

    token = decrypt_connection_token(asset.connection) if asset.connection else None
    comments_unavailable = None
    demographics = InstagramDemographics()

    if not token:
        comments_unavailable = "Reconnect Instagram to read comments and insights."
    else:
        adapter = _service.get_adapter("instagram")
        try:
            people.extend(
                InstagramPerson(**c)
                for c in await adapter.get_recent_commenters(ig_id, token)
            )
        except _MetaAPIError as e:
            comments_unavailable = str(e)

        try:
            demographics = InstagramDemographics(
                available=True, **await adapter.get_follower_demographics(ig_id, token)
            )
        except _MetaAPIError as e:
            # Common and expected: missing insights scope, or under 100
            # followers. Say so instead of rendering an empty panel.
            demographics = InstagramDemographics(
                available=False, reason=_demographics_reason(e)
            )

    people.sort(key=lambda p: p.occurred_at or "", reverse=True)
    return InstagramAudienceOut(
        people=people, demographics=demographics, comments_unavailable=comments_unavailable
    )


def _demographics_reason(exc: MetaAPIError) -> str:
    detail = str(exc).lower()
    if "metric" in detail or "permission" in detail or "(#10" in detail:
        return (
            "Instagram does not share follower demographics for this account "
            "yet — it needs the insights permission and at least 100 followers."
        )
    return f"Could not read follower demographics: {exc}"


@router.get("/instagram/{ig_id}/posts", response_model=InstagramPostsOut)
async def get_instagram_posts(
    ig_id: str,
    ctx: TenantContext = Depends(require_perm("channels.view")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Your own recent Instagram posts with their recent comments.

    An account with no posts returns an empty list - that is the truthful
    answer, not an error. `unavailable` is only set when the read itself could
    not be made (missing token, revoked scope).
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from .credentials import decrypt_connection_token
    from .models import MetaAsset

    asset = (
        await db.execute(
            select(MetaAsset)
            .options(selectinload(MetaAsset.connection))
            .where(
                MetaAsset.tenant_id == tenant_id_of(user),
                MetaAsset.provider == "instagram",
                MetaAsset.asset_type == "ig_account",
                MetaAsset.external_asset_id == ig_id,
            )
        )
    ).scalar_one_or_none()
    if asset is None:
        raise HTTPException(
            status_code=404, detail="Instagram account not found for this workspace"
        )
    token = decrypt_connection_token(asset.connection) if asset.connection else None
    if not token:
        return InstagramPostsOut(
            unavailable="Reconnect Instagram to see your posts."
        )
    adapter = _service.get_adapter("instagram")
    return InstagramPostsOut(posts=[InstagramPostOut(**p) for p in await adapter.get_recent_posts(ig_id, token)])


@router.post("/whatsapp/{phone_number_id}/profile-photo")
async def upload_profile_photo(
    phone_number_id: str,
    file: UploadFile = File(...),
    ctx: TenantContext = Depends(require_perm("channels.edit")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a profile photo and set it on the WhatsApp business profile."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from .credentials import decrypt_connection_token
    from .models import MetaAsset
    from .providers.base import MetaAPIError as _MetaAPIError

    asset = (
        await db.execute(
            select(MetaAsset)
            .options(selectinload(MetaAsset.connection))
            .where(
                MetaAsset.tenant_id == tenant_id_of(user),
                MetaAsset.provider == "whatsapp",
                MetaAsset.asset_type == "phone_number",
                MetaAsset.external_asset_id == phone_number_id,
            )
        )
    ).scalar_one_or_none()
    if asset is None:
        raise HTTPException(status_code=404, detail="Number not found for this account")
    token = decrypt_connection_token(asset.connection) if asset.connection else None
    if not token:
        raise HTTPException(status_code=409, detail="Reconnect WhatsApp — the access token is missing")

    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Photo must be under 5 MB")
    mime = file.content_type or "image/jpeg"
    if mime not in ("image/jpeg", "image/png"):
        raise HTTPException(status_code=400, detail="Only JPG or PNG images are allowed")

    # Resumable upload sessions are created against the owning WABA.
    waba_id = None
    if asset.parent_asset_id:
        parent = await db.get(MetaAsset, asset.parent_asset_id)
        waba_id = parent.external_asset_id if parent else None

    adapter = _service.get_adapter("whatsapp")
    try:
        await adapter.set_profile_photo(
            phone_number_id,
            token,
            content,
            mime,
            waba_id=waba_id,
            file_name=file.filename or "profile.jpg",
        )
    except _MetaAPIError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))

    stored_profile = (asset.asset_metadata or {}).get("business_profile") or {}
    try:
        data = await adapter.get_business_profile(phone_number_id, token)
    except _MetaAPIError:
        data = {}
    if not data:
        data = stored_profile
    if stored_profile.get("hours"):
        data.setdefault("hours", stored_profile["hours"])
    synced_at = _persist_profile(asset, data)
    db.add(asset)
    await db.commit()
    return _profile_out(data, synced_at)


@router.post("/instagram/discover", response_model=MetaAssetListResponse)
async def discover_instagram(
    ctx: TenantContext = Depends(require_perm("channels.connect")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Discover IG accounts linked to the tenant's active Pages."""
    from .providers.base import MetaAPIError as _MetaAPIError

    try:
        rows = await _service.discover_instagram(db, tenant_id_of(user))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except _MetaAPIError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    return MetaAssetListResponse(assets=[_asset_out(a) for a in rows])


@router.get("/{provider}/assets", response_model=MetaAssetListResponse)
async def list_assets(
    provider: str,
    ctx: TenantContext = Depends(require_perm("channels.view")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if provider not in ("whatsapp", "facebook", "instagram"):
        raise HTTPException(status_code=404, detail="Unknown Meta provider")
    rows = await _service.list_assets(db, tenant_id_of(user), provider)
    return MetaAssetListResponse(assets=[_asset_out(a) for a in rows])


@router.post("/{provider}/assets/select", response_model=MetaAssetListResponse)
async def select_assets(
    provider: str,
    body: MetaAssetSelect,
    ctx: TenantContext = Depends(require_perm("channels.edit")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if provider not in ("whatsapp", "facebook", "instagram"):
        raise HTTPException(status_code=404, detail="Unknown Meta provider")
    try:
        rows = await _service.select_assets(db, tenant_id_of(user), provider, body.asset_ids)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return MetaAssetListResponse(assets=[_asset_out(a) for a in rows])


@router.post("/{provider}/validate", response_model=MetaValidateResponse)
async def validate_connection(
    provider: str,
    ctx: TenantContext = Depends(require_perm("channels.view")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if provider not in ("whatsapp", "facebook", "instagram"):
        raise HTTPException(status_code=404, detail="Unknown Meta provider")
    try:
        status, detail = await _service.validate_connection(db, tenant_id_of(user), provider)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    from datetime import datetime, timezone

    conn = await _service.get_connection(db, tenant_id_of(user), provider)
    return MetaValidateResponse(
        connection_id=conn.id if conn else "",
        status=status,
        detail=detail,
        checked_at=datetime.now(timezone.utc).isoformat(),
    )


@router.delete("/{provider}/disconnect")
async def disconnect(
    provider: str,
    revoke: bool = Query(False),
    delete_data: bool = Query(
        False,
        description="Permanently delete this provider's channels, messages and assets",
    ),
    ctx: TenantContext = Depends(require_perm("channels.remove")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if provider not in ("whatsapp", "facebook", "instagram"):
        raise HTTPException(status_code=404, detail="Unknown Meta provider")
    result = await _service.disconnect(
        db, tenant_id_of(user), provider, revoke=revoke, delete_data=delete_data
    )
    return {"disconnected": True, "provider": provider, **result}

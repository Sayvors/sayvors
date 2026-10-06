"""Meta connections API: connect, callback, assets, validate, disconnect."""
import logging
import re
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ....config import settings
from ....core.deps import get_current_user, get_db
from ...users.models import User
from . import oauth as _oauth
from . import service as _service
from .providers.base import MetaAPIError
from .schemas import (
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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await _service.list_connections(db, user.id)
    return MetaConnectionListResponse(connections=[_conn_out(c) for c in rows])


@router.post("/{provider}/connect")
async def start_connect(
    provider: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create an OAuth transaction; return the provider auth entry."""
    origin = _request_origin(request)
    try:
        return await _service.start_connect(
            db, user.id, provider, {"frontend_origin": origin} if origin else None
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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Check SMB App Data sync status for a coexistence connection."""
    conn = await _service.get_connection(db, user.id, "whatsapp")
    if conn is None or conn.connection_type != "coexistence":
        raise HTTPException(status_code=404, detail="No coexistence connection")
    meta = conn.connection_metadata or {}
    return {
        "status": meta.get("smb_sync_status", "unknown"),
        "deadline": meta.get("smb_sync_deadline"),
    }


@router.post("/whatsapp/session")
async def whatsapp_session(
    body: MetaWhatsAppSession,
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
    if user.id != txn.tenant_id:
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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Register (or re-register) a number with the tenant's 2-step PIN.

    Meta only accepts registration for 14 days after Embedded Signup, and a
    wrong PIN must be recoverable — so this exists as a first-class retry
    instead of forcing a full reconnect."""
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
                MetaAsset.tenant_id == user.id,
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
                MetaAsset.tenant_id == user.id,
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
    try:
        data = await adapter.get_business_profile(phone_number_id, token)
    except _MetaAPIError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    return WhatsAppProfileOut(
        about=data.get("about"),
        address=data.get("address"),
        description=data.get("description"),
        email=data.get("email"),
        websites=data.get("websites") or [],
        vertical=data.get("vertical"),
        profile_picture_url=data.get("profile_picture_url"),
    )


@router.patch("/whatsapp/{phone_number_id}/profile", response_model=WhatsAppProfileOut)
async def update_whatsapp_profile(
    phone_number_id: str,
    body: WhatsAppProfileUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update allowlisted business profile fields on Meta."""
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
                MetaAsset.tenant_id == user.id,
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
    if "websites" in fields:
        fields["websites"] = [w if w.startswith("http") else f"https://{w}" for w in fields["websites"]][:2]
    adapter = _service.get_adapter("whatsapp")
    try:
        data = await adapter.set_business_profile(phone_number_id, token, fields)
    except _MetaAPIError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    return WhatsAppProfileOut(
        about=data.get("about"),
        address=data.get("address"),
        description=data.get("description"),
        email=data.get("email"),
        websites=data.get("websites") or [],
        vertical=data.get("vertical"),
        profile_picture_url=data.get("profile_picture_url"),
    )


@router.post("/instagram/discover", response_model=MetaAssetListResponse)
async def discover_instagram(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Discover IG accounts linked to the tenant's active Pages."""
    from .providers.base import MetaAPIError as _MetaAPIError

    try:
        rows = await _service.discover_instagram(db, user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except _MetaAPIError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    return MetaAssetListResponse(assets=[_asset_out(a) for a in rows])


@router.get("/{provider}/assets", response_model=MetaAssetListResponse)
async def list_assets(
    provider: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if provider not in ("whatsapp", "facebook", "instagram"):
        raise HTTPException(status_code=404, detail="Unknown Meta provider")
    rows = await _service.list_assets(db, user.id, provider)
    return MetaAssetListResponse(assets=[_asset_out(a) for a in rows])


@router.post("/{provider}/assets/select", response_model=MetaAssetListResponse)
async def select_assets(
    provider: str,
    body: MetaAssetSelect,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if provider not in ("whatsapp", "facebook", "instagram"):
        raise HTTPException(status_code=404, detail="Unknown Meta provider")
    try:
        rows = await _service.select_assets(db, user.id, provider, body.asset_ids)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return MetaAssetListResponse(assets=[_asset_out(a) for a in rows])


@router.post("/{provider}/validate", response_model=MetaValidateResponse)
async def validate_connection(
    provider: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if provider not in ("whatsapp", "facebook", "instagram"):
        raise HTTPException(status_code=404, detail="Unknown Meta provider")
    try:
        status, detail = await _service.validate_connection(db, user.id, provider)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    from datetime import datetime, timezone

    conn = await _service.get_connection(db, user.id, provider)
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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if provider not in ("whatsapp", "facebook", "instagram"):
        raise HTTPException(status_code=404, detail="Unknown Meta provider")
    result = await _service.disconnect(
        db, user.id, provider, revoke=revoke, delete_data=delete_data
    )
    return {"disconnected": True, "provider": provider, **result}

"""MetaIntegrationService: tenant connections, assets, health.

One generic service for WhatsApp / Facebook / Instagram. Routers call this;
provider differences live in providers/*. All queries are tenant-scoped.
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import oauth as _oauth
from .credentials import decrypt_connection_token, encrypt_credential
from .models import MetaAsset, MetaConnection
from .providers.base import DiscoveredAsset, MetaAPIError, MetaProviderAdapter
from .providers.facebook import FacebookAdapter
from .providers.instagram import InstagramAdapter
from .providers.whatsapp import WhatsAppAdapter

logger = logging.getLogger(__name__)

ADAPTERS: dict[str, MetaProviderAdapter] = {
    "whatsapp": WhatsAppAdapter(),
    "facebook": FacebookAdapter(),
    "instagram": InstagramAdapter(),
}

# Asset types that become Channel rows (inbox / auto-reply UI surface).
MESSAGING_ASSETS: dict[str, str] = {
    "phone_number": "whatsapp",
    "page": "facebook",
    "ig_account": "instagram",
}


def get_adapter(provider: str) -> MetaProviderAdapter:
    try:
        return ADAPTERS[provider]
    except KeyError:
        raise ValueError(f"Unknown Meta provider: {provider}")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Connections ──────────────────────────────────────────


async def list_connections(db: AsyncSession, tenant_id: str) -> list[MetaConnection]:
    rows = (
        await db.execute(
            select(MetaConnection)
            .where(MetaConnection.tenant_id == tenant_id)
            .order_by(MetaConnection.created_at)
        )
    ).scalars().all()
    return list(rows)


async def get_connection(
    db: AsyncSession, tenant_id: str, provider: str
) -> MetaConnection | None:
    return (
        await db.execute(
            select(MetaConnection).where(
                MetaConnection.tenant_id == tenant_id,
                MetaConnection.provider == provider,
            )
        )
    ).scalar_one_or_none()


async def start_connect(
    db: AsyncSession, tenant_id: str, provider: str, metadata: dict | None = None
) -> dict:
    """Create an OAuth transaction and return the provider auth entry."""
    adapter = get_adapter(provider)
    state, _txn = await _oauth.create_transaction(db, tenant_id, provider, metadata)
    try:
        entry = adapter.build_auth_entry(state)
    except MetaAPIError:
        await _oauth.fail_transaction(db, _txn.id)
        raise
    logger.info("Meta connect started provider=%s tenant=%s", provider, tenant_id)
    return {"provider": provider, **entry}


async def store_connection(
    db: AsyncSession,
    tenant_id: str,
    provider: str,
    credentials: dict,
    scopes: list[str] | None = None,
) -> MetaConnection:
    """Upsert the (tenant, provider) connection with encrypted token."""
    token = credentials.get("access_token", "")
    conn = await get_connection(db, tenant_id, provider)
    if conn is None:
        conn = MetaConnection(id=str(uuid.uuid4()), tenant_id=tenant_id, provider=provider)
    conn.connection_type = credentials.get("connection_type", "oauth")
    conn.meta_business_id = credentials.get("business_id")
    if token:
        conn.access_token_encrypted = encrypt_credential(token)
    conn.scopes = scopes or credentials.get("scopes", []) or []
    conn.status = "active"
    conn.connection_metadata = {
        k: v for k, v in credentials.items() if k != "access_token"
    }
    db.add(conn)
    await db.commit()
    await db.refresh(conn)
    logger.info("Meta connection stored provider=%s tenant=%s", provider, tenant_id)
    return conn


# ── Assets ───────────────────────────────────────────────


async def list_assets(
    db: AsyncSession, tenant_id: str, provider: str | None = None
) -> list[MetaAsset]:
    stmt = select(MetaAsset).where(MetaAsset.tenant_id == tenant_id)
    if provider:
        stmt = stmt.where(MetaAsset.provider == provider)
    return list((await db.execute(stmt.order_by(MetaAsset.created_at))).scalars().all())


async def save_discovered_assets(
    db: AsyncSession,
    tenant_id: str,
    provider: str,
    connection: MetaConnection,
    discovered: list[DiscoveredAsset],
) -> list[MetaAsset]:
    """Upsert discovered assets (inactive until the tenant selects them)."""
    out: list[MetaAsset] = []
    # Resolve parent links by external id within this batch + DB.
    existing = {
        a.external_asset_id: a.id
        for a in await list_assets(db, tenant_id, provider)
    }
    for d in discovered:
        row = (
            await db.execute(
                select(MetaAsset).where(
                    MetaAsset.tenant_id == tenant_id,
                    MetaAsset.provider == provider,
                    MetaAsset.external_asset_id == d.external_asset_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = MetaAsset(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                connection_id=connection.id,
                provider=provider,
                asset_type=d.asset_type,
                external_asset_id=d.external_asset_id,
            )
        row.connection_id = connection.id
        row.name = d.name or row.name
        row.username = d.username or row.username
        row.phone = d.phone or row.phone
        row.asset_metadata = {**(row.asset_metadata or {}), **(d.extra or {})}
        if d.parent_external_id:
            parent_id = existing.get(d.parent_external_id)
            if parent_id is None:
                parent = (
                    await db.execute(
                        select(MetaAsset).where(
                            MetaAsset.tenant_id == tenant_id,
                            MetaAsset.external_asset_id == d.parent_external_id,
                        )
                    )
                ).scalar_one_or_none()
                parent_id = parent.id if parent else None
            row.parent_asset_id = parent_id
        db.add(row)
        await db.flush()
        existing[d.external_asset_id] = row.id
        out.append(row)
    await db.commit()
    logger.info(
        "Meta assets discovered provider=%s tenant=%s count=%d",
        provider, tenant_id, len(out),
    )
    return out


async def select_assets(
    db: AsyncSession, tenant_id: str, provider: str, asset_ids: list[str]
) -> list[MetaAsset]:
    """Activate tenant-chosen assets; create Channel rows for messaging ones."""
    from ..models import Channel

    rows = (
        await db.execute(
            select(MetaAsset).where(
                MetaAsset.tenant_id == tenant_id,
                MetaAsset.provider == provider,
                MetaAsset.id.in_(asset_ids),
            )
        )
    ).scalars().all()
    found = {a.id for a in rows}
    missing = set(asset_ids) - found
    if missing:
        raise ValueError("Unknown assets for this tenant")

    activated: list[MetaAsset] = []
    for asset in rows:
        asset.active = True
        asset.status = "connected"
        db.add(asset)
        platform = MESSAGING_ASSETS.get(asset.asset_type)
        if platform:
            label = asset.name or asset.username or asset.phone or asset.external_asset_id
            existing_channel = (
                await db.execute(
                    select(Channel).where(
                        Channel.user_id == tenant_id,
                        Channel.platform == platform,
                        Channel.platform_user_id == asset.external_asset_id,
                    )
                )
            ).scalar_one_or_none()
            if existing_channel is None:
                db.add(
                    Channel(
                        id=str(uuid.uuid4()),
                        user_id=tenant_id,
                        platform=platform,
                        platform_user_id=asset.external_asset_id,
                        display_name=label,
                        status="active",
                    )
                )
        activated.append(asset)
    await db.commit()
    logger.info(
        "Meta assets selected provider=%s tenant=%s count=%d",
        provider, tenant_id, len(activated),
    )
    return activated


# ── Instagram discovery (via selected Facebook Pages) ───


async def discover_instagram(db: AsyncSession, tenant_id: str) -> list[MetaAsset]:
    """Discover IG business accounts linked to the tenant's active Pages."""
    fb_conn = await get_connection(db, tenant_id, "facebook")
    if fb_conn is None:
        raise ValueError("Connect Facebook first")
    ig_conn = await get_connection(db, tenant_id, "instagram")
    if ig_conn is None:
        ig_conn = await store_connection(
            db, tenant_id, "instagram",
            {
                "access_token": decrypt_connection_token(fb_conn) or "",
                "connection_type": "via_facebook",
                "business_id": fb_conn.meta_business_id,
            },
            scopes=list(fb_conn.scopes or []),
        )
    pages = (
        await db.execute(
            select(MetaAsset).where(
                MetaAsset.tenant_id == tenant_id,
                MetaAsset.provider == "facebook",
                MetaAsset.asset_type == "page",
                MetaAsset.active == True,  # noqa: E712
            )
        )
    ).scalars().all()
    adapter = get_adapter("instagram")
    discovered = await adapter.discover_assets(
        {},
        pages=[
            {
                "external_asset_id": p.external_asset_id,
                "page_access_token": (p.asset_metadata or {}).get("page_access_token", ""),
                "name": p.name,
            }
            for p in pages
        ],
    )
    assets = await save_discovered_assets(db, tenant_id, "instagram", ig_conn, discovered)
    # Eligibility check at connect time (professional + reachable).
    token = decrypt_connection_token(ig_conn) or ""
    for asset in assets:
        eligible, detail = await adapter.check_eligibility(asset.external_asset_id, token)
        asset.status = "connected" if eligible else "ineligible"
        asset.asset_metadata = {**(asset.asset_metadata or {}), "eligibility": detail}
        db.add(asset)
    await db.commit()
    return assets


# ── Health / disconnect ──────────────────────────────────

async def validate_connection(
    db: AsyncSession, tenant_id: str, provider: str
) -> tuple[str, str]:
    """Re-check a connection against the provider. Returns (status, detail)."""
    conn = await get_connection(db, tenant_id, provider)
    if conn is None:
        raise ValueError("No connection for this tenant")
    adapter = get_adapter(provider)
    token = decrypt_connection_token(conn)
    ok, detail = await adapter.validate_connection(
        conn, {"access_token": token or ""}
    )
    conn.status = "active" if ok else "needs_reauth"
    conn.last_validated_at = _utcnow()
    if ok:
        conn.last_successful_api_call_at = _utcnow()
    db.add(conn)
    await db.commit()
    logger.info(
        "Meta validate provider=%s tenant=%s ok=%s", provider, tenant_id, ok
    )
    return conn.status, detail


async def disconnect(
    db: AsyncSession, tenant_id: str, provider: str, revoke: bool = False
) -> None:
    """Mark connection revoked; deactivate assets. Best-effort provider revoke."""
    conn = await get_connection(db, tenant_id, provider)
    if conn is None:
        return
    if revoke:
        adapter = get_adapter(provider)
        revoke_fn = getattr(adapter, "revoke", None)
        if revoke_fn is not None:
            try:
                await revoke_fn(conn, {"access_token": decrypt_connection_token(conn) or ""})
            except Exception as e:
                logger.warning("Meta revoke failed provider=%s: %s", provider, e)
    conn.status = "revoked"
    conn.access_token_encrypted = None
    db.add(conn)
    assets = await list_assets(db, tenant_id, provider)
    for asset in assets:
        asset.active = False
        asset.status = "disconnected"
        db.add(asset)
    await db.commit()
    logger.info("Meta disconnect provider=%s tenant=%s", provider, tenant_id)

"""OAuth transaction lifecycle: server-side state, tenant binding, one-time use.

The state value handed to the frontend is random; only its sha256 is stored.
Callbacks present the state; the tenant comes from the transaction row —
never from a callback parameter.
"""
import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import MetaOAuthTransaction

logger = logging.getLogger(__name__)

STATE_TTL_MINUTES = 10
VALID_PROVIDERS = ("whatsapp", "facebook", "instagram")


def _hash_state(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


async def create_transaction(
    db: AsyncSession, tenant_id: str, provider: str, metadata: dict | None = None
) -> tuple[str, MetaOAuthTransaction]:
    """Create a pending transaction. Returns (raw_state, row)."""
    if provider not in VALID_PROVIDERS:
        raise ValueError(f"Unknown Meta provider: {provider}")
    state = secrets.token_urlsafe(32)
    row = MetaOAuthTransaction(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        provider=provider,
        state_hash=_hash_state(state),
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=STATE_TTL_MINUTES),
        transaction_metadata=metadata or {},
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    logger.info("Meta OAuth started provider=%s tenant=%s", provider, tenant_id)
    return state, row


async def consume_transaction(
    db: AsyncSession, state: str | None, provider: str
) -> MetaOAuthTransaction | None:
    """Claim a pending, unexpired transaction (one-time use).

    Returns the row with status flipped to completed, or None when the
    state is invalid, expired, already used, or for another provider.
    SELECT-first (no UPDATE..RETURNING) so SQLite/Postgres behave alike.
    """
    if not state:
        return None
    row = (
        await db.execute(
            select(MetaOAuthTransaction).where(
                MetaOAuthTransaction.state_hash == _hash_state(state),
                MetaOAuthTransaction.provider == provider,
                MetaOAuthTransaction.status == "pending",
            )
        )
    ).scalar_one_or_none()
    if row is None:
        logger.warning("Meta OAuth state rejected provider=%s", provider)
        return None
    expires_at = row.expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        # SQLite drops tzinfo — interpret stored UTC as UTC.
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if expires_at is not None and expires_at <= now:
        row.status = "expired"
        db.add(row)
        await db.commit()
        logger.warning("Meta OAuth state expired provider=%s", provider)
        return None
    row.status = "completed"
    row.completed_at = now
    db.add(row)
    await db.commit()
    await db.refresh(row)
    logger.info(
        "Meta OAuth completed provider=%s tenant=%s", provider, row.tenant_id
    )
    return row


async def fail_transaction(db: AsyncSession, transaction_id: str) -> None:
    await db.execute(
        update(MetaOAuthTransaction)
        .where(MetaOAuthTransaction.id == transaction_id)
        .values(status="failed", completed_at=datetime.now(timezone.utc))
    )
    await db.commit()

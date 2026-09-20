"""Shared scheduling primitives — one copy, used by every worker.

Posts, media, and Localith syncs all coordinate across uvicorn workers
with the same Postgres advisory-lock pattern and the same retry-then-park
policy. This module is the single implementation; feature modules keep
thin wrappers (same names) so existing callers and tests don't churn.

Rules:
- Publishing-type work is NOT idempotent: same key never runs twice at
  once (blocking take for user clicks, try-take + SKIP for loops).
- Different keys proceed in parallel (per-branch / per-post namespaces).
- Off-Postgres (sqlite tests, single-process dev) there is nothing to
  coordinate with: takes succeed trivially — and crucially as HELD, never
  as held-by-other (which would make loops skip all work).
"""
import logging
from datetime import timedelta

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Retry-then-park: failed scheduled work retries with backoff this many
# times, then parks as failed for manual retry.
MAX_PUBLISH_ATTEMPTS = 5
RETRY_BASE_SECONDS = 300
RETRY_MAX_SECONDS = 7200


def is_postgres(db: AsyncSession) -> bool:
    """Advisory locks exist only on Postgres."""
    try:
        bind = db.get_bind() if hasattr(db, "get_bind") else db.bind  # type: ignore[union-attr]
        return bind is not None and bind.dialect.name == "postgresql"
    except Exception:
        return False


def _stmt(blocking: bool, namespace: str, key: str | int):
    fn = "pg_advisory_lock" if blocking else "pg_try_advisory_lock"
    if isinstance(key, int) and not namespace:
        # Legacy global key form: SELECT pg_advisory_lock(64821410933).
        return sa_text(f"SELECT {fn}({key})")
    return sa_text(f"SELECT {fn}(hashtext('{namespace}' || :key))").bindparams(
        key=str(key)
    )


async def take_lock(db: AsyncSession, blocking: bool, namespace: str, key: str | int) -> bool:
    """Take the lock for key. Blocking waits; try-take returns False when
    another worker holds it (caller must SKIP, not wait). Trivially held
    off-Postgres. Only call try-take on a clean session: a miss ends with
    a rollback."""
    if not is_postgres(db):
        return True
    try:
        if blocking:
            await db.execute(_stmt(True, namespace, key))
            return True
        row = (await db.execute(_stmt(False, namespace, key))).scalar()
        if row:
            return True
        try:
            await db.rollback()
        except Exception:
            pass
        return False
    except Exception as e:
        logger.debug("Advisory lock unavailable, proceeding unlocked: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass
        return False


async def release_lock(db: AsyncSession, namespace: str, key: str | int) -> None:
    try:
        if isinstance(key, int) and not namespace:
            await db.execute(sa_text(f"SELECT pg_advisory_unlock({key})"))
            return
        await db.execute(
            sa_text(
                f"SELECT pg_advisory_unlock(hashtext('{namespace}' || :key))"
            ).bindparams(key=str(key))
        )
    except Exception:
        pass


def retry_delay(attempts: int, base: int = RETRY_BASE_SECONDS, cap: int = RETRY_MAX_SECONDS) -> timedelta:
    """Backoff after N consecutive failures: base, 2x, 4x … capped."""
    seconds = min(base * (2 ** max(0, attempts - 1)), cap)
    return timedelta(seconds=seconds)


def provider_post_id(response: object) -> str | None:
    """Provider's object id, when it returns one (reserved for future
    remote deletion: per-tenant native Google or a Localith delete)."""
    if not isinstance(response, dict):
        return None
    for key in ("id", "postId", "post_id", "mediaId", "media_id"):
        value = response.get(key)
        if value:
            return str(value)
    for value in response.values():
        if isinstance(value, dict):
            nested = provider_post_id(value)
            if nested:
                return nested
    return None

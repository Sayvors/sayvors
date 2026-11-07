"""Tenant lifecycle operations for the platform admin console.

Three destructive-adjacent actions live here, separate from the read-only
admin service so their guards are reviewable in one place:

* ``export_tenant`` — a complete JSON snapshot of every tenant-scoped table,
  taken before a delete and safe to hand to the customer.
* ``purge_tenant`` — permanent removal of a workspace and all of its rows.
* suspension is a pair of column writes, but the guard lives here too.

Scoping is derived from the ORM metadata instead of a hand-written table list:
a new tenant-owned table is covered automatically, and a table without any
tenant/user/channel column is never touched. System tables (operators, audit
log, alembic version) are always excluded.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import Base

logger = logging.getLogger(__name__)

# Never exported or purged through a tenant scope.
_SYSTEM_TABLES = {"platform_operators", "admin_audit_logs", "alembic_version"}

# Columns that must never appear in an export. Hashes and provider secrets are
# not customer data, and shipping them in a downloadable file is a leak.
_SECRET_COLUMN_MARKERS = (
    "password_hash",
    "key_encrypted",
    "secret",
    "token_hash",
    "encrypted",
)


def _is_secret_column(name: str) -> bool:
    lowered = name.lower()
    return any(marker in lowered for marker in _SECRET_COLUMN_MARKERS)


def _serialize(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value


async def _tenant_user_ids(db: AsyncSession, tenant_id: str) -> list[str]:
    """Owner + every employee attached to this workspace."""
    from ..users.models import User

    rows = (
        await db.execute(select(User.id).where(User.tenant_id == tenant_id))
    ).scalars().all()
    return sorted({tenant_id, *rows})


async def _tenant_channel_ids(db: AsyncSession, tenant_id: str) -> list[str]:
    from ..channels.models import Channel

    return list(
        (await db.execute(select(Channel.id).where(Channel.user_id == tenant_id)))
        .scalars()
        .all()
    )


def _scope_clause(table, tenant_id: str, user_ids: list[str], channel_ids: list[str]):
    """The WHERE clause that selects this table's rows for a tenant, or None.

    Precedence matters: `tenant_id` is the authoritative workspace marker,
    then direct owners (`user_id`), then channel children.
    """
    if table.name in _SYSTEM_TABLES:
        return None
    if table.name == "users":
        return table.c.id.in_(user_ids)
    if "tenant_id" in table.c:
        return table.c.tenant_id == tenant_id
    if "user_id" in table.c:
        return table.c.user_id.in_(user_ids)
    if "channel_id" in table.c and channel_ids:
        return table.c.channel_id.in_(channel_ids)
    return None


async def export_tenant(db: AsyncSession, tenant_id: str) -> dict:
    """Every tenant-scoped row as plain JSON-ready data."""
    from ..users.models import User

    user = await db.get(User, tenant_id)
    if user is None:
        raise ValueError("Tenant not found")
    user_ids = await _tenant_user_ids(db, tenant_id)
    channel_ids = await _tenant_channel_ids(db, tenant_id)

    tables: dict[str, list[dict]] = {}
    counts: dict[str, int] = {}
    for table in Base.metadata.sorted_tables:
        clause = _scope_clause(table, tenant_id, user_ids, channel_ids)
        if clause is None:
            continue
        rows = (await db.execute(select(table).where(clause))).all()
        if not rows:
            continue
        exported: list[dict] = []
        for row in rows:
            record = {}
            for key, value in row._mapping.items():
                if _is_secret_column(str(key)):
                    continue
                record[str(key)] = _serialize(value)
            exported.append(record)
        tables[table.name] = exported
        counts[table.name] = len(exported)

    return {
        "export_version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "tenant": {
            "id": user.id,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "business_name": user.business_name,
            "plan": user.plan,
            "created_at": _serialize(user.created_at),
        },
        "counts": counts,
        "tables": tables,
    }


async def purge_tenant(db: AsyncSession, tenant_id: str) -> dict:
    """Permanently delete the workspace and every tenant-owned row.

    Deletion follows reverse dependency order (children first) and runs in one
    transaction: a partial purge would leave an account that can neither log
    in nor be recreated. The caller must have verified the confirmation text.
    """
    from ..users.models import User

    user = await db.get(User, tenant_id)
    if user is None:
        raise ValueError("Tenant not found")
    user_ids = await _tenant_user_ids(db, tenant_id)
    channel_ids = await _tenant_channel_ids(db, tenant_id)

    # Storage keys are collected before the rows disappear; the objects are
    # removed best-effort afterwards so a bucket outage cannot abort the purge.
    storage_keys: list[str] = []
    for table in Base.metadata.sorted_tables:
        if table.name in _SYSTEM_TABLES:
            continue
        key_columns = [
            column.name
            for column in table.c
            if column.name.endswith("storage_key") or column.name == "file_key"
        ]
        if not key_columns:
            continue
        clause = _scope_clause(table, tenant_id, user_ids, channel_ids)
        if clause is None:
            continue
        for column_name in key_columns:
            values = (
                await db.execute(select(table.c[column_name]).where(clause))
            ).scalars().all()
            storage_keys.extend(str(value) for value in values if value)

    deleted: dict[str, int] = {}
    for table in reversed(Base.metadata.sorted_tables):
        clause = _scope_clause(table, tenant_id, user_ids, channel_ids)
        if clause is None:
            continue
        result = await db.execute(delete(table).where(clause))
        if result.rowcount:
            deleted[table.name] = int(result.rowcount)

    # EventOutbox has no tenant column by design (it predates tenancy); its
    # payload carries tenant_id. Sweep it explicitly so a purge leaves no
    # events that would later try to publish for a deleted workspace.
    if "event_outbox" in Base.metadata.tables:
        from ..outbox.models import EventOutbox

        rows = (await db.execute(select(EventOutbox))).scalars().all()
        removed = 0
        for row in rows:
            payload = row.payload if isinstance(row.payload, dict) else {}
            if payload.get("tenant_id") == tenant_id:
                await db.delete(row)
                removed += 1
        if removed:
            deleted["event_outbox"] = removed

    # Employees share the owner's tenant_id; their user rows are covered by
    # the `users` clause above (id IN user_ids), so no extra delete is needed.
    await db.commit()

    # Redis memory/chat profile is derived state; clear it so a recreated
    # tenant id could never inherit the previous owner's notes.
    try:
        from ..assistant.memory import forget_profile

        await forget_profile(tenant_id)
    except Exception as e:  # pragma: no cover - best effort
        logger.warning("Purge could not clear assistant profile tenant=%s: %s", tenant_id[:8], e)

    if storage_keys:
        try:
            from ...core.storage import delete_media

            for key in storage_keys:
                try:
                    delete_media(tenant_id, key)
                except Exception as e:  # pragma: no cover - best effort
                    logger.warning("Purge storage delete failed key=%s: %s", key[:40], e)
        except Exception as e:  # pragma: no cover - best effort
            logger.warning("Purge storage unavailable for tenant=%s: %s", tenant_id[:8], e)

    logger.warning(
        "Tenant purged tenant=%s tables=%d rows=%d",
        tenant_id,
        len(deleted),
        sum(deleted.values()),
    )
    return {"deleted": deleted, "total_rows": sum(deleted.values())}

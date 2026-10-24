"""Rebuild the denormalized ``channel_threads`` summary from its source.

The inbox reads ``channel_threads`` in one query; the event listener keeps it
current on every message insert. That listener is deliberately best-effort —
a summary failure must never drop the customer message that triggered it — so
a lock timeout or a bug can leave a row stale. This script is the repair
path: it recomputes each thread from ``channel_messages`` and writes the
correction.

Default is a dry run that reports drift, like ``scripts/dedupe_channels.py``.
Nothing is written unless ``--apply`` is passed. Recomputing a correct row is
a no-op, so the script is safe to re-run.

Usage (from services/api, venv active):
    python scripts/rebuild_channel_threads.py                    # report only
    python scripts/rebuild_channel_threads.py --apply
    python scripts/rebuild_channel_threads.py --apply --tenant-id <id>
    python scripts/rebuild_channel_threads.py --apply --limit 500

The key scan is bounded by ``--limit`` (default 5,000) and ordered by most
recent activity, so a large tenant can be repaired in passes. The per-thread
recompute uses the ``(channel_id, contact_phone_hash, created_at)`` index.
"""
import argparse
import asyncio
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import async_session  # noqa: E402

logger = logging.getLogger("rebuild_channel_threads")

DEFAULT_LIMIT = 5000
UNKNOWN_HASH = "__unknown__"

# One thread key + its newest message. Window functions keep this to a single
# pass over the thread's messages instead of a correlated subquery per field.
_THREAD_SQL = text(
    """
    WITH msgs AS (
        SELECT
            m.*,
            COALESCE(m.contact_phone_hash, :unknown) AS thread_hash
        FROM channel_messages m
        WHERE m.channel_id = :channel_id
          AND COALESCE(m.contact_phone_hash, :unknown) = :phone_hash
    ),
    ranked AS (
        SELECT *, ROW_NUMBER() OVER (ORDER BY created_at DESC, id DESC) AS rn
        FROM msgs
    ),
    last_out AS (
        SELECT MAX(created_at) AS at FROM msgs WHERE direction = 'outbound'
    )
    SELECT
        (SELECT COUNT(*) FROM msgs) AS total_count,
        (SELECT contact_phone FROM ranked
            WHERE contact_phone IS NOT NULL ORDER BY rn LIMIT 1) AS contact_phone,
        (SELECT contact_name FROM ranked
            WHERE contact_name IS NOT NULL ORDER BY rn LIMIT 1) AS contact_name,
        (SELECT category FROM ranked
            WHERE category IS NOT NULL ORDER BY rn LIMIT 1) AS category,
        (SELECT priority FROM ranked
            WHERE priority IS NOT NULL ORDER BY rn LIMIT 1) AS priority,
        r.direction AS last_direction,
        r.content AS last_message_preview,
        r.created_at AS last_message_at,
        CASE
            WHEN :phone_hash = :unknown THEN 0
            WHEN (SELECT at FROM last_out) IS NULL THEN (SELECT COUNT(*) FROM msgs)
            ELSE (
                SELECT COUNT(*) FROM msgs
                WHERE direction = 'inbound'
                  AND created_at > (SELECT at FROM last_out)
            )
        END AS unread_count
    FROM ranked r
    WHERE r.rn = 1
    """
)

_UPSERT_SQL = text(
    """
    INSERT INTO channel_threads (
        id, channel_id, contact_phone, contact_phone_hash, contact_name,
        last_message_at, last_direction, last_message_preview,
        total_count, unread_count, category, priority,
        created_at, updated_at
    ) VALUES (
        :id, :channel_id, :contact_phone, :phone_hash, :contact_name,
        :last_message_at, :last_direction, :last_message_preview,
        :total_count, :unread_count, :category, :priority,
        :now, :now
    )
    ON CONFLICT (channel_id, contact_phone_hash) DO UPDATE SET
        contact_phone = EXCLUDED.contact_phone,
        contact_name = EXCLUDED.contact_name,
        last_message_at = EXCLUDED.last_message_at,
        last_direction = EXCLUDED.last_direction,
        last_message_preview = EXCLUDED.last_message_preview,
        total_count = EXCLUDED.total_count,
        unread_count = EXCLUDED.unread_count,
        category = EXCLUDED.category,
        priority = EXCLUDED.priority,
        updated_at = EXCLUDED.updated_at
    """
)

_SELECT_EXISTING = text(
    """
    SELECT id, contact_phone, contact_name, last_message_at, last_direction,
           last_message_preview, total_count, unread_count, category, priority
    FROM channel_threads
    WHERE channel_id = :channel_id AND contact_phone_hash = :phone_hash
    """
)


def _drift(existing, row) -> bool:
    """True when the stored summary differs from the recomputed one."""
    if existing is None:
        return True
    fields = (
        "contact_phone",
        "contact_name",
        "last_message_at",
        "last_direction",
        "last_message_preview",
        "total_count",
        "unread_count",
        "category",
        "priority",
    )
    for field in fields:
        if existing[field] != row[field]:
            return True
    return False


async def _keys(db, tenant_id: str | None, limit: int):
    rows = (
        await db.execute(
            text(
                """
                SELECT m.channel_id,
                       COALESCE(m.contact_phone_hash, :unknown) AS phone_hash,
                       MAX(m.created_at) AS last_at
                FROM channel_messages m
                JOIN channels c ON c.id = m.channel_id
                WHERE (CAST(:tenant_id AS TEXT) IS NULL OR c.user_id = :tenant_id)
                GROUP BY m.channel_id, COALESCE(m.contact_phone_hash, :unknown)
                ORDER BY MAX(m.created_at) DESC
                LIMIT :limit
                """
            ),
            {"tenant_id": tenant_id, "unknown": UNKNOWN_HASH, "limit": limit},
        )
    ).all()
    return rows


async def rebuild(tenant_id: str | None, limit: int, apply: bool) -> dict:
    stats = {"scanned": 0, "missing": 0, "drifted": 0, "written": 0, "samples": []}
    async with async_session() as db:
        keys = await _keys(db, tenant_id, limit)
        for key in keys:
            stats["scanned"] += 1
            row = (
                await db.execute(
                    _THREAD_SQL,
                    {
                        "channel_id": key.channel_id,
                        "phone_hash": key.phone_hash,
                        "unknown": UNKNOWN_HASH,
                    },
                )
            ).mappings().one()
            existing = (
                await db.execute(
                    _SELECT_EXISTING,
                    {"channel_id": key.channel_id, "phone_hash": key.phone_hash},
                )
            ).mappings().one_or_none()

            if not _drift(existing, row):
                continue
            if existing is None:
                stats["missing"] += 1
            else:
                stats["drifted"] += 1
            if len(stats["samples"]) < 10:
                stats["samples"].append(
                    f"{key.channel_id}/{key.phone_hash}: "
                    f"stored total={existing['total_count'] if existing else 'missing'} "
                    f"unread={existing['unread_count'] if existing else '-'} -> "
                    f"total={row['total_count']} unread={row['unread_count']}"
                )

            if apply:
                await db.execute(
                    _UPSERT_SQL,
                    {
                        "id": existing["id"] if existing else str(uuid.uuid4()),
                        "channel_id": key.channel_id,
                        "phone_hash": key.phone_hash,
                        "contact_phone": row["contact_phone"],
                        "contact_name": row["contact_name"],
                        "last_message_at": row["last_message_at"],
                        "last_direction": row["last_direction"],
                        "last_message_preview": row["last_message_preview"],
                        "total_count": row["total_count"],
                        "unread_count": row["unread_count"],
                        "category": row["category"],
                        "priority": row["priority"],
                        "now": datetime.now(timezone.utc),
                    },
                )
                stats["written"] += 1
        if apply:
            await db.commit()
        else:
            await db.rollback()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write corrections")
    parser.add_argument("--tenant-id", default=None, help="limit to one tenant")
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"max thread keys to scan (default {DEFAULT_LIMIT})",
    )
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be at least 1")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    stats = asyncio.run(rebuild(args.tenant_id, args.limit, args.apply))

    print(f"scanned:  {stats['scanned']}")
    print(f"missing:  {stats['missing']}")
    print(f"drifted:  {stats['drifted']}")
    print(f"written:  {stats['written']}" if args.apply else "written:  0 (dry run)")
    for sample in stats["samples"]:
        print(f"  {sample}")
    if not args.apply and (stats["missing"] or stats["drifted"]):
        print("\nDry run only. Re-run with --apply to write the corrections.")


if __name__ == "__main__":
    main()

"""One-time channel twin cleanup (safe to re-run; default is dry-run).

Finds google_reviews channels sharing one location identity
(user_id, platform, listing_key) and merges each group into its oldest row,
re-pointing every child table. Normally unneeded — the c4d5e6f7a8b9
migration already merged on deploy and the unique index blocks new twins —
but useful to AUDIT counts or to clean tenants created while the migration
had not run yet.

Usage (from services/api, venv active):
    python scripts/dedupe_channels.py                 # dry-run report only
    python scripts/dedupe_channels.py --apply         # actually merge
    python scripts/dedupe_channels.py --apply --user <user-id>
    python scripts/dedupe_channels.py --backfill-only # just fill missing listing_key values
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import async_session  # noqa: E402
from app.modules.channels.models import Channel  # noqa: E402

CHILD_TABLES: tuple[tuple[str, bool], ...] = (
    ("channel_messages", False),
    ("review_replies", False),
    ("review_insights", False),
    ("channel_services", False),
    ("auto_reply_configs", True),
    ("channel_verifications", True),
)


def _key_of(channel: Channel) -> str | None:
    if channel.listing_key:
        return channel.listing_key
    try:
        meta = json.loads(channel.metadata_json or "{}")
    except (ValueError, TypeError):
        return None
    if not isinstance(meta, dict):
        return None
    key = meta.get("listing_id") or meta.get("location_id")
    return str(key) if key else None


async def main() -> int:
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--apply", action="store_true", help="merge for real (default: report only)")
    args.add_argument("--user", default=None, help="limit to one user_id")
    args.add_argument("--backfill-only", action="store_true", help="only fill missing listing_key values")
    ns = args.parse_args()

    from sqlalchemy import text as _text

    async with async_session() as db:
        q = select(Channel).where(Channel.platform == "google_reviews")
        if ns.user:
            q = q.where(Channel.user_id == ns.user)
        channels = list((await db.execute(q.order_by(Channel.created_at, Channel.id))).scalars().all())

        # 1. Backfill missing keys (harmless when the migration already ran).
        backfilled = 0
        for ch in channels:
            if not ch.listing_key:
                key = _key_of(ch)
                if key:
                    ch.listing_key = key
                    backfilled += 1
        if backfilled:
            if ns.apply or ns.backfill_only:
                await db.commit()
                print(f"backfilled listing_key on {backfilled} channel(s)")
            else:
                await db.rollback()
                print(f"would backfill listing_key on {backfilled} channel(s) (dry-run)")

        if ns.backfill_only:
            return 0

        # 2. Group by identity.
        groups: dict[tuple[str, str, str], list[Channel]] = {}
        for ch in channels:
            key = ch.listing_key or _key_of(ch)
            if not key:
                continue
            groups.setdefault((ch.user_id, ch.platform, key), []).append(ch)
        twins = {k: v for k, v in groups.items() if len(v) > 1}
        if not twins:
            print("no duplicate channels found")
            return 0

        for (user_id, _platform, key), rows in twins.items():
            rows.sort(key=lambda c: (c.created_at, c.id))
            print(f"user={user_id} key={key}: keeping {rows[0].id} "
                  f"({rows[0].display_name}), merging {[r.id for r in rows[1:]]})")

        if not ns.apply:
            print(f"dry-run: {sum(len(v) - 1 for v in twins.values())} row(s) would be merged. Re-run with --apply.")
            return 0

        # 3. Merge.
        merged = 0
        for (_user_id, _platform, _key), rows in twins.items():
            rows.sort(key=lambda c: (c.created_at, c.id))
            survivor, dupes = rows[0], rows[1:]
            for dupe in dupes:
                for table, unique_per_channel in CHILD_TABLES:
                    if unique_per_channel:
                        has_own = (
                            await db.execute(
                                _text(f"SELECT 1 FROM {table} WHERE channel_id = :s LIMIT 1"),
                                {"s": survivor.id},
                            )
                        ).first()
                        if has_own:
                            await db.execute(
                                _text(f"DELETE FROM {table} WHERE channel_id = :d"),
                                {"d": dupe.id},
                            )
                            continue
                    await db.execute(
                        _text(f"UPDATE {table} SET channel_id = :s WHERE channel_id = :d"),
                        {"s": survivor.id, "d": dupe.id},
                    )
                await db.delete(dupe)
                merged += 1
        await db.commit()
        print(f"merged {merged} duplicate channel row(s)")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

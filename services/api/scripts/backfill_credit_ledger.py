"""Cut existing tenants over to the durable AI-credit ledger (safe to re-run).

The migration adds the ledger columns; it deliberately does not move balances.
This script writes one ``balance_resync`` opening row per tenant and sets
``users.ai_credit_cents`` to the legacy computed balance (grants minus metered
spend). The row is keyed ``ledger-opening:<tenant>``, so a second run is a
no-op.

Default is a dry-run report, like ``scripts/dedupe_channels.py``: nothing is
written unless ``--apply`` is passed.

Usage (from services/api, venv active):
    python scripts/backfill_credit_ledger.py                     # report only
    python scripts/backfill_credit_ledger.py --apply             # write openings
    python scripts/backfill_credit_ledger.py --apply --tenant-id <id>
    python scripts/backfill_credit_ledger.py --apply --limit 500
    python scripts/backfill_credit_ledger.py --apply --force     # retention gap
    python scripts/backfill_credit_ledger.py --apply --no-sync-redis

Run the dry run before applying. A tenant whose spend window predates usage
retention is reported as unreliable; ``--force`` is required to accept its
upper-bound balance.
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import async_session  # noqa: E402
from app.modules.billing.budget import sync_balance  # noqa: E402
from app.modules.billing.ledger import (  # noqa: E402
    OPENING_KEY_PREFIX,
    UnsafeLedgerBootstrap,
    ensure_ledger_initialized,
)
from app.modules.billing.models import BillingEvent  # noqa: E402
from app.modules.billing.wallet import compute_balance  # noqa: E402
from app.modules.users.models import User  # noqa: E402

logger = logging.getLogger("backfill_credit_ledger")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the opening rows (without it, this is a report only)",
    )
    parser.add_argument(
        "--tenant-id",
        default=None,
        help="only process one tenant",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="stop after this many tenants (0 = no limit)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="apply an unreliable upper bound whose spend predates retention",
    )
    parser.add_argument(
        "--no-sync-redis",
        action="store_true",
        help="do not overwrite the Redis mirror after committing",
    )
    return parser.parse_args()


async def _tenant_ids(tenant_id: str | None, limit: int) -> list[str]:
    query = select(User.id).order_by(User.created_at, User.id)
    if tenant_id:
        query = query.where(User.id == tenant_id)
    if limit:
        query = query.limit(limit)
    async with async_session() as db:
        return list((await db.execute(query)).scalars().all())


async def _opening_exists(db, tenant_id: str) -> bool:
    row = (
        await db.execute(
            select(BillingEvent.id).where(
                BillingEvent.tenant_id == tenant_id,
                BillingEvent.idempotency_key == f"{OPENING_KEY_PREFIX}{tenant_id}",
            )
        )
    ).scalar_one_or_none()
    return row is not None


async def _report_one(tenant_id: str) -> dict:
    async with async_session() as db:
        if await _opening_exists(db, tenant_id):
            return {"tenant_id": tenant_id, "state": "initialized"}
        preview = await compute_balance(tenant_id, db)
        return {"tenant_id": tenant_id, "state": "pending", **preview}


async def _apply_one(tenant_id: str, *, force: bool, sync_redis: bool) -> dict:
    async with async_session() as db:
        if await _opening_exists(db, tenant_id):
            return {"tenant_id": tenant_id, "state": "initialized"}
        try:
            balance = await ensure_ledger_initialized(
                tenant_id,
                db,
                allow_unreliable=False,
                force=force,
            )
            await db.commit()
        except UnsafeLedgerBootstrap as e:
            await db.rollback()
            return {
                "tenant_id": tenant_id,
                "state": "skipped_unreliable",
                "warning": str(e),
            }
        except Exception as e:
            await db.rollback()
            logger.exception("Credit-ledger backfill failed for %s", tenant_id)
            return {"tenant_id": tenant_id, "state": "error", "error": str(e)}

    synced = None
    if sync_redis:
        synced = await sync_balance(tenant_id, balance)
    return {"tenant_id": tenant_id, "state": "opened", "balance_cents": balance, "redis_synced": synced}


def _print_report(row: dict) -> None:
    state = row["state"]
    if state == "initialized":
        print(f"  {row['tenant_id']:38s} already initialized")
        return
    if state == "pending":
        reliability = "ok" if row.get("reliable") else "UNRELIABLE"
        print(
            f"  {row['tenant_id']:38s} {row['balance_cents']:>8}¢ "
            f"{reliability:10s} spend={row['spent_cents']}¢ calls={row['calls']}"
        )
        if row.get("warning"):
            print(f"    ! {row['warning']}")
        return
    if state == "opened":
        print(
            f"  {row['tenant_id']:38s} opened at {row['balance_cents']}¢ "
            f"(redis_synced={row.get('redis_synced')})"
        )
        return
    print(f"  {row['tenant_id']:38s} {state}: {row.get('warning') or row.get('error')}")


async def main() -> int:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    ids = await _tenant_ids(args.tenant_id, args.limit)
    if args.tenant_id and not ids:
        print(f"Tenant not found: {args.tenant_id}")
        return 1
    if not ids:
        print("No tenants found.")
        return 0

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"credit ledger backfill — {mode}, {len(ids)} tenant(s)")
    print(f"opening key prefix : {OPENING_KEY_PREFIX}")
    print()

    opened = skipped = errors = initialized = unreliable = 0
    for tenant_id in ids:
        if args.apply:
            row = await _apply_one(
                tenant_id, force=args.force, sync_redis=not args.no_sync_redis
            )
        else:
            row = await _report_one(tenant_id)
        _print_report(row)

        if row["state"] == "opened":
            opened += 1
        elif row["state"] == "initialized":
            initialized += 1
        elif row["state"] == "skipped_unreliable":
            skipped += 1
        elif row["state"] == "error":
            errors += 1
        elif row["state"] == "pending" and not row.get("reliable"):
            unreliable += 1

    print()
    print(
        f"summary: opened={opened} already_initialized={initialized} "
        f"skipped_unreliable={skipped} unreliable_preview={unreliable} "
        f"errors={errors}"
    )
    if not args.apply:
        print("Dry run. Re-run with --apply to write the opening rows.")
        if unreliable:
            print(
                f"{unreliable} tenant(s) have a retention gap; review them and "
                "use --force only after checking the preview."
            )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

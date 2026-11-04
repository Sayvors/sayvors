"""Grant the one-time free-trial AI credit to existing tenants.

New signups get the credit inside the signup transaction. Accounts created
before that path shipped (including the current staging tenant) still sit at
zero and fail every AI call. This script is the idempotent backfill.

Dry run by default:

    python -m scripts.backfill_trial_credits

Apply:

    python -m scripts.backfill_trial_credits --apply
"""
import argparse
import asyncio
import sys
from pathlib import Path

_API_DIR = Path(__file__).resolve().parents[1]
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from sqlalchemy import func, select

from app.config import settings
from app.database import async_session
from app.modules.billing.models import BillingEvent, Plan, TenantSubscription
from app.modules.billing.service import grant_trial_credit
from app.modules.users.models import User

PAID_SLUGS = {"starter", "pro", "growth", "enterprise"}


async def main(apply: bool, email: str | None = None) -> None:
    async with async_session() as db:
        stmt = select(User).where(
            User.plan.in_(("free", "free-trial")),
            User.ai_credit_cents == 0,
        )
        if email:
            stmt = stmt.where(func.lower(User.email) == email.strip().lower())
        users = (await db.execute(stmt)).scalars().all()

        granted = skipped = 0
        for user in users:
            trial_exists = (
                await db.execute(
                    select(BillingEvent.id).where(
                        BillingEvent.tenant_id == user.id,
                        BillingEvent.idempotency_key == f"trial:{user.id}",
                    )
                )
            ).scalar_one_or_none()
            if trial_exists is not None:
                skipped += 1
                continue

            sub = (
                await db.execute(
                    select(TenantSubscription).where(
                        TenantSubscription.tenant_id == user.id
                    )
                )
            ).scalar_one_or_none()
            if sub is not None:
                plan = await db.get(Plan, sub.plan_id)
                if plan is not None and plan.slug in PAID_SLUGS:
                    skipped += 1
                    continue

            print(f"{'grant' if apply else 'would grant'}: {user.email} ({user.id})")
            if apply:
                try:
                    await grant_trial_credit(user, db)
                    await db.commit()
                    granted += 1
                except Exception as exc:  # noqa: BLE001
                    await db.rollback()
                    print(f"  failed: {type(exc).__name__}: {exc}")
                    skipped += 1
            else:
                granted += 1

    amount = settings.TRIAL_CREDIT_CENTS / 100
    verb = "granted" if apply else "would grant"
    print(
        f"{verb} ${amount:.2f} to {granted} tenant(s); skipped {skipped} "
        f"(already granted or on a paid plan)."
    )
    if not apply:
        print("Dry run only. Re-run with --apply to write the grants.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the grants. Without this flag the script only reports.",
    )
    parser.add_argument(
        "--email",
        default=None,
        help="Only grant this tenant email (useful for a controlled staging test).",
    )
    args = parser.parse_args()
    asyncio.run(main(args.apply, args.email))

"""Backfill plan subscriptions for tenants that predate the plans tables.

Idempotent: only inserts for tenants that have no subscription row.
Assigns the 'free-trial' plan by default (admin can re-grant later).
"""

import asyncio
import sys
import uuid
from pathlib import Path

_API_DIR = Path(__file__).resolve().parents[1]
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.modules.billing.models import Plan, TenantSubscription
from app.modules.users.models import User


async def main() -> None:
    async with async_session() as db:
        plan = (
            await db.execute(select(Plan).where(Plan.slug == "free-trial"))
        ).scalar_one_or_none()
        if plan is None:
            print("free-trial plan not found — run migrations first.")
            return
        tenants = (await db.execute(select(User))).scalars().all()
        created = 0
        for t in tenants:
            existing = (
                await db.execute(
                    select(TenantSubscription).where(TenantSubscription.tenant_id == t.id)
                )
            ).scalar_one_or_none()
            if existing is not None:
                continue
            db.add(TenantSubscription(
                id=str(uuid.uuid4()),
                tenant_id=t.id,
                plan_id=plan.id,
                status="active",
                granted_by="backfill",
            ))
            created += 1
        await db.commit()
        print(f"backfilled {created} tenants onto free-trial (of {len(tenants)} total).")


if __name__ == "__main__":
    asyncio.run(main())

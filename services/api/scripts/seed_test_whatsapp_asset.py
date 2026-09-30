"""Dev helper: bind a WhatsApp asset to a tenant so webhook events resolve.

Embedded Signup writes meta_connections + meta_assets; when testing without
it (e.g. messages flowing to a test number before onboarding completes), this
script inserts the same rows by hand so webhook ingress resolves the tenant
and enqueues normalized events to Kafka.

Usage:
  python scripts/seed_test_whatsapp_asset.py                    # list users + current assets
  python scripts/seed_test_whatsapp_asset.py --email a@b.c      # bind test number to that tenant
  python scripts/seed_test_whatsapp_asset.py --email a@b.c \
      --phone-number-id 1363611116825808 --waba-id 1453762226572111 --phone "+15556259436"
"""
import argparse
import asyncio
import sys
import uuid
from pathlib import Path

import asyncpg

API_DIR = Path(__file__).resolve().parents[1]

# The Meta test number this repo has been testing against (from webhook logs).
DEFAULT_PHONE_NUMBER_ID = "1363611116825808"
DEFAULT_WABA_ID = "1453762226572111"
DEFAULT_PHONE = "+15556259436"


def _load_env() -> dict:
    env = {}
    for line in (API_DIR / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


async def list_state(conn: asyncpg.Connection) -> None:
    users = await conn.fetch("SELECT id, email FROM users LIMIT 50")
    print(f"users ({len(users)}):")
    for u in users:
        print(f"  {u['id']}  {u['email']}")
    assets = await conn.fetch(
        "SELECT tenant_id, provider, asset_type, external_asset_id, phone, active FROM meta_assets"
    )
    print(f"\nmeta_assets ({len(assets)}):")
    for a in assets:
        print(
            f"  tenant={a['tenant_id']} {a['provider']}/{a['asset_type']} "
            f"ext={a['external_asset_id']} phone={a['phone']} active={a['active']}"
        )


async def seed(
    conn: asyncpg.Connection,
    email: str,
    phone_number_id: str,
    waba_id: str,
    phone: str,
) -> None:
    user = await conn.fetchrow("SELECT id FROM users WHERE email = $1", email)
    if user is None:
        print(f"ERROR: no user with email {email!r}")
        sys.exit(1)
    tenant_id = user["id"]

    existing = await conn.fetchval(
        "SELECT id FROM meta_connections WHERE tenant_id = $1 AND provider = 'whatsapp'",
        tenant_id,
    )
    if existing:
        conn_id = existing
        print(f"reusing existing whatsapp connection {conn_id} for {email}")
    else:
        conn_id = str(uuid.uuid4())
        await conn.execute(
            """
            INSERT INTO meta_connections
                (id, tenant_id, provider, connection_type, status, scopes,
                 metadata, created_at, updated_at)
            VALUES ($1, $2, 'whatsapp'::meta_provider, 'dev_seed',
                    'active'::meta_connection_status, '[]'::json, '{}'::json,
                    now(), now())
            """,
            conn_id,
            tenant_id,
        )
        print(f"inserted meta_connection {conn_id}")

    # Token is left NULL on purpose: resolution + webhook enqueue need only
    # the asset rows. Sending (AI replies) goes through a token added later
    # via the proper Embedded Signup path or a system-user token.
    waba_asset_id = str(uuid.uuid4())
    await conn.execute(
        """
        INSERT INTO meta_assets
            (id, tenant_id, connection_id, provider, asset_type, external_asset_id,
             parent_asset_id, name, phone, active, status, metadata,
             created_at, updated_at)
        VALUES ($1, $2, $3, 'whatsapp'::meta_provider, 'waba'::meta_asset_type, $4,
                NULL, $5, NULL, true, 'connected', '{}'::json, now(), now())
        ON CONFLICT ON CONSTRAINT uq_meta_assets_provider_external DO NOTHING
        """,
        waba_asset_id,
        tenant_id,
        conn_id,
        waba_id,
        f"WABA {waba_id} (dev seed)",
    )
    await conn.execute(
        """
        INSERT INTO meta_assets
            (id, tenant_id, connection_id, provider, asset_type, external_asset_id,
             parent_asset_id, name, phone, active, status, metadata,
             created_at, updated_at)
        VALUES ($1, $2, $3, 'whatsapp'::meta_provider, 'phone_number'::meta_asset_type, $4,
                $5, $6, $7, true, 'connected', '{"source": "dev_seed"}'::json, now(), now())
        ON CONFLICT ON CONSTRAINT uq_meta_assets_provider_external DO NOTHING
        """,
        str(uuid.uuid4()),
        tenant_id,
        conn_id,
        phone_number_id,
        waba_asset_id,
        f"Test number {phone}",
        phone,
    )
    print(f"inserted assets: waba={waba_id}, phone_number={phone_number_id} -> tenant {tenant_id}")
    print("next message to this number will resolve + enqueue to Kafka 'meta-events'")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", help="tenant (users.email) to bind the test number to")
    ap.add_argument("--phone-number-id", default=DEFAULT_PHONE_NUMBER_ID)
    ap.add_argument("--waba-id", default=DEFAULT_WABA_ID)
    ap.add_argument("--phone", default=DEFAULT_PHONE)
    args = ap.parse_args()

    url = _load_env()["DATABASE_URL"].replace(
        "postgresql+asyncpg://", "postgresql://", 1
    )
    conn = await asyncpg.connect(url)
    try:
        if args.email:
            await seed(conn, args.email, args.phone_number_id, args.waba_id, args.phone)
        else:
            await list_state(conn)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
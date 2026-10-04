"""Attach a WhatsApp access token to a tenant's meta connection.

Testing companion to seed_test_whatsapp_asset.py: the dev seed leaves
access_token_encrypted NULL on purpose (resolution + enqueue need no token),
but SENDING (AI replies) does. Paste the token from the Embedded Signup
session or a Business Settings system-user token here and it is stored
Fernet-encrypted with the app's own key derivation — the same scheme the
signup flow uses.

The token is read from --token or a hidden prompt (never shell history,
never printed back).

Usage:
  python scripts/set_whatsapp_token.py --email a@b.c --token EAAG...
  python scripts/set_whatsapp_token.py --email a@b.c   # prompts
"""
import argparse
import asyncio
import getpass
import sys
from pathlib import Path

import asyncpg

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))


def _load_env() -> dict:
    env = {}
    for line in (API_DIR / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


def _encrypt(plaintext: str) -> str:
    from app.modules.channels.service import encrypt_token

    return encrypt_token(plaintext)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True, help="tenant (users.email) owning the connection")
    ap.add_argument("--token", help="access token; omitted -> hidden prompt")
    args = ap.parse_args()

    token = args.token or getpass.getpass("WhatsApp access token: ").strip()
    if not token:
        print("ERROR: empty token")
        sys.exit(1)

    url = _load_env()["DATABASE_URL"].replace(
        "postgresql+asyncpg://", "postgresql://", 1
    )
    conn = await asyncpg.connect(url)
    try:
        user = await conn.fetchrow("SELECT id FROM users WHERE email = $1", args.email)
        if user is None:
            print(f"ERROR: no user with email {args.email!r}")
            sys.exit(1)
        tenant_id = user["id"]

        row = await conn.fetchrow(
            "SELECT id FROM meta_connections WHERE tenant_id = $1 AND provider = 'whatsapp' "
            "ORDER BY created_at DESC LIMIT 1",
            tenant_id,
        )
        if row is None:
            print(f"ERROR: no whatsapp meta_connection for {args.email} — run "
                  "seed_test_whatsapp_asset.py first")
            sys.exit(1)

        await conn.execute(
            """
            UPDATE meta_connections
            SET access_token_encrypted = $2, status = 'active'::meta_connection_status,
                updated_at = now()
            WHERE id = $1
            """,
            row["id"],
            _encrypt(token),
        )
        print(f"token stored (encrypted) on connection {row['id']} for {args.email}")
        print("the meta consumer can now send AI replies from this number")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
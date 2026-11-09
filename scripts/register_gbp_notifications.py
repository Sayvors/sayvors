"""Register GBP Pub/Sub notifications on connected Business Profile accounts.

One command per Google account (or all accounts with connected channels).
Uses the merchant OAuth tokens already stored on the channel rows, so no
re-auth is needed — the connect flow already requests the
``business.manage`` scope this API requires.

Dry-run by default: prints the exact PATCH it would send. ``--apply``
performs it. Verify afterwards with ``--check``.

Usage (from ``services/api`` with the deployment's env/database):

    python ../scripts/register_gbp_notifications.py \
        --topic projects/PROJECT/topics/sayvors-gbp-events

    python ../scripts/register_gbp_notifications.py \
        --topic projects/PROJECT/topics/sayvors-gbp-events \
        --account accounts/1234567890 --apply

    python ../scripts/register_gbp_notifications.py --check
"""
from __future__ import annotations

import argparse
import asyncio
import sys

import httpx

NOTIFICATIONS_API = "https://mybusinessnotifications.googleapis.com/v1"
# NEW_REVIEW + UPDATED_REVIEW cover the pull trigger; the other enum values
# (GOOGLE_UPDATE, NEW_CUSTOMER_MEDIA, ...) are not review events.
REVIEW_NOTIFICATION_TYPES = ["NEW_REVIEW", "UPDATED_REVIEW"]


async def _collect_channels(account_filter: str | None):
    """Load active google_reviews channels (deduped per Google account)."""
    from sqlalchemy import select

    from app.modules.channels.models import Channel
    from app.modules.channels.service import decrypt_token
    from app.database import async_session

    async with async_session() as db:
        rows = (
            await db.execute(
                select(Channel).where(
                    Channel.platform == "google_reviews",
                    Channel.status == "active",
                )
            )
        ).scalars().all()
        channels = []
        seen_accounts: set[str] = set()
        for ch in rows:
            account = ch.platform_user_id or ""
            if not account or account in seen_accounts:
                continue
            if account_filter and account_filter not in (account, f"accounts/{account}"):
                continue
            seen_accounts.add(account)
            channels.append(
                (
                    account,
                    decrypt_token(ch.access_token) if ch.access_token else None,
                    decrypt_token(ch.refresh_token) if ch.refresh_token else None,
                )
            )
    return channels


async def _bearer(account: str, access_token: str | None, refresh_token: str | None) -> str:
    """Fresh bearer token, reusing the client's refresh logic."""
    from app.modules.channels.google_reviews import GoogleReviewsClient

    client = GoogleReviewsClient(access_token or "", refresh_token or "")
    try:
        return await client.refresh_access_token()
    finally:
        await client.close()


async def register(topic: str, account_filter: str | None, apply: bool, check: bool) -> int:
    channels = await _collect_channels(account_filter)
    if not channels:
        print("No active google_reviews channels found"
              + (f" matching {account_filter}" if account_filter else ""))
        return 1

    failed = 0
    async with httpx.AsyncClient(timeout=15) as http:
        for account, access_token, refresh_token in channels:
            name = f"accounts/{account}/notificationSetting"
            url = f"{NOTIFICATIONS_API}/accounts/{account}/notificationSetting"
            body = {
                "name": name,
                "pubsubTopic": topic,
                "notificationTypes": REVIEW_NOTIFICATION_TYPES,
            }
            label = f"accounts/{account}"
            try:
                bearer = await _bearer(account, access_token, refresh_token)
            except Exception as e:
                print(f"✗ {label}: token refresh failed — {e}")
                failed += 1
                continue

            try:
                if check:
                    resp = await http.get(url, headers={"Authorization": f"Bearer {bearer}"})
                    print(f"{'✓' if resp.status_code == 200 else '✗'} {label} current: "
                          f"{resp.status_code} {resp.text[:300]}")
                    if resp.status_code != 200:
                        failed += 1
                    continue

                if not apply:
                    print(f"DRY-RUN {label}: PATCH {url}")
                    print(f"  updateMask=notificationTypes,pubsubTopic")
                    print(f"  body={body}")
                    continue

                resp = await http.patch(
                    url,
                    params={"updateMask": "notificationTypes,pubsubTopic"},
                    headers={"Authorization": f"Bearer {bearer}"},
                    json=body,
                )
                if resp.status_code == 200:
                    print(f"✓ {label}: notifications registered → {topic}")
                else:
                    # Print Google's error verbatim: a wrong updateMask or a
                    # missing publisher grant shows up here, word for word.
                    print(f"✗ {label}: {resp.status_code} {resp.text[:400]}")
                    failed += 1
            except Exception as e:
                print(f"✗ {label}: request failed — {e}")
                failed += 1
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--topic",
        help="Pub/Sub topic resource name: projects/PROJECT/topics/NAME",
    )
    parser.add_argument(
        "--account",
        help="Restrict to one Google account id (raw id or accounts/<id>)",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Perform the PATCH (default: dry-run print)",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Only GET and print each account's current notification setting",
    )
    args = parser.parse_args()

    if not args.check and not args.topic:
        parser.error("--topic is required (or use --check)")
    return asyncio.run(register(args.topic or "", args.account, args.apply, args.check))


if __name__ == "__main__":
    sys.exit(main())

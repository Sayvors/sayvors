#!/usr/bin/env python
"""Drive the Meta webhook ingress locally with a synthetic WhatsApp message.

This exercises the REAL path — ingress -> meta_webhook_events -> outbox ->
Kafka -> meta_events_worker -> consumer -> ChannelMessage -> AI reply — without
needing Meta, a tunnel, or a phone. Only Meta's own delivery is skipped; every
line of our own code runs.

Use it to verify the per-conversation context fix (send from two different
numbers and confirm the AI does not see the other's words) and the Phase C
handoff (quote a ticket number).

Usage (from services/api, or anywhere — uses only the stdlib):

    python scripts/meta-local-replay.py --phone 15550001111 \
        --text "any update on TK-000001?" --name Sara

Requires META_APP_SECRET in services/api/.env, because the ingress verifies
X-Hub-Signature-256 = HMAC-SHA256(raw_body, META_APP_SECRET).
"""

import argparse
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request


def load_secret(env_path: str) -> str:
    if not os.path.exists(env_path):
        sys.exit(f"No {env_path} — cannot sign the request (META_APP_SECRET missing).")
    with open(env_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("META_APP_SECRET="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("META_APP_SECRET not set in " + env_path)


def build_payload(phone_number_id: str, from_phone: str, text: str, name: str) -> bytes:
    """A WhatsApp cloud-API message.received body, shaped as parser.py expects:
    `contacts` rides beside `messages` on the value, never inside a message."""
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "WABA-FAKE-ID",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "display_phone_number": "15550000000",
                        "phone_number_id": phone_number_id,
                    },
                    # The sender's profile name — how the inbox names the thread.
                    "contacts": [{"profile": {"name": name}, "wa_id": from_phone}],
                    "messages": [{
                        # Unique per send: the consumer drops a repeat wamid as a
                        # Kafka replay, so reusing one would silently no-op.
                        "id": "wamid.FAKE" + secrets.token_hex(8).upper(),
                        "from": from_phone,
                        "timestamp": str(int(time.time())),
                        "type": "text",
                        "text": {"body": text},
                    }],
                },
            }],
        }],
    }
    # The HMAC is over the EXACT bytes we send, so serialize once and reuse.
    return json.dumps(payload).encode("utf-8")


def post(url: str, body: bytes, secret: str, timeout: int = 15):
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": f"sha256={sig}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except urllib.error.URLError as e:
        sys.exit(f"Could not reach {url}: {e.reason}\nIs the API running on :8000?")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--phone", required=True,
                   help="sender phone (contact_phone) — use a DIFFERENT one per customer")
    p.add_argument("--text", required=True, help="message body")
    p.add_argument("--name", default=None, help="sender profile name")
    p.add_argument("--number-id", default=os.environ.get("WA_PHONE_NUMBER_ID"),
                   help="phone_number_id (MetaAsset.external_asset_id); "
                        "defaults to $WA_PHONE_NUMBER_ID")
    p.add_argument("--url", default="http://127.0.0.1:8000/api/v1/meta/webhooks")
    p.add_argument("--env", default="services/api/.env")
    args = p.parse_args()

    if not args.number_id:
        sys.exit("--number-id (or $WA_PHONE_NUMBER_ID) is required: it is the "
                 "asset id the consumer re-resolves ownership from.")

    secret = load_secret(args.env)
    body = build_payload(args.number_id, args.phone, args.text, args.name or args.phone)
    status, text_out = post(args.url, body, secret)

    print(f"POST {args.url}")
    print(f"  from    {args.phone}  ({args.name or 'no name'})")
    print(f"  text    {args.text!r}")
    print(f"  -> HTTP {status} {text_out.strip()[:200]}")
    if status != 200:
        sys.exit(1)
    print("\n200 = accepted and queued. The reply is generated asynchronously by the")
    print("Kafka consumer, so watch the API log, not this script.")


if __name__ == "__main__":
    main()
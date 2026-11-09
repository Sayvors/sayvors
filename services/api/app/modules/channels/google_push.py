"""GBP Pub/Sub push ingress: Google tells us the moment a review lands.

Realtime layer of the three-layer review-pull design (push ≈ seconds,
60s incremental poll, daily sweep heal). Google documents Business
Profile notifications as best-effort delivery, so this endpoint only
*accelerates* discovery — the poll+sweep layers remain the correctness
guarantee and must never be removed because "the webhook exists".

Verification is fail-closed: without a configured OIDC audience the
route refuses everything (503), and every accepted request must carry a
Google-signed OIDC token whose audience matches the push subscription's
configured audience. A correctly-signed token from an unexpected service
account is rejected when GOOGLE_PUBSUB_PUSH_EMAIL is set.

Duplicate pushes are safe: each triggered pull runs through the same
atomic per-channel claim (``polling_locked_until``) as the background
worker, and every downstream step is idempotent (unique
``platform_message_id``, replied-checks, read-back confirmation).
"""
import asyncio
import base64
import json
import logging
import binascii

from fastapi import Request
from google.auth.transport import requests as google_auth_requests
from google.oauth2.id_token import verify_oauth2_token
from sqlalchemy import select

from ...config import settings

logger = logging.getLogger(__name__)

# Flood ceiling, not a per-push budget — Pub/Sub retries on non-2xx and
# the 60s poll covers anything dropped here. Mirrors the Meta webhook
# posture: signature checks protect authenticity, the rate limit protects
# availability, both fail-closed.
PUSH_RATE_MAX = 600
PUSH_RATE_WINDOW_SECONDS = 60
# Pub/Sub push bodies are small JSON envelopes; anything larger is not a
# GBP notification. Cap before reading so a flood cannot force big reads.
PUSH_MAX_BODY_BYTES = 64 * 1024

# Bounded concurrency for webhook-triggered pulls. Each pull opens its own
# DB session (same as the worker pass) and reuses the poll pipeline, so
# the same claim/backoff/release semantics apply.
_PULL_TASK_CONCURRENCY = 5
# Hard ceiling on queued pull tasks: a burst of pushes beyond this is
# deliberately dropped — the 60s poll heals any review a dropped pull
# would have fetched, and unbounded task growth would silently eat memory.
_PULL_TASK_QUEUE_MAX = 200

_pull_semaphore = asyncio.Semaphore(_PULL_TASK_CONCURRENCY)
_pull_tasks: set[asyncio.Task] = set()


def push_configured() -> bool:
    """True when the push ingress is configured (fail-closed otherwise)."""
    return bool(settings.GOOGLE_PUBSUB_PUSH_AUDIENCE)


def verify_push_oidc(request: Request) -> bool:
    """Verify the Pub/Sub push OIDC bearer token. Returns False on ANY doubt.

    ``verify_oauth2_token`` checks Google's signature, the configured
    audience and expiry; the optional email pin additionally rejects a
    validly-signed token minted by an identity other than our push
    subscription's service account.
    """
    audience = settings.GOOGLE_PUBSUB_PUSH_AUDIENCE
    if not audience:
        return False
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return False
    token = auth[len("Bearer "):].strip()
    if not token or len(token) > 4096:
        return False
    try:
        claims = verify_oauth2_token(
            token,
            google_auth_requests.Request(),
            audience=audience,
        )
    except Exception as e:  # noqa: BLE001 — any crypto/aud/expiry failure is a reject
        logger.warning("Google Pub/Sub push OIDC verification failed: %s: %s", type(e).__name__, e)
        return False
    expected_email = settings.GOOGLE_PUBSUB_PUSH_EMAIL
    if expected_email and claims.get("email") != expected_email:
        logger.warning(
            "Google Pub/Sub push from unexpected identity email=%r", claims.get("email")
        )
        return False
    return True


def parse_push_envelope(raw_body: bytes) -> tuple[str | None, dict | None]:
    """Decode a Pub/Sub push body into (message_id, notification dict).

    Returns (None, None) when the envelope is not a recognizable Pub/Sub
    push — the caller acks anyway (200) to avoid a retry storm over a
    body Pub/Sub will resend byte-identical, but the log line makes the
    drop visible.
    """
    try:
        envelope = json.loads(raw_body)
    except Exception:
        logger.warning("Google push body is not JSON (%.200s)", raw_body)
        return None, None
    message = envelope.get("message") if isinstance(envelope, dict) else None
    if not isinstance(message, dict):
        logger.warning("Google push envelope has no message object (%.200s)", raw_body)
        return None, None
    data = message.get("data")
    if not isinstance(data, str) or len(data) > PUSH_MAX_BODY_BYTES:
        logger.warning("Google push message has no/oversized data field")
        return None, None
    try:
        decoded = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        logger.warning("Google push data is not valid base64")
        return None, None
    try:
        notification = json.loads(decoded)
    except Exception:
        logger.warning("Google push data is not JSON (%.200s)", decoded)
        return None, None
    if not isinstance(notification, dict):
        logger.warning("Google push data is not a JSON object")
        return None, None
    return str(message.get("messageId") or ""), notification


def extract_location_ids(notification: dict) -> list[str]:
    """Pull location id(s) out of a GBP notification, defensively.

    The documented payload carries resource names like
    ``accounts/{a}/locations/{l}`` (under ``location``) or the review
    name ``accounts/{a}/locations/{l}/reviews/{r}`` (under ``review``);
    field shape varies by notification type, so accept both spellings
    plus a bare id. Never trust more than the id: this function only
    picks which channel to poll — the pull re-fetches everything from
    Google, so a forged/odd payload cannot inject review content.
    """
    ids: list[str] = []
    for key in ("location", "review"):
        value = notification.get(key)
        if isinstance(value, str) and value:
            parts = value.split("/")
            if "locations" in parts:
                idx = parts.index("locations")
                if idx + 1 < len(parts) and parts[idx + 1]:
                    ids.append(parts[idx + 1])
    bare = notification.get("locationId") or notification.get("location_id")
    if isinstance(bare, str) and bare and not bare.startswith("accounts/"):
        ids.append(bare)
    out: list[str] = []
    seen: set[str] = set()
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


async def trigger_pulls_for_locations(db, location_ids: list[str]) -> int:
    """Spawn a bounded targeted pull for each active channel on these locations.

    Lookup goes through the indexed ``listing_key`` column (the same key
    the OAuth callback writes). One location can legitimately map to
    several channels (two tenants connected to one listing), and each
    gets its own pipeline run. Returns the number of pulls spawned.
    """
    from .models import AutoReplyConfig, Channel
    from .reviews_worker import _poll_one_channel

    rows = (
        await db.execute(
            select(Channel.id, AutoReplyConfig.id)
            .join(AutoReplyConfig, AutoReplyConfig.channel_id == Channel.id)
            .where(
                Channel.platform == "google_reviews",
                Channel.status == "active",
                Channel.listing_key.in_(location_ids),
            )
        )
    ).all()

    spawned = 0
    for channel_id, config_id in rows:
        if len(_pull_tasks) >= _PULL_TASK_QUEUE_MAX:
            logger.warning(
                "Google push pull queue full (%d) — dropping pull for channel %s; "
                "the 60s poll will fetch it",
                len(_pull_tasks), channel_id,
            )
            break
        task = asyncio.create_task(
            _poll_one_channel(str(channel_id), str(config_id), _pull_semaphore)
        )
        _pull_tasks.add(task)
        task.add_done_callback(_pull_tasks.discard)
        spawned += 1
    return spawned

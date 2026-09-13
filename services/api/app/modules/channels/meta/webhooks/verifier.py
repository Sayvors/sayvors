"""Meta webhook verification: handshake + request signature.

Signature: X-Hub-Signature-256: sha256=<hex> = HMAC-SHA256(raw_body,
META_APP_SECRET). The hex is compared AFTER the `sha256=` prefix, on raw
request bytes (never re-serialized JSON).
"""
import hashlib
import hmac

from .....config import settings

SIGNATURE_HEADER = "x-hub-signature-256"
MAX_BODY_BYTES = 1_000_000


def verify_handshake(mode: str | None, verify_token: str | None, challenge: str | None) -> str | None:
    """Return the challenge to echo, or None when verification fails."""
    expected = settings.META_WEBHOOK_VERIFY_TOKEN or ""
    if mode == "subscribe" and verify_token and challenge:
        if expected and hmac.compare_digest(verify_token, expected):
            return challenge
    return None


def verify_signature(raw_body: bytes, signature: str | None) -> bool:
    """Validate the X-Hub-Signature-256 header against the app secret."""
    secret = settings.META_APP_SECRET or ""
    if not secret or not signature:
        return False
    hex_part = signature
    if hex_part.startswith("sha256="):
        hex_part = hex_part[len("sha256="):]
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, hex_part)

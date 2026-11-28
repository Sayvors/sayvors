"""Meta credential handling: encryption at rest + log redaction.

Application code must access tokens through `decrypt_connection_token`;
never log tokens, secrets, or Authorization headers. Uses the same Fernet
derivation as channels.service so there is exactly one encryption scheme.
"""
import logging
from datetime import datetime, timezone

from ..service import decrypt_token as _decrypt, encrypt_token as _encrypt

logger = logging.getLogger(__name__)

_REDACT_KEYS = ("token", "secret", "authorization", "code", "password", "pin")


def encrypt_credential(plaintext: str) -> str:
    return _encrypt(plaintext)


def decrypt_credential(ciphertext: str | None) -> str | None:
    if not ciphertext:
        return None
    try:
        return _decrypt(ciphertext)
    except Exception:
        logger.warning("Meta credential decryption failed")
        return None


def decrypt_connection_token(connection) -> str | None:
    """Return a usable token, failing closed for rejected/expired WhatsApp auth."""
    if connection is None:
        return None
    if getattr(connection, "provider", None) == "whatsapp":
        if getattr(connection, "status", None) in {"expired", "revoked", "needs_reauth"}:
            return None
        now = datetime.now(timezone.utc)
        for field in ("token_expires_at", "data_access_expires_at"):
            deadline = getattr(connection, field, None)
            if deadline is None:
                continue
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            if deadline <= now:
                return None
    return decrypt_credential(getattr(connection, "access_token_encrypted", None))


def sanitize_metadata(value, *, depth: int = 0):
    """Recursively mask credential fields before persisting provider metadata."""
    if depth >= 8:
        return "***"
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            name = str(key).lower()
            safe_name = name in {"token_type", "token_kind", "token_expiry_source"}
            sensitive = name in {"token", "code"} or any(
                part in name for part in ("access_token", "authorization", "secret", "password", "pin")
            )
            out[key] = "***" if sensitive and not safe_name else sanitize_metadata(item, depth=depth + 1)
        return out
    if isinstance(value, list):
        return [sanitize_metadata(item, depth=depth + 1) for item in value]
    return value


def redact(mapping: dict | None) -> dict:
    """Return a copy with credential-looking values masked (safe to log)."""
    if not mapping:
        return {}
    out = {}
    for k, v in mapping.items():
        if any(s in str(k).lower() for s in _REDACT_KEYS):
            out[k] = "***"
        else:
            out[k] = v
    return out

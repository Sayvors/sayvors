"""Meta credential handling: encryption at rest + log redaction.

Application code must access tokens through `decrypt_connection_token`;
never log tokens, secrets, or Authorization headers. Uses the same Fernet
derivation as channels.service so there is exactly one encryption scheme.
"""
import logging

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
    """Return the plaintext token for a MetaConnection, or None."""
    return decrypt_credential(getattr(connection, "access_token_encrypted", None))


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

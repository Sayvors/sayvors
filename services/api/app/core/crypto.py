"""Symmetric encryption for secrets at rest.

Channel OAuth tokens, message bodies, contact phones and TTS provider keys
all share one Fernet key. It lives in ``core`` rather than in the channel
module so a capability module (tts) can read its own credentials without
importing a channel — that one-way dependency is what lets the module be
extracted later.

Primary key: CHANNEL_ENCRYPTION_KEY (dedicated, independent of the JWT
signing secret — leaking one must not unlock the other). When unset, the
legacy JWT-derived key is used so existing deployments keep working, and a
loud log tells operators to set the dedicated key.

Decryption tries the primary key first, then falls back to legacy, so
setting CHANNEL_ENCRYPTION_KEY later never breaks previously stored
ciphertext. New writes always use the primary key.
"""

import base64
import functools
import hashlib
import logging

from ..config import settings

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def get_fernet():
    """The process-wide Fernet instance (derived once, then cached)."""
    from cryptography.fernet import Fernet, InvalidToken

    def _fernet_from(secret: str):
        key = hashlib.sha256(secret.encode()).digest()
        return Fernet(base64.urlsafe_b64encode(key))

    primary_secret = (settings.CHANNEL_ENCRYPTION_KEY or "").strip()
    legacy_fernet = _fernet_from(settings.JWT_SECRET)

    if primary_secret:

        class _PrimaryFirstFernet:
            def encrypt(self, data: bytes) -> bytes:
                return _fernet_from(primary_secret).encrypt(data)

            def decrypt(self, token: bytes) -> bytes:
                try:
                    return _fernet_from(primary_secret).decrypt(token)
                except InvalidToken:
                    return legacy_fernet.decrypt(token)

        return _PrimaryFirstFernet()

    logger.warning(
        "CHANNEL_ENCRYPTION_KEY is not set — credential encryption is falling "
        "back to a key derived from JWT_SECRET. Set a dedicated "
        "CHANNEL_ENCRYPTION_KEY so JWT and storage keys are independent."
    )

    class _LegacyFernet:
        def encrypt(self, data: bytes) -> bytes:
            return legacy_fernet.encrypt(data)

        def decrypt(self, data: bytes) -> bytes:
            return legacy_fernet.decrypt(data)

    return _LegacyFernet()


def encrypt_secret(value: str) -> str:
    """Encrypt a secret at rest. Empty input passes through unchanged."""
    if not value:
        return value
    return get_fernet().encrypt(value.encode()).decode()


def decrypt_secret(encrypted: str) -> str:
    """Decrypt a value written by :func:`encrypt_secret`."""
    if not encrypted:
        return encrypted
    return get_fernet().decrypt(encrypted.encode()).decode()

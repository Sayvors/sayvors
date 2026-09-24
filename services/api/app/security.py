import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from google.auth.transport import requests as google_auth_requests
from google.oauth2.id_token import verify_oauth2_token

from .config import settings

logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_admin_token() -> str:
    """Short-lived admin session token (type claim separates it from user tokens)."""
    from .config import settings as _settings

    expire = datetime.now(timezone.utc) + timedelta(minutes=_settings.ADMIN_SESSION_MINUTES)
    jti = secrets.token_hex(16)
    return jwt.encode(
        {"sub": "admin", "exp": expire, "jti": jti, "type": "admin"},
        _settings.JWT_SECRET,
        algorithm=_settings.JWT_ALGORITHM,
    )


def create_access_token(subject: str, version: int = 0) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_ACCESS_EXPIRATION_MINUTES)
    jti = secrets.token_hex(16)
    return jwt.encode(
        {"sub": subject, "exp": expire, "jti": jti, "type": "access", "ver": version},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )


def create_refresh_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_EXPIRATION_DAYS)
    jti = secrets.token_hex(16)
    return jwt.encode(
        {"sub": subject, "exp": expire, "jti": jti, "type": "refresh"},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_verification_token() -> str:
    return secrets.token_urlsafe(32)


def generate_csrf_token() -> str:
    return secrets.token_hex(32)


def create_email_verification_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=24)
    return jwt.encode(
        {"sub": user_id, "exp": expire, "type": "email_verify"},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )


def create_password_reset_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=1)
    return jwt.encode(
        {"sub": user_id, "exp": expire, "type": "password_reset"},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )


def create_token_fingerprint(user_agent: str, ip: str) -> str:
    raw = f"{user_agent}:{ip}"
    return hashlib.sha256(raw.encode()).hexdigest()


def verify_google_id_token(id_token: str) -> dict:
    """Verify a Google Identity Services ID token and return its claims.

    Checks signature (against Google's certs), audience, and expiry inside
    verify_oauth2_token, then enforces our own claim requirements.
    Raises ValueError("invalid_token") on cryptographic/audience failure and
    ValueError("unverified_email") when the token is well-formed but unusable
    for sign-in.
    """
    try:
        claims = verify_oauth2_token(
            id_token,
            google_auth_requests.Request(),
            audience=settings.GOOGLE_CLIENT_ID,
        )
    except Exception as e:
        logger.warning("Google ID token verification failed: %s: %s", type(e).__name__, e)
        raise ValueError("invalid_token")
    if not claims.get("sub") or not claims.get("email") or claims.get("email_verified") is not True:
        raise ValueError("unverified_email")
    return claims

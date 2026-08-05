from datetime import datetime, timedelta, timezone

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...security import (
    create_access_token,
    create_refresh_token,
    create_email_verification_token,
    create_password_reset_token,
    create_token_fingerprint,
    decode_token,
    hash_password,
    hash_token,
    verify_password,
)
from ..users.models import User
from .models import RefreshToken, EmailVerification, PasswordReset, LoginAttempt
from .schemas import (
    SignupRequest,
    LoginRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
)
from .rate_limit import blacklist_token, is_token_blacklisted, store_session, delete_session, delete_all_sessions
from .events import (
    log_signup,
    log_login,
    log_login_failed,
    log_logout,
    log_password_reset,
    log_password_reset_request,
    log_email_verified,
    log_token_refresh,
    log_account_locked,
)


async def signup(body: SignupRequest, db: AsyncSession, user_agent: str, ip: str) -> dict:
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise ValueError("Email already registered")

    user = User(
        first_name=body.first_name,
        last_name=body.last_name,
        email=body.email,
        password_hash=hash_password(body.password),
        business_type=body.business_type,
        referral=body.referral,
        newsletter=body.newsletter,
    )
    db.add(user)
    await db.flush()

    raw_token = create_email_verification_token(user.id)
    verification = EmailVerification(
        user_id=user.id,
        token_hash=hash_token(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    db.add(verification)

    refresh_raw = create_refresh_token(user.id)
    refresh = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(refresh_raw),
        fingerprint=create_token_fingerprint(user_agent, ip),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_EXPIRATION_DAYS),
        user_agent=user_agent[:500],
        ip_address=ip[:45],
    )
    db.add(refresh)
    await db.commit()

    access_token = create_access_token(user.id)

    # Store session in Redis
    import json
    from ...modules.redis.client import get_redis
    try:
        redis = await get_redis()
        session_data = {"user_id": user.id, "ip": ip, "user_agent": user_agent[:200]}
        await store_session(user.id, user.id, session_data, settings.JWT_REFRESH_EXPIRATION_DAYS * 86400)
    except Exception:
        pass

    await log_signup(user.id, user.email, ip, user_agent[:200])

    return {
        "access_token": access_token,
        "refresh_token": refresh_raw,
        "user": {
            "id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "email_verified": user.email_verified,
        },
        "verification_token": raw_token,
    }


async def login(body: LoginRequest, db: AsyncSession, user_agent: str, ip: str) -> dict:
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if user and user.locked_until and user.locked_until > datetime.now(timezone.utc):
        raise ValueError("Account is temporarily locked. Try again later.")

    attempt = LoginAttempt(email=body.email, ip_address=ip, success=False)
    db.add(attempt)

    if not user or not verify_password(body.password, user.password_hash):
        if user:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= settings.MAX_LOGIN_ATTEMPTS:
                user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=settings.LOCKOUT_MINUTES)
                await log_account_locked(body.email, ip)
        await db.commit()
        await log_login_failed(body.email, ip, user_agent[:200], "invalid_credentials")
        raise ValueError("Invalid email or password")

    user.failed_login_attempts = 0
    user.locked_until = None
    attempt.success = True

    access_token = create_access_token(user.id)
    refresh_raw = create_refresh_token(user.id)
    refresh = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(refresh_raw),
        fingerprint=create_token_fingerprint(user_agent, ip),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_EXPIRATION_DAYS),
        user_agent=user_agent[:500],
        ip_address=ip[:45],
    )
    db.add(refresh)
    await db.commit()

    # Store session in Redis
    try:
        from ...modules.redis.client import get_redis
        redis = await get_redis()
        session_data = {"user_id": user.id, "ip": ip, "user_agent": user_agent[:200]}
        await store_session(user.id, user.id, session_data, settings.JWT_REFRESH_EXPIRATION_DAYS * 86400)
    except Exception:
        pass

    await log_login(user.id, user.email, ip, user_agent[:200])

    return {
        "access_token": access_token,
        "refresh_token": refresh_raw,
        "user": {
            "id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "email_verified": user.email_verified,
        },
    }


async def refresh_tokens(refresh_token: str, db: AsyncSession) -> dict:
    try:
        payload = decode_token(refresh_token)
        if payload.get("type") != "refresh":
            raise ValueError("Invalid token type")

        # Check if token is blacklisted
        if await is_token_blacklisted(payload.get("jti", "")):
            raise ValueError("Token revoked")
    except ValueError:
        raise
    except Exception:
        raise ValueError("Invalid refresh token")

    token_hash = hash_token(refresh_token)
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked == False,
        )
    )
    db_token = result.scalar_one_or_none()

    if not db_token:
        raise ValueError("Refresh token revoked or not found")

    if db_token.expires_at < datetime.now(timezone.utc):
        raise ValueError("Refresh token expired")

    # Revoke old token (rotation) and blacklist in Redis
    db_token.revoked = True
    try:
        from ...modules.redis.client import get_redis
        redis = await get_redis()
        ttl = int((db_token.expires_at - datetime.now(timezone.utc)).total_seconds())
        if ttl > 0:
            await blacklist_token(payload["jti"], ttl)
    except Exception:
        pass

    # Create new tokens
    user_id = payload["sub"]
    access_token = create_access_token(user_id)
    new_refresh_raw = create_refresh_token(user_id)
    new_refresh = RefreshToken(
        user_id=user_id,
        token_hash=hash_token(new_refresh_raw),
        fingerprint=db_token.fingerprint,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_EXPIRATION_DAYS),
        user_agent=db_token.user_agent,
        ip_address=db_token.ip_address,
    )
    db.add(new_refresh)
    await db.commit()

    await log_token_refresh(user_id)

    return {
        "access_token": access_token,
        "refresh_token": new_refresh_raw,
    }


async def logout(refresh_token: str | None, user_id: str, all_devices: bool, db: AsyncSession):
    if all_devices:
        await db.execute(
            delete(RefreshToken).where(RefreshToken.user_id == user_id)
        )
        try:
            from ...modules.redis.client import get_redis
            redis = await get_redis()
            await delete_all_sessions(user_id)
        except Exception:
            pass
    elif refresh_token:
        token_hash = hash_token(refresh_token)
        await db.execute(
            delete(RefreshToken).where(
                RefreshToken.user_id == user_id,
                RefreshToken.token_hash == token_hash,
            )
        )
    await db.commit()
    await log_logout(user_id, all_devices)


async def forgot_password(body: ForgotPasswordRequest, db: AsyncSession, ip: str) -> str | None:
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user:
        return None

    raw_token = create_password_reset_token(user.id)
    reset = PasswordReset(
        user_id=user.id,
        token_hash=hash_token(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(reset)
    await db.commit()

    await log_password_reset_request(body.email, ip)
    return raw_token


async def reset_password(body: ResetPasswordRequest, db: AsyncSession) -> bool:
    try:
        payload = decode_token(body.token)
        if payload.get("type") != "password_reset":
            raise ValueError("Invalid token type")
    except ValueError:
        raise
    except Exception:
        raise ValueError("Invalid or expired reset token")

    token_hash = hash_token(body.token)
    result = await db.execute(
        select(PasswordReset).where(
            PasswordReset.token_hash == token_hash,
            PasswordReset.used == False,
        )
    )
    db_reset = result.scalar_one_or_none()

    if not db_reset or db_reset.expires_at < datetime.now(timezone.utc):
        raise ValueError("Invalid or expired reset token")

    db_reset.used = True

    user_result = await db.execute(select(User).where(User.id == payload["sub"]))
    user = user_result.scalar_one_or_none()
    if not user:
        raise ValueError("User not found")

    user.password_hash = hash_password(body.password)
    user.failed_login_attempts = 0
    user.locked_until = None

    await db.execute(delete(RefreshToken).where(RefreshToken.user_id == user.id))
    await db.commit()

    # Delete all sessions
    try:
        from ...modules.redis.client import get_redis
        await delete_all_sessions(user.id)
    except Exception:
        pass

    await log_password_reset(user.id, user.email)
    return True


async def verify_email(token: str, db: AsyncSession) -> bool:
    try:
        payload = decode_token(token)
        if payload.get("type") != "email_verify":
            raise ValueError("Invalid token type")
    except ValueError:
        raise
    except Exception:
        raise ValueError("Invalid or expired verification token")

    token_hash_val = hash_token(token)
    result = await db.execute(
        select(EmailVerification).where(
            EmailVerification.token_hash == token_hash_val,
            EmailVerification.used == False,
        )
    )
    db_verification = result.scalar_one_or_none()

    if not db_verification or db_verification.expires_at < datetime.now(timezone.utc):
        raise ValueError("Invalid or expired verification token")

    db_verification.used = True

    user_result = await db.execute(select(User).where(User.id == payload["sub"]))
    user = user_result.scalar_one_or_none()
    if not user:
        raise ValueError("User not found")

    user.email_verified = True
    await db.commit()

    await log_email_verified(user.id, user.email)
    return True


async def get_user_sessions(user_id: str, db: AsyncSession) -> list[dict]:
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked == False,
            RefreshToken.expires_at > datetime.now(timezone.utc),
        )
    )
    tokens = result.scalars().all()
    return [
        {
            "id": t.id,
            "device": t.user_agent,
            "ip": t.ip_address,
            "created_at": t.created_at.isoformat(),
        }
        for t in tokens
    ]


async def cleanup_expired_data(db: AsyncSession) -> dict:
    """Delete old login_attempts (>30d) and expired/revoked refresh_tokens (>7d).

    Called on startup and can be scheduled periodically.
    Returns counts of deleted rows.
    """
    now = datetime.now(timezone.utc)
    login_cutoff = now - timedelta(days=30)
    token_cutoff = now - timedelta(days=7)

    # Delete old login attempts
    result = await db.execute(
        delete(LoginAttempt).where(LoginAttempt.created_at < login_cutoff)
    )
    login_deleted = result.rowcount

    # Delete expired refresh tokens
    result = await db.execute(
        delete(RefreshToken).where(
            (RefreshToken.expires_at < now) | (RefreshToken.revoked == True)
        )
    )
    token_deleted = result.rowcount

    await db.commit()
    return {"login_attempts_deleted": login_deleted, "refresh_tokens_deleted": token_deleted}

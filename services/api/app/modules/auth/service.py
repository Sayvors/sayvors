from datetime import datetime, timedelta, timezone

from sqlalchemy import select, delete, update, func
from sqlalchemy.exc import IntegrityError
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

    access_token = create_access_token(user.id, user.token_version or 0)

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

    # Gate sign-in on email verification: send the OTP now. A send
    # failure must not fail signup — the user can resend from login.
    try:
        from ...modules.email.service import send_otp_email
        await send_otp_email(user.email, "signup")
    except Exception:
        import logging
        logging.getLogger(__name__).warning("OTP email failed for %s", user.email)

    return {
        "access_token": access_token,
        "refresh_token": refresh_raw,
        "user": {
            "id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "email_verified": user.email_verified,
            "onboarded": user.onboarded,
        },
        "verification_token": raw_token,
    }


async def login(body: LoginRequest, db: AsyncSession, user_agent: str, ip: str) -> dict:
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if user and user.locked_until and user.locked_until > datetime.now(timezone.utc):
        raise ValueError("Account is temporarily locked. Try again later.")

    if not user or not verify_password(body.password, user.password_hash):
        # Only failures (and lockouts) hit the login_attempts table — at scale,
        # a row per successful login is an insert firehose. Successes are
        # already recorded via log_login events.
        db.add(LoginAttempt(email=body.email, ip_address=ip, success=False))
        if user:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= settings.MAX_LOGIN_ATTEMPTS:
                user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=settings.LOCKOUT_MINUTES)
                await log_account_locked(body.email, ip)
        await db.commit()
        await log_login_failed(body.email, ip, user_agent[:200], "invalid_credentials")
        raise ValueError("Invalid email or password")

    if not user.email_verified:
        # Resend the OTP so the user is never stuck, then refuse sign-in.
        try:
            from ...modules.email.service import send_otp_email
            await send_otp_email(user.email, "signup")
        except Exception:
            pass
        raise ValueError("EMAIL_NOT_VERIFIED: verify the code sent to your email first.")

    user.failed_login_attempts = 0
    user.locked_until = None

    access_token = create_access_token(user.id, user.token_version or 0)
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
            "onboarded": user.onboarded,
        },
    }


async def _issue_session(user: User, db: AsyncSession, event: str,
                         user_agent: str, ip: str,
                         metadata: dict | None = None) -> dict:
    """Access + refresh tokens, refresh row, Redis session, auth event.
    The single session-issuance path shared by Google sign-in."""
    access_token = create_access_token(user.id, user.token_version or 0)
    refresh_raw = create_refresh_token(user.id)
    db.add(RefreshToken(
        user_id=user.id,
        token_hash=hash_token(refresh_raw),
        fingerprint=create_token_fingerprint(user_agent, ip),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_EXPIRATION_DAYS),
        user_agent=user_agent[:500],
        ip_address=ip[:45],
    ))
    await db.commit()

    try:
        from ...modules.redis.client import get_redis
        redis = await get_redis()
        session_data = {"user_id": user.id, "ip": ip, "user_agent": user_agent[:200]}
        await store_session(user.id, user.id, session_data,
                            settings.JWT_REFRESH_EXPIRATION_DAYS * 86400)
    except Exception:
        pass

    if event == "signup":
        await log_signup(user.id, user.email, ip, user_agent[:200], metadata=metadata)
    else:
        await log_login(user.id, user.email, ip, user_agent[:200], metadata=metadata)

    return {
        "access_token": access_token,
        "refresh_token": refresh_raw,
        "user": {
            "id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "email_verified": user.email_verified,
            "onboarded": user.onboarded,
        },
    }


async def google_login(claims: dict, db: AsyncSession,
                       user_agent: str, ip: str) -> dict:
    """Find-or-create from verified Google claims; issue a session.

    Google's tokens are never stored — only the profile snapshot lands on the
    user row (google_sub / name / avatar_url).
    """
    import secrets as _secrets

    sub = claims["sub"]
    email = claims["email"].strip().lower()
    name = (claims.get("name") or "").strip()
    picture = claims.get("picture")
    first, _sep, last = name.partition(" ")
    if not first:
        first = email.split("@", 1)[0]
        last = ""

    try:
        event = "login"
        result = await db.execute(select(User).where(User.google_sub == sub))
        user = result.scalar_one_or_none()

        if user is None:
            result = await db.execute(
                select(User).where(func.lower(User.email) == email)
            )
            user = result.scalar_one_or_none()
            if user is not None:
                # Decision 1A: link — existing password account adopts Google.
                if user.google_sub is None:
                    user.google_sub = sub
                if picture:
                    user.avatar_url = picture
            else:
                user = User(
                    first_name=first[:100],
                    last_name=last[:100],
                    email=email,
                    password_hash=hash_password(_secrets.token_urlsafe(32)),
                    email_verified=True,
                    onboarded=False,
                    google_sub=sub,
                    avatar_url=picture,
                )
                db.add(user)
                await db.flush()  # assign user.id before the refresh-token row
                event = "signup"
        else:
            if first:
                user.first_name = first[:100]
            if last:
                user.last_name = last[:100]
            if picture:
                user.avatar_url = picture

        return await _issue_session(user, db, event, user_agent, ip,
                                    metadata={"via": "google"})
    except IntegrityError:
        # Concurrent signup race: the row exists now — sign in with it.
        await db.rollback()
        result = await db.execute(select(User).where(User.google_sub == sub))
        user = result.scalar_one_or_none()
        if user is None:
            raise ValueError("Could not create account")
        return await _issue_session(user, db, "login", user_agent, ip,
                                    metadata={"via": "google"})


async def refresh_tokens(
    refresh_token: str, db: AsyncSession, user_agent: str = "", ip: str = ""
) -> dict:
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
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    db_token = result.scalar_one_or_none()

    if not db_token:
        raise ValueError("Refresh token revoked or not found")

    # ── Reuse detection ─────────────────────────────────
    # A presented token that is already revoked means it was stolen/leaked:
    # the legitimate client moved on to the rotated token. Kill the whole
    # family (all sessions for this user) and force a fresh login.
    if db_token.revoked:
        user_id = db_token.user_id
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id)
            .values(revoked=True)
        )
        await db.commit()
        try:
            await delete_all_sessions(user_id)
        except Exception:
            pass
        await log_account_locked(payload.get("sub", user_id), ip or "unknown")
        raise ValueError("Refresh token reuse detected. All sessions revoked.")

    if db_token.expires_at < datetime.now(timezone.utc):
        raise ValueError("Refresh token expired")

    # ── Device (user-agent) check ───────────────────────
    # The token is bound to the device that received it. We compare the
    # user-agent stored on the row directly (IPs drift legitimately on mobile
    # networks, so IP is recorded but not enforced).
    if user_agent and db_token.user_agent and user_agent[:500] != db_token.user_agent:
        db_token.revoked = True
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == db_token.user_id)
            .values(revoked=True)
        )
        await db.commit()
        try:
            await delete_all_sessions(db_token.user_id)
        except Exception:
            pass
        raise ValueError("Session validation failed. Please log in again.")

    # Revoke old token (rotation) and blacklist in Redis
    db_token.revoked = True
    try:
        ttl = int((db_token.expires_at - datetime.now(timezone.utc)).total_seconds())
        if ttl > 0:
            await blacklist_token(payload["jti"], ttl)
    except Exception:
        pass

    # Create new tokens
    user_id = payload["sub"]
    _ver = (await db.execute(select(User.token_version).where(User.id == user_id))).scalar_one_or_none()
    access_token = create_access_token(user_id, _ver or 0)
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


async def logout(refresh_token: str | None, user_id: str, all_devices: bool, db: AsyncSession,
               access_jti: str | None = None, access_ttl: int = 0):
    # G1: the presented access token dies with the session — blacklist its
    # jti for its remaining lifetime so it cannot outlive logout.
    if access_jti and access_ttl > 0:
        try:
            await blacklist_token(access_jti, access_ttl)
        except Exception:
            pass
    if all_devices:
        await db.execute(
            delete(RefreshToken).where(RefreshToken.user_id == user_id)
        )
        # Bump the token generation: every access token issued before this
        # moment is rejected by get_current_user, Redis or not.
        await db.execute(
            update(User).where(User.id == user_id).values(
                token_version=User.token_version + 1
            )
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

    # Send the reset email (same branded format as OTP). A send failure
    # must not reveal anything or break the generic endpoint response.
    try:
        from ...modules.email.service import send_password_reset_email

        reset_url = f"{(settings.FRONTEND_URL or '').rstrip('/')}/reset-password?token={raw_token}"
        await send_password_reset_email(
            user.email, user.first_name or "there", reset_url
        )
    except Exception:
        import logging

        logging.getLogger(__name__).warning("Password-reset email failed for %s", body.email)

    return raw_token


async def _geo_lookup(ip: str) -> str:
    """Best-effort "City, Region, Country" for an IP; never raises, 5s cap."""
    if not ip or ip in ("unknown", "testclient"):
        return "Unknown location"
    try:
        import httpx

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"https://ipwho.is/{ip}")
            data = resp.json()
        if not data.get("success", True):
            return "Unknown location"
        loc = ", ".join(
            p for p in (data.get("city"), data.get("region"), data.get("country")) if p
        )
        return loc or "Unknown location"
    except Exception:
        return "Unknown location"


def _describe_device(user_agent: str) -> str:
    """Human-readable device summary from a User-Agent (fixed strings only —
    the raw UA is attacker-controlled and never echoed into the email)."""
    ua = user_agent or ""
    if not ua.strip():
        return "Unknown device"

    browser = "Unknown browser"
    for needle, name in (
        ("Edg/", "Edge"),
        ("OPR/", "Opera"),
        ("Firefox/", "Firefox"),
        ("Chrome/", "Chrome"),
        ("Safari/", "Safari"),
    ):
        if needle in ua:
            browser = name
            break

    if "Windows" in ua:
        os_name = "Windows"
    elif "Android" in ua:
        os_name = "Android"
    elif "iPhone" in ua or "iPad" in ua:
        os_name = "iOS"
    elif "Mac OS X" in ua or "Macintosh" in ua:
        os_name = "macOS"
    elif "Linux" in ua:
        os_name = "Linux"
    else:
        os_name = "Unknown OS"

    if "iPad" in ua or "Tablet" in ua:
        device_type = "Tablet"
    elif "Mobile" in ua or "Android" in ua or "iPhone" in ua:
        device_type = "Mobile"
    else:
        device_type = "Desktop"

    return f"{browser} on {os_name} ({device_type})"


async def reset_password(body: ResetPasswordRequest, db: AsyncSession, ip: str, ua: str) -> bool:
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

    if not db_reset:
        raise ValueError("Invalid or expired reset token")
    expires_at = db_reset.expires_at
    if expires_at.tzinfo is None:
        # SQLite (tests) returns naive timestamps; Postgres returns aware.
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise ValueError("Invalid or expired reset token")

    db_reset.used = True

    user_result = await db.execute(select(User).where(User.id == payload["sub"]))
    user = user_result.scalar_one_or_none()
    if not user:
        raise ValueError("User not found")

    user.password_hash = hash_password(body.password)
    user.failed_login_attempts = 0
    user.locked_until = None
    # G1: password change kills every prior access token generation.
    user.token_version = (user.token_version or 0) + 1

    await db.execute(delete(RefreshToken).where(RefreshToken.user_id == user.id))
    await db.commit()

    # Delete all sessions
    try:
        from ...modules.redis.client import get_redis
        await delete_all_sessions(user.id)
    except Exception:
        pass

    await log_password_reset(user.id, user.email, ip=ip, ua=ua)

    # Security confirmation: time + IP + location + device. A send failure
    # must never undo or fail the reset that already committed above.
    try:
        from ...modules.email.service import send_password_reset_success_email

        await send_password_reset_success_email(
            user.email,
            user.first_name or "there",
            when=datetime.now(timezone.utc),
            ip=ip,
            location=await _geo_lookup(ip),
            device=_describe_device(ua),
        )
    except Exception:
        import logging

        logging.getLogger(__name__).warning(
            "Password-reset success email failed for %s", user.email
        )
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


async def verify_signup_otp(
    email: str, code: str, db: AsyncSession, user_agent: str = "", ip: str = ""
) -> dict:
    """Check the signup OTP, mark the user verified, and sign them in.

    Returns the same session payload as login() so the frontend can
    take the user straight to the dashboard.
    """
    from ...modules.email.service import verify_otp

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError("No account with that email")
    just_verified = False
    if not user.email_verified:
        if not await verify_otp(email, code):
            raise ValueError("Invalid or expired code.")
        user.email_verified = True
        just_verified = True
        await log_email_verified(user.id, user.email)

    access_token = create_access_token(user.id, user.token_version or 0)
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

    try:
        from ...modules.redis.client import get_redis
        redis = await get_redis()
        session_data = {"user_id": user.id, "ip": ip, "user_agent": user_agent[:200]}
        await store_session(user.id, user.id, session_data, settings.JWT_REFRESH_EXPIRATION_DAYS * 86400)
    except Exception:
        pass

    await log_login(user.id, user.email, ip, user_agent[:200])

    if just_verified:
        # Greeting upon account creation (same branded format as OTP).
        # Never fail verification because the greeting failed.
        try:
            from ...modules.email.service import send_welcome_email

            await send_welcome_email(user.email, user.first_name or "there")
        except Exception:
            import logging

            logging.getLogger(__name__).warning("Welcome email failed for %s", user.email)

    return {
        "access_token": access_token,
        "refresh_token": refresh_raw,
        "user": {
            "id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "email_verified": user.email_verified,
            "onboarded": user.onboarded,
        },
    }


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

    Deletes run in bounded batches so large tables never take long locks.
    Called on startup and by the periodic retention task (see events.py /
    main.py lifespan).
    """
    from ...config import settings as cfg

    now = datetime.now(timezone.utc)
    login_cutoff = now - timedelta(days=30)
    token_cutoff = now - timedelta(days=7)
    batch = cfg.RETENTION_DELETE_BATCH_SIZE

    # Delete old login attempts in batches
    login_deleted = 0
    while True:
        result = await db.execute(
            delete(LoginAttempt).where(
                LoginAttempt.id.in_(
                    select(LoginAttempt.id)
                    .where(LoginAttempt.created_at < login_cutoff)
                    .limit(batch)
                )
            )
        )
        login_deleted += result.rowcount or 0
        await db.commit()
        if (result.rowcount or 0) < batch:
            break

    # Delete expired/old revoked refresh tokens in batches.
    # Revoked rows are kept for a grace period because refresh-token reuse
    # detection needs to observe them (presented-again revoked token => steal).
    token_deleted = 0
    while True:
        result = await db.execute(
            delete(RefreshToken).where(
                RefreshToken.id.in_(
                    select(RefreshToken.id)
                    .where(
                        (RefreshToken.expires_at < token_cutoff)
                        | (
                            (RefreshToken.revoked == True)  # noqa: E712
                            & (RefreshToken.created_at < token_cutoff)
                        )
                    )
                    .limit(batch)
                )
            )
        )
        token_deleted += result.rowcount or 0
        await db.commit()
        if (result.rowcount or 0) < batch:
            break

    return {"login_attempts_deleted": login_deleted, "refresh_tokens_deleted": token_deleted}


async def run_retention_loop() -> None:
    """Periodically purge expired auth data. Started from app lifespan."""
    import asyncio
    import logging

    from ...config import settings as cfg
    from ...database import async_session

    log = logging.getLogger(__name__)
    while True:
        await asyncio.sleep(cfg.RETENTION_CLEANUP_INTERVAL_SECONDS)
        try:
            async with async_session() as db:
                result = await cleanup_expired_data(db)
                if any(result.values()):
                    log.info("Retention cleanup: %s", result)
        except Exception as e:
            log.error("Retention cleanup failed: %s", e)

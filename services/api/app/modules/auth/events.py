import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

AUTH_TOPIC = "auth-events"


async def log_auth_event(
    event_type: str,
    user_id: str | None = None,
    email: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    success: bool = True,
    metadata: dict | None = None,
) -> None:
    """Publish an auth event via the outbox pattern.

    Writes to the event_outbox table (local PostgreSQL, ~1-2ms).
    A background worker picks it up and delivers to Kafka.
    If Kafka is down, events queue up and retry automatically.
    """
    try:
        from ..outbox.service import enqueue_event

        event = {
            "event_type": event_type,
            "user_id": user_id,
            "email": email,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "success": success,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {},
        }

        await enqueue_event(
            event_type=event_type,
            payload=event,
            topic=AUTH_TOPIC,
        )
    except Exception:
        # Outbox enqueue should never fail the request.
        # If the DB is down, we log and move on.
        logger.exception("Failed to enqueue auth event: %s", event_type)


async def log_signup(user_id: str, email: str, ip: str, ua: str) -> None:
    await log_auth_event("signup", user_id=user_id, email=email, ip_address=ip, user_agent=ua)


async def log_login(user_id: str, email: str, ip: str, ua: str) -> None:
    await log_auth_event("login", user_id=user_id, email=email, ip_address=ip, user_agent=ua)


async def log_login_failed(email: str, ip: str, ua: str, reason: str) -> None:
    await log_auth_event("login_failed", email=email, ip_address=ip, user_agent=ua, success=False, metadata={"reason": reason})


async def log_logout(user_id: str, all_devices: bool) -> None:
    await log_auth_event("logout", user_id=user_id, metadata={"all_devices": all_devices})


async def log_password_reset(user_id: str, email: str) -> None:
    await log_auth_event("password_reset", user_id=user_id, email=email)


async def log_password_reset_request(email: str, ip: str) -> None:
    await log_auth_event("password_reset_request", email=email, ip_address=ip)


async def log_email_verified(user_id: str, email: str) -> None:
    await log_auth_event("email_verified", user_id=user_id, email=email)


async def log_token_refresh(user_id: str) -> None:
    await log_auth_event("token_refresh", user_id=user_id)


async def log_account_locked(email: str, ip: str) -> None:
    await log_auth_event("account_locked", email=email, ip_address=ip, metadata={"reason": "max_attempts_exceeded"})

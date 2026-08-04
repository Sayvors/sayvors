import json
from datetime import datetime, timezone

from ..kafka.client import get_kafka_producer

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
    """Publish an auth event to Kafka."""
    try:
        producer = await get_kafka_producer()
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
        key = f"{event_type}:{user_id or email}".encode()
        value = json.dumps(event).encode()
        await producer.send_and_wait(AUTH_TOPIC, key=key, value=value)
    except Exception:
        pass


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

"""Authentication event logging helpers.

This module provides a thin API for recording authentication lifecycle events such as
signup, login, logout, password reset, and failed login attempts. Events are emitted
through the application's outbox pattern so the request path stays fast and the
actual delivery to Kafka or downstream systems happens asynchronously.

The purpose of this abstraction is to keep authentication auditing centralized while
preventing request failures from breaking legitimate user flows.
"""

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
    """Queue an auth event for asynchronous delivery via the outbox pattern.

    The event is written to the local ``event_outbox`` table first. A background worker
    later reads those rows and pushes them to Kafka. This pattern keeps the request path
    resilient even when the messaging system is temporarily unavailable.

    Args:
        event_type: Logical event name, such as ``login`` or ``password_reset``.
        user_id: Optional authenticated user ID.
        email: Optional email associated with the action.
        ip_address: Optional client IP address for security investigation.
        user_agent: Optional client user-agent string.
        success: Whether the event represents a successful or failed action.
        metadata: Additional event-specific details such as failure reasons.
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
    """Record a successful user registration event."""

    await log_auth_event("signup", user_id=user_id, email=email, ip_address=ip, user_agent=ua)


async def log_login(user_id: str, email: str, ip: str, ua: str) -> None:
    """Record a successful authentication event for an existing user."""

    await log_auth_event("login", user_id=user_id, email=email, ip_address=ip, user_agent=ua)


async def log_login_failed(email: str, ip: str, ua: str, reason: str) -> None:
    """Record a failed login attempt with the reason in metadata."""

    await log_auth_event(
        "login_failed",
        email=email,
        ip_address=ip,
        user_agent=ua,
        success=False,
        metadata={"reason": reason},
    )


async def log_logout(user_id: str, all_devices: bool) -> None:
    """Record a logout event, optionally including whether all devices were signed out."""

    await log_auth_event("logout", user_id=user_id, metadata={"all_devices": all_devices})


async def log_password_reset(user_id: str, email: str, ip: str | None = None,
                             ua: str | None = None) -> None:
    """Record a completed password reset for a user, with request context."""

    await log_auth_event(
        "password_reset",
        user_id=user_id,
        email=email,
        ip_address=ip,
        user_agent=ua,
    )


async def log_password_reset_request(email: str, ip: str) -> None:
    """Record a password reset request from a given IP address."""

    await log_auth_event("password_reset_request", email=email, ip_address=ip)


async def log_email_verified(user_id: str, email: str) -> None:
    """Record successful email verification for the user."""

    await log_auth_event("email_verified", user_id=user_id, email=email)


async def log_token_refresh(user_id: str) -> None:
    """Record a JWT refresh for an authenticated user."""

    await log_auth_event("token_refresh", user_id=user_id)


async def log_account_locked(email: str, ip: str) -> None:
    """Record that an account was locked due to repeated failed attempts."""

    await log_auth_event(
        "account_locked",
        email=email,
        ip_address=ip,
        metadata={"reason": "max_attempts_exceeded"},
    )

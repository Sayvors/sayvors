"""Email API routes.

This module exposes the email-related endpoints used by the application:

- POST /api/v1/email/send: sends a generic transactional notification.
  PLATFORM-ADMIN ONLY — this is a sending capability, not a tenant feature.
  Recipients are restricted to the platform's own sending domain unless
  EMAIL_SEND_ALLOW_ANY_RECIPIENT is explicitly enabled.
- POST /api/v1/email/otp/request: issues a one-time passcode for public flows like
  signup or login. Requests are rate-limited by IP and email address.
- POST /api/v1/email/otp/verify: validates a previously sent OTP code for a given email.
  Rate-limited; the OTP itself enforces a hard per-code attempt budget (see service).
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...core.deps import get_db, require_admin
from ..auth.rate_limit import rate_limit
from ..users.models import User
from . import service

router = APIRouter(prefix="/api/v1/email", tags=["email"])


class SendRequest(BaseModel):
    """Payload for sending a standard notification email.

    Attributes:
        to: Recipient email address.
        subject: Email subject line.
        message: Plain-text content for the body (rendered as escaped text).
        cta_url: Optional call-to-action destination used by templates.
    """

    to: EmailStr
    subject: str = Field(..., min_length=1, max_length=200)
    message: str = Field(..., min_length=1, max_length=5000)
    cta_url: str | None = None


class OtpRequest(BaseModel):
    """Request model for generating a verification code.

    The purpose field helps identify the flow requesting the OTP, such as signup,
    login, or password recovery.
    """

    email: EmailStr
    purpose: str = Field("verification", max_length=40)


class OtpVerify(BaseModel):
    """Payload for verifying an email OTP against a stored value."""

    email: EmailStr
    code: str = Field(..., min_length=4, max_length=10)


def _recipient_allowed(to: str) -> bool:
    """Restrict outbound generic email to the platform's own sending domain.

    A generic send-to-anyone primitive from a free signup account turns the
    product into a spam/phishing relay on our domain. Internal notifications
    only need to reach our own users' addresses on the sending domain.
    """
    if settings.EMAIL_SEND_ALLOW_ANY_RECIPIENT:
        return True
    from_domain = (settings.EMAIL_FROM or "").rsplit("@", 1)[-1].strip().lower()
    to_domain = to.rsplit("@", 1)[-1].strip().lower()
    return bool(from_domain) and to_domain == from_domain


@router.post("/send")
async def send_notification(
    body: SendRequest,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    """Send a generic notification email (platform admin only).

    Recipients are limited to the platform sending domain; the body is
    plain text (HTML-escaped server-side) and cta_url must be an absolute
    http(s) URL.
    """
    ip = request.client.host if request.client else "unknown"
    if not await rate_limit(f"email-send:{ip}", 10, 60):
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")

    if not _recipient_allowed(str(body.to)):
        raise HTTPException(status_code=403, detail="Recipient domain is not allowed.")

    try:
        msg_id = await service.send_notification_email(
            str(body.to), body.subject, body.message, body.cta_url
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"ok": True, "id": msg_id}


@router.post("/otp/request")
async def request_otp(body: OtpRequest, request: Request):
    """Request a one-time password for a public email verification flow.

    Requests are throttled per IP and email to reduce spam and abuse. The endpoint
    returns a generic success response to avoid exposing whether an address exists.
    """

    ip = request.client.host if request.client else "unknown"
    if not await rate_limit(f"otp:{ip}:{str(body.email).lower()}", 3, 300):
        raise HTTPException(status_code=429, detail="Too many codes requested. Try again in a few minutes.")
    try:
        await service.send_otp_email(str(body.email), body.purpose)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {"ok": True, "message": "Code sent (valid 10 minutes)."}


@router.post("/otp/verify")
async def check_otp(body: OtpVerify, request: Request):
    """Validate a one-time password sent to the provided email address.

    Rate-limited per IP+email; the OTP additionally carries a hard attempt
    budget (5 wrong entries invalidate the code), so this endpoint cannot be
    used as an unthrottled guessing oracle.
    """

    ip = request.client.host if request.client else "unknown"
    if not await rate_limit(f"otp-verify:{ip}:{str(body.email).lower()}", 10, 60):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")
    ok = await service.verify_otp(str(body.email), body.code)
    if not ok:
        raise HTTPException(status_code=400, detail="Invalid or expired code.")
    return {"ok": True, "verified": True}


# ── Resend webhook ──────────────────────────────────────────────────────
# Delivery/bounce/complaint events. Svix-signed; an unsigned request is
# rejected rather than trusted, because a forged "unsubscribed" event would
# suppress arbitrary addresses.

def _verify_svix(headers, body: bytes) -> bool:
    import base64
    import hashlib
    import hmac
    import time

    secret = (settings.RESEND_WEBHOOK_SECRET or "").strip()
    if not secret:
        return False
    msg_id = headers.get("svix-id") or ""
    timestamp = headers.get("svix-timestamp") or ""
    signatures = headers.get("svix-signature") or ""
    if not msg_id or not timestamp or not signatures:
        return False
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    if abs(int(time.time()) - ts) > 300:
        return False
    raw_secret = secret.split("_", 1)[1] if secret.startswith("whsec_") else secret
    try:
        key = base64.b64decode(raw_secret)
    except Exception:
        return False
    signed = f"{msg_id}.{timestamp}.".encode() + body
    expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    for part in signatures.split():
        value = part.split(",", 1)[1] if "," in part else part
        if hmac.compare_digest(value, expected):
            return True
    return False


@router.post("/webhook/resend")
async def resend_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Resend delivery events → outbox status, events and suppressions."""
    import json

    from .outbox import apply_provider_event

    body = await request.body()
    if not _verify_svix(request.headers, body):
        raise HTTPException(status_code=401, detail="Invalid webhook signature.")
    try:
        payload = json.loads(body)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON.") from None
    event_type = str(payload.get("type") or "")
    data = payload.get("data") or {}
    recipients = data.get("to") or []
    email = recipients[0] if isinstance(recipients, list) and recipients else None
    if isinstance(recipients, str):
        email = recipients
    await apply_provider_event(
        db,
        event_type=event_type,
        provider_id=str(data.get("email_id") or "") or None,
        email=email,
        detail=json.dumps(data, default=str)[:1000],
        provider_event_id=request.headers.get("svix-id"),
    )
    return {"ok": True}


@router.get("/unsubscribe", response_class=HTMLResponse)
@router.post("/unsubscribe", response_class=HTMLResponse)
async def unsubscribe(email: str, token: str, db: AsyncSession = Depends(get_db)):
    """One-click unsubscribe (also target of List-Unsubscribe-Post)."""
    from .outbox import suppress, verify_unsubscribe_token

    if not verify_unsubscribe_token(email, token):
        raise HTTPException(status_code=400, detail="Invalid unsubscribe link.")
    normalized = email.strip().lower()
    await suppress(db, normalized, "unsubscribe", "one-click link")
    await db.execute(
        update(User).where(func.lower(User.email) == normalized).values(newsletter=False)
    )
    await db.commit()
    return HTMLResponse(
        "<html><body style=\"font-family:Arial,sans-serif;padding:40px;text-align:center\">"
        "<h1>Unsubscribed</h1><p>You will not receive further email from Sayvors.</p>"
        "</body></html>"
    )

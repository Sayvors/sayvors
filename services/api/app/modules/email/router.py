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
from pydantic import BaseModel, EmailStr, Field

from ...config import settings
from ...core.deps import require_admin
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

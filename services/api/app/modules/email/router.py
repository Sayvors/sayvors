"""Email API routes.

This module exposes the email-related endpoints used by the application:

- POST /api/v1/email/send: sends a generic transactional notification to a recipient.
  This endpoint is protected and requires an authenticated user.
- POST /api/v1/email/otp/request: issues a one-time passcode for public flows like
  signup or login. Requests are rate-limited by IP and email address.
- POST /api/v1/email/otp/verify: validates a previously sent OTP code for a given email.

The handlers intentionally keep validation and business logic separated from the HTTP
layer so the service layer owns the actual sending and verification behavior.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from ...core.deps import get_current_user
from ..auth.rate_limit import rate_limit
from ..users.models import User
from . import service

router = APIRouter(prefix="/api/v1/email", tags=["email"])


class SendRequest(BaseModel):
    """Payload for sending a standard notification email.

    Attributes:
        to: Recipient email address.
        subject: Email subject line.
        message: Plain-text or HTML-like content for the body.
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


@router.post("/send")
async def send_notification(body: SendRequest, _user: User = Depends(get_current_user)):
    """Send a generic notification email for an authenticated user.

    This endpoint is intended for internal application notifications such as
    administrative alerts, user updates, and other non-public communications.
    """

    try:
        msg_id = await service.send_notification_email(
            str(body.to), body.subject, body.message, body.cta_url
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
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
async def check_otp(body: OtpVerify):
    """Validate a one-time password sent to the provided email address."""

    ok = await service.verify_otp(str(body.email), body.code)
    if not ok:
        raise HTTPException(status_code=400, detail="Invalid or expired code.")
    return {"ok": True, "verified": True}

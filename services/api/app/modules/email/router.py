"""Email endpoints.

- POST /api/v1/email/send        generic send (logged-in users, for notifications)
- POST /api/v1/email/otp/request public OTP request (for signup / login flows)
- POST /api/v1/email/otp/verify  public OTP check
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from ...core.deps import get_current_user
from ..users.models import User
from . import service

router = APIRouter(prefix="/api/v1/email", tags=["email"])


class SendRequest(BaseModel):
    to: EmailStr
    subject: str = Field(..., min_length=1, max_length=200)
    message: str = Field(..., min_length=1, max_length=5000)
    cta_url: str | None = None


class OtpRequest(BaseModel):
    email: EmailStr
    purpose: str = Field("verification", max_length=40)


class OtpVerify(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=4, max_length=10)


@router.post("/send")
async def send_notification(body: SendRequest, _user: User = Depends(get_current_user)):
    try:
        msg_id = await service.send_notification_email(
            str(body.to), body.subject, body.message, body.cta_url
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {"ok": True, "id": msg_id}


@router.post("/otp/request")
async def request_otp(body: OtpRequest):
    try:
        await service.send_otp_email(str(body.email), body.purpose)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {"ok": True, "message": "Code sent (valid 10 minutes)."}


@router.post("/otp/verify")
async def check_otp(body: OtpVerify):
    ok = await service.verify_otp(str(body.email), body.code)
    if not ok:
        raise HTTPException(status_code=400, detail="Invalid or expired code.")
    return {"ok": True, "verified": True}

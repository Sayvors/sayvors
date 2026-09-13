from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...core.deps import get_current_user, get_db
from ...security import generate_csrf_token
from ..auth.rate_limit import rate_limit
from .schemas import (
    SignupRequest,
    LoginRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    VerifyEmailRequest,
    VerifyOtpRequest,
    LogoutRequest,
)
from .service import (
    signup,
    login,
    refresh_tokens,
    logout,
    forgot_password,
    reset_password,
    verify_email,
    verify_signup_otp,
    get_user_sessions,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _ip_in_trusted_proxy(ip: str) -> bool:
    """Check whether a peer IP matches a configured trusted proxy (IP or CIDR)."""
    import ipaddress

    if not ip or ip == "unknown":
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in settings.TRUSTED_PROXIES:
        try:
            if addr in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False


def get_client_ip(request: Request) -> str:
    """Resolve the real client IP.

    Forwarded headers (X-Forwarded-For / X-Real-IP) are only trusted when the
    direct peer is a configured trusted proxy — otherwise any client could
    spoof them to bypass IP-based rate limits. When trusted, we take the
    rightmost XFF entry (the one added by our closest trusted proxy), not the
    leftmost (fully client-controlled).
    """
    peer = request.client.host if request.client else ""
    if not _ip_in_trusted_proxy(peer):
        return peer or "unknown"

    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        # Rightmost entry was appended by the closest trusted proxy.
        return forwarded_for.split(",")[-1].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return peer or "unknown"


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup_endpoint(
    body: SignupRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    ip = get_client_ip(request)
    user_agent = request.headers.get("user-agent", "")

    if not await rate_limit(f"signup:{ip}", 5, 60):
        raise HTTPException(status_code=429, detail="Too many signup attempts. Try again later.")

    try:
        result = await signup(body, db, user_agent, ip)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    verification_token = result.pop("verification_token", None)
    refresh_token = result.pop("refresh_token")

    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=settings.REFRESH_COOKIE_MAX_AGE,
        path="/",
    )

    csrf_token = generate_csrf_token()
    response.set_cookie(
        key=settings.CSRF_COOKIE_NAME,
        value=csrf_token,
        httponly=False,
        secure=True,
        samesite="lax",
        max_age=settings.REFRESH_COOKIE_MAX_AGE,
        path="/",
    )

    return {
        "access_token": result["access_token"],
        "user": result["user"],
    }


@router.post("/login")
async def login_endpoint(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    ip = get_client_ip(request)
    user_agent = request.headers.get("user-agent", "")

    if not await rate_limit(f"login:ip:{ip}", 10, 60):
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.")
    # Per-identity limit stops one account being hammered from many IPs.
    if not await rate_limit(f"login:user:{body.email.lower()}", 10, 60):
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.")

    try:
        result = await login(body, db, user_agent, ip)
    except ValueError as e:
        if str(e).startswith("EMAIL_NOT_VERIFIED"):
            raise HTTPException(
                status_code=403,
                detail={"code": "email_not_verified", "message": str(e).split(": ", 1)[-1]},
            )
        raise HTTPException(status_code=401, detail=str(e))

    refresh_token = result.pop("refresh_token")

    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=settings.REFRESH_COOKIE_MAX_AGE,
        path="/",
    )

    csrf_token = generate_csrf_token()
    response.set_cookie(
        key=settings.CSRF_COOKIE_NAME,
        value=csrf_token,
        httponly=False,
        secure=True,
        samesite="lax",
        max_age=settings.REFRESH_COOKIE_MAX_AGE,
        path="/",
    )

    return result


@router.post("/refresh")
async def refresh_endpoint(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    refresh_token: str | None = Cookie(default=None, alias=settings.REFRESH_COOKIE_NAME),
):
    if not refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token")

    ip = get_client_ip(request)
    user_agent = request.headers.get("user-agent", "")
    if not await rate_limit(f"refresh:{ip}", 30, 60):
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")

    try:
        result = await refresh_tokens(refresh_token, db, user_agent=user_agent, ip=ip)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    new_refresh = result.pop("refresh_token")
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=new_refresh,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=settings.REFRESH_COOKIE_MAX_AGE,
        path="/",
    )

    csrf_token = generate_csrf_token()
    response.set_cookie(
        key=settings.CSRF_COOKIE_NAME,
        value=csrf_token,
        httponly=False,
        secure=True,
        samesite="lax",
        max_age=settings.REFRESH_COOKIE_MAX_AGE,
        path="/",
    )

    return result


@router.post("/logout")
async def logout_endpoint(
    body: LogoutRequest,
    response: Response,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await logout(body.refresh_token, user.id, body.all_devices, db)
    response.delete_cookie(settings.REFRESH_COOKIE_NAME, path="/")
    response.delete_cookie(settings.CSRF_COOKIE_NAME, path="/")
    return {"message": "Logged out"}


@router.post("/csrf-token")
async def csrf_token_endpoint(response: Response):
    csrf_token = generate_csrf_token()
    response.set_cookie(
        key=settings.CSRF_COOKIE_NAME,
        value=csrf_token,
        httponly=False,
        secure=True,
        samesite="lax",
        max_age=settings.REFRESH_COOKIE_MAX_AGE,
        path="/",
    )
    return {"csrf_token": csrf_token}


@router.post("/forgot-password")
async def forgot_password_endpoint(
    body: ForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    ip = get_client_ip(request)
    if not await rate_limit(f"forgot:{ip}", 3, 60):
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")

    token = await forgot_password(body, db, ip)
    # Email is sent inside forgot_password(); keep the response generic
    # so account existence is never revealed.
    return {"message": "If email exists, a reset link has been sent"}


@router.post("/reset-password")
async def reset_password_endpoint(
    body: ResetPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    ip = get_client_ip(request)
    if not await rate_limit(f"reset:{ip}", 3, 60):
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")

    try:
        await reset_password(body, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"message": "Password reset successful"}


@router.post("/verify-email")
async def verify_email_endpoint(
    body: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        await verify_email(body.token, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"message": "Email verified successfully"}


@router.post("/verify-otp")
async def verify_otp_endpoint(
    body: VerifyOtpRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    ip = get_client_ip(request)
    user_agent = request.headers.get("user-agent", "")
    if not await rate_limit(f"verify-otp:{ip}", 10, 60):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")
    try:
        result = await verify_signup_otp(str(body.email), body.code, db, user_agent, ip)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    refresh_token = result.pop("refresh_token")
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=settings.REFRESH_COOKIE_MAX_AGE,
        path="/",
    )
    csrf_token = generate_csrf_token()
    response.set_cookie(
        key=settings.CSRF_COOKIE_NAME,
        value=csrf_token,
        httponly=False,
        secure=True,
        samesite="lax",
        max_age=settings.REFRESH_COOKIE_MAX_AGE,
        path="/",
    )
    return result


@router.get("/me")
async def me(user=Depends(get_current_user)):
    return {
        "id": user.id,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "email_verified": user.email_verified,
        "onboarded": user.onboarded,
        "theme": user.theme or "light",
        "language": user.language or "en",
        "created_at": user.created_at.isoformat(),
    }


@router.patch("/me")
async def update_me(body: dict, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    allowed_fields = {"onboarded", "first_name", "last_name"}
    update_data = {k: v for k, v in body.items() if k in allowed_fields}
    if not update_data:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    for field, value in update_data.items():
        setattr(user, field, value)
    db.add(user)
    await db.commit()
    return {"message": "Updated"}


@router.get("/sessions")
async def sessions(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    sessions = await get_user_sessions(user.id, db)
    return {"sessions": sessions}

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
    get_user_sessions,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def get_client_ip(request: Request) -> str:
    # Only trust X-Forwarded-For from a known reverse proxy (the first hop).
    # In production behind a proxy, use the rightmost untrusted hop.
    # For now, use the first value (leftmost = original client behind trusted proxy).
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


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

    if not await rate_limit(f"login:{ip}", 10, 60):
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.")

    try:
        result = await login(body, db, user_agent, ip)
    except ValueError as e:
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
    if not await rate_limit(f"refresh:{ip}", 30, 60):
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")

    try:
        result = await refresh_tokens(refresh_token, db)
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
    if token:
        # TODO: send email with token
        pass
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


@router.get("/me")
async def me(user=Depends(get_current_user)):
    return {
        "id": user.id,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "email_verified": user.email_verified,
        "created_at": user.created_at.isoformat(),
    }


@router.get("/sessions")
async def sessions(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    sessions = await get_user_sessions(user.id, db)
    return {"sessions": sessions}

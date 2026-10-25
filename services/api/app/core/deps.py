from collections.abc import AsyncGenerator

import jwt
from fastapi import Cookie, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import async_session

security = HTTPBearer()
_optional_bearer = HTTPBearer(auto_error=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


async def get_current_user(
    access_cookie: str | None = Cookie(default=None, alias=settings.ACCESS_COOKIE_NAME),
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
    db: AsyncSession = Depends(get_db),
):
    # G2: access token lives in an httpOnly cookie, not the JSON body.
    # Read from cookie first (SPA), fall back to Bearer header (mobile/API).
    # When called directly in tests (no FastAPI DI), access_cookie may be a
    # Cookie() sentinel — treat non-str as None.
    if not isinstance(access_cookie, str):
        access_cookie = None
    token = access_cookie
    if token is None and credentials:
        token = credentials.credentials
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        user_id: str = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

        token_type = payload.get("type")
        if token_type != "access":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    from ..modules.users.models import User

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    # Team suspension is enforced here — not only in team get_context — so a
    # suspended member is blocked on EVERY authenticated endpoint (messages,
    # reviews, meta, billing…), including routes that never resolve a tenant
    # context. Owners (no tenant) and detached accounts are unaffected.
    if user.tenant_id and user.tenant_id != user.id:
        from ..modules.team.models import TeamMember

        member = (
            await db.execute(
                select(TeamMember.status).where(
                    TeamMember.user_id == user.id, TeamMember.tenant_id == user.tenant_id
                )
            )
        ).scalar_one_or_none()
        if member == "suspended":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account is suspended")
    # G1 revocation: a blacklisted jti (logout / reuse detection) or a stale
    # token version (password change / logout-all) must not authenticate.
    # is_token_blacklisted fails closed when Redis is down.
    from ..modules.auth.rate_limit import is_token_blacklisted

    if await is_token_blacklisted(payload.get("jti", "")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked")
    if payload.get("ver", 0) != (user.token_version or 0):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked")
    return user


async def require_admin(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
):
    """Platform admin gate: separate password, no user record.

    Accepts only tokens minted by the admin login (type claim "admin").
    Regular user access tokens are rejected here even when valid.

    Token source: Authorization header, else the httpOnly login cookie.
    /api/v1/admin/* is exempt from the global CSRF middleware, so a
    cookie-authenticated request MUST carry X-Requested-With — a custom
    header cannot be attached cross-origin without a CORS preflight that
    foreign origins will never pass.
    """
    cookie_auth = credentials is None
    token = credentials.credentials if credentials else request.cookies.get(settings.ADMIN_COOKIE_NAME, "")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin authentication required")
    if cookie_auth and request.headers.get("x-requested-with") != "XMLHttpRequest":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing CSRF header")
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required")
        operator_id = payload.get("sub")
        if operator_id and operator_id != "admin":
            from ..database import async_session
            from ..modules.admin.models import PlatformOperator

            async with async_session() as db:
                op_row = await db.get(PlatformOperator, operator_id)
            if op_row is None or not op_row.is_active:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Operator account disabled or removed")
            admin_ctx = {"admin": True, "operator_id": op_row.id, "username": op_row.username, "role": op_row.role}
        else:
            admin_ctx = {"admin": True, "operator_id": None, "username": "legacy-admin", "role": "superadmin"}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin session expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token")
    from ..modules.auth.rate_limit import is_token_blacklisted

    if await is_token_blacklisted(payload.get("jti", "")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin token revoked")
    return admin_ctx

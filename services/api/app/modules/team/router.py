"""Team management API: permission catalog, roles, members, invites.

Public surface (no session): GET /invites/preview and POST /invites/accept
— both are gated by the unguessable invite token, which doubles as the
anti-CSRF proof (that path is exempted in main.py). Everything else requires
authentication and is scoped by TenantContext; owners pass every check.
"""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...core.deps import get_current_user, get_db
from ...security import create_access_token, create_refresh_token, hash_token
from ..auth.models import RefreshToken
from ..auth.rate_limit import rate_limit, store_session
from ..auth.router import _set_session_cookies, get_client_ip
from ..channels.models import Channel
from ..users.models import User
from .context import TenantContext, get_context, require_perm
from .models import TeamMember, TeamRole
from .permissions import (
    ACTION_LABELS,
    AREA_LABELS,
    PERMISSION_CATALOG,
    ROLE_TEMPLATES,
    is_valid_permission,
    validate_role_permissions,
)
from . import service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/team", tags=["team"])


async def _optional_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """The accept endpoint works pre-auth (new account) and post-auth
    (existing account joins). Resolve a bearer token when one is presented;
    never raise for its absence."""
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    try:
        return await get_current_user_token(auth[7:].strip(), db)
    except HTTPException:
        return None


async def get_current_user_token(token: str, db: AsyncSession) -> User:
    """Same checks as core.deps.get_current_user, from a raw header string."""
    import jwt as _jwt

    from ...security import decode_token

    try:
        payload = decode_token(token)
    except _jwt.InvalidTokenError:
        # Expired/garbage bearer on the public accept endpoint is optional
        # auth: _optional_user catches this and treats the caller as anonymous.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
    user = await db.get(User, payload.get("sub", ""))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    from ..auth.rate_limit import is_token_blacklisted

    if await is_token_blacklisted(payload.get("jti", "")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked")
    if payload.get("ver", 0) != (user.token_version or 0):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked")
    return user


# ── schemas ──────────────────────────────────────────────


class RoleIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    permissions: list[str] = Field(default_factory=list)


class RolePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    permissions: list[str] | None = None


class InviteIn(BaseModel):
    email: EmailStr
    role_id: str
    channel_levels: dict[str, str] = Field(default_factory=dict)


class AcceptInviteIn(BaseModel):
    token: str = Field(min_length=10, max_length=256)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)


class MemberPatch(BaseModel):
    role_id: str | None = None
    status: str | None = None
    channel_levels: dict[str, str] | None = None


# ── catalog + context ────────────────────────────────────


@router.get("/permissions")
async def permission_catalog(user: object = Depends(get_current_user)):
    """Single source of truth for the role builder UI."""
    return {
        "areas": [
            {
                "area": area,
                "label": AREA_LABELS.get(area, area.title()),
                "actions": [
                    {"permission": f"{area}.{action}", "action": action,
                     "label": ACTION_LABELS.get(action, action.title())}
                    for action in actions
                ],
            }
            for area, actions in PERMISSION_CATALOG.items()
        ],
        "role_templates": [
            {"name": name, "permissions": perms, "is_system": True}
            for name, perms in ROLE_TEMPLATES.items()
        ],
    }


@router.get("/context")
async def team_context(
    ctx: TenantContext = Depends(get_context),
    db: AsyncSession = Depends(get_db),
):
    """What the signed-in principal may do — drives sidebar/nav gating."""
    owner = await db.get(User, ctx.tenant_id)
    business_name = None
    if owner is not None:
        business_name = (
            owner.business_name
            or f"{owner.first_name} {owner.last_name}".strip()
            or owner.email
        )
    return {
        "tenant_id": ctx.tenant_id,
        "business_name": business_name,
        "is_owner": ctx.is_owner,
        "role_name": ctx.role_name,
        "member_id": getattr(ctx.member, "id", None),
        "status": getattr(ctx.member, "status", "active"),
        "permissions": sorted(ctx.permissions),
        "channel_overrides": ctx.channel_overrides,
    }


# ── roles ────────────────────────────────────────────────


@router.get("/roles")
async def list_roles(
    ctx: TenantContext = Depends(require_perm("team.view")),
    db: AsyncSession = Depends(get_db),
):
    roles = await service.ensure_system_roles(db, ctx.tenant_id)
    await db.commit()
    return {
        "roles": [
            {"id": r.id, "name": r.name, "is_system": r.is_system,
             "permissions": r.permissions or [], "members_count": 0}
            for r in roles
        ]
    }


@router.post("/roles", status_code=status.HTTP_201_CREATED)
async def create_role(
    body: RoleIn,
    ctx: TenantContext = Depends(require_perm("team.manage")),
    db: AsyncSession = Depends(get_db),
):
    if not body.permissions:
        raise HTTPException(status_code=422, detail="A role needs at least one permission")
    perms = validate_role_permissions(body.permissions)
    dup = (
        await db.execute(
            select(TeamRole).where(TeamRole.tenant_id == ctx.tenant_id, TeamRole.name == body.name.strip())
        )
    ).scalar_one_or_none()
    if dup:
        raise HTTPException(status_code=409, detail="A role with this name already exists")
    role = await service.create_custom_role(db, ctx.tenant_id, body.name.strip(), perms)
    await db.commit()
    return {"id": role.id, "name": role.name, "is_system": False, "permissions": role.permissions}


async def _tenant_role(db: AsyncSession, tenant_id: str, role_id: str) -> TeamRole:
    role = await db.get(TeamRole, role_id)
    if role is None or role.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Role not found")
    return role


@router.patch("/roles/{role_id}")
async def patch_role(
    role_id: str,
    body: RolePatch,
    ctx: TenantContext = Depends(require_perm("team.manage")),
    db: AsyncSession = Depends(get_db),
):
    role = await _tenant_role(db, ctx.tenant_id, role_id)
    if role.is_system:
        raise HTTPException(status_code=400, detail="System roles cannot be edited — clone it as a custom role")
    if body.permissions is not None:
        if not body.permissions:
            raise HTTPException(status_code=422, detail="A role needs at least one permission")
        role.permissions = validate_role_permissions(body.permissions)
    if body.name is not None and body.name.strip() != role.name:
        dup = (
            await db.execute(
                select(TeamRole).where(TeamRole.tenant_id == ctx.tenant_id, TeamRole.name == body.name.strip())
            )
        ).scalar_one_or_none()
        if dup:
            raise HTTPException(status_code=409, detail="A role with this name already exists")
        role.name = body.name.strip()
    await db.commit()
    return {"id": role.id, "name": role.name, "is_system": False, "permissions": role.permissions}


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: str,
    ctx: TenantContext = Depends(require_perm("team.manage")),
    db: AsyncSession = Depends(get_db),
):
    role = await _tenant_role(db, ctx.tenant_id, role_id)
    if role.is_system:
        raise HTTPException(status_code=400, detail="System roles cannot be deleted")
    in_use = (
        await db.execute(select(TeamMember.id).where(TeamMember.role_id == role_id).limit(1))
    ).scalar_one_or_none()
    if in_use:
        raise HTTPException(status_code=409, detail="This role is assigned to team members")
    await db.delete(role)
    await db.commit()


# ── members ──────────────────────────────────────────────


@router.get("/members")
async def list_members(
    ctx: TenantContext = Depends(require_perm("team.view")),
    db: AsyncSession = Depends(get_db),
):
    await service.ensure_system_roles(db, ctx.tenant_id)
    members = await service.list_members(db, ctx.tenant_id)
    roles = await service.list_roles(db, ctx.tenant_id)
    roles_by_id = {r.id: r for r in roles}

    user_ids = [m.user_id for m in members if m.user_id]
    users_by_id = {}
    if user_ids:
        users_by_id = {
            u.id: u
            for u in (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars()
        }
    owner = await db.get(User, ctx.tenant_id)

    out = []
    if owner is not None:
        out.append({
            "id": None, "email": owner.email, "name": f"{owner.first_name} {owner.last_name}".strip(),
            "role_name": "Owner", "role_id": None, "is_owner": True, "status": "active",
            "invited_at": None, "accepted_at": None, "channels": None,
        })
    member_entries = []
    for m in members:
        u = users_by_id.get(m.user_id) if m.user_id else None
        role = roles_by_id.get(m.role_id)
        entry = {
            "id": m.id, "email": m.email,
            "name": f"{u.first_name} {u.last_name}".strip() if u else m.email.split("@")[0],
            "role_name": role.name if role else "", "role_id": m.role_id,
            "is_owner": False, "status": m.status,
            "invited_at": m.invited_at.isoformat() if m.invited_at else None,
            "accepted_at": m.accepted_at.isoformat() if m.accepted_at else None,
            "channels": {},  # filled below from team_member_channels
        }
        out.append(entry)
        member_entries.append(entry)
    # per-channel overrides in one query
    from .models import TeamMemberChannel

    by_member = {m.id: entry for m, entry in zip(members, member_entries) if m.id}
    if by_member:
        rows = (
            await db.execute(
                select(TeamMemberChannel).where(TeamMemberChannel.member_id.in_(list(by_member)))
            )
        ).scalars()
        for row in rows:
            entry = by_member.get(row.member_id)
            if entry is not None:
                entry["channels"] = {**(entry["channels"] or {}), row.channel_id: row.level}
    await db.commit()
    return {"members": out}


@router.get("/channels")
async def tenant_channels(
    ctx: TenantContext = Depends(require_perm("team.view")),
    db: AsyncSession = Depends(get_db),
):
    """Minimal channel list for the invite/role access matrix (no secrets)."""
    rows = (
        await db.execute(
            select(Channel.id, Channel.platform, Channel.display_name, Channel.platform_user_id, Channel.status)
            .where(Channel.user_id == ctx.tenant_id)
            .order_by(Channel.display_name)
        )
    ).all()
    return {
        "channels": [
            {
                "id": r.id,
                "platform": getattr(r.platform, "value", str(r.platform)),
                "name": r.display_name or r.platform_user_id or r.id,
                "status": getattr(r.status, "value", str(r.status)),
            }
            for r in rows
        ]
    }


async def _tenant_member(db: AsyncSession, tenant_id: str, member_id: str) -> TeamMember:
    member = await service.get_member(db, tenant_id, member_id)
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")
    return member


@router.patch("/members/{member_id}")
async def patch_member(
    member_id: str,
    body: MemberPatch,
    ctx: TenantContext = Depends(require_perm("team.manage")),
    db: AsyncSession = Depends(get_db),
):
    member = await _tenant_member(db, ctx.tenant_id, member_id)
    if ctx.member is not None and member.id == ctx.member.id:
        raise HTTPException(status_code=400, detail="You cannot modify your own membership")
    if body.role_id is not None:
        role = await _tenant_role(db, ctx.tenant_id, body.role_id)
        await service.change_member_role(db, member, role)
    if body.status is not None:
        try:
            await service.set_member_status(db, member, body.status)
        except ValueError:
            raise HTTPException(status_code=422, detail="status must be active or suspended")
    if body.channel_levels is not None:
        await service.set_member_channels(db, member, body.channel_levels, tenant_id=ctx.tenant_id)
    await db.commit()
    return {"id": member.id, "status": member.status, "role_id": member.role_id}


@router.delete("/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    member_id: str,
    ctx: TenantContext = Depends(require_perm("team.manage")),
    db: AsyncSession = Depends(get_db),
):
    member = await _tenant_member(db, ctx.tenant_id, member_id)
    if ctx.member is not None and member.id == ctx.member.id:
        raise HTTPException(status_code=400, detail="You cannot remove yourself — ask the workspace owner")
    await service.remove_member(db, member)
    await db.commit()


# ── invites ──────────────────────────────────────────────


async def _business_name(db: AsyncSession, tenant_id: str) -> str:
    owner = await db.get(User, tenant_id)
    if owner and owner.business_name:
        return owner.business_name
    return owner.first_name if owner else "the team"


@router.post("/invites", status_code=status.HTTP_201_CREATED)
async def create_invite(
    body: InviteIn,
    request: Request,
    ctx: TenantContext = Depends(require_perm("team.manage")),
    db: AsyncSession = Depends(get_db),
):
    if not settings.TESTING:
        if not await rate_limit(f"team-invite:{ctx.tenant_id}", 20, 3600):
            raise HTTPException(status_code=429, detail="Too many invites — try again later")

    role = await _tenant_role(db, ctx.tenant_id, body.role_id)
    normalized = body.email.strip().lower()

    if ctx.is_owner and normalized == ctx.user.email.lower():
        raise HTTPException(status_code=400, detail="You already own this workspace — you have full access")

    existing_member = (
        await db.execute(
            select(TeamMember).where(
                TeamMember.tenant_id == ctx.tenant_id,
                TeamMember.email == normalized,
            )
        )
    ).scalar_one_or_none()
    if existing_member is not None:
        if existing_member.status == "active":
            raise HTTPException(status_code=409, detail="This person is already a member of this workspace")
        raise HTTPException(
            status_code=409,
            detail="This person already has a pending invite — use Resend instead",
        )

    existing_user = (
        await db.execute(select(User).where(User.email == normalized))
    ).scalar_one_or_none()
    if (
        existing_user is not None
        and existing_user.tenant_id not in (None, existing_user.id, ctx.tenant_id)
    ):
        raise HTTPException(
            status_code=409,
            detail="This person already works in another workspace",
        )

    try:
        member, raw = await service.invite_member(
            db, ctx.tenant_id, ctx.user.id, normalized, role, body.channel_levels or None,
        )
    except ValueError as e:
        if str(e) == "already_active":
            raise HTTPException(status_code=409, detail="This person is already an active member")
        raise
    await db.commit()

    invite_url = f"{settings.FRONTEND_URL.rstrip('/')}/invite/{raw}"
    from ..email.service import send_team_invite_email

    try:
        await send_team_invite_email(
            member.email,
            f"{ctx.user.first_name} {ctx.user.last_name}".strip() or ctx.user.email,
            await _business_name(db, ctx.tenant_id),
            role.name,
            invite_url,
        )
    except Exception:
        # The membership row exists — the UI can resend; never 500 after commit.
        logger.warning("Invite email failed for %s", member.email, exc_info=True)
    return {
        "id": member.id, "email": member.email, "status": member.status,
        "role_id": member.role_id, "role_name": role.name,
        "invited_at": member.invited_at.isoformat(),
        "expires_at": member.invite_expires_at.isoformat(),
    }


@router.get("/invites/preview")
async def invite_preview(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Public: what the /invite/[token] page renders before any action."""
    if not settings.TESTING:
        if not await rate_limit(f"team-preview:{get_client_ip(request)}", 30, 3600):
            raise HTTPException(status_code=429, detail="Too many requests")
    try:
        member = await service.get_invite(db, token)
    except ValueError as e:
        code = str(e)
        raise HTTPException(
            status_code=status.HTTP_410_GONE if code == "expired_token" else status.HTTP_404_NOT_FOUND,
            detail="This invite link has expired — ask for a new one" if code == "expired_token"
            else "This invite link is invalid or was already used",
        )
    role = await db.get(TeamRole, member.role_id)
    owner = await db.get(User, member.tenant_id)
    account_exists = (
        await db.execute(select(User.id).where(User.email == member.email))
    ).scalar_one_or_none() is not None
    return {
        "email": member.email,
        "business_name": (owner.business_name if owner and owner.business_name else None) or "Sayvors",
        "inviter_name": (
            f"{owner.first_name} {owner.last_name}".strip() if owner else ""
        ) or "the workspace owner",
        "role_name": role.name if role else "member",
        "expires_at": member.invite_expires_at.isoformat() if member.invite_expires_at else None,
        "account_exists": account_exists,
    }


@router.post("/invites/accept")
async def accept_invite(
    body: AcceptInviteIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(_optional_user),
):
    """Dual-path accept:
    - New email → creates the account (password required), signs them in.
    - Existing email → 401 login_required until that account authenticates,
      then the same call (with their session) completes the join. The token
      alone can never graft an existing account into a workspace.
    """
    if not settings.TESTING:
        if not await rate_limit(f"team-accept:{get_client_ip(request)}", 20, 3600):
            raise HTTPException(status_code=429, detail="Too many attempts — try again later")
    try:
        member = await service.get_invite(db, body.token)
    except ValueError as e:
        code = str(e)
        raise HTTPException(
            status_code=status.HTTP_410_GONE if code == "expired_token" else status.HTTP_404_NOT_FOUND,
            detail="This invite link has expired — ask for a new one" if code == "expired_token"
            else "This invite link is invalid or was already used",
        )

    existing_user = (
        await db.execute(select(User).where(User.email == member.email))
    ).scalar_one_or_none()

    if existing_user is not None:
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "login_required", "email": member.email},
            )
        if user.id != existing_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This invite is for {member.email} — sign in with that account",
            )
        other = (
            await db.execute(
                select(TeamMember.id).where(
                    TeamMember.user_id == user.id, TeamMember.tenant_id != member.tenant_id
                ).limit(1)
            )
        ).scalar_one_or_none()
        if other:
            raise HTTPException(status_code=409, detail="You are already a member of another workspace")
        member = await service.join_existing_user(db, member, user)
        await db.commit()
        return {"status": "joined", "email": user.email, "tenant_id": member.tenant_id}

    if not body.password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "password_required", "email": member.email},
        )
    created = await service.accept_invite_new_user(
        db, member, password=body.password,
        first_name=body.first_name, last_name=body.last_name,
    )
    await db.commit()

    # Sign the fresh account in (signup's session pattern).
    user_agent = request.headers.get("user-agent", "")
    ip = get_client_ip(request)
    refresh_raw = create_refresh_token(created.id)
    from ...security import create_token_fingerprint

    db.add(RefreshToken(
        user_id=created.id,
        token_hash=hash_token(refresh_raw),
        fingerprint=create_token_fingerprint(user_agent, ip),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_EXPIRATION_DAYS),
        user_agent=user_agent[:500],
        ip_address=ip[:45],
    ))
    await db.commit()
    _set_session_cookies(response, refresh_raw)
    try:
        await store_session(
            created.id, created.id,
            {"user_id": created.id, "ip": ip, "user_agent": user_agent[:200]},
            settings.JWT_REFRESH_EXPIRATION_DAYS * 86400,
        )
    except Exception:
        pass
    return {
        "status": "joined",
        "email": created.email,
        "tenant_id": created.tenant_id,
        "access_token": create_access_token(created.id, created.token_version or 0),
        "user": {
            "id": created.id, "first_name": created.first_name, "last_name": created.last_name,
            "email": created.email, "email_verified": True, "onboarded": created.onboarded,
        },
    }


@router.post("/invites/{member_id}/resend")
async def resend_invite(
    member_id: str,
    ctx: TenantContext = Depends(require_perm("team.manage")),
    db: AsyncSession = Depends(get_db),
):
    member = await _tenant_member(db, ctx.tenant_id, member_id)
    if member.status != "invited":
        raise HTTPException(status_code=400, detail="This member has already accepted their invite")
    role = await db.get(TeamRole, member.role_id)
    _, raw = await service.invite_member(
        db, ctx.tenant_id, ctx.user.id, member.email, role
    )
    await db.commit()
    from ...config import settings as _s

    invite_url = f"{_s.FRONTEND_URL.rstrip('/')}/invite/{raw}"
    from ..email.service import send_team_invite_email

    try:
        await send_team_invite_email(
            member.email, f"{ctx.user.first_name} {ctx.user.last_name}".strip() or ctx.user.email,
            await _business_name(db, ctx.tenant_id), role.name if role else "member", invite_url,
        )
    except Exception:
        logger.warning("Invite email failed on resend for %s", member.email, exc_info=True)
    return {"id": member.id, "status": member.status, "expires_at": member.invite_expires_at.isoformat()}


@router.delete("/invites/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(
    member_id: str,
    ctx: TenantContext = Depends(require_perm("team.manage")),
    db: AsyncSession = Depends(get_db),
):
    member = await _tenant_member(db, ctx.tenant_id, member_id)
    if member.status != "invited":
        raise HTTPException(status_code=400, detail="Only pending invites can be revoked")
    await service.remove_member(db, member)
    await db.commit()

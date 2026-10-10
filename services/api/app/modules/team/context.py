"""Request context for team RBAC.

`get_context` wraps `get_current_user` and resolves the workspace the
request acts on: owners act on their own tenant (tenant_id == user.id);
employees act on the workspace they were invited to (users.tenant_id).
Routers use `ctx.tenant_id` for scoping and `require_perm(...)` for
authorization — the database stays the source of truth (no role claims
in the JWT, so permission changes apply on the next request).
"""

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_current_user, get_db

# Virtual permissions for per-channel levels (never stored in roles —
# role-level channel defaults are channels.view / channels.edit).
CHANNEL_LEVEL_NONE = "none"
CHANNEL_LEVEL_VIEW = "view"
CHANNEL_LEVEL_EDIT = "edit"


def tenant_id_of(user) -> str:
    """The workspace a principal acts on: their tenant_id when they are an
    employee, else their own id (owner — tenant_id is NULL or self).
    Tenant-scoped queries in services use this instead of user.id."""
    tid = getattr(user, "tenant_id", None)
    return tid or user.id


@dataclass(frozen=True)
class TenantContext:
    user: object  # users.User row
    tenant_id: str  # the workspace this request acts on
    member: object | None  # team_members row; None ⇒ the owner themself
    role: object | None  # team_roles row (None for owners)
    permissions: frozenset[str]
    channel_overrides: dict[str, str]  # channel_id → "none"|"view"|"edit"

    @property
    def is_owner(self) -> bool:
        return self.member is None

    @property
    def role_name(self) -> str:
        if self.is_owner:
            return "Owner"
        return getattr(self.role, "name", "") if self.role else ""

    def has(self, perm: str) -> bool:
        """Catalog permission check (e.g. "inbox.reply"). Owners pass all."""
        return self.is_owner or perm in self.permissions

    def has_any(self, *perms: str) -> bool:
        return any(self.has(p) for p in perms)

    def channel_level(self, channel_id: str) -> str:
        """Effective per-channel access: member override, else the role's
        channel default, else nothing. Owners can do everything."""
        if self.is_owner:
            return CHANNEL_LEVEL_EDIT
        override = self.channel_overrides.get(channel_id)
        if override is not None:
            return override
        if "channels.edit" in self.permissions:
            return CHANNEL_LEVEL_EDIT
        if "channels.view" in self.permissions:
            return CHANNEL_LEVEL_VIEW
        return CHANNEL_LEVEL_NONE

    def can_edit_channel(self, channel_id: str) -> bool:
        return self.channel_level(channel_id) == CHANNEL_LEVEL_EDIT

    def visible_channel_ids(self) -> set[str] | None:
        """Channel ids the member may see at all (overrides denying view are
        excluded). None ⇒ no restriction beyond the role default (owners and
        role-default viewers see everything)."""
        if self.is_owner:
            return None
        if "channels.view" in self.permissions or "channels.edit" in self.permissions:
            return None
        return {cid for cid, lvl in self.channel_overrides.items() if lvl != CHANNEL_LEVEL_NONE}


async def get_context(
    user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TenantContext:
    from .models import TeamMember, TeamMemberChannel, TeamRole

    tenant_id = (getattr(user, "tenant_id", None) or user.id) or user.id
    if tenant_id == user.id:
        return TenantContext(
            user=user, tenant_id=user.id, member=None, role=None,
            permissions=frozenset(), channel_overrides={},
        )

    member = (
        await db.execute(
            select(TeamMember).where(
                TeamMember.tenant_id == tenant_id,
                TeamMember.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are no longer a member of this workspace",
        )
    if member.status == "suspended":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account is suspended")
    if member.status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invite not accepted yet")

    role = await db.get(TeamRole, member.role_id)
    permissions = frozenset(role.permissions or []) if role else frozenset()
    overrides = {
        row.channel_id: row.level
        for row in (
            await db.execute(select(TeamMemberChannel).where(TeamMemberChannel.member_id == member.id))
        ).scalars()
    }
    return TenantContext(
        user=user, tenant_id=tenant_id, member=member, role=role,
        permissions=permissions, channel_overrides=overrides,
    )


def require_perm(perm: str):
    """Dependency factory: gate an endpoint behind one catalog permission.

    Usage: `ctx: TenantContext = Depends(require_perm("team.manage"))` —
    the resolved context is returned so the handler can scope by ctx.tenant_id.
    """

    async def _dep(ctx: TenantContext = Depends(get_context)) -> TenantContext:
        if not ctx.has(perm):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing permission: {perm}")
        return ctx

    return _dep

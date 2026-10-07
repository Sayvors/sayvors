"""Team operations: role seeding/CRUD, invites, membership lifecycle.

Security model:
- Invite tokens are 32-byte urlsafe secrets; only the SHA-256 hash is stored
  (same pattern as password resets). Single-use: acceptance flips the member
  to active and clears the hash.
- Accepting never resets an existing account's password. A new email creates
  a fresh user attached to the workspace; an existing email must authenticate
  as that user (router enforces a valid session before joining).
- Removing a member detaches them: their users.tenant_id is cleared so they
  fall back to their own (empty) workspace.
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...security import generate_verification_token, hash_password, hash_token
from ..users.models import User
from .models import TeamMember, TeamMemberChannel, TeamRole
from .permissions import ROLE_TEMPLATES

logger = logging.getLogger(__name__)

INVITE_TTL_DAYS = 7


async def _system_roles_by_name(db: AsyncSession, tenant_id: str) -> dict[str, TeamRole]:
    rows = (
        await db.execute(
            select(TeamRole).where(TeamRole.tenant_id == tenant_id, TeamRole.is_system.is_(True))
        )
    ).scalars().all()
    return {r.name: r for r in rows}


async def ensure_system_roles(db: AsyncSession, tenant_id: str) -> list[TeamRole]:
    """Seed the read-only role templates once per workspace; idempotent.

    Existing system roles are re-synced to the current template — they are
    platform-managed (the API refuses edits), so a row written by an older
    catalog (e.g. Admin carrying a duplicated team.view) is repaired here.

    Race-safe: two parallel first-load requests (members + roles) can both
    find an empty workspace and both try to seed. The INSERT runs inside a
    savepoint, so the loser rolls back, re-reads the winner's rows and returns
    them instead of dying on uq_team_roles_tenant_name.
    """
    have = await _system_roles_by_name(db, tenant_id)
    if any(name not in have for name in ROLE_TEMPLATES):
        try:
            async with db.begin_nested():
                for name, perms in ROLE_TEMPLATES.items():
                    if name not in have:
                        db.add(TeamRole(
                            tenant_id=tenant_id, name=name, is_system=True, permissions=list(perms),
                        ))
                await db.flush()
        except IntegrityError:
            pass  # a concurrent request seeded first — re-read below
        have = await _system_roles_by_name(db, tenant_id)
    for name, perms in ROLE_TEMPLATES.items():
        role = have.get(name)
        if role is not None and role.permissions != list(perms):
            role.permissions = list(perms)
    await db.flush()
    return [have[name] for name in ROLE_TEMPLATES if name in have]


async def create_custom_role(db: AsyncSession, tenant_id: str, name: str, permissions: list[str]) -> TeamRole:
    role = TeamRole(tenant_id=tenant_id, name=name, is_system=False, permissions=list(permissions))
    db.add(role)
    await db.flush()
    return role


async def list_roles(db: AsyncSession, tenant_id: str) -> list[TeamRole]:
    return list(
        (await db.execute(select(TeamRole).where(TeamRole.tenant_id == tenant_id).order_by(TeamRole.created_at)))
        .scalars()
    )


async def list_members(db: AsyncSession, tenant_id: str) -> list[TeamMember]:
    return list(
        (
            await db.execute(
                select(TeamMember)
                .where(TeamMember.tenant_id == tenant_id)
                .order_by(TeamMember.invited_at.desc())
            )
        ).scalars()
    )


def _new_invite_token() -> tuple[str, str, datetime]:
    raw = generate_verification_token()
    expires = datetime.now(timezone.utc) + timedelta(days=INVITE_TTL_DAYS)
    return raw, hash_token(raw), expires


async def invite_member(
    db: AsyncSession,
    tenant_id: str,
    invited_by: str,
    email: str,
    role: TeamRole,
    channel_levels: dict[str, str] | None = None,
) -> tuple[TeamMember, str]:
    """Create a pending membership + its invite token (raw token returned
    once, for the email). Re-inviting a still-pending email rotates the
    token instead of failing the unique constraint."""
    normalized = email.strip().lower()
    member = (
        await db.execute(
            select(TeamMember).where(TeamMember.tenant_id == tenant_id, TeamMember.email == normalized)
        )
    ).scalar_one_or_none()
    raw, token_hash, expires = _new_invite_token()
    if member is None:
        member = TeamMember(
            tenant_id=tenant_id,
            email=normalized,
            role_id=role.id,
            status="invited",
            invited_by=invited_by,
        )
        db.add(member)
    elif member.status == "active":
        raise ValueError("already_active")
    member.role_id = role.id
    member.invite_token_hash = token_hash
    member.invite_expires_at = expires
    member.invited_by = invited_by
    member.invited_at = datetime.now(timezone.utc)
    if channel_levels:
        await set_member_channels(db, member, channel_levels, tenant_id=tenant_id)
    await db.flush()
    return member, raw


async def get_invite(db: AsyncSession, raw_token: str) -> TeamMember:
    """Resolve + validate a raw invite token without consuming it."""
    member = (
        await db.execute(select(TeamMember).where(TeamMember.invite_token_hash == hash_token(raw_token)))
    ).scalar_one_or_none()
    if member is None or member.status != "invited":
        raise ValueError("invalid_token")
    expires_at = member.invite_expires_at
    if expires_at is not None:
        # SQLite returns naive datetimes even for timezone=True columns —
        # normalize before comparing with the aware now(), or the TypeError
        # escapes as a 500 instead of a clean "expired" answer.
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            raise ValueError("expired_token")
    return member


async def accept_invite_new_user(
    db: AsyncSession,
    member: TeamMember,
    *,
    password: str,
    first_name: str | None = None,
    last_name: str | None = None,
) -> User:
    """Consume an invite by CREATING the account (email proved by receiving
    the invite). Never called when the email already has an account — the
    router sends those through authenticated join instead."""
    user = User(
        first_name=(first_name or "").strip() or "Teammate",
        last_name=(last_name or "").strip() or "",
        email=member.email,
        password_hash=hash_password(password),
        email_verified=True,
        tenant_id=member.tenant_id,
    )
    db.add(user)
    await db.flush()
    _activate_member(member, user)
    await db.flush()
    return user


def _activate_member(member: TeamMember, user: User) -> None:
    """Flip a pending invite to active membership (phase 1: one workspace
    per account — accepting moves users.tenant_id into the workspace)."""
    member.user_id = user.id
    member.status = "active"
    member.accepted_at = datetime.now(timezone.utc)
    member.invite_token_hash = None
    member.invite_expires_at = None
    user.tenant_id = member.tenant_id


async def join_existing_user(db: AsyncSession, member: TeamMember, user: User) -> TeamMember:
    """Complete a pending invite for an email that already has an account.
    The router has already authenticated that user — the invite link alone
    must never be able to graft an existing account into a workspace."""
    _activate_member(member, user)
    await db.flush()
    return member


async def set_member_channels(
    db: AsyncSession,
    member: TeamMember,
    channel_levels: dict[str, str],
    *,
    tenant_id: str,
) -> None:
    """Replace the member's per-channel overrides. Channel ids must belong
    to the workspace (channels.user_id == tenant_id); levels ∈ none|view|edit."""
    from ..channels.models import Channel

    valid_levels = {"none", "view", "edit"}
    clean = {cid: lvl for cid, lvl in channel_levels.items() if lvl in valid_levels}
    if clean:
        owned = set(
            (
                await db.execute(
                    select(Channel.id).where(
                        Channel.user_id == tenant_id, Channel.id.in_(set(clean))
                    )
                )
            ).scalars()
        )
        clean = {cid: lvl for cid, lvl in clean.items() if cid in owned}
    existing = (
        await db.execute(select(TeamMemberChannel).where(TeamMemberChannel.member_id == member.id))
    ).scalars().all()
    for row in existing:
        if row.channel_id not in clean:
            await db.delete(row)
        else:
            row.level = clean[row.channel_id]
    have = {r.channel_id for r in existing}
    for cid, lvl in clean.items():
        if cid not in have:
            db.add(TeamMemberChannel(member_id=member.id, channel_id=cid, level=lvl))
    await db.flush()


async def change_member_role(db: AsyncSession, member: TeamMember, role: TeamRole) -> None:
    member.role_id = role.id
    await db.flush()


async def set_member_status(db: AsyncSession, member: TeamMember, status: str) -> None:
    if status not in ("active", "suspended"):
        raise ValueError("bad_status")
    member.status = status
    await db.flush()


async def remove_member(db: AsyncSession, member: TeamMember) -> None:
    """Delete the membership and detach the user from the workspace.
    Overrides are removed explicitly — SQLite (tests) does not enforce
    ON DELETE CASCADE, and the explicit delete is harmless on Postgres."""
    from sqlalchemy import delete

    if member.user_id:
        user = await db.get(User, member.user_id)
        if user is not None and user.tenant_id == member.tenant_id:
            user.tenant_id = None
    await db.execute(delete(TeamMemberChannel).where(TeamMemberChannel.member_id == member.id))
    await db.delete(member)
    await db.flush()


async def list_member_overrides(db: AsyncSession, member_id: str) -> dict[str, str]:
    return {
        row.channel_id: row.level
        for row in (
            await db.execute(
                select(TeamMemberChannel).where(TeamMemberChannel.member_id == member_id)
            )
        ).scalars()
    }


async def get_member(db: AsyncSession, tenant_id: str, member_id: str) -> TeamMember | None:
    return (
        await db.execute(
            select(TeamMember).where(TeamMember.tenant_id == tenant_id, TeamMember.id == member_id)
        )
    ).scalar_one_or_none()


def secret_token() -> str:
    return secrets.token_urlsafe(32)

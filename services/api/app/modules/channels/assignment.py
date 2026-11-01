"""Conversation assignment: who owns a handoff.

A handoff used to be a flag. `conversation_mode="human"` says the AI is muted;
it does not say which human is responsible. This module is the only writer of
`assigned_to` on threads, leads and review tickets, so the three surfaces
cannot disagree about the owner.

Rules that matter at team scale:

* **Only real, active teammates who can work the channel.** A pending invite
  has no user_id yet; a member without `inbox.reply` (or `reviews.reply` for a
  Google channel) cannot answer; a member with no channel access cannot open
  the thread. All three are filtered out here rather than letting an
  unopenable thread be assigned.
* **Tenant scope comes from the caller, never the request body.** Every query
  is scoped by the workspace and the channel must belong to it.
* **The lead mirrors the thread.** The leads board and digest read the lead
  row, so the same write lands there; otherwise "mine" would mean two things.
* **Silence is not ownership.** Assigning to yourself records the owner but
  does not notify you; assigning someone else writes one directed
  notification and broadcasts the change to open tabs.
"""

import logging
from datetime import datetime, timezone
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..notifications.service import notify
from ..team.models import TeamMember, TeamMemberChannel, TeamRole
from ..users.models import User
from .models import Channel, Lead

logger = logging.getLogger(__name__)


class AssignmentError(Exception):
    """A request that cannot be honoured (bad assignee / missing channel)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _display_name(user: User | None) -> str:
    if user is None:
        return ""
    return (
        f"{user.first_name or ''} {user.last_name or ''}".strip()
        or user.email
        or user.id
    )


def _needed_permission(channel: Channel) -> str:
    """What a person must be able to do to own this channel's work."""
    return "reviews.reply" if channel.platform == "google_reviews" else "inbox.reply"


def _channel_level(permissions: set[str], override: str | None) -> str:
    if override in {"view", "edit", "none"}:
        return override
    if "channels.edit" in permissions:
        return "edit"
    if "channels.view" in permissions:
        return "view"
    return "none"


async def _tenant_channel(
    db: AsyncSession, tenant_id: str, channel_id: str
) -> Channel:
    channel = (
        await db.execute(
            select(Channel).where(
                Channel.id == channel_id,
                Channel.user_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if channel is None:
        raise AssignmentError("Channel not found")
    return channel


async def assignable_users(
    db: AsyncSession, tenant_id: str, channel_id: str
) -> list[dict]:
    """People who can actually take this channel's conversations.

    Owner first, then active members by name. Excludes pending invites,
    suspended members, members without the reply capability, and members with
    no access to this channel.
    """
    channel = await _tenant_channel(db, tenant_id, channel_id)
    needed = _needed_permission(channel)

    owner = await db.get(User, tenant_id)
    rows = (
        await db.execute(
            select(TeamMember, TeamRole)
            .join(TeamRole, TeamRole.id == TeamMember.role_id)
            .where(
                TeamMember.tenant_id == tenant_id,
                TeamMember.status == "active",
                TeamMember.user_id.isnot(None),
            )
        )
    ).all()
    member_ids = [m.id for m, _ in rows]
    overrides: dict[str, str] = {}
    if member_ids:
        overrides = {
            row.member_id: row.level
            for row in (
                await db.execute(
                    select(TeamMemberChannel).where(
                        TeamMemberChannel.member_id.in_(member_ids),
                        TeamMemberChannel.channel_id == channel_id,
                    )
                )
            ).scalars()
        }
    user_ids = [m.user_id for m, _ in rows if m.user_id]
    users = {}
    if user_ids:
        users = {
            u.id: u
            for u in (
                await db.execute(select(User).where(User.id.in_(user_ids)))
            ).scalars()
        }

    out: list[dict] = []
    if owner is not None:
        out.append({
            "user_id": owner.id,
            "name": _display_name(owner),
            "email": owner.email,
            "role_name": "Owner",
            "is_owner": True,
        })

    seen = {owner.id} if owner is not None else set()
    for member, role in rows:
        user = users.get(member.user_id)
        if user is None or user.id in seen:
            continue
        permissions = set(role.permissions or [])
        if needed not in permissions:
            continue
        if _channel_level(permissions, overrides.get(member.id)) == "none":
            continue
        seen.add(user.id)
        out.append({
            "user_id": user.id,
            "name": _display_name(user),
            "email": user.email,
            "role_name": role.name,
            "is_owner": False,
        })

    out.sort(key=lambda u: (0 if u["is_owner"] else 1, u["name"].lower()))
    return out


async def validate_assignee(
    db: AsyncSession,
    tenant_id: str,
    channel_id: str,
    user_id: str | None,
) -> dict | None:
    """Return the assignee entry, or None for an unassignment.

    Raises AssignmentError for a user who is not allowed to own this channel.
    """
    if not user_id:
        return None
    allowed = {
        person["user_id"]: person
        for person in await assignable_users(db, tenant_id, channel_id)
    }
    person = allowed.get(user_id)
    if person is None:
        raise AssignmentError(
            "That person cannot be assigned this conversation. They must be an "
            "active teammate with access to this channel."
        )
    return person


async def assign_thread(
    db: AsyncSession,
    *,
    tenant_id: str,
    channel_id: str,
    contact_phone: str,
    assignee_id: str | None,
    actor: User,
) -> dict | None:
    """Set or clear the owner of one conversation, mirroring the lead row.

    Returns the assignee payload (None when unassigned), or raises
    AssignmentError. Commits; the caller reads the thread state afterwards.
    """
    from .conversation_mode import get_thread

    thread = await get_thread(db, channel_id, contact_phone)
    if thread is None:
        raise AssignmentError("Conversation not found")

    assignee = await validate_assignee(db, tenant_id, channel_id, assignee_id)
    now = _now() if assignee_id else None
    thread.assigned_to = assignee_id
    thread.assigned_at = now

    # The leads board and digest read the lead row; mirror the same owner so
    # "mine" cannot mean two different things on two screens.
    leads = (
        await db.execute(
            select(Lead).where(
                Lead.tenant_id == tenant_id,
                Lead.channel_id == channel_id,
                Lead.contact_id == contact_phone,
                Lead.merged_into_id.is_(None),
            )
        )
    ).scalars().all()
    for lead in leads:
        lead.assigned_to = assignee_id
        lead.assigned_at = now
        db.add(lead)

    db.add(thread)

    if assignee_id and assignee_id != actor.id:
        actor_name = _display_name(actor) or "A teammate"
        await notify(
            db,
            assignee_id,
            "assignment",
            f"{actor_name} assigned a conversation to you",
            body=thread.contact_name or contact_phone,
            data={
                "channel_id": channel_id,
                "contact_phone": contact_phone,
                "assigned_by": actor.id,
            },
            href=(
                f"/dashboard/channels/inbox?channel={quote(channel_id, safe='')}"
                f"&key={quote(contact_phone, safe='')}"
            ),
        )

    await db.commit()

    from .realtime import publish_inbox_event

    await publish_inbox_event(tenant_id, {
        "type": "assignment",
        "channel_id": channel_id,
        "contact_phone": contact_phone,
        "assigned_to": assignee_id,
        "assignee_name": assignee["name"] if assignee else None,
        "assigned_at": now.isoformat() if now else None,
    })
    if assignee_id and assignee_id != actor.id:
        await publish_inbox_event(tenant_id, {
            "type": "notification",
            "notification": {
                "kind": "assignment",
                "channel_id": channel_id,
                "contact_id": contact_phone,
                "contact_name": thread.contact_name,
                "preview": "A conversation was assigned to you.",
            },
        })

    logger.info(
        "thread assigned channel=%s contact=%s to=%s by=%s",
        channel_id, contact_phone, assignee_id, actor.id,
    )
    return assignee


async def assign_review_issue(
    db: AsyncSession,
    *,
    tenant_id: str,
    issue,
    assignee_id: str | None,
    actor: User,
) -> dict | None:
    """Set the owner on a review ticket. The caller commits and broadcasts."""
    assignee = await validate_assignee(
        db, tenant_id, issue.channel_id, assignee_id
    )
    issue.assigned_to = assignee_id
    issue.assigned_at = _now() if assignee_id else None

    if assignee_id and assignee_id != actor.id:
        actor_name = _display_name(actor) or "A teammate"
        await notify(
            db,
            assignee_id,
            "assignment",
            f"{actor_name} assigned a review ticket to you",
            body=issue.ticket_number or issue.reviewer_name or issue.summary,
            data={"issue_id": issue.id, "channel_id": issue.channel_id},
            href="/dashboard/reviews/issues",
        )
    return assignee

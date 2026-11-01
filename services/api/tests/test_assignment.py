"""HAND-10: a handoff has an owner, not just a flag.

Covers the assignable set (tenant scope + channel access), the thread/lead
mirror, the notification, the inbox endpoints, and review-ticket assignment.
"""
import uuid

import pytest
from sqlalchemy import select

from app.modules.channels import assignment
from app.modules.channels.models import (
    Channel,
    ChannelMessage,
    Lead,
    ReviewIssue,
)
from app.modules.channels.service import hash_contact_phone
from app.modules.notifications.models import Notification
from app.modules.team.models import TeamMember, TeamRole
from app.modules.users.models import User

OWNER = "assign-owner"
PHONE = "+966500000020"


def _user(user_id: str, name: str) -> User:
    return User(
        id=user_id, first_name=name, last_name="Tester",
        email=f"{user_id}@example.com", password_hash="x",
    )


def _channel(user_id: str, channel_id: str, platform: str = "whatsapp") -> Channel:
    return Channel(
        id=channel_id, user_id=user_id, platform=platform,
        platform_user_id=f"pn-{channel_id}", display_name="Assign",
        status="active",
    )


def _member(
    tenant_id: str, member_id: str, user_id: str, role: TeamRole
) -> TeamMember:
    return TeamMember(
        id=member_id, tenant_id=tenant_id, user_id=user_id,
        email=f"{user_id}@example.com", role_id=role.id, status="active",
    )


@pytest.mark.asyncio
async def test_assignable_users_require_access_and_reply(db, user_id):
    channel_id = "chan-assignable"
    db.add(_user(user_id, "Owner"))
    db.add(_channel(user_id, channel_id))

    agent_role = TeamRole(
        id="role-agent", tenant_id=user_id, name="Agent",
        permissions=["inbox.reply", "channels.view"],
    )
    reply_only_role = TeamRole(
        id="role-reply-only", tenant_id=user_id, name="Reply only",
        permissions=["inbox.reply"],  # no channels.view -> no channel access
    )
    db.add_all([agent_role, reply_only_role])
    await db.flush()

    agent = _user("agent-1", "Agent")
    blocked = _user("agent-2", "Blocked")
    pending = _user("agent-3", "Pending")
    outsider = _user("agent-4", "Outsider")
    db.add_all([agent, blocked, pending, outsider])
    await db.flush()

    db.add(_member(user_id, "tm-agent", agent.id, agent_role))
    db.add(_member(user_id, "tm-blocked", blocked.id, reply_only_role))
    db.add(TeamMember(
        id="tm-pending", tenant_id=user_id, user_id=None,
        email="pending@example.com", role_id=agent_role.id, status="invited",
    ))
    other_role = TeamRole(
        id="role-other", tenant_id="other-tenant", name="Agent",
        permissions=["inbox.reply", "channels.view"],
    )
    db.add(other_role)
    await db.flush()
    db.add(TeamMember(
        id="tm-other", tenant_id="other-tenant", user_id=outsider.id,
        email=outsider.email, role_id=other_role.id, status="active",
    ))
    await db.commit()

    people = await assignment.assignable_users(db, user_id, channel_id)
    ids = {p["user_id"] for p in people}

    assert ids == {user_id, agent.id}
    assert people[0]["is_owner"] is True, "the owner is always a candidate"


@pytest.mark.asyncio
async def test_assignment_mirrors_the_lead_and_notifies(db, user_id, monkeypatch):
    channel_id = "chan-assign-write"
    db.add(_user(user_id, "Owner"))
    db.add(_channel(user_id, channel_id))
    role = TeamRole(
        id="role-write", tenant_id=user_id, name="Agent",
        permissions=["inbox.reply", "channels.view"],
    )
    db.add(role)
    await db.flush()
    agent = _user("agent-write", "Amina")
    db.add(agent)
    await db.flush()
    db.add(_member(user_id, "tm-write", agent.id, role))

    lead = Lead(
        id=str(uuid.uuid4()), tenant_id=user_id, channel_id=channel_id,
        platform="whatsapp", contact_id=PHONE, stage="qualified",
        language="en", opt_out=False, thread_key=PHONE,
    )
    db.add(lead)
    await db.commit()

    events: list[dict] = []

    async def _capture(tenant_id, event):
        events.append(event)

    from app.modules.channels import realtime
    monkeypatch.setattr(realtime, "publish_inbox_event", _capture)

    from app.modules.channels.conversation_mode import set_mode
    await set_mode(
        db, tenant_id=user_id, channel_id=channel_id, contact_phone=PHONE,
        mode="human", by="system", reason="escalation",
    )

    owner = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one()
    person = await assignment.assign_thread(
        db,
        tenant_id=user_id,
        channel_id=channel_id,
        contact_phone=PHONE,
        assignee_id=agent.id,
        actor=owner,
    )
    await db.refresh(lead)

    assert person is not None and person["name"] == "Amina Tester"
    assert lead.assigned_to == agent.id
    assert lead.assigned_at is not None

    note = (
        await db.execute(
            select(Notification).where(
                Notification.user_id == agent.id,
                Notification.type == "assignment",
            )
        )
    ).scalar_one_or_none()
    assert note is not None, "the assignee is told once"
    assert agent.id in (note.href or "") or "inbox" in (note.href or "")

    mode_events = [e for e in events if e.get("type") == "assignment"]
    assert mode_events and mode_events[0]["assigned_to"] == agent.id
    assert mode_events[0]["assignee_name"] == "Amina Tester"

    # Unassigning clears both rows; an assignment is not permanent.
    await assignment.assign_thread(
        db,
        tenant_id=user_id,
        channel_id=channel_id,
        contact_phone=PHONE,
        assignee_id=None,
        actor=owner,
    )
    await db.refresh(lead)
    assert lead.assigned_to is None
    assert lead.assigned_at is None


@pytest.mark.asyncio
async def test_assignment_rejects_someone_who_cannot_work_the_channel(
    db, user_id
):
    channel_id = "chan-assign-invalid"
    db.add(_user(user_id, "Owner"))
    db.add(_channel(user_id, channel_id))
    role = TeamRole(
        id="role-no-access", tenant_id=user_id, name="No access",
        permissions=["inbox.reply"],
    )
    db.add(role)
    await db.flush()
    blocked = _user("agent-blocked", "Blocked")
    db.add(blocked)
    await db.flush()
    db.add(_member(user_id, "tm-blocked-write", blocked.id, role))
    await db.commit()

    from app.modules.channels.conversation_mode import set_mode
    await set_mode(
        db, tenant_id=user_id, channel_id=channel_id, contact_phone=PHONE,
        mode="human", by="system", reason="escalation",
    )
    owner = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one()

    with pytest.raises(assignment.AssignmentError):
        await assignment.assign_thread(
            db,
            tenant_id=user_id,
            channel_id=channel_id,
            contact_phone=PHONE,
            assignee_id=blocked.id,
            actor=owner,
        )


@pytest.mark.asyncio
async def test_inbox_assignment_endpoints(client, db, user_id):
    channel_id = "chan-assign-http"
    db.add(_user(user_id, "Owner"))
    db.add(_channel(user_id, channel_id))
    role = TeamRole(
        id="role-http", tenant_id=user_id, name="Agent",
        permissions=["inbox.reply", "channels.view"],
    )
    db.add(role)
    await db.flush()
    agent = _user("agent-http", "Sara")
    db.add(agent)
    await db.flush()
    db.add(_member(user_id, "tm-http", agent.id, role))
    db.add(Lead(
        id=str(uuid.uuid4()), tenant_id=user_id, channel_id=channel_id,
        platform="whatsapp", contact_id=PHONE, stage="qualified",
        language="en", opt_out=False, thread_key=PHONE,
    ))
    db.add(ChannelMessage(
        id=str(uuid.uuid4()), channel_id=channel_id, direction="inbound",
        content="hello", content_type="text", status="delivered",
        contact_phone=PHONE, contact_phone_hash=hash_contact_phone(PHONE),
    ))
    await db.commit()

    # The mode switch creates the thread row the assignment write expects.
    created = client.patch(
        f"/api/v1/inbox/threads/{channel_id}/%2B966500000020/mode",
        json={"mode": "human"},
    )
    assert created.status_code == 200, created.text

    people = client.get(
        f"/api/v1/inbox/assignees?channel_id={channel_id}"
    )
    assert people.status_code == 200, people.text
    ids = {p["user_id"] for p in people.json()["assignees"]}
    assert ids == {user_id, agent.id}

    r = client.patch(
        f"/api/v1/inbox/threads/{channel_id}/%2B966500000020/assignee",
        json={"assigned_to": agent.id},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["assigned_to"] == agent.id
    assert body["assignee_name"] == "Sara Tester"
    assert body["assigned_at"] is not None
    assert body["mode"] == "human", "claiming must not silently resume the AI"

    listed = client.get("/api/v1/inbox/threads").json()["threads"]
    row = next(t for t in listed if t["channel_id"] == channel_id)
    assert row["assigned_to"] == agent.id
    assert row["assignee_name"] == "Sara Tester"

    leads = client.get("/api/v1/leads").json()["leads"]
    lead_row = next(l for l in leads if l["channel_id"] == channel_id)
    assert lead_row["assigned_to"] == agent.id
    assert lead_row["assignee_name"] == "Sara Tester"

    cleared = client.patch(
        f"/api/v1/inbox/threads/{channel_id}/%2B966500000020/assignee",
        json={"assigned_to": None},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["assigned_to"] is None

    bad = client.patch(
        f"/api/v1/inbox/threads/{channel_id}/%2B966500000020/assignee",
        json={"assigned_to": "not-a-member"},
    )
    assert bad.status_code == 400, bad.text


@pytest.mark.asyncio
async def test_review_ticket_assignment(client, db, user_id):
    channel_id = "chan-review-assign"
    db.add(_user(user_id, "Owner"))
    db.add(_channel(user_id, channel_id, platform="google_reviews"))
    role = TeamRole(
        id="role-review", tenant_id=user_id, name="Agent",
        permissions=["reviews.reply", "channels.view"],
    )
    db.add(role)
    await db.flush()
    agent = _user("agent-review", "Noor")
    db.add(agent)
    await db.flush()
    db.add(_member(user_id, "tm-review", agent.id, role))

    issue = ReviewIssue(
        id=str(uuid.uuid4()), tenant_id=user_id, channel_id=channel_id,
        review_id="review-assign-1", rating=1,
        primary_category="service", subcategory="other",
        intent="complaint", sentiment="negative", priority="high",
        needs_attention=True, status="open", ticket_number="T-9001",
        reviewer_name="Customer",
    )
    db.add(issue)
    await db.commit()

    r = client.patch(
        f"/api/v1/reviews/issues/{issue.id}",
        json={"assigned_to": agent.id},
    )
    assert r.status_code == 200, r.text
    assert r.json()["assigned_to"] == agent.id
    assert r.json()["assigned_at"] is not None

    note = (
        await db.execute(
            select(Notification).where(
                Notification.user_id == agent.id,
                Notification.type == "assignment",
            )
        )
    ).scalar_one_or_none()
    assert note is not None

    cleared = client.patch(
        f"/api/v1/reviews/issues/{issue.id}", json={"assigned_to": None}
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["assigned_to"] is None

    bad = client.patch(
        f"/api/v1/reviews/issues/{issue.id}",
        json={"assigned_to": "not-a-member"},
    )
    assert bad.status_code == 400, bad.text

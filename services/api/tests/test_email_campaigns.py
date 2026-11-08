"""Newsletter campaigns expand into the durable outbox exactly once per user."""
import pytest
from sqlalchemy import select

from app.modules.analytics.models import ReviewInsight
from app.modules.channels.models import Channel
from app.modules.email import campaigns
from app.modules.email.models import EmailCampaign, EmailOutbox, EmailSuppression
from app.modules.email.schemas import CampaignPreviewIn
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio


class _factory:
    """Session factory bound to the test session's engine."""

    def __init__(self, session):
        from sqlalchemy.ext.asyncio import async_sessionmaker

        self._factory = async_sessionmaker(session.bind, expire_on_commit=False)

    def __call__(self):
        return self._factory()


async def _seed_users(db) -> list[str]:
    rows = [
        User(
            id=f"campaign-user-{i:04d}",
            email=f"campaign{i}@example.com",
            first_name=f"User{i}",
            last_name="Test",
            password_hash="x",
            email_verified=True,
            newsletter=True,
        )
        for i in range(3)
    ]
    rows.append(
        User(
            id="campaign-user-unsub",
            email="unsubscribed@example.com",
            first_name="No",
            last_name="News",
            password_hash="x",
            email_verified=True,
            newsletter=False,
        )
    )
    rows.append(
        User(
            id="campaign-user-unverified",
            email="unverified@example.com",
            first_name="Un",
            last_name="Verified",
            password_hash="x",
            email_verified=False,
            newsletter=True,
        )
    )
    db.add_all(rows)
    await db.commit()
    return [row.id for row in rows[:3]]


async def _draft(db, *, batch_size: int = 2) -> EmailCampaign:
    campaign = EmailCampaign(
        name="Weekly updates",
        subject="Hello {name}",
        html="<p>Hi {name}, news for {email}.</p>",
        text="Hi {name}, news for {email}.",
        batch_size=batch_size,
        interval_seconds=60,
        status="draft",
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)
    return campaign


async def test_variables_resolve_per_tenant_and_hide_the_internal_id(db):
    ids = await _seed_users(db)
    db.add(
        Channel(
            id="campaign-review-channel",
            user_id=ids[0],
            platform="google_reviews",
            platform_user_id="acc",
            status="active",
        )
    )
    await db.flush()
    db.add_all(
        [
            ReviewInsight(
                id="campaign-review-1",
                user_id=ids[0],
                channel_id="campaign-review-channel",
                review_id="review-1",
                rating=5,
            ),
            ReviewInsight(
                id="campaign-review-2",
                user_id=ids[0],
                channel_id="campaign-review-channel",
                review_id="review-2",
                rating=4,
            ),
        ]
    )
    user = await db.get(User, ids[0])
    user.plan = "free-trial"
    await db.commit()

    user = await db.get(User, ids[0])
    contexts = await campaigns.build_variable_contexts(db, [user])
    context = contexts[ids[0]]

    assert context["text"]["reviews"] == "2"
    assert context["text"]["tenant_total_reviews"] == "2"
    assert context["text"]["avg_rating"] == "4.5"
    assert context["text"]["tenant_free_trial_days_left"] == "14"
    assert context["text"]["dashboard_url"].endswith("/dashboard")

    rendered = campaigns.render_campaign_text(
        "Hi {name}: {reviews} reviews, {avg_rating}. {tenant_id}",
        context,
        html=False,
    )
    assert rendered == "Hi User0: 2 reviews, 4.5. {tenant_id}"


async def test_preview_renders_against_a_real_tenant(db):
    await _seed_users(db)
    preview = await campaigns.preview_campaign(
        db,
        CampaignPreviewIn(
            subject="Hi {name}",
            html="<p>{reviews} reviews, average {avg_rating}.</p>",
        ),
    )

    assert preview["tenant"]["email"].startswith("campaign")
    assert preview["subject"].startswith("Hi User")
    assert "0 reviews" in preview["body_html"]
    assert preview["html"].startswith("<!DOCTYPE html>")


async def test_campaign_walks_the_snapshot_in_batches(db):
    eligible = await _seed_users(db)
    campaign = await _draft(db, batch_size=2)

    await campaigns.start_campaign(db, campaign)
    assert campaign.status == "running"
    assert campaign.total_recipients == len(eligible)
    assert campaign.max_user_id == max(eligible)

    walked = await campaigns.expand_one(db, campaign)
    assert walked == 2
    assert campaign.status == "running"
    assert campaign.expanded_recipients == 2

    walked = await campaigns.expand_one(db, campaign)
    assert walked == 1
    assert campaign.status == "completed"
    assert campaign.expanded_recipients == len(eligible)

    rows = (
        await db.execute(
            select(EmailOutbox).where(EmailOutbox.campaign_id == campaign.id)
        )
    ).scalars().all()
    assert len(rows) == len(eligible)
    assert {row.to_email for row in rows} == {
        f"campaign{i}@example.com" for i in range(3)
    }
    assert all(row.kind == "newsletter" for row in rows)
    assert all(row.headers.get("List-Unsubscribe") for row in rows)
    assert any("User0" in row.html for row in rows)


async def test_suppressed_recipient_is_skipped_but_cursor_advances(db):
    await _seed_users(db)
    db.add(
        EmailSuppression(
            email="campaign0@example.com",
            reason="complaint",
            detail="test",
        )
    )
    await db.commit()
    campaign = await _draft(db, batch_size=50)
    await campaigns.start_campaign(db, campaign)

    await campaigns.expand_one(db, campaign)

    rows = (
        await db.execute(
            select(EmailOutbox).where(EmailOutbox.campaign_id == campaign.id)
        )
    ).scalars().all()
    assert {row.to_email for row in rows} == {
        "campaign1@example.com",
        "campaign2@example.com",
    }
    assert campaign.status == "completed"
    assert campaign.expanded_recipients == 3


async def test_audience_preview_lists_addresses_and_suppression(db):
    await _seed_users(db)
    db.add(
        EmailSuppression(
            email="campaign1@example.com",
            reason="complaint",
            detail="test",
        )
    )
    await db.commit()

    items = await campaigns.list_audience(db)

    assert [item["email"] for item in items] == [
        "campaign0@example.com",
        "campaign1@example.com",
        "campaign2@example.com",
    ]
    assert [item["suppressed"] for item in items] == [False, True, False]
    assert items[0]["tenant_id"] == "campaign-user-0000"
    # Unsubscribed and unverified users are not in the audience at all.
    assert all("unsubscribed" not in (item["email"] or "") for item in items)
    assert all("unverified" not in (item["email"] or "") for item in items)


async def test_recipient_list_shows_address_status_and_error(db):
    await _seed_users(db)
    campaign = await _draft(db, batch_size=50)
    await campaigns.start_campaign(db, campaign)
    await campaigns.expand_one(db, campaign)

    failed = (
        await db.execute(
            select(EmailOutbox).where(EmailOutbox.campaign_id == campaign.id)
        )
    ).scalars().first()
    failed.status = "failed"
    failed.error = "mailbox full"
    await db.commit()

    page = await campaigns.list_campaign_recipients(
        db, campaign.id, status="failed"
    )

    assert page["total"] == 1
    assert page["items"][0]["email"] == failed.to_email
    assert page["items"][0]["tenant_id"] == failed.tenant_id
    assert page["items"][0]["status"] == "failed"
    assert page["items"][0]["error"] == "mailbox full"


async def test_cancel_stops_future_expansion_and_cancels_queued_rows(db, monkeypatch):
    await _seed_users(db)
    campaign = await _draft(db, batch_size=2)
    await campaigns.start_campaign(db, campaign)
    await campaigns.expand_one(db, campaign)  # two rows are queued

    await campaigns.cancel_campaign(db, campaign)

    rows = (
        await db.execute(
            select(EmailOutbox).where(EmailOutbox.campaign_id == campaign.id)
        )
    ).scalars().all()
    assert rows
    assert {row.status for row in rows} == {"cancelled"}
    assert all(row.error == "Campaign cancelled" for row in rows)

    monkeypatch.setattr("app.database.async_session", _factory(db))
    assert await campaigns.expand_due_campaigns() == 0
    await db.refresh(campaign)
    assert campaign.status == "cancelled"


async def test_admin_campaign_endpoints(client, db):
    from app.core.deps import require_admin
    from app.main import app
    from app.modules.admin.router import admin_rate_limit

    await _seed_users(db)
    app.dependency_overrides[require_admin] = lambda: {
        "admin": True,
        "operator_id": "op-1",
        "username": "tester",
        "role": "superadmin",
    }
    app.dependency_overrides[admin_rate_limit] = lambda: None
    try:
        audience = client.get("/api/v1/admin/email/campaigns/audience")
        assert audience.status_code == 200
        assert audience.json()["eligible"] == 3

        created = client.post(
            "/api/v1/admin/email/campaigns",
            json={
                "name": "Weekly updates",
                "subject": "Hello",
                "html": "<p>Hi</p>",
            },
        )
        assert created.status_code == 201, created.text
        campaign = created.json()
        assert campaign["status"] == "draft"
        assert campaign["name"] == "Weekly updates"
        assert campaign["subject"] == "Hello"

        started = client.post(
            f"/api/v1/admin/email/campaigns/{campaign['id']}/start"
        )
        assert started.status_code == 200, started.text
        assert started.json()["status"] == "running"
        assert started.json()["total_recipients"] == 3

        listed = client.get("/api/v1/admin/email/campaigns")
        assert listed.status_code == 200
        assert listed.json()["items"][0]["id"] == campaign["id"]

        cancelled = client.post(
            f"/api/v1/admin/email/campaigns/{campaign['id']}/cancel"
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
    finally:
        app.dependency_overrides.pop(require_admin, None)
        app.dependency_overrides.pop(admin_rate_limit, None)

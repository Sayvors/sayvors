"""Employee profile: contact fields, credit aggregate, AI analysis, reviews.

Covers the profile read model added on top of §33: the merchant-entered
profile fields, the per-employee credit aggregate, the AI's per-review read,
and the rule that only reviews naming the employee appear on their profile.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.config import settings
from app.modules.analytics.models import ReviewInsight, StaffMember
from app.modules.analytics.staff_mentions import record_mentions

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.mark.asyncio
async def test_profile_aggregates_credit_and_ai_analysis(
    client, db, user_id, channel_id
):
    emp = client.post(
        "/api/v1/staff",
        json={
            "name": "Ahmad",
            "listing_id": "loc-1",
            "job_title": "Shift lead",
            "phone": "+1 555 0100",
            "email": "ahmad@example.com",
            "bio": "Opens the branch and keeps the queue moving.",
        },
    ).json()
    client.post(
        "/api/v1/staff", json={"name": "Sara", "listing_id": "loc-1"}
    )

    now = datetime.now(timezone.utc)
    db.add_all(
        [
            ReviewInsight(
                user_id=user_id,
                channel_id=channel_id,
                review_id="rev-a",
                rating=5,
                review_text="Ahmad was so supportive and fixed my order.",
                reviewer_name="Lina",
                sentiment="positive",
                topics=[{"name": "service", "sentiment": "positive"}],
                meaning={
                    "version": 3,
                    "intent": "praising",
                    "subject": "other",
                    "problem": None,
                    "evidence": ["Ahmad was so supportive"],
                    "confidence": 0.9,
                    "needs_human": False,
                },
                created_at=now,
                review_updated_at=now,
            ),
            ReviewInsight(
                user_id=user_id,
                channel_id=channel_id,
                review_id="rev-b",
                rating=2,
                review_text="Ahmad was rude and the wait was long.",
                reviewer_name="Omar",
                sentiment="negative",
                topics=[
                    {"name": "service", "sentiment": "negative"},
                    {"name": "waiting time", "sentiment": "negative"},
                ],
                meaning={
                    "version": 3,
                    "intent": "complaining",
                    "subject": "other",
                    "problem": "rude service",
                    "evidence": ["Ahmad was rude"],
                    "confidence": 0.8,
                    "needs_human": False,
                },
                created_at=now - timedelta(days=2),
                review_updated_at=now - timedelta(days=2),
            ),
            # A review for the other employee: must never appear on Ahmad's page.
            ReviewInsight(
                user_id=user_id,
                channel_id=channel_id,
                review_id="rev-c",
                rating=5,
                review_text="Sara was wonderful.",
                reviewer_name="Hala",
                sentiment="positive",
                topics=[{"name": "service", "sentiment": "positive"}],
                meaning={"version": 3, "entities": {"staff": []}},
                created_at=now,
                review_updated_at=now,
            ),
        ]
    )
    await db.commit()

    await record_mentions(
        db,
        user_id=user_id,
        channel_id=channel_id,
        review_id="rev-a",
        rating=5,
        review_created_at=now,
        staff_entities=[{"name": "Ahmad", "sentiment": "positive"}],
    )
    await record_mentions(
        db,
        user_id=user_id,
        channel_id=channel_id,
        review_id="rev-b",
        rating=2,
        review_created_at=now - timedelta(days=2),
        staff_entities=[{"name": "Ahmad", "sentiment": "negative"}],
    )
    await record_mentions(
        db,
        user_id=user_id,
        channel_id=channel_id,
        review_id="rev-c",
        rating=5,
        review_created_at=now,
        staff_entities=[{"name": "Sara", "sentiment": "positive"}],
    )
    await db.commit()

    resp = client.get(f"/api/v1/staff/{emp['id']}")
    assert resp.status_code == 200
    data = resp.json()

    assert data["employee"]["job_title"] == "Shift lead"
    assert data["employee"]["phone"] == "+1 555 0100"
    assert data["employee"]["email"] == "ahmad@example.com"
    assert data["employee"]["bio"].startswith("Opens the branch")

    stats = data["stats"]
    assert stats["mentions"] == 2
    assert stats["positive"] == 1
    assert stats["negative"] == 1
    assert stats["avg_rating"] == 3.5
    assert stats["positive_pct"] == 50.0

    analysis = data["analysis"]
    assert analysis["source"] == "review_ai"
    assert analysis["meaning_version"] == 3
    assert "Ahmad" in analysis["summary"]
    assert analysis["top_themes"][0]["name"] == "service"
    assert analysis["top_themes"][0]["mentions"] == 2
    assert any(q["review_id"] == "rev-a" for q in analysis["highlights"])
    assert any(q["review_id"] == "rev-b" for q in analysis["concerns"])

    # Only the two reviews that name Ahmad — never Sara's.
    assert {r["review_id"] for r in data["reviews"]} == {"rev-a", "rev-b"}
    newest = data["reviews"][0]
    assert newest["review_id"] == "rev-a"
    assert newest["reviewer_name"] == "Lina"
    assert newest["review_text"].startswith("Ahmad was so supportive")
    assert newest["ai"]["intent"] == "praising"
    assert newest["ai"]["evidence"] == ["Ahmad was so supportive"]


@pytest.mark.asyncio
async def test_profile_window_excludes_older_mentions(
    client, db, user_id, channel_id
):
    emp = client.post(
        "/api/v1/staff", json={"name": "Ahmad", "listing_id": "loc-1"}
    ).json()
    now = datetime.now(timezone.utc)
    db.add_all(
        [
            ReviewInsight(
                user_id=user_id,
                channel_id=channel_id,
                review_id="recent",
                rating=5,
                review_text="Ahmad was great today.",
                sentiment="positive",
                topics=[],
                meaning={"version": 3},
                created_at=now,
                review_updated_at=now,
            ),
            ReviewInsight(
                user_id=user_id,
                channel_id=channel_id,
                review_id="old",
                rating=1,
                review_text="Ahmad was rude months ago.",
                sentiment="negative",
                topics=[],
                meaning={"version": 3},
                created_at=now - timedelta(days=200),
                review_updated_at=now - timedelta(days=200),
            ),
        ]
    )
    await db.commit()

    await record_mentions(
        db, user_id=user_id, channel_id=channel_id, review_id="recent",
        rating=5, review_created_at=now,
        staff_entities=[{"name": "Ahmad", "sentiment": "positive"}],
    )
    await record_mentions(
        db, user_id=user_id, channel_id=channel_id, review_id="old",
        rating=1, review_created_at=now - timedelta(days=200),
        staff_entities=[{"name": "Ahmad", "sentiment": "negative"}],
    )
    await db.commit()

    all_time = client.get(f"/api/v1/staff/{emp['id']}").json()
    assert all_time["stats"]["mentions"] == 2

    windowed = client.get(f"/api/v1/staff/{emp['id']}?days=30").json()
    assert windowed["window_days"] == 30
    assert windowed["stats"]["mentions"] == 1
    assert windowed["stats"]["avg_rating"] == 5.0
    assert [r["review_id"] for r in windowed["reviews"]] == ["recent"]


@pytest.mark.asyncio
async def test_profile_contact_fields_patch_and_clear(client, user_id):
    emp = client.post(
        "/api/v1/staff",
        json={"name": "Ahmad", "listing_id": "loc-1", "email": "old@example.com"},
    ).json()

    patched = client.patch(
        f"/api/v1/staff/{emp['id']}",
        json={
            "job_title": "Barista",
            "phone": "+1 555 0111",
            "email": "new@example.com",
            "bio": "Two years at the branch.",
        },
    )
    assert patched.status_code == 200
    body = patched.json()
    assert body["job_title"] == "Barista"
    assert body["phone"] == "+1 555 0111"
    assert body["email"] == "new@example.com"

    cleared = client.patch(
        f"/api/v1/staff/{emp['id']}",
        json={"email": "", "phone": "", "job_title": ""},
    )
    assert cleared.status_code == 200
    assert cleared.json()["email"] is None
    assert cleared.json()["phone"] is None
    assert cleared.json()["job_title"] is None


@pytest.mark.asyncio
async def test_profile_picture_upload_and_remove(
    client, db, user_id, monkeypatch, tmp_path
):
    """The employee photo is validated as an image and stored on the public
    media backend; removing it clears the row without touching the employee."""
    monkeypatch.setattr(settings, "MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.setattr(settings, "MEDIA_PUBLIC_PATH", "/media-files")
    monkeypatch.setattr(settings, "GCS_PUBLIC_BUCKET", "")
    monkeypatch.setattr(settings, "GCS_PRIVATE_BUCKET", "")
    monkeypatch.setattr(settings, "AWS_S3_BUCKET", "")
    monkeypatch.setattr(settings, "S3_MEDIA_BUCKET", "")
    monkeypatch.setattr(settings, "S3_DOCS_BUCKET", "")

    emp = client.post(
        "/api/v1/staff", json={"name": "Ahmad", "listing_id": "loc-1"}
    ).json()

    # A renamed non-image is rejected before it reaches storage.
    fake = client.post(
        f"/api/v1/staff/{emp['id']}/avatar",
        files={"file": ("avatar.png", b"not an image", "image/png")},
    )
    assert fake.status_code == 400

    uploaded = client.post(
        f"/api/v1/staff/{emp['id']}/avatar",
        files={"file": ("avatar.png", PNG, "image/png")},
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["avatar_url"].endswith(".png")

    removed = client.delete(f"/api/v1/staff/{emp['id']}/avatar")
    assert removed.status_code == 200
    assert removed.json()["ok"] is True
    assert client.get(f"/api/v1/staff/{emp['id']}").json()["employee"]["avatar_url"] is None


@pytest.mark.asyncio
async def test_profile_is_tenant_scoped(client, db, user_id, other_user_id):
    """Another tenant's employee id must not resolve through this tenant's
    profile endpoint (the row filter is on user_id, not just the id)."""
    emp = client.post(
        "/api/v1/staff", json={"name": "Ahmad", "listing_id": "loc-1"}
    ).json()

    member_row = (
        await db.execute(
            select(StaffMember).where(StaffMember.id == emp["id"])
        )
    ).scalar_one()
    member_row.user_id = other_user_id
    await db.commit()

    resp = client.get(f"/api/v1/staff/{emp['id']}")
    assert resp.status_code == 404
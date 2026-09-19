"""Notification center tests: helper, list, unread, read flows.

Calls endpoint coroutines directly (the shared HTTP client fixture is
broken in this environment — see pre-existing test_api.py failures).
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.modules.notifications import router as notif_router
from app.modules.notifications.models import Notification
from app.modules.notifications.service import notify
from app.modules.users.models import User


def _user(user_id: str) -> User:
    return User(
        id=user_id,
        email="notif-test@sayvors.com",
        first_name="Notif",
        last_name="Tester",
        password_hash="x",
        onboarded=True,
    )


async def _seed(db, user_id: str, n: int = 3, read_first: int = 0):
    now = datetime.now(timezone.utc)
    for i in range(n):
        db.add(Notification(
            id=f"n-{user_id[:4]}-{i}",
            user_id=user_id,
            type="review_pulled",
            title=f"Review {i}",
            body="snippet",
            data={"rating": 5},
            href="/dashboard/reviews",
            read_at=(now - timedelta(minutes=i)) if i < read_first else None,
            created_at=now - timedelta(minutes=i),
        ))
    await db.commit()


@pytest.mark.asyncio
async def test_notify_helper_creates_row(db, user_id):
    from app.modules.notifications import service as notif_service

    nid = await notif_service.notify(
        db, user_id, "sync_completed", "Synced Al Malqa — 2 new review(s)",
        None, data={"new_reviews": 2}, href="/dashboard",
    )
    assert nid
    row = await db.get(Notification, nid)
    assert row is not None
    assert row.title.startswith("Synced")
    assert row.read_at is None
    assert row.data == {"new_reviews": 2}


@pytest.mark.asyncio
async def test_list_newest_first_with_counts(db, user_id):
    await _seed(db, user_id, n=3, read_first=1)

    resp = await notif_router.list_notifications(
        unread_only=False, category=None, limit=30, offset=0,
        user=_user(user_id), db=db,
    )
    assert resp.total == 3
    assert resp.unread == 2
    assert [i.title for i in resp.items] == ["Review 0", "Review 1", "Review 2"]


@pytest.mark.asyncio
async def test_list_unread_only(db, user_id):
    await _seed(db, user_id, n=3, read_first=1)

    resp = await notif_router.list_notifications(
        unread_only=True, category=None, limit=30, offset=0,
        user=_user(user_id), db=db,
    )
    assert resp.total == 2
    assert all(i.read_at is None for i in resp.items)


@pytest.mark.asyncio
async def test_list_paginates(db, user_id):
    await _seed(db, user_id, n=5)

    page1 = await notif_router.list_notifications(
        unread_only=False, category=None, limit=2, offset=0,
        user=_user(user_id), db=db,
    )
    page2 = await notif_router.list_notifications(
        unread_only=False, category=None, limit=2, offset=2,
        user=_user(user_id), db=db,
    )
    assert page1.total == 5
    assert [i.id for i in page1.items] != [i.id for i in page2.items]


@pytest.mark.asyncio
async def test_unread_count(db, user_id):
    await _seed(db, user_id, n=4, read_first=1)

    resp = await notif_router.unread_count(user=_user(user_id), db=db)
    assert resp == {"unread": 3}


@pytest.mark.asyncio
async def test_mark_read_and_idempotent(db, user_id):
    await _seed(db, user_id, n=1)

    first = await notif_router.mark_read(
        notification_id=f"n-{user_id[:4]}-0", user=_user(user_id), db=db,
    )
    assert first.read_at is not None
    second = await notif_router.mark_read(
        notification_id=f"n-{user_id[:4]}-0", user=_user(user_id), db=db,
    )
    assert second.read_at == first.read_at

    resp = await notif_router.unread_count(user=_user(user_id), db=db)
    assert resp == {"unread": 0}


@pytest.mark.asyncio
async def test_mark_read_404_for_other_user(db, user_id):
    await _seed(db, user_id, n=1)
    other = _user("00000000-0000-0000-0000-000000000000")

    with pytest.raises(HTTPException) as exc:
        await notif_router.mark_read(
            notification_id=f"n-{user_id[:4]}-0", user=other, db=db,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_read_all(db, user_id):
    await _seed(db, user_id, n=3)

    resp = await notif_router.mark_all_read(user=_user(user_id), db=db)
    assert resp == {"marked": 3}

    count = await notif_router.unread_count(user=_user(user_id), db=db)
    assert count == {"unread": 0}

@pytest.mark.asyncio
async def test_list_filters_by_category(db, user_id):
    from app.modules.notifications import router as notif_router

    for i, (t, title) in enumerate([
        ("sync_completed", "Synced A"),
        ("review_pulled", "New review"),
        ("reply_posted", "Replied"),
        ("sync_failed", "Sync broke"),
    ]):
        db.add(Notification(
            id=f"n-cat-{i}", user_id=user_id, type=t, title=title,
        ))
    await db.commit()

    syncs = await notif_router.list_notifications(
        unread_only=False, category="syncs", limit=30, offset=0,
        user=_user(user_id), db=db,
    )
    assert syncs.total == 2
    assert sorted(i.type for i in syncs.items) == ["sync_completed", "sync_failed"]

    replies = await notif_router.list_notifications(
        unread_only=False, category="replies", limit=30, offset=0,
        user=_user(user_id), db=db,
    )
    assert replies.total == 1
    assert replies.items[0].type == "reply_posted"

    reviews = await notif_router.list_notifications(
        unread_only=False, category="reviews", limit=30, offset=0,
        user=_user(user_id), db=db,
    )
    assert reviews.total == 1


@pytest.mark.asyncio
async def test_category_summary_counts(db, user_id):
    from app.modules.notifications import router as notif_router

    await _seed(db, user_id, n=3, read_first=1)  # 3x review_pulled, 1 read
    db.add(Notification(
        id="n-cat-s1", user_id=user_id, type="sync_completed", title="Synced",
    ))
    await db.commit()

    out = await notif_router.category_summary(user=_user(user_id), db=db)
    cats = out["categories"]
    assert cats["reviews"] == {"total": 3, "unread": 2}
    assert cats["syncs"] == {"total": 1, "unread": 1}
    assert cats["replies"] == {"total": 0, "unread": 0}

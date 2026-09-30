"""Advisory-lock isolation: a lock must not break the caller's session.

Regression tests for the 502 "Localith sync failed: greenlet_spawn has not been
called". `take_lock` used to `db.rollback()` the session it was handed: once
when a try-take found the lock held elsewhere, and again when the lock
statement itself failed. Session.rollback() expires every ORM object loaded in
the open transaction (commits do not — we run expire_on_commit=False), so the
caller's next plain attribute read became a lazy load AsyncSession cannot
await: MissingGreenlet. For a sync request that victim was the `User` row the
auth dependency had already loaded on that same session.

Covers app.modules.scheduling.take_lock and the multi-branch Localith loop,
which must survive a rollback caused by a failed branch. No network; sqlite
DB, with `is_postgres` forced True so the lock statements actually run.
"""
import sys
from pathlib import Path

import pytest
from sqlalchemy import select, text as sa_text
from sqlalchemy.exc import MissingGreenlet

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.localith import service as localith_service
from app.modules.scheduling import take_lock
from app.modules.users.models import User


async def _user_with_open_transaction(db, user_id):
    """A User row loaded the way the auth dependency loads it.

    The select leaves a transaction open — that is the state in which a
    rollback would expire the row and break the caller.
    """
    db.add(User(
        id=user_id,
        first_name="Test",
        last_name="Owner",
        email=f"{user_id}@example.com",
        password_hash="x",
        business_type="Food & Restaurant",
    ))
    await db.commit()
    return (await db.execute(
        select(User).where(User.id == user_id)
    )).scalar_one()


@pytest.fixture
def on_postgres(monkeypatch):
    """Force the advisory-lock path: sqlite has no advisory locks, and
    `take_lock` short-circuits to True on it, hiding the rollback entirely."""
    monkeypatch.setattr("app.modules.scheduling.is_postgres", lambda db: True)


async def _assert_caller_state_intact(db, user, user_id):
    """The caller's row must still be readable without a re-fetch."""
    assert user.business_type == "Food & Restaurant"
    again = (await db.execute(
        select(User).where(User.id == user_id)
    )).scalar_one()
    assert again.business_type == "Food & Restaurant"


@pytest.mark.asyncio
async def test_try_lock_miss_does_not_expire_caller_state(
    db, user_id, monkeypatch, on_postgres
):
    """Lock held elsewhere is a normal answer, not a fault.

    A miss used to roll the session back, which expired every loaded object —
    so the caller's very next attribute read raised MissingGreenlet.
    """
    user = await _user_with_open_transaction(db, user_id)
    monkeypatch.setattr(
        "app.modules.scheduling._stmt",
        lambda *a, **k: sa_text("SELECT 0"),  # scalar() -> 0, i.e. a miss
    )

    assert await take_lock(db, False, "sayvors:localith-sync:", "listing-a") is False
    await _assert_caller_state_intact(db, user, user_id)


@pytest.mark.asyncio
async def test_lock_statement_failure_raises_and_leaves_session_usable(
    db, user_id, monkeypatch, on_postgres
):
    """A broken lock statement must fail loudly, not silently run unlocked.

    The sync cannot continue on a session whose transaction is aborted — and
    the caller must not be left holding expired objects either.
    """
    user = await _user_with_open_transaction(db, user_id)
    monkeypatch.setattr(
        "app.modules.scheduling._stmt",
        lambda *a, **k: sa_text("SELECT no_such_lock_fn_xyz(1)"),
    )

    with pytest.raises(Exception) as err:
        await take_lock(db, True, "sayvors:localith-sync:", "listing-a")
    assert "no_such_lock_fn_xyz" in str(err.value)
    await _assert_caller_state_intact(db, user, user_id)


@pytest.mark.asyncio
async def test_failed_branch_does_not_stop_the_next_branch(db, user_id, monkeypatch):
    """A branch that fails must not poison the branches after it.

    The failed branch's rollback used to expire the not-yet-synced connection
    rows, and the loop's next `connection.listing_id` read raised
    MissingGreenlet — failing the whole sync instead of one branch.
    """
    from app.modules.localith.models import LocalithConnection

    db.add(LocalithConnection(
        id="lc-lock-dead", user_id=user_id, listing_id="listing-a",
        listing_name="Branch A",
    ))
    db.add(LocalithConnection(
        id="lc-lock-live", user_id=user_id, listing_id="listing-b",
        listing_name="Branch B",
    ))
    await db.commit()
    user = await _user_with_open_transaction(db, user_id)

    synced: list[str] = []

    async def _fake_single(user_id_, db_, connection, days_back=30):
        if connection.listing_id == "listing-a":
            raise RuntimeError("provider is down")
        synced.append(connection.listing_id)
        return {"fetched": 4, "new_reviews": 1}

    monkeypatch.setattr(
        localith_service, "_sync_single_connection", _fake_single
    )

    totals = await localith_service.sync_connection(user, db)

    # Before the fix this call raised MissingGreenlet out of the loop.
    assert synced == ["listing-b"]
    assert totals == {
        "fetched": 4, "new_reviews": 1, "branches": 1, "errors": 1,
    }
    # The rollback did expire the caller's row — that is inherent to undoing
    # the failed branch's writes, and precisely why the sync must not read it
    # afterwards. Documented here so nobody "fixes" the snapshot by reading
    # connection.listing_id again.
    with pytest.raises(MissingGreenlet):
        _ = user.business_type
    fresh = (await db.execute(
        select(User).where(User.id == user_id)
    )).scalar_one()
    assert fresh.business_type == "Food & Restaurant"

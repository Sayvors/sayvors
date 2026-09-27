"""The live reply Google already shows must be stored, not discarded.

Localith returns the business's reply on every review payload:

    "replies": [{"id": ..., "text": ..., "createdOn": ...}]

The adapter used to collapse that to `has_replies=True` and drop the text, so
a review answered on the listing had no stored response — the detail page could
only say "answered outside Sayvors" and offer a blind re-reply.

These tests pin the adapter parsing and the adoption rules:
  * a live reply with no row on file  -> creates a `posted` row
  * a posted row whose text differs   -> corrected in place (GBP edit wins)
  * a draft awaiting approval         -> never touched
  * no replies / blank reply text     -> nothing written
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from integrations.channels import embedsocial

from app.modules.channels.models import Channel, ReviewReply
from app.modules.localith.service import _adopt_live_reply


# ── Adapter: the reply text survives the mapping ──────────────────

def test_reply_text_is_captured_from_live_payload():
    review = embedsocial.to_internal_review({
        "id": "r1",
        "captionText": "Great product",
        "replies": [{
            "id": "5924dea6",
            "text": "Glad you love it!",
            "createdOn": "2026-09-25 10:55:50",
        }],
    })
    assert review.has_replies is True
    assert review.reply_text == "Glad you love it!"
    assert review.reply_external_id == "5924dea6"
    assert review.reply_published_at == "2026-09-25 10:55:50"


def test_latest_reply_wins_over_older_ones():
    review = embedsocial.to_internal_review({
        "id": "r2",
        "replies": [
            {"id": "old", "text": "first", "createdOn": "2026-09-01 10:00:00"},
            {"id": "new", "text": "latest", "createdOn": "2026-09-25 10:55:50"},
            {"id": "mid", "text": "middle", "createdOn": "2026-09-10 10:00:00"},
        ],
    })
    assert review.reply_external_id == "new"
    assert review.reply_text == "latest"


def test_undated_replies_take_the_last_one():
    """Undated entries come in provider order — the later one is newer."""
    review = embedsocial.to_internal_review({
        "id": "r3", "replies": [{"text": "older"}, {"text": "newer"}],
    })
    assert review.reply_text == "newer"


def test_no_replies_means_no_text():
    review = embedsocial.to_internal_review({"id": "r4", "replies": []})
    assert review.has_replies is False
    assert review.reply_text is None

    bare = embedsocial.to_internal_review({"id": "r5"})
    assert bare.has_replies is False
    assert bare.reply_text is None


def test_blank_reply_text_is_not_adopted():
    """A reply object with only whitespace must not become a response."""
    review = embedsocial.to_internal_review({
        "id": "r6", "replies": [{"id": "x", "text": "   "}],
    })
    assert review.has_replies is True
    assert review.reply_text is None


def test_malformed_replies_does_not_crash():
    review = embedsocial.to_internal_review({"id": "r7", "replies": "oops"})
    assert review.has_replies is False
    assert review.reply_text is None


def test_bare_string_reply_yields_text_but_no_id():
    review = embedsocial.to_internal_review({"id": "r8", "replies": ["plain reply"]})
    assert review.has_replies is True
    assert review.reply_text == "plain reply"
    assert review.reply_external_id is None


# ── Adoption: what actually lands in the database ────────────────

def _review(**kw):
    base = dict(
        rating=4,
        text="In the new version there is a lot to see.",
        reviewer="Syed Syab Ahmad Shah",
        has_replies=True,
        reply_text="Glad you love the new features!",
        reply_external_id="ext-1",
        reply_published_at="2026-09-25 10:55:50",
    )
    base.update(kw)
    return embedsocial.InternalReview(external_id="f5878bdb", **base)


async def _rows(db, channel_id, review_id):
    return (await db.execute(
        select(ReviewReply).where(
            ReviewReply.channel_id == channel_id,
            ReviewReply.review_id == review_id,
        )
    )).scalars().all()


@pytest.mark.asyncio
async def test_live_reply_is_adopted_when_no_row_exists(db, channel_id):
    channel = await db.get(Channel, channel_id)

    changed = await _adopt_live_reply(db, channel, "localith:f5878bdb", _review())
    await db.commit()
    assert changed is True

    rows = await _rows(db, channel_id, "localith:f5878bdb")
    assert len(rows) == 1
    assert rows[0].status == "posted"
    assert rows[0].reply_text == "Glad you love the new features!"
    assert rows[0].reply_external_id == "ext-1"
    assert rows[0].replied_at is not None


@pytest.mark.asyncio
async def test_adoption_is_idempotent_across_repeated_syncs(db, channel_id):
    channel = await db.get(Channel, channel_id)
    assert await _adopt_live_reply(db, channel, "localith:f5878bdb", _review()) is True
    await db.commit()
    # Every later poll sees the same reply and must not duplicate the row.
    assert await _adopt_live_reply(db, channel, "localith:f5878bdb", _review()) is False
    assert await _adopt_live_reply(db, channel, "localith:f5878bdb", _review()) is False
    await db.commit()

    rows = await _rows(db, channel_id, "localith:f5878bdb")
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_gbp_edit_corrects_the_stored_reply(db, channel_id):
    """A reply edited directly in Google must win over what we stored."""
    channel = await db.get(Channel, channel_id)
    await _adopt_live_reply(db, channel, "localith:f5878bdb", _review())
    await db.commit()

    edited = _review(reply_text="Edited in the Business Profile.", reply_external_id="ext-2")
    assert await _adopt_live_reply(db, channel, "localith:f5878bdb", edited) is True
    await db.commit()

    rows = await _rows(db, channel_id, "localith:f5878bdb")
    assert len(rows) == 1
    assert rows[0].reply_text == "Edited in the Business Profile."
    assert rows[0].reply_external_id == "ext-2"
    assert rows[0].status == "posted"


@pytest.mark.asyncio
async def test_pending_draft_is_never_clobbered(db, channel_id):
    """The merchant's in-flight work outranks whatever the provider reports."""
    channel = await db.get(Channel, channel_id)
    db.add(ReviewReply(
        id="draft-1", channel_id=channel_id, review_id="localith:f5878bdb",
        rating=4, reply_text="My careful draft", status="pending_approval",
    ))
    await db.commit()

    assert await _adopt_live_reply(db, channel, "localith:f5878bdb", _review()) is False
    await db.commit()

    rows = await _rows(db, channel_id, "localith:f5878bdb")
    assert len(rows) == 1
    assert rows[0].status == "pending_approval"
    assert rows[0].reply_text == "My careful draft"


@pytest.mark.asyncio
async def test_nothing_written_without_a_live_reply(db, channel_id):
    channel = await db.get(Channel, channel_id)
    unreplied = _review(has_replies=False, reply_text=None)
    assert await _adopt_live_reply(db, channel, "localith:f5878bdb", unreplied) is False

    blank = _review(reply_text="   ")
    assert await _adopt_live_reply(db, channel, "localith:f5878bdb", blank) is False
    await db.commit()

    assert await _rows(db, channel_id, "localith:f5878bdb") == []

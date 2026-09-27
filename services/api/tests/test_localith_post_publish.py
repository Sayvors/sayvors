"""Localith post publishing: the body shape that actually works.

Every case here was verified against the live endpoint. Three of them were
wrong in our code and each one made a post fail in a way the merchant could not
act on, because the API's error said nothing useful:

  * `offer` and `event` are answered with a bare `400 bad_request` for this
    account, for every field combination including the full documented shape.
  * `scheduledOn` rejects every ISO 8601 form — including the one in Localith's
    own example — and accepts only "YYYY-MM-DD HH:MM".
  * `scheduled_on` was stored on the row and then never passed to the API, so a
    scheduled post was published by our worker instead of being scheduled.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from integrations.channels import embedsocial as es

LISTING = "a690420582bc3b00b307737132e5df8b"


@pytest.fixture
def captured(monkeypatch):
    """Capture the request body instead of calling Localith."""
    seen: dict = {}

    def _fake_post(path, body, timeout=60, api_key=None):
        seen["path"] = path
        seen["body"] = body
        return [{"id": "posted"}]

    monkeypatch.setattr(es, "_post", _fake_post)
    return seen


def _publish(**kw):
    return es.publish_media_post(LISTING, **kw)


# ── scheduledOn: the only format Localith accepts ───────────────

def test_scheduled_on_uses_the_format_localith_accepts(captured):
    """ISO 8601 is rejected with 422, even in Localith's own example format."""
    _publish(
        post_type="update",
        caption="x",
        scheduled_on=datetime(2026, 10, 1, 14, 30, tzinfo=timezone.utc),
    )
    assert captured["body"]["scheduledOn"] == "2026-10-01 14:30"


@pytest.mark.parametrize(
    "value",
    [
        "2026-10-01T14:30:00+00:00",
        "2026-10-01T14:30:00Z",
        "2026-10-01T14:30:00.000Z",
        "2026-10-01 14:30",
    ],
)
def test_scheduled_on_forms_all_normalise(captured, value):
    _publish(post_type="update", caption="x", scheduled_on=value)
    assert captured["body"]["scheduledOn"] == "2026-10-01 14:30"


def test_scheduled_on_is_converted_to_utc(captured):
    from datetime import timedelta

    tz = timezone(timedelta(hours=5))
    _publish(
        post_type="update",
        caption="x",
        scheduled_on=datetime(2026, 10, 1, 19, 30, tzinfo=tz),  # 14:30 UTC
    )
    assert captured["body"]["scheduledOn"] == "2026-10-01 14:30"


def test_unparseable_scheduled_on_is_passed_through(captured):
    """Don't rewrite something we cannot read — let the API judge it."""
    _publish(post_type="update", caption="x", scheduled_on="whenever")
    assert captured["body"]["scheduledOn"] == "whenever"


def test_no_scheduled_on_means_no_field(captured):
    _publish(post_type="update", caption="x")
    assert "scheduledOn" not in captured["body"]


# ── offer / event must go out as an update ──────────────────────

def test_offer_is_sent_as_update(captured):
    """Localith answers a real offer with 400 and no detail, so this cannot ship as-is."""
    _publish(post_type="offer", caption="Save 2%")
    assert captured["body"]["type"] == "update"
    assert captured["body"]["captionText"] == "Save 2%"


def test_event_is_sent_as_update(captured):
    _publish(post_type="event", caption="Grand opening")
    assert captured["body"]["type"] == "update"


def test_update_stays_an_update(captured):
    _publish(post_type="update", caption="x")
    assert captured["body"]["type"] == "update"


def test_an_unknown_type_is_still_rejected(captured):
    with pytest.raises(ValueError):
        _publish(post_type="flyer", caption="x")
    assert "body" not in captured


# ── start/end dates were never the problem ──────────────────────

def test_start_and_end_dates_pass_through_as_iso(captured):
    """Verified working for update, in every ISO form tested."""
    _publish(
        post_type="update",
        caption="x",
        start_date=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc).isoformat(),
        end_date=datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc).isoformat(),
    )
    assert captured["body"]["startDate"].startswith("2026-10-01T09:00:00")
    assert captured["body"]["endDate"].startswith("2026-10-08T09:00:00")


def test_offer_keeps_its_schedule_when_downgraded(captured):
    """Downgrading the type must not drop the dates that made it an offer."""
    _publish(
        post_type="offer",
        caption="Save 2%",
        start_date="2026-10-01T09:00:00+00:00",
        end_date="2026-10-08T09:00:00+00:00",
    )
    body = captured["body"]
    assert body["type"] == "update"
    assert "startDate" in body and "endDate" in body


def test_posts_to_the_right_endpoint(captured):
    _publish(post_type="update", caption="x")
    assert captured["path"] == "rest/v1/content_publishing_media"

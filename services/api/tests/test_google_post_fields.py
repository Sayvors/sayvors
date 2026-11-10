"""Field rules for Google local posts. Pure: no network, no database.

Each rule here decides what Google accepts for a post type. A wrong rule means
a rejected post on the business's profile, so every rule has its own test.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.modules.channels.meta.providers.google_post_fields import (
    DEFAULT_WINDOW_DAYS,
    EVENT_TITLE_MAX_CHARS,
    OFFER_TERMS_DEFAULT,
    SUMMARY_MAX_CHARS,
    build_post_fields,
    build_summary,
    call_to_action_block,
    event_title,
    parse_instant,
    resolve_window,
    scheduled_time_rfc3339,
    topic_type_for,
)

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


def test_summary_joins_caption_and_description():
    assert build_summary("Open today", "Fresh bread from 7am") == (
        "Open today\n\nFresh bread from 7am"
    )


def test_summary_does_not_repeat_a_description_equal_to_the_caption():
    assert build_summary("Same line", "Same line") == "Same line"


def test_summary_falls_back_to_whichever_text_exists():
    assert build_summary("", "Only the body") == "Only the body"
    assert build_summary("Only the hook", None) == "Only the hook"
    assert build_summary("", "") == ""


def test_summary_is_capped_at_the_google_limit():
    assert len(build_summary("x" * 3000, "")) == SUMMARY_MAX_CHARS


def test_event_title_is_the_first_line_of_the_caption():
    assert event_title("Grand opening\nDoors at 9", "details") == "Grand opening"


def test_event_title_falls_back_to_the_description_then_a_default():
    assert event_title("", "Open house") == "Open house"
    assert event_title("", "") == "Event"


def test_event_title_is_capped():
    assert len(event_title("y" * 500, "")) == EVENT_TITLE_MAX_CHARS


def test_window_defaults_to_a_week_from_now():
    begin, finish = resolve_window(None, None, NOW)
    assert begin == NOW
    assert finish == NOW + timedelta(days=DEFAULT_WINDOW_DAYS)


def test_window_rejects_an_end_before_the_start():
    with pytest.raises(ValueError):
        resolve_window(NOW + timedelta(days=2), NOW + timedelta(days=1), NOW)


def test_event_times_are_sent_in_the_business_timezone():
    """06:00 UTC is 09:00 in Saudi Arabia. Google reads the schedule as the
    business's local time, so the local clock is what must be sent."""
    built = build_post_fields(
        topic="EVENT",
        caption="Open",
        description="",
        cta_type=None,
        cta_url=None,
        start=datetime(2026, 11, 20, 6, 0, tzinfo=timezone.utc),
        end=datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc),
        coupon_code=None,
        terms=None,
        now=NOW,
    )
    schedule = built.fields["event"]["schedule"]
    assert schedule["startTime"]["hours"] == 9
    assert schedule["endTime"]["hours"] == 13


def test_a_date_crossing_midnight_moves_the_day_in_the_business_timezone():
    """22:00 UTC on the 9th is 01:00 on the 10th in Riyadh."""
    built = build_post_fields(
        topic="EVENT",
        caption="Late",
        description="",
        cta_type=None,
        cta_url=None,
        start=datetime(2026, 11, 9, 22, 0, tzinfo=timezone.utc),
        end=datetime(2026, 11, 10, 22, 0, tzinfo=timezone.utc),
        coupon_code=None,
        terms=None,
        now=NOW,
    )
    schedule = built.fields["event"]["schedule"]
    assert schedule["startDate"] == {"year": 2026, "month": 11, "day": 10}
    assert schedule["startTime"]["hours"] == 1


def test_an_offer_has_event_and_offer_and_no_button():
    built = build_post_fields(
        topic="OFFER",
        caption="Summer sale",
        description="",
        cta_type="shop",
        cta_url="https://shop.example/sale",
        start=None,
        end=None,
        coupon_code="SAVE10",
        terms="While stocks last",
        now=NOW,
    )
    assert "callToAction" not in built.fields
    assert built.fields["offer"] == {
        "termsConditions": "While stocks last",
        "couponCode": "SAVE10",
        "redeemOnlineUrl": "https://shop.example/sale",
    }
    assert "event" in built.fields
    assert built.window is not None


def test_an_offer_without_terms_uses_the_default_terms():
    built = build_post_fields(
        topic="OFFER",
        caption="Sale",
        description="",
        cta_type=None,
        cta_url=None,
        start=None,
        end=None,
        coupon_code=None,
        terms=None,
        now=NOW,
    )
    assert built.fields["offer"] == {"termsConditions": OFFER_TERMS_DEFAULT}


def test_an_offer_never_sends_a_description_field():
    built = build_post_fields(
        topic="OFFER",
        caption="Sale",
        description="More details",
        cta_type=None,
        cta_url=None,
        start=None,
        end=None,
        coupon_code=None,
        terms=None,
        now=NOW,
    )
    assert set(built.fields["offer"]) <= {"termsConditions", "couponCode", "redeemOnlineUrl"}


def test_a_standard_post_without_a_button_says_so_explicitly():
    built = build_post_fields(
        topic="STANDARD",
        caption="Hi",
        description="",
        cta_type=None,
        cta_url=None,
        start=None,
        end=None,
        coupon_code=None,
        terms=None,
        now=NOW,
    )
    assert built.fields["callToAction"] is None
    assert built.window is None


def test_a_standard_post_button_carries_its_action_and_url():
    built = build_post_fields(
        topic="STANDARD",
        caption="Hi",
        description="",
        cta_type="learn_more",
        cta_url="https://sayvors.com",
        start=None,
        end=None,
        coupon_code=None,
        terms=None,
        now=NOW,
    )
    assert built.fields["callToAction"] == {
        "actionType": "LEARN_MORE",
        "url": "https://sayvors.com",
    }


def test_a_call_button_carries_no_url():
    assert call_to_action_block("call", "https://ignored.example") == {"actionType": "CALL"}


def test_a_link_button_without_a_url_is_refused():
    with pytest.raises(ValueError):
        call_to_action_block("book", "   ")


def test_an_unknown_button_type_is_refused():
    with pytest.raises(ValueError):
        call_to_action_block("dance", "https://x.example")


def test_topic_mapping_and_the_legacy_post_method():
    assert topic_type_for("update") == "STANDARD"
    assert topic_type_for("post") == "STANDARD"
    assert topic_type_for("event") == "EVENT"
    assert topic_type_for("offer") == "OFFER"
    with pytest.raises(ValueError):
        topic_type_for("banner")


def test_a_future_schedule_becomes_rfc3339_utc():
    assert scheduled_time_rfc3339("2026-11-20T08:00:00+03:00", NOW) == "2026-11-20T05:00:00Z"


def test_a_past_or_missing_schedule_means_publish_now():
    assert scheduled_time_rfc3339(None, NOW) is None
    assert scheduled_time_rfc3339("2026-11-01T08:00:00Z", NOW) is None


def test_an_unreadable_schedule_is_an_error_not_a_silent_publish():
    with pytest.raises(ValueError):
        scheduled_time_rfc3339("next tuesday", NOW)


def test_a_naive_instant_is_read_as_utc():
    assert parse_instant("2026-11-20T08:00:00") == datetime(
        2026, 11, 20, 8, 0, tzinfo=timezone.utc
    )

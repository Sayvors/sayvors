"""Conversation categorisation — one scale, one "important" rule.

The inbox ranks conversations and the tenant filters them, so the rule
has to mean the same thing wherever the conversation came from. A
one-star Google review and a WhatsApp message that says "this is
broken" both need a human now; a five-star review does not.

These tests pin:

- a Google review's priority comes from its rating, mapped onto the
  SAME scale the chat path uses
- "important" is derived, and spans every source
- a Google reviewer gets their OWN thread key, so reviews do not
  collapse into the catch-all "unknown" bucket
"""
import pytest

from app.modules.channels.service import categorize_message, is_important


# ── Google reviews: the rating is the signal ───────────────────────────


@pytest.mark.parametrize(
    "rating,expected_category,expected_priority",
    [
        (1, "complaint", "urgent"),
        (2, "complaint", "high"),
        (3, "feedback", "normal"),
        (4, "feedback", "low"),
        (5, "feedback", "low"),
    ],
)
def test_a_google_review_is_categorised_by_its_rating(
    rating, expected_category, expected_priority
):
    category, priority = categorize_message(
        "Some text", platform="google_reviews", rating=rating
    )
    assert category == expected_category
    assert priority == expected_priority


def test_a_google_review_without_a_rating_falls_back_to_the_keywords():
    """No rating means no rating-based rule — the chat path applies."""
    category, priority = categorize_message(
        "this is broken", platform="google_reviews", rating=None
    )
    assert (category, priority) == ("complaint", "high")


# ── Chat: the keyword path ─────────────────────────────────────────────


def test_a_complaint_message_is_high():
    assert categorize_message("my order is broken")[1] == "high"
    assert categorize_message("I want a refund")[0] == "complaint"


def test_an_urgent_message_is_urgent():
    category, priority = categorize_message("this is urgent, please help")
    assert priority == "urgent"
    assert category == "important"


def test_a_plain_message_is_normal():
    assert categorize_message("what time do you open") == ("normal", "normal")


# ── "important" — one rule, every source ───────────────────────────────


def test_important_spans_every_source():
    """A one-star Google review and an angry WhatsApp customer are the
    same kind of thing: they need a human now."""
    google = categorize_message("bad", platform="google_reviews", rating=1)
    chat = categorize_message("this is a scam, terrible service")
    assert is_important(*reversed(google)) is True
    assert is_important(*reversed(chat)) is True


def test_a_complaint_is_important_whatever_its_priority():
    assert is_important("normal", "complaint") is True


def test_praise_and_smalltalk_are_not_important():
    assert is_important("low", "feedback") is False
    assert is_important("normal", "normal") is False


def test_a_missing_priority_reads_as_normal():
    assert is_important(None, None) is False


# ── A Google reviewer gets their own thread ────────────────────────────


class _Review:
    """The bits of a Google review the worker uses to identify a reviewer."""

    def __init__(self, review_id, *, author_name=None, author_profile_url=None, rating=5):
        self.review_id = review_id
        self.author_name = author_name
        self.author_profile_url = author_profile_url
        self.rating = rating
        self.text = "hello"


def _key(review):
    from app.modules.channels.reviews_worker import _google_reviewer_key

    return _google_reviewer_key(review)


def test_a_reviewer_gets_a_stable_thread_key():
    review = _Review("r1", author_name="Fatma", author_profile_url="https://g.co/p/1")
    assert _key(review) == _key(review)


def test_two_reviewers_get_different_thread_keys():
    a = _Review("r1", author_name="Fatma", author_profile_url="https://g.co/p/1")
    b = _Review("r2", author_name="Omar", author_profile_url="https://g.co/p/2")
    assert _key(a) != _key(b)


def test_two_reviews_by_the_same_reviewer_share_a_thread():
    """A reviewer who leaves three reviews is one conversation."""
    a = _Review("r1", author_name="Fatma", author_profile_url="https://g.co/p/1")
    b = _Review("r2", author_name="Fatma", author_profile_url="https://g.co/p/1")
    assert _key(a) == _key(b)


def test_the_thread_key_can_never_be_mistaken_for_a_phone_number():
    review = _Review("r1", author_name="Fatma", author_profile_url="https://g.co/p/1")
    key = _key(review)
    assert key.startswith("google:")
    assert not key[len("google:"):].isdigit()


def test_a_reviewer_with_no_identity_still_gets_a_thread():
    """Better its own thread than the shared catch-all."""
    review = _Review("r-only-id")
    key = _key(review)
    assert key.startswith("google:")
    assert key != _key(_Review("r-other-id"))

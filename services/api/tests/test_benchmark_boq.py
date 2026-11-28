"""BOQ review depth: field mapping, pagination, window enforcement, fallback.

The endpoint is undocumented, so these tests pin the exact payload shape the
parser depends on. If Google moves a field, the parser raises instead of storing
garbage â€” and these fixtures are where the expected shape is written down.

No network: every test injects a fake client.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.config import settings
from app.modules.benchmark import boq, placedetail

FTID = "0x3e2efb00092dac35:0xfdf71e5a3e9b48fa"
PLACE_ID = "ChIJbX3jKQD_Lj4RCQzYIquZgfE"
MAPS_URL = (
    "https://www.google.com/maps/place/Test/@24.8,46.6,17z/data=!3m1!4b1"
    f"!4m6!3m5!1s{FTID}!8m2!3d24.8!4d46.6!16s%2Fg%2F11xkz44ltd"
)


def _ms(days_ago: float = 1) -> str:
    moment = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return str(int(moment.timestamp() * 1000))


def _raw_review(
    review_id: str = "rev-1",
    *,
    rating: int = 5,
    text: str = "Great place",
    days_ago: float = 1,
    author: str = "Alice",
    photo: str = "https://lh3.googleusercontent.com/a/abc=s64",
    reply: str | None = None,
) -> list:
    """One review in the panel's fixed-position array shape (len 49)."""
    raw = [None] * 49
    raw[1] = rating
    raw[2] = ["Ù‚Ø¨Ù„ 3 Ø£ÙŠØ§Ù…", 2, _ms(days_ago)]
    raw[3] = [author, photo, "https://www.google.com/maps/contrib/1/reviews"]
    raw[4] = [None, "Ù‚Ø¨Ù„ ÙŠÙˆÙ…", reply] if reply else None
    raw[5] = review_id
    raw[27] = text
    raw[28] = text
    raw[44] = ["Google"]
    return raw


def _body(reviews: list, next_token: str = "") -> str:
    """An XSSI-prefixed BOQ response with `reviews` and an optional next token."""
    node = [None, None, reviews, None, None, None, next_token]
    payload = [None] * 11
    payload[10] = node
    import json

    return ")]}'\n" + json.dumps([None, payload])


class _Response:
    def __init__(self, status: int = 200, text: str = ""):
        self.status_code = status
        self.text = text


class _Client:
    """Fake httpx.AsyncClient that replays a queue of BOQ pages."""

    def __init__(self, pages: list[str], status: int = 200):
        self.pages = list(pages)
        self.status = status
        self.requests: list[dict] = []

    async def get(self, url, **kwargs):
        self.requests.append({"url": url, **kwargs})
        text = self.pages.pop(0) if self.pages else ""
        return _Response(self.status, text)

    async def aclose(self) -> None:
        return None


# â”€â”€ Identity â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_feature_id_read_from_real_maps_url():
    assert boq.feature_id(MAPS_URL) == FTID


def test_feature_id_absent_for_bare_place_id_url():
    """A ChIJ place-id URL has no feature id, and BOQ cannot be called with one.

    This is the failure mode that returns HTTP 200 + an empty body, so the
    adapter must refuse rather than report "no reviews".
    """
    assert boq.feature_id("https://www.google.com/maps/place/?q=place_id:ChIJabc") is None
    assert boq.feature_id("") is None
    assert boq.feature_id(None) is None


# â”€â”€ Field mapping â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_review_maps_every_bench_field():
    review = boq._review(_raw_review("rev-9", rating=4, text="Loved it", reply="Thanks!"))

    assert review["review_id"] == "rev-9"
    assert review["rating"] == 4
    assert review["text"] == "Loved it"
    assert review["author"] == "Alice"
    assert review["author_photo"].startswith("https://lh3.googleusercontent.com")
    assert review["owner_answer"] == "Thanks!"
    # Publish time is epoch millis in the payload and RFC3339 in the bench.
    published = datetime.fromisoformat(review["publish_time"])
    assert published.tzinfo is not None
    assert published <= datetime.now(timezone.utc)


def test_review_text_markup_is_cleaned():
    """The panel embeds <br> and HTML entities; the UI renders plain text."""
    review = boq._review(_raw_review(text="Line one<br>Line two &amp; more"))

    assert review["text"] == "Line one\nLine two & more"


def test_review_without_text_stays_empty():
    """Rating-only reviews return empty strings, never neighbouring fields."""
    review = boq._review(_raw_review(text=""))

    assert review["text"] == ""
    assert review["rating"] == 5


def test_review_without_id_is_dropped():
    assert boq._review(_raw_review("")) is None
    assert boq._review("not-a-list") is None


def test_review_rejects_out_of_range_rating():
    assert boq._review(_raw_review(rating=0))["rating"] is None
    assert boq._review(_raw_review(rating=9))["rating"] is None


def test_reply_time_is_relative_and_therefore_omitted():
    """A localized "3 days ago" string has no anchor; guessing a date is worse."""
    review = boq._review(_raw_review(reply="Thanks"))

    assert review["owner_answer"] == "Thanks"
    assert review["owner_answer_time"] is None


def test_photo_that_is_not_a_url_is_omitted():
    assert boq._review(_raw_review(photo=""))["author_photo"] is None


# â”€â”€ Payload validation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_parse_page_reads_reviews_and_token():
    reviews, token = boq._parse_page(_body([_raw_review()], next_token="tok-2"))

    assert len(reviews) == 1
    assert token == "tok-2"


def test_parse_page_rejects_empty_body():
    """An empty body is a block, not an empty review list."""
    with pytest.raises(boq.BoqError):
        boq._parse_page("")


def test_parse_page_rejects_changed_layout():
    with pytest.raises(boq.BoqError):
        boq._parse_page(")]}'\n" + '{"not": "the panel shape"}')


# â”€â”€ Pagination and window â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


async def test_fetch_reviews_paginates_until_depth():
    first = _body([_raw_review(f"r{i}") for i in range(10)], next_token="t2")
    second = _body([_raw_review(f"s{i}") for i in range(20)])
    client = _Client([first, second])

    reviews = await boq.fetch_reviews(FTID, max_reviews=30, client=client)

    assert len(reviews) == 30
    assert len(client.requests) == 2
    # Newest first, so the UI's "Newest" label is truthful.
    times = [r["publish_time"] for r in reviews]
    assert times == sorted(times, reverse=True)


async def test_fetch_reviews_stops_at_window_cutoff():
    """Oldest review on page one is outside the window: stop after one request."""
    reviews = [_raw_review(f"new{i}", days_ago=1) for i in range(9)]
    reviews.append(_raw_review("old", days_ago=90))
    client = _Client([_body(reviews, next_token="t2")])

    kept = await boq.fetch_reviews(FTID, max_reviews=500, days=30, client=client)

    assert len(client.requests) == 1, "paging continued past the window cutoff"
    assert len(kept) == 9
    assert all(r["review_id"] != "old" for r in kept)


async def test_fetch_reviews_dedupes_across_pages():
    page_one = _body([_raw_review("dup"), _raw_review("a")], next_token="t2")
    page_two = _body([_raw_review("dup"), _raw_review("b")])
    client = _Client([page_one, page_two])

    reviews = await boq.fetch_reviews(FTID, max_reviews=50, client=client)

    ids = [r["review_id"] for r in reviews]
    assert sorted(ids) == ["a", "b", "dup"]


async def test_fetch_reviews_honours_the_depth_cap():
    reviews = [_raw_review(f"r{i}") for i in range(20)]
    client = _Client([_body(reviews, next_token="t2")])

    kept = await boq.fetch_reviews(FTID, max_reviews=5, client=client)

    assert len(kept) == 5
    assert len(client.requests) == 1


async def test_fetch_reviews_maps_rate_limit_to_503():
    client = _Client([], status=429)

    with pytest.raises(boq.BoqError) as exc:
        await boq.fetch_reviews(FTID, client=client)

    assert exc.value.status_code == 503


async def test_fetch_reviews_requires_a_feature_id():
    with pytest.raises(boq.BoqError):
        await boq.fetch_reviews("")


async def test_reviews_for_place_without_feature_id_makes_no_request():
    """Legacy rows without a canonical Maps URL must not scrape a guess."""
    assert await boq.reviews_for_place("saved-1", maps_url=None) == []


# â”€â”€ Full place fetch: place facts + deep reviews â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


async def test_get_place_composes_metadata_and_deep_reviews(monkeypatch):
    called = {}
    deep = [{
        "review_id": "rev-deep", "rating": 5, "text": "Great",
        "publish_time": "2026-11-23T00:00:00+00:00", "author": "A",
        "author_photo": None, "owner_answer": None, "owner_answer_time": None,
    }]

    async def fake_details(feature, **kwargs):
        called["detail"] = feature
        return {
            "place_id": PLACE_ID, "name": "Wahmy Burger", "address": "Riyadh",
            "rating": 4.4, "review_count": 6633, "latitude": 24.8152,
            "longitude": 46.7774, "types": ["Hamburger restaurant"],
            "thumbnail": "https://lh3.googleusercontent.com/cover", "reviews": [],
            "photos": [], "reviews_per_score": None, "source": "placedetail",
        }

    async def fake_reviews(feature, *, max_reviews, days, full_history=False, client=None):
        called["reviews"] = {
            "feature": feature, "max_reviews": max_reviews,
            "days": days, "full_history": full_history,
        }
        return deep

    monkeypatch.setattr(placedetail, "get_place", fake_details)
    monkeypatch.setattr(boq, "fetch_reviews", fake_reviews)

    place = await boq.get_place(PLACE_ID, maps_url=MAPS_URL, reviews_limit=250)

    assert called["detail"] == FTID
    assert called["reviews"] == {
        "feature": FTID, "max_reviews": 250,
        "days": boq.DEFAULT_REVIEW_WINDOW_DAYS, "full_history": False,
    }
    assert place["name"] == "Wahmy Burger"
    assert place["rating"] == 4.4
    assert place["review_count"] == 6633
    assert place["thumbnail"] == "https://lh3.googleusercontent.com/cover"
    assert place["types"] == ["Hamburger restaurant"]
    assert place["reviews"] == deep
    assert place["maps_url"] == MAPS_URL
    assert place["source"] == "boq"


async def test_get_place_can_disable_reviews_without_losing_metadata(monkeypatch):
    monkeypatch.setattr(settings, "BOQ_REVIEWS_ENABLED", False)

    async def fake_details(feature, **kwargs):
        return {"name": "Wahmy Burger", "rating": 4.4}

    async def fail(*args, **kwargs):
        raise AssertionError("reviews fetched while disabled")

    monkeypatch.setattr(placedetail, "get_place", fake_details)
    monkeypatch.setattr(boq, "fetch_reviews", fail)

    place = await boq.get_place(PLACE_ID, maps_url=MAPS_URL)
    assert place["name"] == "Wahmy Burger"
    assert place["reviews"] == []


async def test_get_place_requires_a_feature_id(monkeypatch):
    async def fail(*args, **kwargs):
        raise AssertionError("detail fetched without a feature id")

    monkeypatch.setattr(placedetail, "get_place", fail)

    with pytest.raises(boq.BoqError) as exc:
        await boq.get_place(
            PLACE_ID, maps_url="https://www.google.com/maps/place/?q=place_id:ChIJx"
        )
    assert exc.value.status_code == 422


async def test_get_place_propagates_detail_errors(monkeypatch):
    async def boom(feature, **kwargs):
        raise placedetail.PlaceDetailError("blocked", 503)

    monkeypatch.setattr(placedetail, "get_place", boom)

    with pytest.raises(boq.BoqError) as exc:
        await boq.get_place(PLACE_ID, maps_url=MAPS_URL)
    assert exc.value.status_code == 503


async def test_get_place_zero_limit_means_no_reviews(monkeypatch):
    async def fake_details(feature, **kwargs):
        return {"name": "Wahmy Burger", "rating": 4.4}

    async def fail(*args, **kwargs):
        raise AssertionError("reviews fetched for limit=0")

    monkeypatch.setattr(placedetail, "get_place", fake_details)
    monkeypatch.setattr(boq, "fetch_reviews", fail)

    place = await boq.get_place(PLACE_ID, maps_url=MAPS_URL, reviews_limit=0)
    assert place["reviews"] == []

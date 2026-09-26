"""Business Health Scorecard: dimension classification + heuristic scoring."""
from app.modules.analytics.dimensions import (
    DIMENSION_BY_KEY,
    STANDARD_DIMENSIONS,
    score_dimensions,
)


def _row(text: str, rating: int) -> dict:
    return {"text": text, "rating": rating, "replied": True, "topics": []}


def test_standard_set_is_the_agreed_six():
    assert [d.key for d in STANDARD_DIMENSIONS] == [
        "credibility", "support", "speed", "quality", "value", "environment",
    ]
    assert DIMENSION_BY_KEY["support"].label == "Customer Support & Staff"


def test_matches_dimension_and_splits_sentiment():
    rows = [
        _row("The waiter was incredibly friendly and helpful", 5),
        _row("Rude staff ignored us and nobody was friendly", 2),
        _row("ok", 3),
    ]
    out = {d["key"]: d for d in score_dimensions(rows)}
    support = out["support"]
    assert support["mentions"] == 2
    assert support["positive"] == 1
    assert support["negative"] == 1
    assert support["avg_rating"] == 3.5
    assert support["signal"] == "mixed"
    assert support["confidence"] == "low"


def test_zero_mention_dimensions_are_omitted():
    rows = [_row("food was delicious and fresh", 5)]
    keys = [d["key"] for d in score_dimensions(rows)]
    assert keys == ["quality"]
    assert "credibility" not in keys


def test_never_emits_a_non_dimension_name():
    """Regression guard: raw words like 'version'/'thanks' must not appear."""
    rows = [
        _row("new version of the app is really awesome thanks for keeping things", 5),
        _row("stuff and things", 4),
    ]
    labels = {d["label"] for d in score_dimensions(rows)}
    assert labels == set()  # no dimension keyword present -> nothing to show


def test_pure_praise_is_strong_and_pure_complaint_is_weak():
    praise = score_dimensions([_row("fresh tasty food every time", 5), _row("delicious", 5)])
    assert praise[0]["signal"] == "strong"
    complain = score_dimensions([_row("cold and stale food", 1)])
    assert complain[0]["signal"] == "weak"
    assert complain[0]["negative"] == 1
    assert complain[0]["positive"] == 0


def test_confidence_scales_with_mentions():
    assert score_dimensions([_row("clean", 5)])[0]["confidence"] == "low"
    three = score_dimensions([_row("clean", 5), _row("spotless", 5), _row("tidy", 4)])
    assert three[0]["confidence"] == "medium"
    five = score_dimensions([_row("clean", 5) for _ in range(5)])
    assert five[0]["confidence"] == "high"


def test_verdict_states_only_supported_counts():
    d = score_dimensions([_row("waited 30 minutes in queue", 2)])[0]
    assert d["key"] == "speed"
    assert "1 review(s) criticise it" in d["verdict"]
    assert "praise" not in d["verdict"]


def test_evidence_quotes_are_trimmed_and_capped():
    long = "waited forever " + ("x " * 200) + "terrible queue"
    out = score_dimensions([_row(long, 1), _row("queue again", 1), _row("slow", 2)])
    assert len(out[0]["evidence"]) == 2
    assert len(out[0]["evidence"][0]["quote"]) <= 141
    assert out[0]["evidence"][0]["rating"] == 1

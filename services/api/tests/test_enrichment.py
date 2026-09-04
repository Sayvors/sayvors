"""Enrichment unit tests (no DB, no LLM)."""
from app.modules.analytics.enrichment import (
    _extract_json,
    _heuristic_enrich,
    _valid_result,
)


def test_heuristic_negative_detects_topics_and_problems():
    r = _heuristic_enrich(1, "Slow service, rude staff, dirty tables, cold food, nobody answered the phone.")
    assert r["sentiment"] == "negative"
    assert r["sentiment_score"] < 0
    names = {t["name"] for t in r["topics"]}
    assert {"service", "waiting time", "cleanliness", "communication"} <= names
    assert all(p["severity"] == "high" for p in r["problems"])


def test_heuristic_positive():
    r = _heuristic_enrich(5, "Best burgers in the city, friendly staff, great service!")
    assert r["sentiment"] == "positive"
    assert r["sentiment_score"] > 0
    assert r["products"] == []


def test_heuristic_rating_only():
    r = _heuristic_enrich(4, None)
    assert r["sentiment"] == "positive"
    assert r["topics"] == []


def test_extract_json_from_markdown():
    assert _extract_json('```json\n{"sentiment": "positive"}\n```') == {"sentiment": "positive"}


def test_extract_json_from_prose():
    assert _extract_json("Here: {\"sentiment\": \"neutral\", \"sentiment_score\": 0.1} done") == {
        "sentiment": "neutral",
        "sentiment_score": 0.1,
    }


def test_extract_json_invalid_returns_none():
    assert _extract_json("not json at all") is None


def test_valid_result_clamps_and_normalises():
    data = _valid_result({
        "sentiment": "POSITIVE",
        "sentiment_score": 5,
        "topics": [{"name": "staff", "sentiment": "positive"}],
        "products": "bad value",
        "problems": [{"name": "x", "severity": "extreme"}],
    })
    assert data["sentiment"] == "positive"
    assert data["sentiment_score"] == 1.0
    assert data["products"] == []
    assert data["problems"][0]["severity"] == "medium"


def test_valid_result_defaults_missing():
    data = _valid_result({})
    assert data["sentiment"] == "neutral"
    assert data["topics"] == []
    assert data["products"] == []
    assert data["problems"] == []
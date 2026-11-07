"""Conversation insights JSON parsing must be tolerant but never fake data."""
from app.modules.analytics.insights_worker import _extract_insights_json


def test_parses_plain_json():
    parsed = _extract_insights_json(
        '{"top_questions": [{"question": "hours", "count": 2}]}'
    )
    assert parsed is not None
    assert parsed["top_questions"][0]["count"] == 2


def test_parses_fenced_json_with_surrounding_prose():
    raw = (
        "Here are the insights:\n```json\n"
        '{"intents": [{"intent": "booking", "count": 3}]}\n'
        "```\nLet me know if you need more."
    )
    parsed = _extract_insights_json(raw)
    assert parsed is not None
    assert parsed["intents"][0]["intent"] == "booking"


def test_returns_none_for_truncated_json():
    assert _extract_insights_json('{"top_questions": [{"question": "hou') is None


def test_returns_none_for_non_object_json():
    assert _extract_insights_json("[1, 2, 3]") is None

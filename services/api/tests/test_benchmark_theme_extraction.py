import pytest

from app.modules.benchmark.theme_extraction import (
    extract_local_themes,
    group_theme_comparison,
    normalize_theme_key,
    validate_llm_themes,
)


def _reviews():
    return [
        {"review_id": "r1", "text": "Helpful staff and fast service", "rating": 5, "sentiment": "positive", "author": "A", "time": "2026-11-01T00:00:00Z", "answered": True},
        {"review_id": "r2", "text": "The staff were helpful and the service was fast", "rating": 5, "sentiment": "positive", "author": "B", "time": "2026-11-02T00:00:00Z", "answered": False},
        {"review_id": "r3", "text": "Helpful staff but slow service", "rating": 3, "sentiment": "neutral", "author": "C", "time": "2026-11-03T00:00:00Z", "answered": False},
        {"review_id": "r4", "text": "Slow service and rude staff", "rating": 1, "sentiment": "negative", "author": "D", "time": "2026-11-04T00:00:00Z", "answered": True},
        {"review_id": "r5", "text": "خدمة بطيئة والموظفين غير متعاونين", "rating": 2, "sentiment": "negative", "author": "E", "time": "2026-11-05T00:00:00Z", "answered": False},
        {"review_id": "r6", "text": "الخدمة بطيئة جدا", "rating": 1, "sentiment": "negative", "author": "F", "time": "2026-11-06T00:00:00Z", "answered": False},
    ]


def test_local_extractor_counts_distinct_reviews_not_occurrences():
    themes = extract_local_themes(_reviews())
    staff = next(theme for theme in themes if theme["label"] == "helpful staff")
    assert staff["mentions"] == 3
    assert staff["sample_size"] == 6
    assert staff["pct"] == 50.0
    assert staff["positive_mentions"] == 2
    assert staff["neutral_mentions"] == 1
    assert len(staff["examples"]) == 2


def test_local_extractor_ignores_single_mentions():
    themes = extract_local_themes(_reviews())
    assert all(theme["mentions"] >= 2 for theme in themes)
    assert not any(theme["label"] == "rude staff" for theme in themes)


def test_local_extractor_normalizes_arabic_variants():
    themes = extract_local_themes(_reviews()[4:])
    service = next(theme for theme in themes if theme["normalized"] == "بطيئه خدمه")
    assert service["mentions"] == 2
    assert service["negative_mentions"] == 2


def test_local_extractor_prefers_specific_phrase_when_evidence_is_identical():
    reviews = [
        {"text": "الخدمة بطيئة", "rating": 1, "sentiment": "negative"},
        {"text": "الخدمة بطيئة جدا", "rating": 1, "sentiment": "negative"},
    ]
    themes = extract_local_themes(reviews)
    assert themes[0]["normalized"] == "بطيئه خدمه"
    assert not any(theme["normalized"] == "خدمه" for theme in themes)


def test_normalize_theme_key_is_stable():
    assert normalize_theme_key("Helpful staff") == normalize_theme_key("helpful staff")
    assert normalize_theme_key("الخدمة البطيئة") == normalize_theme_key("الخدمه البطيئه")


def test_llm_validation_rejects_hallucinated_counts_and_indices():
    reviews = _reviews()
    payload = {"themes": [{"label": "helpful staff", "sentiment": "positive", "mentions": 99, "review_indices": [0, 1]}]}
    assert validate_llm_themes(payload, reviews) is None

    payload = {"themes": [{"label": "helpful staff", "sentiment": "positive", "mentions": 2, "review_indices": [0, 99]}]}
    assert validate_llm_themes(payload, reviews) is None


def test_llm_validation_uses_real_review_evidence():
    reviews = _reviews()
    payload = {"themes": [{"label": "helpful staff", "sentiment": "positive", "mentions": 2, "review_indices": [0, 1]}]}
    themes = validate_llm_themes(payload, reviews)
    assert themes is not None
    assert themes[0]["mentions"] == 2
    assert themes[0]["positive_mentions"] == 2
    assert themes[0]["examples"][0]["review_id"] == "r1"


def test_group_theme_comparison_merges_same_theme_across_businesses():
    subjects = [
        {"key": "own:mine", "name": "Mine", "themes": [{"label": "helpful staff", "normalized": "helpful staff", "sentiment": "positive", "mentions": 3, "sample_size": 6, "pct": 50.0, "examples": []}]},
        {"key": "saved:peer", "name": "Peer", "themes": [{"label": "Helpful Staff", "normalized": "helpful staff", "sentiment": "positive", "mentions": 1, "sample_size": 10, "pct": 10.0, "examples": []}]},
    ]
    rows = group_theme_comparison(subjects, own_key="own:mine")
    assert len(rows) == 1
    assert rows[0]["label"] == "helpful staff"
    assert rows[0]["own_pct"] == 50.0
    assert rows[0]["peer_median_pct"] == 10.0
    assert rows[0]["gap_pct"] == 40.0

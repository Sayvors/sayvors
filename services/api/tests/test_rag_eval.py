"""P2 eval scoring: pure functions and golden-set validation.

The golden set itself must come from real support questions, so it is not
seeded with invented data. These tests pin the metric semantics instead.
"""
import json

import pytest

from app.modules.rag.eval import recall_at_k, score_case, summarize
from scripts.rag_eval import format_review, load_golden


def test_recall_at_k_counts_only_the_top_k():
    assert recall_at_k(["a", "b"], ["b", "c", "a"], 2) == 0.5
    assert recall_at_k(["a", "b"], ["b", "c", "a"], 3) == 1.0


def test_unlabelled_cases_are_not_scored_as_zero():
    assert recall_at_k([], ["a"], 4) is None
    case = score_case({"id": "x"}, retrieved=["a"], prompt_block="", k=4)
    assert case["labelled"] is False


def test_evidence_requires_every_labelled_fact():
    assert score_case(
        {"expected_facts": ["85 SAR", "Riyadh"]},
        retrieved=[], prompt_block="85 SAR per bag. Delivery: Riyadh.", k=4,
    )["evidence_in_prompt"] is True
    assert score_case(
        {"expected_facts": ["85 SAR", "Jeddah"]},
        retrieved=[], prompt_block="85 SAR per bag.", k=4,
    )["evidence_in_prompt"] is False


def test_summarize_separates_verticals_and_skips_unlabelled():
    rows = [
        score_case({"vertical": "coffee", "expected_chunk_ids": ["a"]},
                   retrieved=["a"], prompt_block="", k=4),
        score_case({"vertical": "coffee", "expected_chunk_ids": ["b"]},
                   retrieved=[], prompt_block="", k=4),
        score_case({"vertical": "bakery", "expected_chunk_ids": ["c"]},
                   retrieved=["c"], prompt_block="", k=4),
        score_case({"vertical": "bakery"}, retrieved=["c"], prompt_block="", k=4),
    ]
    report = summarize(rows)
    assert report["unlabelled"] == 1
    assert report["overall"]["cases"] == 3
    assert report["overall"]["recall_at_k"] == pytest.approx(2 / 3, abs=1e-4)
    assert report["verticals"]["coffee"]["recall_at_k"] == 0.5
    assert report["verticals"]["bakery"]["recall_at_k"] == 1.0


def test_loader_rejects_a_wrong_schema_version(tmp_path):
    path = tmp_path / "golden.json"
    path.write_text(json.dumps({"version": 99, "cases": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="version"):
        load_golden(str(path))


def test_review_mode_shows_what_came_back_for_labelling():
    text = format_review({
        "cases": [
            {
                "id": "q01", "vertical": "food", "question": "كم سعر القهوة؟",
                "retrieved": [
                    {"id": "chunk-1", "content": "اللاتيه بـ15 ريال"},
                    {"id": "chunk-2", "content": "Delivery inside Riyadh"},
                ],
            },
            {"id": "q02", "vertical": "hotel", "question": "غرفة ليلتين", "retrieved": []},
        ]
    })
    assert "[q01] (food) كم سعر القهوة؟" in text
    assert "1. chunk-1  اللاتيه بـ15 ريال" in text
    assert "2. chunk-2" in text
    assert "(no hits — check the databank id)" in text


def test_loader_accepts_a_file_level_databank(tmp_path):
    path = tmp_path / "golden.json"
    path.write_text(
        json.dumps({
            "version": 1,
            "databank_id": "bank-1",
            "cases": [{"question": "price?"}],
        }),
        encoding="utf-8",
    )
    assert load_golden(str(path))[0]["databank_id"] == "bank-1"


def test_loader_rejects_a_case_without_a_databank(tmp_path):
    path = tmp_path / "golden.json"
    path.write_text(
        json.dumps({"version": 1, "cases": [{"question": "price?"}]}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="databank_id"):
        load_golden(str(path))

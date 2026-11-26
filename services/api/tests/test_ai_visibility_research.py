"""Grounded LLM research contract and bounded response validation."""
import json
from types import SimpleNamespace

import pytest

from app.modules.ai_visibility import research


def _source(source_id, excerpt):
    return {
        "id": source_id,
        "label": "S1",
        "title": "Example",
        "url": "https://example.com",
        "excerpt": excerpt,
    }


def test_build_messages_contains_only_numbered_sources():
    messages = research.build_messages(
        branch={"name": "Acme Coffee", "address": "Riyadh"},
        prompt="Best coffee near Malqa",
        locale="en",
        sources=[_source("src-1", "Acme has fresh beans.")],
    )
    payload = "\n".join(message.content for message in messages)
    assert "[S1]" in payload
    assert "Acme has fresh beans." in payload
    assert "Use only the supplied sources" in payload


def test_parse_structured_response_rejects_invalid_json():
    with pytest.raises(research.ResearchValidationError):
        research.parse_response("not json", [_source("src-1", "Evidence")])


def test_parse_structured_response_accepts_valid_payload():
    payload = {
        "answer": "Acme Coffee is a strong option [S1].",
        "claims": [
            {
                "claim": "Acme has fresh beans",
                "quote": "fresh beans",
                "source_ids": ["S1"],
                "status": "supported",
            }
        ],
        "mentioned": True,
        "cited": True,
        "recommended": True,
        "incorrect": False,
        "competitors": [
            {
                "name": "Rival",
                "quote": "Rival is nearby",
                "source_ids": ["S1"],
            }
        ],
        "suggested_actions": [],
    }
    parsed = research.parse_response(
        json.dumps(payload), [_source("src-1", "fresh beans")]
    )
    assert parsed.answer.startswith("Acme Coffee")
    assert parsed.claims[0].source_ids == ["S1"]


@pytest.mark.asyncio
async def test_select_research_model_prefers_largest_context(monkeypatch):
    class _Model:
        def __init__(self, model_id, context):
            self.id = model_id
            self.context = context

    async def _models(_db):
        return [(_Model("small", 8000), "database"), (_Model("large", 128000), "database")]

    monkeypatch.setattr(research, "list_tenant_models", _models)
    assert await research.select_research_model(object()) == "large"


@pytest.mark.asyncio
async def test_select_research_model_rejects_empty_configuration(monkeypatch):
    async def _models(_db):
        return []

    monkeypatch.setattr(research, "list_tenant_models", _models)
    with pytest.raises(research.ResearchValidationError, match="no_llm_model_configured"):
        await research.select_research_model(object())


def test_parse_response_accepts_fenced_json():
    payload = {
        "answer": "Acme is nearby [S1].",
        "claims": [],
        "mentioned": True,
        "cited": True,
        "recommended": False,
        "incorrect": False,
        "competitors": [],
        "suggested_actions": [],
    }
    parsed = research.parse_response(
        f"```json\n{json.dumps(payload)}\n```", [_source("src-1", "Acme is nearby.")]
    )
    assert parsed.answer == payload["answer"]


def test_parse_response_recovers_json_wrapped_in_prose():
    payload = {
        "answer": "Acme is nearby [S1].",
        "claims": [],
        "mentioned": True,
        "cited": True,
        "recommended": False,
        "incorrect": False,
        "competitors": [],
        "suggested_actions": [],
    }
    parsed = research.parse_response(
        f"Here is the research you requested:\n{json.dumps(payload)}\nEnd of brief.",
        [_source("src-1", "Acme is nearby.")],
    )
    assert parsed.answer == payload["answer"]


def test_parse_response_recovers_json_after_prose_with_braces():
    payload = {
        "answer": "Acme is nearby [S1].",
        "claims": [],
        "mentioned": True,
        "cited": True,
        "recommended": False,
        "incorrect": False,
        "competitors": [],
        "suggested_actions": [],
    }
    parsed = research.parse_response(
        f"Use the format {{answer, claims}}. {json.dumps(payload)}",
        [_source("src-1", "Acme is nearby.")],
    )
    assert parsed.answer == payload["answer"]


def test_parse_response_accepts_missing_model_outcomes():
    parsed = research.parse_response(
        json.dumps({
            "answer": "Acme is nearby [S1].",
            "claims": [{
                "claim": "Acme is nearby",
                "quote": "Acme is nearby",
                "source_ids": ["S1"],
            }],
        }),
        [_source("src-1", "Acme is nearby.")],
    )
    assert parsed.mentioned is False
    assert parsed.claims[0].status == "unsupported"


def test_parse_response_coerces_source_id_string_and_trailing_comma():
    parsed = research.parse_response(
        '{"answer":"Acme is nearby [S1].","claims":['
        '{"claim":"Acme is nearby","quote":"Acme is nearby",'
        '"source_ids":"S1","status":"supported",},],}',
        [_source("src-1", "Acme is nearby.")],
    )
    assert parsed.claims[0].source_ids == ["S1"]


def test_parse_response_unwraps_double_encoded_json():
    inner = json.dumps({
        "answer": "Acme is nearby [S1].",
        "claims": [],
        "mentioned": False,
        "cited": False,
        "recommended": False,
        "incorrect": False,
    })
    parsed = research.parse_response(json.dumps(inner), [_source("src-1", "Acme is nearby.")])
    assert parsed.answer == "Acme is nearby [S1]."


def test_response_collections_are_hard_bounded():
    claim = {
        "claim": "Acme is nearby",
        "quote": "Acme is nearby",
        "source_ids": ["S1"],
        "status": "supported",
    }
    competitor = {"name": "Rival", "quote": "Rival is nearby", "source_ids": ["S1"]}
    action = {
        "category": "content",
        "title": "Publish details",
        "rationale": "Improve the evidence",
        "source_ids": ["S1"],
    }
    base = {
        "answer": "Acme is nearby [S1].",
        "mentioned": True,
        "cited": True,
        "recommended": False,
        "incorrect": False,
    }
    for key, row, limit in (
        ("claims", claim, research.MAX_RESEARCH_CLAIMS),
        ("competitors", competitor, research.MAX_COMPETITOR_MENTIONS),
        ("suggested_actions", action, research.MAX_SUGGESTED_ACTIONS),
    ):
        with pytest.raises(research.ResearchValidationError):
            research.parse_response(
                json.dumps({**base, key: [row] * (limit + 1)}),
                [_source("src-1", "Acme is nearby.")],
            )


@pytest.mark.asyncio
async def test_complete_research_uses_metered_gateway(monkeypatch):
    from app.modules.llm import gateway

    source = _source("src-1", "Acme has fresh beans.")
    payload = {
        "answer": "Acme has fresh beans [S1].",
        "claims": [],
        "mentioned": True,
        "cited": True,
        "recommended": False,
        "incorrect": False,
        "competitors": [],
        "suggested_actions": [],
    }
    calls = []

    async def _model(_db):
        return "large:model"

    async def _complete(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(content=json.dumps(payload))

    monkeypatch.setattr(research, "select_research_model", _model)
    monkeypatch.setattr(gateway, "complete", _complete)

    model, parsed = await research.complete_research(
        object(),
        tenant_id="tenant-1",
        channel_id="channel-1",
        branch={"name": "Acme"},
        prompt="Best coffee",
        locale="en",
        sources=[source],
    )

    assert model == "large:model"
    assert parsed.answer == payload["answer"]
    assert len(calls) == 1
    assert calls[0]["model"] == model
    assert calls[0]["tenant_id"] == "tenant-1"
    assert calls[0]["channel_id"] == "channel-1"
    assert calls[0]["purpose"] == research.RESEARCH_PURPOSE
    assert calls[0]["temperature"] == research.RESEARCH_TEMPERATURE
    assert calls[0]["max_tokens"] == research.RESEARCH_MAX_TOKENS

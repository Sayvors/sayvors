"""Agentic RAG unit tests — no live Gemini/DB access required."""

import pytest

from app.modules.llm.providers.base import LLMResponse, LLMUsage, ToolCall
from app.modules.rag import agent
from app.modules.rag.agent import _filter_args, _redact, ask_question
from app.modules.rag.connectors import rows_to_csv, validate_readonly_sql
from app.modules.rag.tools import TOOL_RUNNERS, tool_definitions


# ── SQL guard ──────────────────────────────────────────────

def test_guard_accepts_select_with_forced_limit():
    out = validate_readonly_sql("SELECT id FROM users", 50)
    assert out.upper().startswith("SELECT")
    assert "LIMIT 50" in out.upper()


def test_guard_rejects_writes_and_stacking():
    for bad in [
        "DROP TABLE users",
        "DELETE FROM users",
        "UPDATE users SET x = 1",
        "INSERT INTO users VALUES (1)",
        "SELECT 1; SELECT 2",
        "",
        "   ",
    ]:
        with pytest.raises(ValueError):
            validate_readonly_sql(bad, 50)


def test_guard_accepts_with_and_keeps_explicit_limit():
    out = validate_readonly_sql("WITH a AS (SELECT 1 AS x) SELECT * FROM a LIMIT 5", 50)
    assert "LIMIT 5" in out.upper()
    assert "LIMIT 50" not in out.upper()


def test_rows_to_csv_shapes():
    csv_text = rows_to_csv(["a", "b"], [[1, None], ["x", True]])
    lines = csv_text.strip().splitlines()
    assert lines[0] == "a,b"
    assert lines[1] == "1,"
    assert lines[2] == "x,True"


# ── tool registry ──────────────────────────────────────────

def test_six_tools_registered():
    defs = tool_definitions()
    assert [d.name for d in defs] == [
        "vector_search", "keyword_search", "read_around",
        "db_schema", "db_query", "get_document",
    ]
    assert set(TOOL_RUNNERS.keys()) == {d.name for d in defs}


def test_filter_args_and_redact():
    async def runner(ctx, query, top_k=5):
        return {}

    assert _filter_args(runner, {"query": "x", "top_k": 2, "junk": 1}) == {"query": "x", "top_k": 2}
    assert _redact({"password": "s3cret", "sql": "SELECT 1"})["password"] == "***"


# ── agent loop with fakes ──────────────────────────────────

class _FakeProvider:
    def __init__(self):
        self.calls = 0

    async def complete(self, req):
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                content="Let me search the docs.",
                provider="fake", model="fake", usage=LLMUsage(),
                finish_reason="tool_calls",
                tool_calls=[ToolCall(name="keyword_search",
                                     arguments={"query": "refund policy", "top_k": 3})],
            )
        return LLMResponse(content="Refunds are issued within 30 days.",
                           provider="fake", model="fake", usage=LLMUsage())


async def _fake_keyword_search(ctx, query, top_k=5):
    return {"passages": [{"content": "Refunds within 30 days.",
                          "origin": "snapshot:policy.txt",
                          "score": 0.9,
                          "document_id": "d1"}]}


class _User:
    id = "u1"


@pytest.mark.asyncio
async def test_agent_loop_uses_tool_then_answers(monkeypatch):
    fake = _FakeProvider()
    monkeypatch.setattr(agent, "get_provider", lambda name: fake)
    monkeypatch.setattr(agent, "get_databank", _fake_bank)
    monkeypatch.setitem(TOOL_RUNNERS, "keyword_search", _fake_keyword_search)

    result = await ask_question("bank1", "What is the refund policy?", _User(), db=None)

    assert result["answer"] == "Refunds are issued within 30 days."
    assert result["steps_used"] == 2
    assert any(t["tool"] == "keyword_search" for t in result["trace"])
    assert result["citations"][0]["source"] == "snapshot:policy.txt"
    assert result["citations"][0]["kind"] == "snapshot"


@pytest.mark.asyncio
async def test_agent_unknown_tool_does_not_crash(monkeypatch):
    class _BadProvider:
        calls = 0

        async def complete(self, req):
            type(self).calls += 1
            if type(self).calls == 1:
                return LLMResponse(content="", provider="fake", model="fake",
                                   usage=LLMUsage(), finish_reason="tool_calls",
                                   tool_calls=[ToolCall(name="nope", arguments={})])
            return LLMResponse(content="Gave up gracefully.", provider="fake",
                               model="fake", usage=LLMUsage())

    monkeypatch.setattr(agent, "get_provider", lambda name: _BadProvider())
    monkeypatch.setattr(agent, "get_databank", _fake_bank)

    result = await ask_question("bank1", "Hi?", _User(), db=None)
    assert result["answer"] == "Gave up gracefully."
    assert any("unknown tool" in t["observation"] for t in result["trace"])


def _bank():
    class _Bank:
        id = "bank1"

    return _Bank()


async def _fake_bank(*args, **kwargs):
    return _bank()

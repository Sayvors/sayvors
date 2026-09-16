"""Ask Sayvors assistant endpoint tests.

Calls the endpoint coroutine directly (the shared HTTP client fixture is
broken in this environment — see pre-existing test_api.py failures).
"""
import pytest
from fastapi import HTTPException

from app.modules.assistant.router import AssistantChatRequest, chat
from app.modules.users.models import User


def _user(user_id: str) -> User:
    return User(
        id=user_id,
        email="assistant-test@sayvors.com",
        first_name="Chat",
        last_name="Tester",
        password_hash="x",
        onboarded=True,
    )


@pytest.mark.asyncio
async def test_assistant_chat_answers_from_snapshot(db, user_id, channel_id, monkeypatch):
    """Happy path: snapshot-only grounding (no databank in test DB)."""
    from app.modules.assistant import router as assistant_router

    async def fake_rag(db, user, message):
        return "", [], False

    async def fake_llm(model, system_prompt, history, message, user):
        assert "LIVE BUSINESS DATA" in system_prompt
        assert "replies_posted_today_utc" in system_prompt
        assert message == "How are my reviews doing?"
        return "You have 2 indexed reviews and a 4.5 average rating."

    monkeypatch.setattr(assistant_router, "_rag_answer", fake_rag)
    monkeypatch.setattr(assistant_router, "_llm_reply", fake_llm)

    resp = await chat(
        body=AssistantChatRequest(message="How are my reviews doing?", history=[]),
        user=_user(user_id),
        db=db,
    )
    assert resp.reply.startswith("You have 2 indexed reviews")
    assert resp.grounded_in_rag is False
    assert resp.citations == []
    assert resp.model  # resolved silently — never shown to users in the UI


@pytest.mark.asyncio
async def test_assistant_chat_grounds_in_rag_when_available(db, user_id, monkeypatch):
    """When a Databank exists and the RAG agent answers, citations flow through."""
    from app.modules.assistant import router as assistant_router

    async def fake_rag(db, user, message):
        return (
            "Our refund policy allows 14 days.",
            [{"source": "refund-policy.pdf"}],
            True,
        )

    async def fake_llm(model, system_prompt, history, message, user):
        assert "refund policy allows 14 days" in system_prompt
        return "Refunds are allowed within 14 days per your policy."

    monkeypatch.setattr(assistant_router, "_rag_answer", fake_rag)
    monkeypatch.setattr(assistant_router, "_llm_reply", fake_llm)

    resp = await chat(
        body=AssistantChatRequest(message="What is the refund policy?", history=[]),
        user=_user(user_id),
        db=db,
    )
    assert resp.grounded_in_rag is True
    assert resp.citations == [{"source": "refund-policy.pdf"}]
    assert "14 days" in resp.reply


@pytest.mark.asyncio
async def test_assistant_chat_llm_failure_is_502(db, user_id, monkeypatch):
    from app.modules.assistant import router as assistant_router

    async def fake_rag(db, user, message):
        return "", [], False

    async def boom(*a, **k):
        raise RuntimeError("provider down")

    monkeypatch.setattr(assistant_router, "_rag_answer", fake_rag)
    monkeypatch.setattr(assistant_router, "_llm_reply", boom)

    with pytest.raises(HTTPException) as exc:
        await chat(
            body=AssistantChatRequest(message="hello", history=[]),
            user=_user(user_id),
            db=db,
        )
    assert exc.value.status_code == 502
    assert "unavailable" in exc.value.detail


@pytest.mark.asyncio
async def test_assistant_chat_history_is_included(db, user_id, monkeypatch):
    """Recent conversation turns reach the model so follow-ups work."""
    from app.modules.assistant import router as assistant_router
    from app.modules.assistant.router import ChatMessage

    async def fake_rag(db, user, message):
        return "", [], False

    seen = {}

    async def fake_llm(model, system_prompt, history, message, user):
        seen["history"] = [(m.role, m.content) for m in history]
        seen["message"] = message
        return "Sure — your 1-star reviews mention late delivery."

    monkeypatch.setattr(assistant_router, "_rag_answer", fake_rag)
    monkeypatch.setattr(assistant_router, "_llm_reply", fake_llm)

    resp = await chat(
        body=AssistantChatRequest(
            message="And what are they complaining about?",
            history=[
                ChatMessage(role="user", content="How are my reviews?"),
                ChatMessage(role="assistant", content="You have 12 reviews, 4.2 average."),
            ],
        ),
        user=_user(user_id),
        db=db,
    )
    assert seen["history"] == [
        ("user", "How are my reviews?"),
        ("assistant", "You have 12 reviews, 4.2 average."),
    ]
    assert "complaining" in seen["message"]
    assert "late delivery" in resp.reply

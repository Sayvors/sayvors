"""Abusive-review flagging: the model triages, a human decides.

The single most important property here is that a failure never leaves an
accusation on a review. If the LLM errors, returns junk, or invents a quote,
the score must come back None ("unknown") rather than defaulting to "abusive".
"""
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.analytics.abuse_triage import (
    AbuseAssessment,
    _extract_json,
    assess_review,
)


class _FakeProvider:
    def __init__(self, content=None, error=None):
        self.content = content
        self.error = error

    async def complete(self, request):
        if self.error:
            raise self.error
        return type("Resp", (), {"content": self.content})()


@pytest.fixture
def fake_provider(monkeypatch):
    def install(content=None, error=None):
        import app.modules.llm.providers.registry as registry

        monkeypatch.setattr(
            registry, "get_provider_for_model", lambda model: _FakeProvider(content, error)
        )
        monkeypatch.setattr(
            "app.modules.llm.service._resolve_model", lambda model: ("gpt-4o-mini", None)
        )
    return install


# ── Output handling ──────────────────────────────────────────────

def test_extract_json_handles_fences_and_prose():
    assert _extract_json('{"score": 0.1}') == {"score": 0.1}
    assert _extract_json('```json\n{"score": 0.2}\n```') == {"score": 0.2}
    assert _extract_json('Here you go: {"score": 0.3} hope that helps') == {"score": 0.3}
    assert _extract_json("not json at all") is None


@pytest.mark.asyncio
async def test_valid_assessment_is_returned(fake_provider):
    fake_provider(
        '{"score": 0.86, "labels": ["harassment", "profanity"], '
        '"rationale": "Targets the owner directly with slurs."}'
    )
    out = await assess_review(text="You are a Fraud and a liar", rating=1)
    assert isinstance(out, AbuseAssessment)
    assert out.score == pytest.approx(0.86)
    assert out.labels == ["harassment", "profanity"]


@pytest.mark.asyncio
async def test_llm_failure_yields_no_verdict(fake_provider):
    fake_provider(error=RuntimeError("provider down"))
    assert await assess_review(text="anything", rating=1) is None


@pytest.mark.asyncio
async def test_unparseable_output_yields_no_verdict(fake_provider):
    fake_provider("I cannot help with that.")
    assert await assess_review(text="anything", rating=1) is None


@pytest.mark.asyncio
async def test_out_of_range_score_is_dropped_not_clamped(fake_provider):
    """A score of 1.7 means the output is untrustworthy, not 'very abusive'."""
    fake_provider('{"score": 1.7, "labels": [], "rationale": "x"}')
    assert await assess_review(text="anything", rating=1) is None

    fake_provider('{"score": -0.4, "labels": [], "rationale": "x"}')
    assert await assess_review(text="anything", rating=1) is None


@pytest.mark.asyncio
async def test_fabricated_quote_is_rejected(fake_provider):
    """A rationale quoting text the reviewer never wrote is a hallucination."""
    fake_provider(
        '{"score": 0.9, "labels": ["spam"], "rationale": '
        '"The reviewer wrote \\"buy followers at my site\\" which is spam."}'
    )
    assert await assess_review(text="The food was cold.", rating=1) is None


@pytest.mark.asyncio
async def test_short_fabricated_quote_is_also_rejected(fake_provider):
    """Regression: a 25-char minimum let a 24-char fabrication through."""
    fake_provider(
        '{"score": 0.9, "labels": ["spam"], "rationale": '
        '"Contains \\"click here now ok\\" which is solicitation."}'
    )
    assert await assess_review(text="The food was cold.", rating=1) is None


@pytest.mark.asyncio
async def test_verbatim_quote_is_allowed(fake_provider):
    fake_provider(
        '{"score": 0.7, "labels": ["harassment"], "rationale": '
        '"Calls the owner a \\"complete fraud\\" and a liar."}'
    )
    out = await assess_review(
        text="The owner is a complete fraud and a liar, total scam",
        rating=1,
    )
    assert out is not None and out.score == pytest.approx(0.7)


@pytest.mark.asyncio
async def test_empty_review_is_not_assessed(fake_provider):
    fake_provider('{"score": 0.9, "labels": [], "rationale": "x"}')
    assert await assess_review(text="", rating=1) is None
    assert await assess_review(text="   ", rating=5) is None
    assert await assess_review(text=None, rating=1) is None


@pytest.mark.asyncio
async def test_labels_and_rationale_are_bounded(fake_provider):
    fake_provider(
        '{"score": 0.5, "labels": [' + ",".join(f'"lab{i}"' for i in range(30)) + '], '
        '"rationale": "' + "x" * 5000 + '"}'
    )
    out = await assess_review(text="some review text here", rating=2)
    assert out is not None
    assert len(out.labels) <= 6
    assert len(out.rationale) <= 600


# ── API surface ──────────────────────────────────────────────────

async def _seed(db, user_id, channel_id, text, rating=1):
    from app.modules.analytics.models import ReviewInsight

    row = ReviewInsight(
        id=f"ins-abuse-{abs(hash(text)) % 10**8}",
        user_id=user_id, channel_id=channel_id,
        review_id=f"localith:abuse{abs(hash(text)) % 10**8}",
        rating=rating, review_text=text, reviewer_name="Angry Person",
        sentiment="negative", sentiment_score=0.2,
        topics=[], products=[], problems=[], enrichment_status="done",
    )
    db.add(row)
    await db.commit()
    return row


@pytest.mark.asyncio
async def test_flag_marks_and_scores_but_never_reports(
    db, client, user_id, channel_id, monkeypatch
):
    """Flagging must not touch Google — there is no API to touch."""
    import app.modules.analytics.abuse_router as abuse_router
    import app.modules.analytics.abuse_triage as triage

    async def fake_assess(**kw):
        return AbuseAssessment(score=0.91, labels=["harassment"], rationale="Abusive.")

    monkeypatch.setattr(abuse_router, "assess_review", fake_assess, raising=False)
    monkeypatch.setattr(triage, "assess_review", fake_assess)

    row = await _seed(db, user_id, channel_id, "You are a fraud")

    res = client.post(
        f"/api/v1/analytics/reviews/insights/{row.id}/flag-abuse",
        json={"note": "Targeted abuse of staff"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["abuse_flagged"] is True
    assert body["abuse_score"] == pytest.approx(0.91)
    assert body["abuse_labels"] == ["harassment"]
    assert body["abuse_note"] == "Targeted abuse of staff"
    # Crucially: no verdict yet, and nothing claimed as reported.
    assert body["abuse_verdict"] is None
    assert body["abuse_reported_at"] is None


@pytest.mark.asyncio
async def test_flag_survives_a_failing_model(db, client, user_id, channel_id, monkeypatch):
    import app.modules.analytics.abuse_triage as triage

    async def boom(**kw):
        return None

    monkeypatch.setattr(triage, "assess_review", boom)

    row = await _seed(db, user_id, channel_id, "You are a fraud")
    res = client.post(f"/api/v1/analytics/reviews/insights/{row.id}/flag-abuse", json={})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["abuse_flagged"] is True
    assert body["abuse_score"] is None, "unknown must not be recorded as a score"
    assert body["abuse_labels"] == []


@pytest.mark.asyncio
async def test_verdict_and_report_are_separate_steps(db, client, user_id, channel_id):
    row = await _seed(db, user_id, channel_id, "spam spam buy followers")

    v = client.post(
        f"/api/v1/analytics/reviews/insights/{row.id}/abuse-verdict",
        json={"verdict": "confirmed"},
    )
    assert v.status_code == 200, v.text
    assert v.json()["abuse_verdict"] == "confirmed"
    assert v.json()["abuse_reported_at"] is None, "verdict is not a report"

    r = client.post(f"/api/v1/analytics/reviews/insights/{row.id}/abuse-reported")
    assert r.status_code == 200, r.text
    assert r.json()["abuse_reported_at"] is not None

    c = client.post(f"/api/v1/analytics/reviews/insights/{row.id}/clear-abuse")
    assert c.status_code == 200, c.text
    cleared = c.json()
    assert cleared["abuse_flagged"] is False
    assert cleared["abuse_score"] is None
    assert cleared["abuse_reported_at"] is None


@pytest.mark.asyncio
async def test_cannot_flag_someone_elses_review(db, client, channel_id):
    from app.modules.users.models import User

    row = await _seed(db, "someone-else-entirely", channel_id, "not yours")
    res = client.post(f"/api/v1/analytics/reviews/insights/{row.id}/flag-abuse", json={})
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_flagged_reviews_are_filterable(db, client, user_id, channel_id):
    from app.modules.analytics.service import list_insights

    flagged = await _seed(db, user_id, channel_id, "abusive one")
    await _seed(db, user_id, channel_id, "ordinary one")
    flagged.abuse_flagged = True
    await db.commit()

    rows, total = await list_insights(db, user_id, channel_id=channel_id, abusive=True)
    assert total == 1
    assert rows[0].id == flagged.id

    rows, total = await list_insights(db, user_id, channel_id=channel_id, abusive=False)
    assert total == 1
    assert rows[0].id != flagged.id

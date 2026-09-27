"""The meaning layer: per-review reading that can be checked and corrected.

The failure this exists to prevent: the AI read the Arabic review
"you need to fix your building" as "bank account corrections", and the report
turned that into a HIGH opportunity and a business action. Nothing caught it
because counts were verified and meaning was not.

Pinned here:
  * an invented subject is rejected, not coerced into a legal one
  * a complaint with no verbatim evidence is rejected, not believed
  * abstaining is a real outcome and surfaces as work for a person
  * negation disagreement between model and text lowers confidence
  * a human correction is never overwritten by re-analysis
  * removed reviews no longer leak into the report
"""
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from conftest import TEST_ENGINE

from app.modules.analytics import subjects as S
from app.modules.analytics.enrichment import extract_meaning, is_human_corrected
from app.modules.analytics.intelligence_ai import _held_out_counts, _verify

AR_BUILDING = "يحتاج تصلحون مبناكم"     # "you need to fix your building"
AR_NO_PROBLEM = "ما في مشكلة"          # "there is no problem"  (negated)


class _FakeProvider:
    def __init__(self, content=None, error=None):
        self.content = content
        self.error = error

    async def complete(self, request):
        if self.error:
            raise self.error
        return type("R", (), {"content": self.content})()


@pytest.fixture
def fake_llm(monkeypatch):
    def install(payload=None, error=None):
        import app.modules.llm.providers.registry as registry

        text = payload if isinstance(payload, str) else None
        monkeypatch.setattr(
            registry, "get_provider_for_model",
            lambda model: _FakeProvider(text, error),
        )
        monkeypatch.setattr(
            "app.modules.llm.service._resolve_model", lambda model: ("m", None)
        )
    return install


# ── The building complaint must land on premises ────────────────

@pytest.mark.asyncio
async def test_building_complaint_is_read_as_premises(fake_llm):
    fake_llm(
        '{"intent":"complaining","subject":"facility_premises",'
        '"problem":"The building needs repair","asks":["repair the building"],'
        '"entities":{"location":["Makkah"]},"negated":false,"sentiment":"negative",'
        '"intensity":0.7,"evidence":["مبناكم","تصلحون"],"confidence":0.86}'
    )
    m = await extract_meaning(text=AR_BUILDING, rating=2)

    assert m["subject"] == "facility_premises"
    assert m["subject"] != "billing_payments"
    assert m["needs_human"] is False
    assert m["language"] == "ar"
    assert "مبناكم" in m["evidence"]
    assert m["source"] == "llm"


@pytest.mark.asyncio
async def test_bank_account_subject_is_rejected(fake_llm):
    """The exact fabrication, refused at the boundary."""
    fake_llm(
        '{"intent":"complaining","subject":"bank account","problem":"bank",'
        '"evidence":["bank account"],"confidence":0.95,"sentiment":"negative"}'
    )
    m = await extract_meaning(text=AR_BUILDING, rating=2)

    assert m["subject"] == "other"
    assert m["needs_human"] is True
    assert "invented subject" in (m["reason"] or "")


@pytest.mark.asyncio
async def test_complaint_without_evidence_is_rejected(fake_llm):
    """A negative review with no supporting span is a fabrication."""
    fake_llm(
        '{"intent":"complaining","subject":"billing_payments",'
        '"problem":"customer must correct their bank account","evidence":[],'
        '"confidence":0.95,"sentiment":"negative"}'
    )
    m = await extract_meaning(text=AR_BUILDING, rating=2)

    assert m["needs_human"] is True
    assert "no verbatim evidence" in (m["reason"] or "")


@pytest.mark.asyncio
async def test_fabricated_evidence_is_stripped(fake_llm):
    """Evidence must be in the review; invented quotes never survive."""
    fake_llm(
        '{"intent":"complaining","subject":"facility_premises","problem":"x",'
        '"evidence":["مبناكم","please call my bank about my account"],'
        '"confidence":0.9,"sentiment":"negative"}'
    )
    m = await extract_meaning(text=AR_BUILDING, rating=2)

    assert m["evidence"] == ["مبناكم"]


# ── Praise needs no evidence, so it is not punished for having none ──

@pytest.mark.asyncio
async def test_praise_with_no_evidence_is_accepted(fake_llm):
    fake_llm(
        '{"intent":"praising","subject":"product_quality","problem":null,'
        '"asks":[],"evidence":[],"confidence":0.9,"sentiment":"positive"}'
    )
    m = await extract_meaning(text="Great product", rating=5)
    assert m["needs_human"] is False
    assert m["subject"] == "product_quality"


# ── Negation ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_negation_disagreement_lowers_confidence(fake_llm):
    """Model denies a negation the text plainly contains — trust neither fully.

    The text says "no complaints"; the model reported negated=false. That is
    exactly the inversion that turns a compliment into a complaint, so
    confidence is cut rather than either answer being taken at face value.
    """
    fake_llm(
        '{"intent":"praising","subject":"product_quality","evidence":[],'
        '"negated":false,"confidence":0.9,"sentiment":"positive"}'
    )
    m = await extract_meaning(text="Great product, no complaints at all", rating=5)
    assert m["confidence"] < 0.9
    assert m["confidence"] == pytest.approx(0.54)


@pytest.mark.asyncio
async def test_negation_agreement_keeps_confidence(fake_llm):
    """No penalty when the model and the text agree."""
    fake_llm(
        '{"intent":"praising","subject":"product_quality","evidence":[],'
        '"negated":true,"confidence":0.9,"sentiment":"positive"}'
    )
    m = await extract_meaning(text="Great product, no complaints at all", rating=5)
    assert m["confidence"] == 0.9


@pytest.mark.asyncio
async def test_negated_arabic_complaint_is_not_taken_at_face_value(fake_llm):
    fake_llm(
        '{"intent":"praising","subject":"product_quality","evidence":[],'
        '"negated":false,"confidence":0.85,"sentiment":"positive"}'
    )
    m = await extract_meaning(text=AR_NO_PROBLEM, rating=5)
    # Text contains a negation marker, model denied one -> confidence cut.
    assert m["confidence"] < 0.85


# ── Abstaining is a first-class outcome ────────────────────────

@pytest.mark.asyncio
async def test_low_confidence_queues_for_a_human(fake_llm):
    """Grounded, but the model is unsure — still a person's job."""
    fake_llm(
        '{"intent":"?", "subject":"other","evidence":["Hmm"],"confidence":0.3,'
        '"sentiment":"positive"}'
    )
    m = await extract_meaning(text="Hmm.", rating=3)
    assert m["needs_human"] is True
    assert m["reason"] == "low confidence"


@pytest.mark.asyncio
async def test_llm_failure_abstains_rather_than_guessing(fake_llm):
    fake_llm(error=RuntimeError("provider down"))
    m = await extract_meaning(text=AR_BUILDING, rating=2)
    assert m["needs_human"] is True
    assert m["confidence"] == 0.0
    assert m["subject"] == "other"
    assert m["evidence"] == []


@pytest.mark.asyncio
async def test_unparseable_output_abstains(fake_llm):
    fake_llm("I cannot help with that.")
    m = await extract_meaning(text=AR_BUILDING, rating=2)
    assert m["needs_human"] is True


@pytest.mark.asyncio
async def test_empty_review_abstains(fake_llm):
    m = await extract_meaning(text="", rating=5)
    assert m["needs_human"] is True
    assert m["reason"] == "no review text"


# ── Human corrections are authoritative ─────────────────────────

def test_human_corrected_records_are_recognised():
    assert is_human_corrected({"source": "human"}) is True
    assert is_human_corrected({"source": "llm"}) is False
    assert is_human_corrected(None) is False
    assert is_human_corrected("nonsense") is False


# ── API: the human gate ─────────────────────────────────────────

async def _insight(db, user_id, channel_id, text, rating=2):
    from app.modules.analytics.models import ReviewInsight

    row = ReviewInsight(
        id=f"ins-m-{abs(hash(text)) % 10**8}",
        user_id=user_id, channel_id=channel_id,
        review_id=f"localith:m{abs(hash(text)) % 10**8}",
        rating=rating, review_text=text, reviewer_name="Tester",
        sentiment="negative", sentiment_score=0.2,
        topics=[], products=[], problems=[], enrichment_status="done",
        meaning={
            "subject": "billing_payments",
            "problem": "correct your bank account",
            "evidence": [],
            "confidence": 0.9,
            "needs_human": False,
            "source": "llm",
        },
    )
    db.add(row)
    await db.commit()
    return row


def _row(*, rid, user_id, channel_id, text, rating, sentiment, problems=None,
         meaning=None, days_ago=1):
    """A review row for the report-loading tests."""
    from app.modules.analytics.models import ReviewInsight

    return ReviewInsight(
        id=f"ins-r-{rid}",
        user_id=user_id,
        channel_id=channel_id,
        review_id=f"localith:{rid}",
        rating=rating,
        review_text=text,
        reviewer_name="Tester",
        sentiment=sentiment,
        sentiment_score=0.5,
        topics=[],
        products=[],
        problems=problems or [],
        enrichment_status="done",
        review_updated_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        meaning=meaning,
    )


@pytest.mark.asyncio
async def test_correction_overrides_a_wrong_reading(db, client, user_id, channel_id):
    row = await _insight(db, user_id, channel_id, AR_BUILDING)

    res = client.post(
        f"/api/v1/analytics/reviews/insights/{row.id}/meaning",
        json={"subject": "facility_premises", "problem": "Building needs repair"},
    )
    assert res.status_code == 200, res.text
    meaning = res.json()["meaning"]
    assert meaning["subject"] == "facility_premises"
    assert meaning["source"] == "human"
    assert meaning["corrected_at"] is not None
    assert meaning["needs_human"] is False
    assert meaning["confidence"] == 1.0


@pytest.mark.asyncio
async def test_correction_refuses_an_invented_subject(db, client, user_id, channel_id):
    """Silently coercing to 'other' would reintroduce the original problem."""
    row = await _insight(db, user_id, channel_id, AR_BUILDING)
    res = client.post(
        f"/api/v1/analytics/reviews/insights/{row.id}/meaning",
        json={"subject": "Account Issues"},
    )
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert "not a valid subject" in detail
    assert "facility_premises" in detail


@pytest.mark.asyncio
async def test_correction_cannot_touch_another_tenants_review(
    db, client, channel_id
):
    row = await _insight(db, "someone-else", channel_id, AR_BUILDING)
    res = client.post(
        f"/api/v1/analytics/reviews/insights/{row.id}/meaning",
        json={"subject": "facility_premises"},
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_replay_still_extracts_meaning_for_legacy_rows(
    db, user_id, channel_id, monkeypatch
):
    """Every existing row already says enrichment "done".

    Keyed on enrichment alone, the idempotent-replay guard would skip all of
    them forever and the report would read nothing at all. The replay must
    still fill in meaning, and must not re-run meaning once it is there.
    """
    from app.modules.analytics import consumer
    from app.modules.analytics.models import ReviewInsight

    db.add(_row(
        rid="legacy", user_id=user_id, channel_id=channel_id,
        text=AR_BUILDING, rating=2, sentiment="negative", meaning=None,
    ))
    await db.commit()

    calls: list[str] = []

    async def _fake_extract(*, text, rating, reviewer_name=None, tenant_id=None):
        calls.append(text)
        return {
            "subject": "facility_premises", "problem": "building",
            "evidence": ["مبناكم"], "confidence": 0.9, "intensity": 0.5,
            "needs_human": False, "source": "llm", "language": "ar",
            "intent": "complaining", "asks": [], "entities": {},
            "negated": False, "reason": None,
        }

    payload = {
        "event": "review.discovered",
        "channel_id": channel_id,
        "review_id": "localith:legacy",
        "text": AR_BUILDING,
        "rating": 2,
        "reviewer_name": "Tester",
        "review_updated_at": datetime.now(timezone.utc).isoformat(),
    }

    monkeypatch.setattr(consumer, "async_session", _test_session_factory())
    monkeypatch.setattr(consumer, "extract_meaning", _fake_extract)
    monkeypatch.setattr(consumer, "enrich_review", _fake_enrich)
    monkeypatch.setattr(consumer, "enqueue_event", _fake_enqueue)

    # First pass: meaning is missing, so it must be extracted.
    await consumer._handle_discovered(payload)
    row = await db.get(ReviewInsight, "ins-r-legacy")
    assert row.meaning["subject"] == "facility_premises"
    assert len(calls) == 1

    # Second pass: nothing changed, meaning is present. No second LLM call.
    await consumer._handle_discovered(payload)
    row = await db.get(ReviewInsight, "ins-r-legacy")
    assert len(calls) == 1, "meaning was re-extracted on a no-op replay"
    assert row.meaning["subject"] == "facility_premises"


@pytest.mark.asyncio
async def test_replay_never_overwrites_a_human_correction(
    db, user_id, channel_id, monkeypatch
):
    """A person's reading of a review outranks the model, permanently."""
    from app.modules.analytics import consumer
    from app.modules.analytics.models import ReviewInsight

    db.add(_row(
        rid="fixed", user_id=user_id, channel_id=channel_id,
        text=AR_BUILDING, rating=2, sentiment="negative",
        meaning=_human_meaning(),
    ))
    await db.commit()

    async def _boom(*a, **k):
        raise AssertionError("the model re-ran over a human correction")

    payload = {
        "event": "review.discovered",
        "channel_id": channel_id,
        "review_id": "localith:fixed",
        "text": AR_BUILDING,
        "rating": 2,
        "reviewer_name": "Tester",
        "review_updated_at": datetime.now(timezone.utc).isoformat(),
    }

    monkeypatch.setattr(consumer, "async_session", _test_session_factory())
    monkeypatch.setattr(consumer, "extract_meaning", _boom)
    monkeypatch.setattr(consumer, "enrich_review", _fake_enrich)
    monkeypatch.setattr(consumer, "enqueue_event", _fake_enqueue)

    await consumer._handle_discovered(payload)
    row = await db.get(ReviewInsight, "ins-r-fixed")
    assert row.meaning["source"] == "human"
    assert row.meaning["corrected_at"] == "2026-09-27T00:00:00+00:00"


@pytest.mark.asyncio
async def test_reviewer_edit_invalidates_a_stale_human_correction(
    db, user_id, channel_id, monkeypatch
):
    """A human call on old text is not a call on new text."""
    from app.modules.analytics import consumer
    from app.modules.analytics.models import ReviewInsight

    db.add(_row(
        rid="changed", user_id=user_id, channel_id=channel_id,
        text="old text", rating=2, sentiment="negative",
        meaning=_human_meaning(language="en", evidence="old"),
    ))
    await db.commit()

    seen: list[str] = []

    async def _fake_extract(*, text, rating, reviewer_name=None, tenant_id=None):
        seen.append(text)
        return {
            "subject": "billing_payments", "problem": "charged twice",
            "evidence": ["charged twice"], "confidence": 0.8, "intensity": 0.5,
            "needs_human": False, "source": "llm", "language": "en",
            "intent": "complaining", "asks": [], "entities": {},
            "negated": False, "reason": None,
        }

    payload = {
        "event": "review.discovered",
        "channel_id": channel_id,
        "review_id": "localith:changed",
        "text": "you charged me twice",
        "rating": 1,
        "reviewer_name": "Tester",
        "review_updated_at": datetime.now(timezone.utc).isoformat(),
    }

    monkeypatch.setattr(consumer, "async_session", _test_session_factory())
    monkeypatch.setattr(consumer, "extract_meaning", _fake_extract)
    monkeypatch.setattr(consumer, "enrich_review", _fake_enrich)
    monkeypatch.setattr(consumer, "enqueue_event", _fake_enqueue)

    await consumer._handle_discovered(payload)
    row = await db.get(ReviewInsight, "ins-r-changed")
    assert seen == ["you charged me twice"]
    assert row.meaning["source"] == "llm"
    assert row.meaning["subject"] == "billing_payments"


@pytest.mark.asyncio
async def test_replay_never_claims_a_review_was_just_seen(
    db, user_id, channel_id, monkeypatch
):
    """A replayed event must not write `last_seen_at`.

    `last_seen_at` is the evidence the removal sweep trusts. A Kafka event is
    replayed on redelivery and rebalance, so writing `now` from the consumer
    made ten reviews that had not been seen since the 26th claim they were seen
    that morning — corrupting the one field that decides whether a merchant's
    reviews are still live.
    """
    from app.modules.analytics import consumer
    from app.modules.analytics.models import ReviewInsight
    from datetime import datetime as _dt

    stale = _dt(2026, 9, 26, 11, 25, 39, tzinfo=timezone.utc)
    db.add(_row(
        rid="old", user_id=user_id, channel_id=channel_id,
        text="an old review", rating=5, sentiment="positive", meaning=None,
    ))
    await db.commit()
    await db.execute(
        __import__("sqlalchemy").text(
            "UPDATE review_insights SET last_seen_at = :t WHERE id = 'ins-r-old'"
        ),
        {"t": stale},
    )
    await db.commit()

    async def _fake_extract(*a, **k):
        return {
            "subject": "staff_service", "problem": None, "evidence": ["Great"],
            "confidence": 0.9, "intensity": 0.2, "needs_human": False,
            "source": "llm", "language": "en", "intent": "praising",
            "asks": [], "entities": {}, "negated": False, "reason": None,
        }

    monkeypatch.setattr(consumer, "async_session", _test_session_factory())
    monkeypatch.setattr(consumer, "extract_meaning", _fake_extract)
    monkeypatch.setattr(consumer, "enrich_review", _fake_enrich)
    monkeypatch.setattr(consumer, "enqueue_event", _fake_enqueue)

    await consumer._handle_discovered({
        "event": "review.discovered", "channel_id": channel_id,
        "review_id": "localith:old", "text": "an old review", "rating": 5,
        "reviewer_name": "Tester",
        "review_updated_at": stale.isoformat(),
    })

    row = await db.get(ReviewInsight, "ins-r-old")
    assert row.last_seen_at == stale, "replay rewrote last_seen_at"


@pytest.mark.asyncio
async def test_replay_does_not_resurrect_a_genuinely_removed_review(
    db, user_id, channel_id, monkeypatch
):
    """A replay must not clear a correct removal verdict either.

    The same reasoning as `last_seen_at`: an event replay is not proof the
    review is back on the listing. Only the sync's full fetch can clear it, and
    it does so in the same pass that computes the seen-set.
    """
    from app.modules.analytics import consumer
    from app.modules.analytics.models import ReviewInsight

    gone = _row(
        rid="gone2", user_id=user_id, channel_id=channel_id,
        text="deleted by reviewer", rating=1, sentiment="negative", meaning=None,
    )
    gone.removed_at = datetime(2026, 9, 26, 11, 26, 8, tzinfo=timezone.utc)
    db.add(gone)
    await db.commit()

    async def _fake_extract(*a, **k):
        return {
            "subject": "other", "problem": None, "evidence": [],
            "confidence": 0.5, "intensity": 0.5, "needs_human": True,
            "source": "llm", "language": "en", "intent": "complaining",
            "asks": [], "entities": {}, "negated": False, "reason": "low confidence",
        }

    monkeypatch.setattr(consumer, "async_session", _test_session_factory())
    monkeypatch.setattr(consumer, "extract_meaning", _fake_extract)
    monkeypatch.setattr(consumer, "enrich_review", _fake_enrich)
    monkeypatch.setattr(consumer, "enqueue_event", _fake_enqueue)

    await consumer._handle_discovered({
        "event": "review.discovered", "channel_id": channel_id,
        "review_id": "localith:gone2", "text": "deleted by reviewer", "rating": 1,
        "reviewer_name": "Tester",
        "review_updated_at": datetime.now(timezone.utc).isoformat(),
    })

    row = await db.get(ReviewInsight, "ins-r-gone2")
    assert row.removed_at is not None, "a replay cleared a correct removal verdict"


def _human_meaning(language="ar", evidence="مبناكم"):
    return {
        "subject": "facility_premises", "problem": "the building",
        "evidence": [evidence], "confidence": 1.0,
        "needs_human": False, "source": "human", "language": language,
        "intent": "complaining", "asks": [], "entities": {},
        "negated": False, "intensity": 0.5, "reason": None,
        "corrected_at": "2026-09-27T00:00:00+00:00",
    }


async def _fake_enrich(rating, text, reviewer_name, tenant_id=None):
    """The legacy enrichment step; these tests assert on meaning, not this."""
    return {
        "sentiment": "negative", "sentiment_score": -0.6,
        "topics": [], "products": [], "problems": [],
    }


async def _fake_enqueue(event_type, payload, topic="review-events"):
    return "evt"


def _test_session_factory():
    """Session factory bound to the test engine (the consumer opens its own)."""
    return async_sessionmaker(TEST_ENGINE, class_=AsyncSession, expire_on_commit=False)


# ── The UI must offer exactly the server's subjects ─────────────

def test_frontend_subject_list_matches_the_server():
    """The dropdown and the API must not disagree.

    If the UI offers a subject the API rejects, correction is broken in the
    one place a person is trying to fix a broken reading — and the reverse
    means the API accepts something the UI cannot show.
    """
    from app.modules.analytics import subjects as S

    ts = (_REPO_ROOT / "apps" / "web" / "lib" / "meaning.ts").read_text(
        encoding="utf-8"
    )
    offered = set(re.findall(r'value:\s*"([a-z_]+)"', ts))
    assert offered == set(S.SUBJECT_KEYS), (
        "meaning.ts and subjects.py have drifted apart; "
        f"UI-only={sorted(offered - set(S.SUBJECT_KEYS))} "
        f"server-only={sorted(set(S.SUBJECT_KEYS) - offered)}"
    )


# ── The report may not name a category the meaning layer did not ──

def _rowdict(text, rating, subject, evidence, needs_human=False,
             source="llm", language="en", replied=False):
    """A loaded review as _verify() sees it."""
    return {
        "text": text, "rating": rating, "replied": replied,
        "problems": [],
        "meaning": {
            "subject": subject, "evidence": evidence, "language": language,
            "confidence": 0.9, "needs_human": needs_human, "source": source,
            "problem": "", "intent": "complaining", "asks": [],
            "entities": {}, "negated": False, "intensity": 0.5, "reason": None,
        },
    }


def _parsed_ai_output():
    """A model payload containing the exact fabrication that shipped."""
    from app.modules.analytics.intelligence_ai import (
        AIAction, AIOpportunity, AIIntelligence, AIStrength, AITheme,
    )

    return AIIntelligence(
        summary="Customers mention several areas worth attention this period.",
        themes=[AITheme(
            name="Bank Account Corrections", mentions=4, avg_rating=2.0,
            positive_pct=0, phrases=["call my bank"],
        )],
        opportunities=[AIOpportunity(
            level="HIGH", title="Bank account corrections",
            detail="Customers report bank issues", impact="HIGH",
        )],
        strengths=[AIStrength(title="Bank loyalty", mentions=9, avg=4.8)],
        actions=[AIAction(
            title="Hire a banking specialist",
            detail="Customers need bank account help.",
        )],
    )


def test_report_drops_a_category_the_meaning_layer_never_confirmed():
    rows = [
        _rowdict(AR_BUILDING, 2, "facility_premises", ["مبناكم"], language="ar"),
        _rowdict(AR_BUILDING, 2, "facility_premises", ["تصلحون"], language="ar"),
    ]
    out = _verify(_parsed_ai_output(), {"total": 2}, rows)

    names = [t.name for t in out.themes]
    assert names == ["Facility & premises"]
    assert not any("ank" in n for n in names), names

    text = " ".join(
        [o.title + o.detail for o in out.opportunities]
        + [a.title + a.detail for a in out.actions]
        + [s.title for s in out.strengths]
    )
    assert "bank" not in text.lower()
    assert "Bank" not in text


def test_report_actions_come_from_the_playbook_for_that_subject():
    rows = [
        _rowdict(AR_BUILDING, 2, "facility_premises", ["مبناكم"], language="ar"),
        _rowdict("dirty room", 1, "cleanliness", ["dirty"]),
    ]
    out = _verify(_parsed_ai_output(), {"total": 2}, rows)
    titles = [a.title for a in out.actions]

    assert "Fix the building and premises" in titles
    assert "Reinstate and audit the cleaning schedule" in titles
    # The model's own action had no verified subject behind it.
    assert "Hire a banking specialist" not in titles


def test_priority_follows_real_complaint_volume():
    one = [_rowdict("x", 2, "facility_premises", ["x"])]
    many = [_rowdict(f"x{i}", 2, "facility_premises", ["x"]) for i in range(3)]
    parsed = _parsed_ai_output()

    low = _verify(parsed, {"total": 1}, one).opportunities
    high = _verify(parsed, {"total": 3}, many).opportunities

    assert low[0].level in {"MEDIUM", "MAINTAIN"}
    assert high[0].level == "HIGH"
    assert high[0].impact == "HIGH"


def test_praise_alone_never_becomes_an_opportunity():
    rows = [_rowdict("lovely staff", 5, "staff_service", ["lovely"])]
    out = _verify(_parsed_ai_output(), {"total": 1}, rows)
    assert out.opportunities == []
    assert [a.title for a in out.actions] == ["Coach the staff named in these reviews"] or \
        out.actions == [] or all("Respond to" in a.title for a in out.actions)


def test_unread_reviews_are_held_out_not_grouped():
    rows = [
        _rowdict(AR_BUILDING, 2, "facility_premises", ["مبناكم"], language="ar"),
        _rowdict("hmm", 3, "other", [], needs_human=True),
        _rowdict("not analysed yet", 3, "other", []),
    ]
    # Strip meaning entirely from the third row.
    rows[2]["meaning"] = None
    out = _verify(_parsed_ai_output(), {"total": 3}, rows)

    assert [t.name for t in out.themes] == ["Facility & premises"]
    assert sum(t.mentions for t in out.themes) == 1


def test_held_out_counts_are_surfaced():
    rows = [
        _rowdict("a", 2, "facility_premises", ["a"]),
        # Held for a person: the model would not stand behind this reading.
        _rowdict("b", 3, "other", [], needs_human=True),
        # Never analysed at all.
        {"text": "c", "rating": 3, "replied": False, "problems": [], "meaning": None},
        # Subject outside the closed vocabulary: an invention.
        _rowdict("d", 3, "Account Issues", ["d"]),
        # "other" is a real subject, so this one is reportable, not held out.
        _rowdict("e", 3, "other", ["e"]),
    ]
    held = _held_out_counts(rows)
    assert held["total"] == 3
    assert held["needs_human"] == 1
    assert held["not_analysed"] == 1
    assert held["unclassified"] == 1


def test_report_claims_nothing_when_nothing_is_readable():
    """Better to publish a summary and no categories than invented ones."""
    rows = [_rowdict("hmm", 3, "other", [], needs_human=True)]
    out = _verify(_parsed_ai_output(), {"total": 1}, rows)

    assert out.themes == []
    assert out.opportunities == []
    assert out.strengths == []
    assert out.actions == []
    assert out.summary  # narrative still published


def test_every_playbook_subject_is_a_real_subject():
    """A playbook entry for a non-existent subject is dead code that implies
    coverage the vocabulary does not have."""
    from app.modules.analytics.intelligence_ai import _SUBJECT_PLAYBOOK
    from app.modules.analytics.subjects import SUBJECT_KEYS

    assert set(_SUBJECT_PLAYBOOK) <= set(SUBJECT_KEYS)
    assert set(_SUBJECT_PLAYBOOK) == set(SUBJECT_KEYS), (
        "every subject needs a playbook entry: "
        f"missing {sorted(set(SUBJECT_KEYS) - set(_SUBJECT_PLAYBOOK))}"
    )


def test_held_out_counts_travel_with_the_persisted_report():
    """They must survive the store→serve round trip, or the UI shows nothing.

    The stored-report path rebuilds its response from an explicit key list, so
    a count that is only on the live response disappears for every merchant
    reading a cached report. That is the normal path, not the exception.
    """
    from app.modules.analytics.intelligence_ai import _verified_stats

    rows = [
        _rowdict("a", 2, "facility_premises", ["a"]),
        {"text": "b", "rating": 3, "replied": False, "problems": [], "meaning": None},
    ]
    stats = _verified_stats(rows)
    assert stats["held_out"]["total"] == 1
    assert stats["held_out"]["not_analysed"] == 1
    # stats is copied wholesale into the stored row and back out again.
    assert "held_out" in stats


def test_summary_is_told_how_many_reviews_it_is_not_seeing():
    """An honest summary cannot claim to cover reviews the report withheld."""
    import inspect

    from app.modules.analytics import intelligence_ai as ai

    src = inspect.getsource(ai._call_llm)
    assert "reviews_not_included" in src


# ── Removed reviews must not reach the report ───────────────────

@pytest.mark.asyncio
async def test_report_excludes_removed_reviews(db, user_id, channel_id):
    """The report said 9 reviews while the merchant saw 7."""
    from app.modules.analytics.intelligence_ai import _load_reviews

    for i in range(3):
        db.add(_row(
            rid=f"live{i}", user_id=user_id, channel_id=channel_id,
            text=f"live {i}", rating=5, sentiment="positive",
        ))
    gone = _row(
        rid="gone", user_id=user_id, channel_id=channel_id,
        text="deleted review", rating=1, sentiment="negative",
    )
    gone.removed_at = datetime.now(timezone.utc)
    db.add(gone)
    await db.commit()

    rows = await _load_reviews(db, user_id, None, days=90)
    texts = {r["text"] for r in rows}
    assert "live 0" in texts
    assert "deleted review" not in texts
    assert len(rows) == 3


@pytest.mark.asyncio
async def test_report_passes_complaints_not_just_praise(db, user_id, channel_id):
    """`problems` was being dropped, so the report could only see praise."""
    from app.modules.analytics.intelligence_ai import _load_reviews

    db.add(_row(
        rid="problems", user_id=user_id, channel_id=channel_id,
        text="bad", rating=1, sentiment="negative",
        problems=[{"name": "dirty", "severity": "high"}],
        meaning={
            "subject": "cleanliness", "problem": "dirty",
            "evidence": ["bad"], "confidence": 0.9,
            "needs_human": False, "source": "llm", "language": "en",
        },
    ))
    await db.commit()

    rows = await _load_reviews(db, user_id, None, days=90)
    entry = next(r for r in rows if r["text"] == "bad")
    assert entry["problems"] == ["dirty"]
    assert entry["meaning"]["subject"] == "cleanliness"


@pytest.mark.asyncio
async def test_ungrounded_meaning_withholds_raw_text_from_the_report(
    db, user_id, channel_id
):
    """A checked meaning travels; the raw text is not handed back for re-reading."""
    from app.modules.analytics.intelligence_ai import _load_reviews

    db.add(_row(
        rid="hold", user_id=user_id, channel_id=channel_id,
        text=AR_BUILDING, rating=1, sentiment="negative",
        meaning={
            "subject": "facility_premises", "problem": "building",
            "evidence": ["مبناكم"], "confidence": 0.9,
            "needs_human": False, "source": "llm", "language": "ar",
        },
    ))
    await db.commit()

    rows = await _load_reviews(db, user_id, None, days=90)
    entry = next(
        r for r in rows
        if isinstance(r.get("meaning"), dict)
        and r["meaning"].get("language") == "ar"
    )
    assert entry["text"] == ""
    assert entry["meaning"]["subject"] == "facility_premises"
    assert "مبناكم" in entry["meaning"]["evidence"]

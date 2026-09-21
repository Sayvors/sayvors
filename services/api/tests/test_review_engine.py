"""Tests for the review engine — strategy search, validation, full flow."""
import json
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.review_engine.models import ResponseStrategy, ReviewResponseLog
from app.modules.review_engine.schemas import (
    GeneratedResponse,
    ReviewAnalysis,
    ReviewEngineRequest,
    StrategyMatch,
    ValidationResult,
)
from app.modules.review_engine.strategies import search_strategies, CHANNEL_POLICIES, DEFAULT_BRAND_VOICE
from app.modules.review_engine.validator import validate_response
from app.modules.review_engine.understanding import _rule_based_analysis


# ── helpers ──────────────────────────────────────────────

async def _seed_strategies(db: AsyncSession):
    """Insert the 10 core strategies into the in-memory test DB."""
    from app.modules.review_engine.strategies import CORE_STRATEGIES
    for s in CORE_STRATEGIES:
        db.add(ResponseStrategy(
            id=s["id"],
            name=s["name"],
            description=s["description"],
            category=s["category"],
            conditions=s.get("conditions"),
            instructions=s.get("instructions"),
            compatible_strategies=s.get("compatible_strategies"),
            priority=s.get("priority", 50),
            enabled=True,
        ))
    await db.commit()


# ── strategy search tests ────────────────────────────────

@pytest.mark.asyncio
async def test_search_strategies_positive_review(db):
    await _seed_strategies(db)
    analysis = ReviewAnalysis(
        sentiment="very_positive",
        emotion="joy",
        intent=["praise"],
        issue_type=None,
        product_reference=None,
        urgency="low",
        customer_request="Amazing service!",
        language="en",
    )
    matches = await search_strategies(analysis, "google_review", db)
    ids = [m.strategy_id for m in matches]
    assert "show_appreciation" in ids
    assert "acknowledge_feedback" in ids
    assert "keep_response_minimal" in ids
    # Negative-only strategies should NOT appear
    assert "apologize_for_issue" not in ids
    assert "reassure_customer" not in ids


@pytest.mark.asyncio
async def test_search_strategies_negative_review(db):
    await _seed_strategies(db)
    analysis = ReviewAnalysis(
        sentiment="very_negative",
        emotion="anger",
        intent=["complaint"],
        issue_type="product_quality",
        product_reference="pepperoni pizza",
        urgency="medium",
        customer_request="The pizza was terrible.",
        language="en",
    )
    matches = await search_strategies(analysis, "google_review", db)
    ids = [m.strategy_id for m in matches]
    assert "apologize_for_issue" in ids
    assert "acknowledge_feedback" in ids
    assert "address_specific_issue" in ids
    assert "reassure_customer" in ids
    assert "encourage_another_visit" in ids
    # Positive-only strategies should NOT appear
    assert "show_appreciation" not in ids
    assert "keep_response_minimal" not in ids


@pytest.mark.asyncio
async def test_search_strategies_refund_request(db):
    await _seed_strategies(db)
    analysis = ReviewAnalysis(
        sentiment="very_negative",
        emotion="anger",
        intent=["complaint", "refund_request"],
        issue_type="product_quality",
        product_reference="laptop",
        urgency="high",
        customer_request="I want my money back, this laptop is stolen.",
        language="en",
    )
    matches = await search_strategies(analysis, "google_review", db)
    ids = [m.strategy_id for m in matches]
    assert "invite_private_conversation" in ids


@pytest.mark.asyncio
async def test_search_strategies_returns_sorted_by_priority(db):
    await _seed_strategies(db)
    analysis = ReviewAnalysis(
        sentiment="negative",
        emotion="frustration",
        intent=["complaint"],
        issue_type="service_quality",
        product_reference=None,
        urgency="medium",
        customer_request="Bad service.",
        language="en",
    )
    matches = await search_strategies(analysis, "google_review", db)
    priorities = [m.priority for m in matches]
    assert priorities == sorted(priorities, reverse=True)


# ── validation tests ─────────────────────────────────────

def test_validate_clean_response():
    analysis = ReviewAnalysis(
        sentiment="negative", emotion="frustration", intent=["complaint"],
        issue_type="product_quality", product_reference=None, urgency="medium",
        customer_request="Bad pizza.", language="en",
    )
    response = GeneratedResponse(
        response_text="We're sorry the pizza didn't meet your expectations. We'd love the chance to make it right.",
        strategies_used=["acknowledge_feedback", "apologize_for_issue"],
    )
    policy = CHANNEL_POLICIES["google_review"]
    result = validate_response(response, analysis, policy)
    assert result.passed is True
    assert all(result.checks.values())


def test_validate_rejects_pii():
    analysis = ReviewAnalysis(
        sentiment="negative", emotion="frustration", intent=["complaint"],
        issue_type="billing", product_reference=None, urgency="medium",
        customer_request="Wrong charge.", language="en",
    )
    response = GeneratedResponse(
        response_text="Please call us at 555-123-4567 to resolve this.",
        strategies_used=["invite_private_conversation"],
    )
    policy = CHANNEL_POLICIES["google_review"]
    result = validate_response(response, analysis, policy)
    assert result.passed is False
    assert result.checks["privacy"] is False


def test_validate_rejects_hallucinated_refund():
    analysis = ReviewAnalysis(
        sentiment="negative", emotion="anger", intent=["complaint", "refund_request"],
        issue_type="billing", product_reference=None, urgency="high",
        customer_request="I want a refund.", language="en",
    )
    response = GeneratedResponse(
        response_text="We have processed your refund. It will appear on your statement.",
        strategies_used=["apologize_for_issue"],
    )
    policy = CHANNEL_POLICIES["google_review"]
    result = validate_response(response, analysis, policy)
    assert result.passed is False
    assert result.checks["hallucination"] is False


def test_validate_rejects_too_long():
    analysis = ReviewAnalysis(
        sentiment="neutral", emotion="indifference", intent=[],
        issue_type=None, product_reference=None, urgency="low",
        customer_request="OK.", language="en",
    )
    response = GeneratedResponse(
        response_text="Thank you for your feedback! " * 30,
        strategies_used=["show_appreciation"],
    )
    policy = CHANNEL_POLICIES["google_review"]
    result = validate_response(response, analysis, policy)
    assert result.passed is False
    assert result.checks["length"] is False


def test_validate_rejects_dismissive_for_negative():
    analysis = ReviewAnalysis(
        sentiment="negative", emotion="anger", intent=["complaint"],
        issue_type="service_quality", product_reference=None, urgency="medium",
        customer_request="Terrible.", language="en",
    )
    response = GeneratedResponse(
        response_text="Not our problem. Whatever.",
        strategies_used=["acknowledge_feedback"],
    )
    policy = CHANNEL_POLICIES["google_review"]
    result = validate_response(response, analysis, policy)
    assert result.passed is False
    assert result.checks["sentiment_appropriate"] is False


def test_validate_rejects_rating_change_request():
    analysis = ReviewAnalysis(
        sentiment="negative", emotion="frustration", intent=["complaint"],
        issue_type="service_quality", product_reference=None, urgency="medium",
        customer_request="Bad experience.", language="en",
    )
    response = GeneratedResponse(
        response_text="We're sorry. Please kindly change your review to reflect our efforts.",
        strategies_used=["apologize_for_issue"],
    )
    policy = CHANNEL_POLICIES["google_review"]
    result = validate_response(response, analysis, policy)
    assert result.passed is False
    assert result.checks["instruction_compliance"] is False


# ── rule-based analysis tests ────────────────────────────

def test_rule_based_positive():
    analysis = _rule_based_analysis("Great pizza!", 5)
    assert analysis.sentiment == "very_positive"
    assert "praise" in analysis.intent


def test_rule_based_negative():
    analysis = _rule_based_analysis("Terrible delivery, took 2 hours", 1)
    assert analysis.sentiment == "very_negative"
    assert "complaint" in analysis.intent
    assert analysis.issue_type is not None  # matches either product_quality or delivery


def test_rule_based_neutral():
    analysis = _rule_based_analysis("It was okay", 3)
    assert analysis.sentiment == "neutral"


def test_rule_based_refund():
    analysis = _rule_based_analysis("I want my money back", 1)
    assert "refund_request" in analysis.intent


# ── salvage parser tests ─────────────────────────────────

TRUNCATED_BLOB = """{
  "sentiment": "very_negative",
  "emotion": "anger",
  "intent": ["complaint"],
  "issue_type": "service_quality",
  "product_reference": "food",
  "urgency":"""

def test_salvage_truncated_json():
    from app.modules.review_engine.understanding import _salvage_analysis_json

    data = _salvage_analysis_json(TRUNCATED_BLOB)
    assert data["sentiment"] == "very_negative"
    assert data["emotion"] == "anger"
    assert data["intent"] == ["complaint"]
    assert data["issue_type"] == "service_quality"
    assert data["product_reference"] == "food"
    assert "urgency" not in data  # cut off — caller defaults it


def test_salvage_null_literal():
    from app.modules.review_engine.understanding import _salvage_analysis_json

    data = _salvage_analysis_json('{"sentiment": "neutral", "issue_type": null}')
    assert data["sentiment"] == "neutral"
    assert "issue_type" not in data


# ── issue extraction tests ───────────────────────────────

def _neg_analysis(**kw):
    from app.modules.review_engine.schemas import ReviewAnalysis

    base = dict(sentiment="very_negative", emotion="anger", intent=["complaint"],
                issue_type="service_quality", urgency="medium")
    base.update(kw)
    return ReviewAnalysis(**base)


def test_extract_wait_food_rude():
    from app.modules.review_engine.issues import extract_issues

    issues = extract_issues(
        "Terrible service! Waited 45 minutes for cold food and the waiter was rude.",
        _neg_analysis(),
    )
    keys = [i.key for i in issues]
    assert "wait_time" in keys
    assert "food_temperature" in keys
    assert "staff_behavior" in keys
    wait = next(i for i in issues if i.key == "wait_time")
    assert "45" in " ".join(wait.keywords)


def test_extract_churn_signal():
    from app.modules.review_engine.issues import detect_churn

    assert detect_churn("Never coming back again.")
    assert not detect_churn("Great place, will visit again!")


# ── conflict resolution tests ────────────────────────────

def _match(sid, name="X", priority=50):
    from app.modules.review_engine.schemas import StrategyMatch

    return StrategyMatch(strategy_id=sid, name=name, reason="test", priority=priority)


def test_churn_suppresses_offer():
    from app.modules.review_engine.strategies import resolve_strategy_conflicts

    matches = [_match("acknowledge_feedback", "Acknowledge", 90),
               _match("mention_relevant_offer", "Offer", 35),
               _match("encourage_another_visit", "Visit", 45)]
    active, suppressed = resolve_strategy_conflicts(
        matches, _neg_analysis(), "Awful. Never coming back.")
    assert "mention_relevant_offer" in [s.strategy_id for s in suppressed]
    # Churn kills the visit pitch too — recovery first, no re-engagement.
    assert "encourage_another_visit" in [s.strategy_id for s in suppressed]
    assert [s.strategy_id for s in active] == ["acknowledge_feedback"]


def test_no_churn_no_suppression():
    from app.modules.review_engine.strategies import resolve_strategy_conflicts

    matches = [_match("mention_relevant_offer", "Offer", 35)]
    active, suppressed = resolve_strategy_conflicts(
        matches, _neg_analysis(), "Slow service, might return. Give me a discount next time?")
    assert [s.strategy_id for s in active] == ["mention_relevant_offer"]
    assert not suppressed


# ── fulfillment validation tests ─────────────────────────

def _resp(text):
    from app.modules.review_engine.schemas import GeneratedResponse

    return GeneratedResponse(response_text=text, strategies_used=[])


def test_fulfillment_fails_generic_reply():
    from app.modules.review_engine.issues import extract_issues

    issues = extract_issues(
        "Waited 45 minutes for cold food and the waiter was rude.",
        _neg_analysis())
    result = validate_response(
        _resp("The service you received fell short of our standards."),
        _neg_analysis(), {"max_length": 500, "public": True},
        review_text="Waited 45 minutes for cold food and the waiter was rude.",
        issues=issues,
        active_strategies=[_match("address_specific_issue", "Address", 75)],
    )
    assert result.passed is False
    assert result.checks["issue_coverage"] is False
    assert any(f.strategy_id == "address_specific_issue" and f.status == "fail"
               for f in result.strategy_fulfillment)


def test_fulfillment_passes_specific_reply():
    from app.modules.review_engine.issues import extract_issues

    review = "Waited 45 minutes for cold food and the waiter was rude."
    issues = extract_issues(review, _neg_analysis())
    result = validate_response(
        _resp("We're sorry you waited 45 minutes for cold food and that our waiter was rude. "
              "Thank you for telling us — we take this seriously and are looking into it."),
        _neg_analysis(), {"max_length": 500, "public": True},
        review_text=review, issues=issues,
        active_strategies=[_match("address_specific_issue", "Address", 75),
                           _match("apologize_for_issue", "Apologize", 80)],
    )
    assert result.checks["issue_coverage"] is True
    assert result.checks["response_completeness"] is True


def test_completeness_rejects_truncation():
    result = validate_response(
        _resp("Thank you for sharing your experience. We're truly sorry that the service you received fell short"),
        _neg_analysis(), {"max_length": 500, "public": True},
        review_text="Bad service, cold food, rude staff, waited forever and never coming back.",
    )
    assert result.checks["response_completeness"] is False
    assert result.passed is False


def test_completeness_rejects_json_leak():
    result = validate_response(
        _resp('{"response_text":"Thank you for sharing your experience.'),
        _neg_analysis(), {"max_length": 500, "public": True},
        review_text="Cold food.",
    )
    assert result.checks["response_completeness"] is False


def test_offer_suppressed_but_present_fails():
    result = validate_response(
        _resp("Sorry about that. Here is a 20% discount on your next visit, we appreciate your feedback."),
        _neg_analysis(), {"max_length": 500, "public": True},
        review_text="Terrible. Never coming back.",
        suppressed_ids=["mention_relevant_offer"],
    )
    assert result.checks["offer_appropriateness"] is False


def test_generation_salvage_partial_json():
    from app.modules.review_engine.generator import _salvage_response_text

    out = _salvage_response_text('{"response_text":"Thank you for sharing. We\'re sorry about the wait')
    assert out.startswith("Thank you for sharing")
    assert "response_text" not in out
    assert _salvage_response_text("") == ""
    assert _salvage_response_text("not json at all") == ""


# ── length tier tests ──────────────────────────────────

def test_tier_complaint():
    from app.modules.review_engine.validator import select_tier

    t = select_tier(1, _neg_analysis(), "Terrible service, never coming back.", n_issues=2)
    assert t["max_sentences"] == 3 and t["max_words"] == 70


def test_tier_simple_complaint():
    from app.modules.review_engine.validator import select_tier

    t = select_tier(2, _neg_analysis(), "Slow service.", n_issues=1)
    assert t["label"] == "simple-complaint" and t["max_words"] == 50 and t["max_sentences"] == 2


def test_tier_complex_complaint():
    from app.modules.review_engine.validator import select_tier

    t = select_tier(1, _neg_analysis(), "Long awful review " * 20, n_issues=5)
    assert t["label"] == "complex-complaint" and t["max_words"] == 90


def test_tier_praise():
    from app.modules.review_engine.schemas import ReviewAnalysis
    from app.modules.review_engine.validator import select_tier

    a = ReviewAnalysis(sentiment="very_positive", emotion="joy", intent=["praise"])
    t = select_tier(5, a, "Loved it!")
    assert t["max_sentences"] == 2 and t["max_words"] == 40


# ── quality: ideal short reply passes everything ───────

IDEAL_REPLY = (
    "We're sorry you waited 45 minutes for cold food and that your concern "
    "was met with rude service. We take this seriously and would appreciate "
    "the opportunity to make things right."
)

IDEAL_REVIEW = "Terrible service! Waited 45 minutes for cold food and the waiter was rude. Never coming back."


def test_ideal_reply_passes_all():
    from app.modules.review_engine.issues import extract_issues
    from app.modules.review_engine.strategies import resolve_strategy_conflicts
    from app.modules.review_engine.validator import select_tier

    analysis = _neg_analysis()
    issues = extract_issues(IDEAL_REVIEW, analysis)
    assert len(issues) == 3
    matched = [_match("acknowledge_feedback", "Acknowledge", 90),
               _match("apologize_for_issue", "Apologize", 80),
               _match("address_specific_issue", "Address", 75),
               _match("reassure_customer", "Reassure", 60),
               _match("encourage_another_visit", "Visit", 45),
               _match("mention_relevant_offer", "Offer", 35)]
    active, suppressed = resolve_strategy_conflicts(matched, analysis, IDEAL_REVIEW)
    assert "mention_relevant_offer" in [s.strategy_id for s in suppressed]
    tier = select_tier(1, analysis, IDEAL_REVIEW)
    result = validate_response(
        _resp(IDEAL_REPLY), analysis, {"max_length": 500, "public": True},
        review_text=IDEAL_REVIEW, issues=issues, active_strategies=active,
        suppressed_ids=[s.strategy_id for s in suppressed],
        tier=tier, business_context=None, has_offer_data=False, rating=1,
    )
    assert result.passed is True, result.issues
    assert result.checks["conciseness"] is True
    assert result.checks["naturalness"] is True
    assert result.checks["claim_grounding"] is True


def test_corporate_reply_fails_naturalness():
    result = validate_response(
        _resp("Thank you so much for taking the time to provide this valuable feedback. "
              "We sincerely appreciate your patronage and remain committed to delivering "
              "an exceptional experience."),
        _neg_analysis(), {"max_length": 500, "public": True},
        review_text="Food was good but service was slow.",
    )
    assert result.checks["naturalness"] is False
    assert result.passed is False


def test_training_claim_fails_ungrounded():
    result = validate_response(
        _resp("We're sorry about the rude service. We are retraining our staff to ensure respectful service."),
        _neg_analysis(), {"max_length": 500, "public": True},
        review_text="Waiter was rude.",
        business_context=None,
    )
    assert result.checks["claim_grounding"] is False
    assert result.checks["hallucination"] is False
    assert result.passed is False


def test_training_claim_passes_when_grounded():
    result = validate_response(
        _resp("We're sorry about the rude service. Our team completed retraining last week and we take this seriously."),
        _neg_analysis(), {"max_length": 500, "public": True},
        review_text="Waiter was rude.",
        business_context="Staff completed customer-service training in March.",
    )
    assert result.checks["claim_grounding"] is True


def test_essay_reply_fails_conciseness():
    from app.modules.review_engine.schemas import ReviewAnalysis
    from app.modules.review_engine.validator import select_tier

    a = ReviewAnalysis(sentiment="very_positive", emotion="joy", intent=["praise"])
    essay = ("Thank you! " * 5) + ("We loved serving you and hope every visit is wonderful. " * 4)
    result = validate_response(
        _resp(essay), a, {"max_length": 2000, "public": True},
        review_text="Loved it!", tier=select_tier(5, a, "Loved it!"), rating=5,
    )
    assert result.checks["conciseness"] is False


def test_repetition_fails_naturalness():
    result = validate_response(
        _resp("We're sorry about the wait. We're sorry about the wait."),
        _neg_analysis(), {"max_length": 500, "public": True},
        review_text="Waited too long.",
    )
    assert result.checks["naturalness"] is False


def test_em_dash_fails_naturalness():
    result = validate_response(
        _resp("Thanks for the kind words! Glad you loved it — hope to see you again soon."),
        _neg_analysis(), {"max_length": 500, "public": True},
        review_text="Loved it!",
    )
    assert result.checks["naturalness"] is False
    assert result.passed is False
    assert any("Em dash" in issue for issue in result.issues)


def test_strip_em_dashes():
    from app.modules.review_engine.validator import strip_em_dashes

    assert strip_em_dashes("Sorry you waited — that's not ok.") == "Sorry you waited, that's not ok."
    assert strip_em_dashes("Glad you loved it—hope to see you again.") == "Glad you loved it, hope to see you again."
    assert strip_em_dashes("No dashes here. Just commas, and periods.") == "No dashes here. Just commas, and periods."
    assert strip_em_dashes("") == ""
    assert "—" not in strip_em_dashes("A — b — c")


def test_offer_strategy_skipped_without_data():
    result = validate_response(
        _resp("We're sorry about the slow service and we take this seriously."),
        _neg_analysis(), {"max_length": 500, "public": True},
        review_text="Slow service.",
        active_strategies=[_match("mention_relevant_offer", "Offer", 35)],
        has_offer_data=False,
    )
    f = next(x for x in result.strategy_fulfillment if x.strategy_id == "mention_relevant_offer")
    assert f.status == "pass"


def test_acknowledge_passes_on_overlap_without_magic_word():
    result = validate_response(
        _resp("We're truly sorry you had to wait 45 minutes and received cold food."),
        _neg_analysis(), {"max_length": 500, "public": True},
        review_text="Waited 45 minutes for cold food, terrible.",
        active_strategies=[_match("acknowledge_feedback", "Acknowledge", 90)],
    )
    f = next(x for x in result.strategy_fulfillment if x.strategy_id == "acknowledge_feedback")
    assert f.status == "pass"


# ── channel policy tests ─────────────────────────────────

def test_google_review_policy():
    p = CHANNEL_POLICIES["google_review"]
    assert p["public"] is True
    assert p["max_length"] == 500
    assert p["allow_sensitive_information"] is False


def test_email_policy():
    p = CHANNEL_POLICIES["email"]
    assert p["public"] is False
    assert p["max_length"] == 2000


# ── schema tests ─────────────────────────────────────────

def test_review_analysis_schema():
    a = ReviewAnalysis(
        sentiment="positive", emotion="joy", intent=["praise"],
        issue_type=None, product_reference=None, urgency="low",
        customer_request=None, language="en",
    )
    assert a.sentiment == "positive"
    assert a.language == "en"


def test_review_analysis_invalid_sentiment():
    with pytest.raises(Exception):
        ReviewAnalysis(
            sentiment="wrong", emotion="joy", intent=[],
            issue_type=None, product_reference=None, urgency="low",
            customer_request=None, language="en",
        )


# ── evidence declarations (strategy owns WHAT, layer owns HOW) ───

def test_strategy_evidence_map_declares_data_needs():
    from app.modules.retrieval.evidence import NEED_KINDS
    from app.modules.review_engine.strategies import STRATEGY_EVIDENCE

    assert STRATEGY_EVIDENCE["mention_relevant_offer"] == ["offer"]
    assert STRATEGY_EVIDENCE["recommend_related_product"] == ["product"]
    for kinds in STRATEGY_EVIDENCE.values():
        for kind in kinds:
            assert kind in NEED_KINDS, f"unknown evidence kind {kind}"


def _ev_analysis(**over):
    from app.modules.review_engine.schemas import ReviewAnalysis

    base = dict(sentiment="negative", emotion="disappointment",
                intent=["complaint"], issue_type="product_quality",
                product_reference=None, urgency="low",
                customer_request=None, language="en")
    base.update(over)
    return ReviewAnalysis(**base)


def test_evidence_needs_for_product_strategy():
    from app.modules.review_engine.strategies import evidence_needs_for

    needs = evidence_needs_for(
        _ev_analysis(product_reference="pizza"),
        [_match("recommend_related_product", "Recommend", 40)],
    )
    assert [n.kind for n in needs] == ["product"]
    assert needs[0].query == "pizza"


def test_evidence_needs_for_offer_request():
    from app.modules.review_engine.strategies import evidence_needs_for

    needs = evidence_needs_for(
        _ev_analysis(intent=["complaint", "discount"],
                     customer_request="give me a discount please"),
        [_match("mention_relevant_offer", "Offer", 35)],
    )
    assert [n.kind for n in needs] == ["offer"]


def test_evidence_needs_for_business_question():
    from app.modules.review_engine.strategies import evidence_needs_for

    needs = evidence_needs_for(
        _ev_analysis(intent=["question"],
                     customer_request="what hours are you open?"),
        [_match("acknowledge_feedback", "Ack", 70)],
    )
    assert [n.kind for n in needs] == ["business_profile"]


def test_evidence_needs_empty_without_triggers():
    from app.modules.review_engine.strategies import evidence_needs_for

    needs = evidence_needs_for(
        _ev_analysis(sentiment="positive", emotion="joy", intent=["praise"],
                     issue_type=None),
        [_match("show_appreciation", "Thanks", 60)],
    )
    assert needs == []


@pytest.mark.asyncio
async def test_retrieve_evidence_empty_without_banks(db, user_id):
    """No databanks configured: needs are unfulfilled, never errors."""
    from app.modules.retrieval.evidence import EvidenceNeed
    from app.modules.retrieval.layer import retrieve_evidence

    out = await retrieve_evidence(
        [EvidenceNeed(kind="product", query="pizza")],
        tenant_id=user_id, db=db,
    )
    assert out["product"].has_data is False
    assert out["product"].facts == []
    assert out["product"].rendered == ""


@pytest.mark.asyncio
async def test_retrieve_evidence_never_raises_without_tenant(db):
    from app.modules.retrieval.evidence import EvidenceNeed
    from app.modules.retrieval.layer import retrieve_evidence

    out = await retrieve_evidence(
        [EvidenceNeed(kind="product", query="pizza")],
        tenant_id=None, db=db,
    )
    assert out["product"].has_data is False


def _write_csv_bank(monkeypatch, tmp_path, db_user_id, bank_name="Menu",
                    rows=("name,record_type,category\nShawarma Plate,product,Grill\n",)):
    """A real CSV document on local disk (no embeddings needed)."""
    import uuid

    from app.config import settings as _settings

    monkeypatch.setattr(_settings, "UPLOAD_DIR", str(tmp_path))
    from app.modules.rag.models import Databank, Document

    bank_id = f"bank-{uuid.uuid4().hex[:8]}"
    doc_id = f"doc-{uuid.uuid4().hex[:8]}"
    return bank_id, doc_id, Databank(id=bank_id, user_id=db_user_id, name=bank_name), [
        Document(id=doc_id, databank_id=bank_id, user_id=db_user_id,
                 filename="menu.csv", source_type="upload",
                 file_type="csv", status="completed")
    ], rows[0]


@pytest.mark.asyncio
async def test_retrieve_evidence_structured_fact_has_no_source_labels(
        monkeypatch, tmp_path, db, user_id):
    """Structured rows arrive as facts — the LLM never sees mechanism names."""
    from app.modules.retrieval.evidence import EvidenceNeed
    from app.modules.retrieval.layer import retrieve_evidence
    from app.core.storage import put_doc

    bank_id, doc_id, bank, docs, csv_text = _write_csv_bank(
        monkeypatch, tmp_path, user_id)
    db.add(bank)
    for d in docs:
        db.add(d)
    await db.commit()
    put_doc(bank_id, f"{doc_id}.csv", csv_text.encode())

    out = await retrieve_evidence(
        [EvidenceNeed(kind="product", query="shawarma")],
        tenant_id=user_id, db=db,
    )
    res = out["product"]
    assert res.has_data is True
    assert any("Shawarma Plate" in f for f in res.facts)
    blob = res.rendered.lower()
    for leaked in ("csv", "rag", "hybrid", "vector", "search_products",
                   "structured", "tool", "mode"):
        assert leaked not in blob, f"source label leaked: {leaked}"


@pytest.mark.asyncio
async def test_retrieve_evidence_minimizes_to_budget(
        monkeypatch, tmp_path, db, user_id):
    """Ten matching rows → at most the product budget (3)."""
    from app.modules.retrieval.evidence import EvidenceNeed, NEED_BUDGETS
    from app.modules.retrieval.layer import retrieve_evidence
    from app.core.storage import put_doc

    lines = ["name,record_type,category"]
    lines += [f"Shawarma Item {i},product,Grill" for i in range(10)]
    bank_id, doc_id, bank, docs, _ = _write_csv_bank(
        monkeypatch, tmp_path, user_id, rows=("\n".join(lines),))
    db.add(bank)
    for d in docs:
        db.add(d)
    await db.commit()
    put_doc(bank_id, f"{doc_id}.csv", "\n".join(lines).encode())

    out = await retrieve_evidence(
        [EvidenceNeed(kind="product", query="shawarma")],
        tenant_id=user_id, db=db,
    )
    assert 0 < len(out["product"].items) <= NEED_BUDGETS["product"]


# ── billing/refund suppression ───────────────────────────

def _billing_analysis():
    from app.modules.review_engine.schemas import ReviewAnalysis

    return ReviewAnalysis(sentiment="negative", emotion="anger", intent=["complaint"],
                          issue_type="billing", urgency="high")


def test_billing_suppresses_sales_pitch():
    from app.modules.review_engine.strategies import resolve_strategy_conflicts

    matches = [_match("address_specific_issue", "Address", 75),
               _match("recommend_related_product", "Recommend", 40),
               _match("mention_relevant_offer", "Offer", 35)]
    active, suppressed = resolve_strategy_conflicts(
        matches, _billing_analysis(),
        "Charged twice for my order and nobody would help.")
    ids = [s.strategy_id for s in suppressed]
    assert "recommend_related_product" in ids
    assert "mention_relevant_offer" in ids
    assert "address_specific_issue" in [s.strategy_id for s in active]


def test_explicit_alternative_request_keeps_recommend():
    from app.modules.review_engine.strategies import resolve_strategy_conflicts

    matches = [_match("recommend_related_product", "Recommend", 40)]
    active, _ = resolve_strategy_conflicts(
        matches, _billing_analysis(),
        "Billing is confusing, can you recommend a simpler plan instead?")
    assert [s.strategy_id for s in active] == ["recommend_related_product"]


def test_explicit_offer_request_keeps_offer():
    from app.modules.review_engine.strategies import resolve_strategy_conflicts

    matches = [_match("mention_relevant_offer", "Offer", 35)]
    active, suppressed = resolve_strategy_conflicts(
        matches, _billing_analysis(),
        "Overcharged again. Do you have any discount or credit to make this up?")
    assert [s.strategy_id for s in active] == ["mention_relevant_offer"]
    assert not suppressed


# ── pre-generation prune ─────────────────────────────────

def test_prune_removes_offer_without_data():
    from app.modules.review_engine.strategies import prune_unsatisfiable

    active, suppressed = prune_unsatisfiable(
        [_match("address_specific_issue", "Address", 75),
         _match("mention_relevant_offer", "Offer", 35)], [],
        has_offer_data=False, has_product_data=True)
    assert [s.strategy_id for s in active] == ["address_specific_issue"]
    assert [s.strategy_id for s in suppressed] == ["mention_relevant_offer"]


def test_prune_keeps_offer_with_data():
    from app.modules.review_engine.strategies import prune_unsatisfiable

    active, suppressed = prune_unsatisfiable(
        [_match("mention_relevant_offer", "Offer", 35)], [],
        has_offer_data=True, has_product_data=False)
    assert [s.strategy_id for s in active] == ["mention_relevant_offer"]
    assert not suppressed


# ── anti-gaming + grounding ──────────────────────────────

def test_stock_thank_without_engagement_fails():
    result = validate_response(
        _resp("Thank you for your feedback."),
        _neg_analysis(), {"max_length": 500, "public": True},
        review_text="Waited 45 minutes for cold food and the waiter was rude.",
        active_strategies=[_match("acknowledge_feedback", "Acknowledge", 90)],
    )
    f = next(x for x in result.strategy_fulfillment if x.strategy_id == "acknowledge_feedback")
    assert f.status == "fail"
    assert result.passed is False


def test_future_assurance_fails_grounding():
    result = validate_response(
        _resp("We're sorry about the billing issue. We'll make sure the billing is smooth going forward."),
        _neg_analysis(), {"max_length": 500, "public": True},
        review_text="Charged twice, terrible billing.",
        business_context=None,
    )
    assert result.checks["claim_grounding"] is False
    assert result.checks["hallucination"] is False
    assert result.passed is False


def test_system_fix_fails_without_evidence():
    result = validate_response(
        _resp("Sorry about that. We're upgrading our billing system this week."),
        _neg_analysis(), {"max_length": 500, "public": True},
        review_text="Billing is broken.",
        business_context="We sell shoes.",
    )
    assert result.checks["claim_grounding"] is False


def test_best_effort_failure_is_warning_only():
    result = validate_response(
        _resp("We're sorry you waited 45 minutes for cold food."),
        _neg_analysis(), {"max_length": 500, "public": True},
        review_text="Waited 45 minutes for cold food.",
        active_strategies=[_match("address_specific_issue", "Address", 75),
                           _match("encourage_another_visit", "Visit", 45)],
        tier={"label": "complaint", "max_sentences": 3, "max_words": 70, "min_words": 20},
        rating=1,
    )
    visit = next(x for x in result.strategy_fulfillment if x.strategy_id == "encourage_another_visit")
    assert visit.status == "fail"  # honestly recorded...
    assert result.checks["strategy_fulfillment"] is True  # ...but doesn't block approval


def test_correct_billing_reply_passes():
    from app.modules.review_engine.issues import extract_issues
    from app.modules.review_engine.validator import select_tier

    review = "Charged twice for my order and nobody at the counter would help."
    reply = ("We're sorry to hear about the billing issue with your order. "
             "Please reach out with your account details so we can look into what happened and help resolve it.")
    analysis = _billing_analysis()
    issues = extract_issues(review, analysis)
    tier = select_tier(2, analysis, review, n_issues=len(issues))
    result = validate_response(
        _resp(reply), analysis, {"max_length": 500, "public": True},
        review_text=review, issues=issues,
        active_strategies=[_match("acknowledge_feedback", "Acknowledge", 90),
                           _match("apologize_for_issue", "Apologize", 80),
                           _match("address_specific_issue", "Address", 75)],
        tier=tier, business_context=None, rating=2,
    )
    assert result.passed is True, result.issues


# ── hard eligibility: minimum strategies ─────────────────

def test_recommend_needs_explicit_request():
    from app.modules.review_engine.strategies import resolve_strategy_conflicts

    matches = [_match("recommend_related_product", "Recommend", 40)]
    active, suppressed = resolve_strategy_conflicts(
        matches, _neg_analysis(), "The AI tool is crazy, but it is costly.")
    assert not active
    assert [s.strategy_id for s in suppressed] == ["recommend_related_product"]


def test_encourage_suppressed_on_plain_complaint():
    from app.modules.review_engine.strategies import resolve_strategy_conflicts

    matches = [_match("encourage_another_visit", "Visit", 45)]
    active, suppressed = resolve_strategy_conflicts(
        matches, _neg_analysis(), "The AI tool is crazy, but it is costly.")
    assert not active
    assert [s.strategy_id for s in suppressed] == ["encourage_another_visit"]


def test_encourage_kept_on_return_intent():
    from app.modules.review_engine.strategies import resolve_strategy_conflicts

    matches = [_match("encourage_another_visit", "Visit", 45)]
    active, suppressed = resolve_strategy_conflicts(
        matches, _neg_analysis(), "Bad visit, but I'll give you another try next week.")
    assert [s.strategy_id for s in active] == ["encourage_another_visit"]
    assert not suppressed


def test_offer_needs_explicit_request():
    from app.modules.review_engine.strategies import resolve_strategy_conflicts

    matches = [_match("mention_relevant_offer", "Offer", 35)]
    active, suppressed = resolve_strategy_conflicts(
        matches, _neg_analysis(), "Slow service, disappointed.")
    assert not active
    assert [s.strategy_id for s in suppressed] == ["mention_relevant_offer"]


def test_minimum_set_for_simple_complaint():
    from app.modules.review_engine.strategies import prune_unsatisfiable, resolve_strategy_conflicts

    matches = [_match("acknowledge_feedback", "Acknowledge", 90),
               _match("apologize_for_issue", "Apologize", 80),
               _match("address_specific_issue", "Address", 75),
               _match("encourage_another_visit", "Visit", 45),
               _match("recommend_related_product", "Recommend", 40),
               _match("mention_relevant_offer", "Offer", 35)]
    active, suppressed = resolve_strategy_conflicts(
        matches, _neg_analysis(), "The AI tool is crazy, but it is costly.")
    # Pricing objection makes the offer conditionally eligible (verification at prune).
    assert sorted(s.strategy_id for s in active) == [
        "acknowledge_feedback", "address_specific_issue", "apologize_for_issue",
        "mention_relevant_offer"]
    offer = next(s for s in active if s.strategy_id == "mention_relevant_offer")
    assert offer.conditional is True
    # ...but with no verified offer data it is pruned before generation.
    pruned, suppressed2 = prune_unsatisfiable(
        active, suppressed, has_offer_data=False, has_product_data=False,
        product_ref=None, offer_texts=[])
    assert "mention_relevant_offer" not in [s.strategy_id for s in pruned]
    assert sorted(s.strategy_id for s in pruned) == [
        "acknowledge_feedback", "address_specific_issue", "apologize_for_issue"]


# ── generic issues + promo semantics ─────────────────────

def test_generic_issue_passes_when_subject_referenced():
    from app.modules.review_engine.issues import extract_issues

    # No concrete pattern matches "meh" — generic fallback path.
    review = "The AI tool is meh, not for me."
    analysis = _neg_analysis(issue_type="product_dissatisfaction", product_reference="AI tool")
    issues = extract_issues(review, analysis)
    assert all(i.generic for i in issues)
    result = validate_response(
        _resp("Thank you for sharing your review. We're sorry the AI tool didn't meet your expectations. "
              "Please reach out so we can better understand the issue and help."),
        analysis, {"max_length": 500, "public": True},
        review_text=review, issues=issues,
        active_strategies=[_match("acknowledge_feedback", "Acknowledge", 90),
                           _match("apologize_for_issue", "Apologize", 80),
                           _match("address_specific_issue", "Address", 75)],
        rating=2,
    )
    assert result.checks["issue_coverage"] is True
    assert result.passed is True, result.issues


def test_generic_issue_fails_when_nothing_referenced():
    from app.modules.review_engine.issues import extract_issues

    review = "The AI tool is crazy, but it is costly."
    analysis = _neg_analysis(issue_type="product_dissatisfaction")
    issues = extract_issues(review, analysis)
    result = validate_response(
        _resp("Thank you for your feedback. We appreciate it."),
        analysis, {"max_length": 500, "public": True},
        review_text=review, issues=issues,
        active_strategies=[_match("address_specific_issue", "Address", 75)],
        rating=2,
    )
    assert result.checks["issue_coverage"] is False


def test_promotional_pricing_fails_without_data():
    result = validate_response(
        _resp("Sorry about that. We have current promotional pricing that might help."),
        _neg_analysis(), {"max_length": 500, "public": True},
        review_text="Slow service.",
        suppressed_ids=["mention_relevant_offer"],
    )
    assert result.checks["offer_appropriateness"] is False
    assert result.checks["claim_grounding"] is False
    assert result.passed is False


# ── semantic validation + zero taxonomy ─────────────────

def _dissat_analysis():
    from app.modules.review_engine.schemas import ReviewAnalysis

    return ReviewAnalysis(sentiment="negative", emotion="disappointment", intent=["complaint"],
                          issue_type="product_dissatisfaction", product_reference="AI tool",
                          urgency="low", customer_request=None, language="en")


def test_semantic_equivalent_passes_without_taxonomy():
    from app.modules.review_engine.issues import extract_issues

    review = "The AI tool is crazy, but it is costly."
    analysis = _dissat_analysis()
    issues = extract_issues(review, analysis)
    # Price is now a concrete fact — the reply must address it in natural words.
    reply = ("We're sorry the AI tool feels too expensive for what you need. "
             "Please reach out so we can better understand the issue and help.")
    result = validate_response(
        _resp(reply), analysis, {"max_length": 500, "public": True},
        review_text=review, issues=issues,
        active_strategies=[_match("acknowledge_feedback", "Acknowledge", 90),
                           _match("apologize_for_issue", "Apologize", 80),
                           _match("address_specific_issue", "Address", 75)],
        tier={"label": "simple-complaint", "max_sentences": 2, "max_words": 50, "min_words": 15},
        rating=2,
    )
    assert result.checks["taxonomy_leak"] is True
    assert result.passed is True, result.issues


def test_taxonomy_snake_case_fails():
    result = validate_response(
        _resp("Your feedback about the product_dissatisfaction is important to us and we are sorry."),
        _dissat_analysis(), {"max_length": 500, "public": True},
        review_text="The AI tool is crazy, but it is costly.",
    )
    assert result.checks["taxonomy_leak"] is False
    assert result.passed is False


# ── pricing vs billing classification ────────────────────

def _plain_analysis(**kw):
    from app.modules.review_engine.schemas import ReviewAnalysis

    base = dict(sentiment="neutral", emotion="indifference", intent=[],
                issue_type=None, product_reference=None, urgency="low")
    base.update(kw)
    return ReviewAnalysis(**base)


def _issue_keys(text):
    from app.modules.review_engine.issues import extract_issues

    return [i.key for i in extract_issues(text, _plain_analysis())]


def test_case1_expensive_is_pricing():
    keys = _issue_keys("The AI tool is great but too expensive.")
    assert "pricing" in keys and "billing" not in keys


def test_case2_costly_is_pricing():
    keys = _issue_keys("The AI tool is crazy good, but it is costly.")
    assert "pricing" in keys and "billing" not in keys


def test_case3_charged_too_much_is_billing():
    keys = _issue_keys("I was charged too much for the AI tool.")
    assert "billing" in keys


def test_case4_charged_twice_is_billing():
    keys = _issue_keys("I was charged twice.")
    assert "billing" in keys and "pricing" not in keys


def test_case5_high_price_is_pricing():
    keys = _issue_keys("The price is high, but the product is worth it.")
    assert "pricing" in keys and "billing" not in keys


def test_case6_wrong_invoice_is_billing():
    keys = _issue_keys("My invoice is wrong.")
    assert "billing" in keys and "pricing" not in keys


def test_prompt_distinguishes_pricing_from_billing():
    from app.modules.review_engine.understanding import ANALYSIS_SYSTEM_PROMPT

    assert '"pricing" when' in ANALYSIS_SYSTEM_PROMPT
    assert "NOT make it billing" in ANALYSIS_SYSTEM_PROMPT


def test_pricing_suppresses_sales_with_pricing_reason():
    from app.modules.review_engine.strategies import resolve_strategy_conflicts

    matches = [_match("recommend_related_product", "Recommend", 40),
               _match("mention_relevant_offer", "Offer", 35)]
    active, suppressed = resolve_strategy_conflicts(
        matches, _plain_analysis(sentiment="negative", issue_type="pricing"),
        "The AI tool is great but too expensive.")
    # Recommend: suppressed, pricing-worded reason, no billing language.
    assert "recommend_related_product" in [s.strategy_id for s in suppressed]
    reasons = " ".join(s.reason for s in suppressed)
    assert "Pricing concern" in reasons
    assert "Billing" not in reasons
    # Offer: pricing objection → conditionally eligible (verification at prune).
    offer = next(s for s in active if s.strategy_id == "mention_relevant_offer")
    assert offer.conditional is True


def test_pricing_matches_apologize_conditions():
    from types import SimpleNamespace

    from app.modules.review_engine.strategies import CORE_STRATEGIES, _matches_conditions

    for sid in ("apologize_for_issue", "reassure_customer"):
        seed = next(s for s in CORE_STRATEGIES if s["id"] == sid)
        assert "pricing" in seed["conditions"]["issue_types"]
        fake = SimpleNamespace(conditions=dict(seed["conditions"]))
        analysis = _plain_analysis(sentiment="negative", issue_type="pricing")
        assert _matches_conditions(fake, analysis) is True


def test_pricing_reply_passes_without_billing_language():
    from app.modules.review_engine.issues import extract_issues
    from app.modules.review_engine.validator import select_tier

    review = "The AI tool is carzzyy, but it is costly."
    analysis = _plain_analysis(sentiment="negative", emotion="frustration",
                               intent=["complaint"], issue_type="pricing",
                               product_reference="AI tool")
    issues = extract_issues(review, analysis)
    assert "pricing" in [i.key for i in issues]
    reply = ("We're sorry the AI tool feels too expensive, we're glad you like it, "
             "and we understand pricing is an important consideration. We appreciate the feedback.")
    tier = select_tier(2, analysis, review, n_issues=len(issues))
    result = validate_response(
        _resp(reply), analysis, {"max_length": 500, "public": True},
        review_text=review, issues=issues,
        active_strategies=[_match("acknowledge_feedback", "Acknowledge", 90),
                           _match("apologize_for_issue", "Apologize", 80),
                           _match("address_specific_issue", "Address", 75)],
        tier=tier, business_context=None, rating=2,
    )
    assert result.checks["pricing_purity"] is True
    assert result.passed is True, result.issues


def test_billing_language_fails_in_pricing_reply():
    from app.modules.review_engine.issues import extract_issues

    review = "The AI tool is carzzyy, but it is costly."
    analysis = _plain_analysis(sentiment="negative", intent=["complaint"],
                               issue_type="pricing", product_reference="AI tool")
    issues = extract_issues(review, analysis)
    result = validate_response(
        _resp("Sorry about that. We are reviewing the charge and will process a refund."),
        analysis, {"max_length": 500, "public": True},
        review_text=review, issues=issues, rating=2,
    )
    assert result.checks["pricing_purity"] is False
    assert result.passed is False


def test_rule_based_splits_pricing_and_billing():
    from app.modules.review_engine.understanding import _rule_based_analysis

    assert _rule_based_analysis("Too expensive for me", 2).issue_type == "pricing"
    assert _rule_based_analysis("Charged twice on my card", 1).issue_type == "billing"


# ── minimal execution set ────────────────────────────────

def _pricing_issues():
    from app.modules.review_engine.issues import extract_issues

    analysis = _plain_analysis(sentiment="negative", emotion="frustration",
                               intent=["complaint"], issue_type="pricing",
                               product_reference="AI tool")
    return analysis, extract_issues("The AI tool is carzzyy, but it is costly.", analysis)


def test_selection_pricing_case_minimal_set():
    from app.modules.review_engine.strategies import select_execution_set

    analysis, issues = _pricing_issues()
    eligible = [_match("acknowledge_feedback", "Acknowledge", 90),
                _match("apologize_for_issue", "Apologize", 80),
                _match("address_specific_issue", "Address", 75),
                _match("reassure_customer", "Reassure", 60)]
    execute, out = select_execution_set(
        eligible, [], analysis, issues, "The AI tool is carzzyy, but it is costly.")
    assert sorted(s.strategy_id for s in execute) == [
        "acknowledge_feedback", "address_specific_issue", "apologize_for_issue"]
    deferred = [s.strategy_id for s in out if s.reason.startswith("Deferred")]
    assert deferred == ["reassure_customer"]


def test_selection_keeps_reassure_when_very_negative():
    from app.modules.review_engine.schemas import ReviewAnalysis
    from app.modules.review_engine.strategies import select_execution_set

    analysis = ReviewAnalysis(sentiment="very_negative", emotion="anger", intent=["complaint"],
                              issue_type="service_quality", urgency="high")
    eligible = [_match("acknowledge_feedback", "Acknowledge", 90),
                _match("apologize_for_issue", "Apologize", 80),
                _match("reassure_customer", "Reassure", 60)]
    execute, _ = select_execution_set(eligible, [], analysis, [], "Terrible, never coming back.")
    assert "reassure_customer" in [s.strategy_id for s in execute]


def test_selection_defers_apology_when_mild():
    analysis = _plain_analysis(sentiment="negative", urgency="low")
    from app.modules.review_engine.strategies import select_execution_set

    eligible = [_match("acknowledge_feedback", "Acknowledge", 90),
                _match("apologize_for_issue", "Apologize", 80)]
    execute, out = select_execution_set(eligible, [], analysis, [], "Meh, not great.")
    assert [s.strategy_id for s in execute] == ["acknowledge_feedback"]
    assert any(s.strategy_id == "apologize_for_issue" and s.reason.startswith("Deferred")
               for s in out)


def test_selection_never_empty():
    from app.modules.review_engine.strategies import select_execution_set

    eligible = [_match("reassure_customer", "Reassure", 60)]
    execute, _ = select_execution_set(
        eligible, [], _plain_analysis(sentiment="neutral"), [], "Okay.")
    assert len(execute) == 1


def test_ideal_short_output_passes():
    from app.modules.review_engine.validator import select_tier

    analysis, issues = _pricing_issues()
    reply = ("We appreciate your feedback on our AI tool and understand that the price "
             "feels too high. We're sorry it didn't feel like the right value for you.")
    tier = select_tier(2, analysis, "The AI tool is carzzyy, but it is costly.", n_issues=len(issues))
    result = validate_response(
        _resp(reply), analysis, {"max_length": 500, "public": True},
        review_text="The AI tool is carzzyy, but it is costly.", issues=issues,
        active_strategies=[_match("acknowledge_feedback", "Acknowledge", 90),
                           _match("apologize_for_issue", "Apologize", 80),
                           _match("address_specific_issue", "Address", 75)],
        tier=tier, business_context=None, rating=2,
    )
    assert result.passed is True, result.issues


def test_continuous_improvement_fails_grounding():
    result = validate_response(
        _resp("We're sorry the cost didn't meet your expectations, and we're continually "
              "working to ensure our pricing reflects the value we deliver."),
        _dissat_analysis(), {"max_length": 500, "public": True},
        review_text="The AI tool is costly.",
        business_context=None,
    )
    assert result.checks["claim_grounding"] is False
    assert result.passed is False


def test_pricing_review_claim_fails_grounding():
    result = validate_response(
        _resp("Sorry about that. We're reviewing our pricing plans this quarter."),
        _dissat_analysis(), {"max_length": 500, "public": True},
        review_text="Too expensive.",
        business_context="We sell monthly subscriptions.",
    )
    assert result.checks["claim_grounding"] is False


def test_committed_pricing_claim_fails():
    result = validate_response(
        _resp("We hear you. We're committed to making our pricing work for everyone."),
        _dissat_analysis(), {"max_length": 500, "public": True},
        review_text="Too expensive.",
        business_context=None,
    )
    assert result.checks["claim_grounding"] is False


def test_taxonomy_phrase_fails():
    result = validate_response(
        _resp("Your feedback about the product dissatisfaction is important and we are sorry about the AI tool."),
        _dissat_analysis(), {"max_length": 500, "public": True},
        review_text="The AI tool is crazy, but it is costly.",
    )
    assert result.checks["taxonomy_leak"] is False
    assert result.passed is False


def test_review_process_promise_fails_grounding():
    result = validate_response(
        _resp("We're sorry about that. We'll review the tool's performance this week."),
        _dissat_analysis(), {"max_length": 500, "public": True},
        review_text="The AI tool is crazy.",
        business_context=None,
    )
    assert result.checks["claim_grounding"] is False
    assert result.passed is False


def test_safe_next_step_passes_grounding():
    result = validate_response(
        _resp("We're sorry about that. If you share more details, we'd be happy to understand what went wrong and help."),
        _dissat_analysis(), {"max_length": 500, "public": True},
        review_text="The AI tool is crazy.",
        business_context=None,
    )
    assert result.checks["claim_grounding"] is True
    assert result.checks["taxonomy_leak"] is True


def test_requirements_contain_no_taxonomy_keys():
    from app.modules.review_engine.issues import extract_issues
    from app.modules.review_engine.service import build_requirements

    analysis = _dissat_analysis()
    issues = extract_issues("The AI tool is crazy, but it is costly.", analysis)
    reqs = build_requirements(analysis, issues, [], [], None)
    joined = " ".join(reqs)
    assert "product_dissatisfaction" not in joined
    assert "product_reference" not in joined


# ── pricing offer eligibility + matching ─────────────────

def _pricing_voice_analysis(**kw):
    base = dict(sentiment="negative", emotion="disappointment", intent=["complaint"],
                issue_type="pricing", product_reference="Voice AI", urgency="low")
    base.update(kw)
    from app.modules.review_engine.schemas import ReviewAnalysis

    return ReviewAnalysis(**base)


def test1_pricing_with_product_makes_offer_conditional():
    from app.modules.review_engine.strategies import resolve_strategy_conflicts

    matches = [_match("mention_relevant_offer", "Offer", 35)]
    active, suppressed = resolve_strategy_conflicts(
        matches, _pricing_voice_analysis(),
        "Voice AI is great but too expensive.")
    assert [s.strategy_id for s in active] == ["mention_relevant_offer"]
    assert not suppressed
    assert active[0].conditional is True


def test2_explicit_discount_request_keeps_offer():
    from app.modules.review_engine.strategies import resolve_strategy_conflicts

    matches = [_match("mention_relevant_offer", "Offer", 35)]
    active, suppressed = resolve_strategy_conflicts(
        matches, _pricing_voice_analysis(),
        "Do you have a discount for Voice AI?")
    assert [s.strategy_id for s in active] == ["mention_relevant_offer"]
    assert not suppressed
    assert active[0].conditional is False


def test3_billing_suppresses_offer_despite_product():
    from app.modules.review_engine.schemas import ReviewAnalysis
    from app.modules.review_engine.strategies import resolve_strategy_conflicts

    analysis = ReviewAnalysis(sentiment="negative", emotion="anger", intent=["complaint"],
                              issue_type="billing", product_reference="Voice AI", urgency="high")
    matches = [_match("mention_relevant_offer", "Offer", 35)]
    active, suppressed = resolve_strategy_conflicts(
        matches, analysis, "I was charged twice for Voice AI.")
    assert not active
    assert [s.strategy_id for s in suppressed] == ["mention_relevant_offer"]


def test4_cheaper_options_allows_recommend():
    from app.modules.review_engine.strategies import resolve_strategy_conflicts

    matches = [_match("recommend_related_product", "Recommend", 40)]
    active, suppressed = resolve_strategy_conflicts(
        matches, _pricing_voice_analysis(),
        "Voice AI is too expensive. What cheaper options do you have?")
    assert [s.strategy_id for s in active] == ["recommend_related_product"]
    assert not suppressed


def test5_terrible_service_triggers_no_offer():
    from app.modules.review_engine.issues import extract_issues

    issues = extract_issues("Your service is terrible.", _plain_analysis(sentiment="negative"))
    assert "pricing" not in [i.key for i in issues]
    from app.modules.review_engine.strategies import resolve_strategy_conflicts

    matches = [_match("mention_relevant_offer", "Offer", 35)]
    active, suppressed = resolve_strategy_conflicts(
        matches, _plain_analysis(sentiment="negative"), "Your service is terrible.")
    assert not active
    assert [s.strategy_id for s in suppressed] == ["mention_relevant_offer"]


def test6_prune_drops_unmatched_offer_keeps_matched():
    from app.modules.review_engine.strategies import prune_unsatisfiable

    matches = [_match("mention_relevant_offer", "Offer", 35)]
    # No data at all → suppressed.
    active, suppressed = prune_unsatisfiable(
        matches, [], has_offer_data=False, has_product_data=False,
        product_ref="Voice AI", offer_texts=[])
    assert not active
    # Data but unrelated product → suppressed, never invented.
    active, suppressed = prune_unsatisfiable(
        matches, [], has_offer_data=True, has_product_data=False,
        product_ref="Voice AI", offer_texts=["20% off car detailing"])
    assert not active
    assert "Voice AI" in suppressed[0].reason
    # Data matching the mentioned product → kept.
    active, suppressed = prune_unsatisfiable(
        matches, [], has_offer_data=True, has_product_data=False,
        product_ref="Voice AI", offer_texts=["20% off Voice AI annual plan"])
    assert [s.strategy_id for s in active] == ["mention_relevant_offer"]
    assert not suppressed


def test_offer_match_whole_words_and_general():
    from app.modules.review_engine.strategies import offer_matches_product

    assert offer_matches_product("Voice AI", ["20% off Voice AI annual plan"]) is True
    assert offer_matches_product("Voice AI", ["20% off car detailing"]) is False
    assert offer_matches_product("Voice AI", ["Sitewide 10% off everything"]) is True
    assert offer_matches_product(None, ["20% off Voice AI"]) is False
    assert offer_matches_product("Voice AI", []) is False


def test_value_delivery_claim_fails_ungrounded():
    result = validate_response(
        _resp("We're sorry the cost didn't meet your expectations, and we're always "
              "looking to deliver strong value."),
        _dissat_analysis(), {"max_length": 500, "public": True},
        review_text="The AI tool is costly.",
        business_context=None,
    )
    assert result.checks["claim_grounding"] is False
    assert result.passed is False


# ── business relevance ───────────────────────────────────

AI_DOMAIN = {"terms": ["sayvors", "company", "software", "artificial", "intelligence",
                        "voice", "assistant", "analytics", "platform", "business",
                        "tools", "solutions"],
             "sources": {"channel_services": 2}}


def _rel_analysis(product_ref=None):
    from app.modules.review_engine.schemas import ReviewAnalysis

    return ReviewAnalysis(sentiment="negative", emotion="disappointment", intent=["complaint"],
                          issue_type="product_quality", product_reference=product_ref,
                          urgency="low", customer_request=None, language="en")


def test_pizza_at_ai_company_is_off_topic():
    from app.modules.review_engine.relevance import assess_relevance

    v = assess_relevance("the pizza was bad", _rel_analysis("pizza"), AI_DOMAIN)
    assert v["verdict"] == "off_topic"
    assert "pizza" in v["reason"]


def test_ai_tool_at_ai_company_is_on_topic():
    from app.modules.review_engine.relevance import assess_relevance

    v = assess_relevance("the AI tool is costly", _rel_analysis("AI tool"), AI_DOMAIN)
    assert v["verdict"] == "on_topic"
    assert v["matched_terms"]


def test_no_product_mention_is_uncertain():
    from app.modules.review_engine.relevance import assess_relevance

    v = assess_relevance("terrible service", _rel_analysis(None), AI_DOMAIN)
    assert v["verdict"] == "uncertain"


def test_empty_domain_is_uncertain():
    from app.modules.review_engine.relevance import assess_relevance

    v = assess_relevance("the pizza was bad", _rel_analysis("pizza"), {"terms": []})
    assert v["verdict"] == "uncertain"


def test_stem_tolerant_match():
    from app.modules.review_engine.relevance import assess_relevance

    v = assess_relevance("pizzas were cold",
                         _rel_analysis("pizzas"),
                         {"terms": ["pizza", "restaurant", "italian", "food", "menu", "chef"]})
    assert v["verdict"] == "on_topic"


def test_generic_item_is_uncertain():
    from app.modules.review_engine.relevance import assess_relevance

    v = assess_relevance("the product was bad", _rel_analysis("the product"), AI_DOMAIN)
    assert v["verdict"] == "uncertain"


def test_sparse_domain_is_uncertain():
    from app.modules.review_engine.relevance import assess_relevance

    v = assess_relevance("the pizza was bad", _rel_analysis("pizza"), {"terms": ["shop"]})
    assert v["verdict"] == "uncertain"


def test_retrieval_corroboration_flips_to_on_topic():
    from app.modules.review_engine.relevance import apply_retrieval_corroboration, assess_relevance

    v = assess_relevance("the pizza was bad", _rel_analysis("pizza"), AI_DOMAIN)
    assert v["verdict"] == "off_topic"
    flipped = apply_retrieval_corroboration(v, has_product_data=True)
    assert flipped["verdict"] == "on_topic"
    kept = apply_retrieval_corroboration(v, has_product_data=False)
    assert kept["verdict"] == "off_topic"


# ── engine-level claim grounding ─────────────────────────

def test_user_case_ingredients_and_always_looking_fail():
    reply = ("Thanks for sharing your thoughts. We understand the price feels too high. "
             "They reflect the quality of our ingredients and service. "
             "We're always looking for ways to provide the best value for our guests.")
    result = validate_response(
        _resp(reply), _dissat_analysis(), {"max_length": 500, "public": True},
        review_text="its great, but why is the prices too high?",
        business_context=None, rating=3,
    )
    assert result.checks["claim_grounding"] is False
    assert result.passed is False
    kinds = [v.kind for v in result.claim_verdicts]
    assert "rationale" in kinds
    assert all(v.status == "UNSUPPORTED" and v.source == "NONE"
               for v in result.claim_verdicts if v.kind in ("rationale", "habitual", "superlative"))


def test_extractor_kinds_and_safe_attitudes():
    from app.modules.review_engine.claims import extract_claims

    claims = extract_claims(
        "They reflect the quality of our ingredients. "
        "We're always looking for ways to provide the best value. "
        "Our team completed retraining last month.")
    kinds = [c["kind"] for c in claims]
    assert "rationale" in kinds and "habitual" in kinds and "past_action" in kinds
    # Pure attitudes yield zero claims.
    assert extract_claims("We're sorry about that. Thank you, we take this seriously. "
                          "Please reach out so we can look into it.") == []


def test_grounded_claim_carries_source():
    from app.modules.review_engine.claims import extract_claims, ground_claims

    claims = extract_claims("Our team completed retraining last month.")
    verdicts = ground_claims(claims, "Staff completed customer-service training in March.")
    assert verdicts and verdicts[0]["status"] == "GROUNDED"
    assert "training" in verdicts[0]["source"].lower()


def test_grounded_offer_claim_passes_validation():
    result = validate_response(
        _resp("Sorry the price feels high. Annual plans are currently 20% off, happy to help you switch."),
        _dissat_analysis(), {"max_length": 500, "public": True},
        review_text="Too expensive.",
        business_context="[find_offers] Annual plans 20% off through June",
    )
    assert result.checks["claim_grounding"] is True


def test_why_question_adds_no_invention_requirement():
    from app.modules.review_engine.service import build_requirements

    reqs = build_requirements(
        _plain_analysis(sentiment="neutral", intent=["question"], issue_type="pricing"),
        [], [], [], {"label": "question", "max_sentences": 3, "max_words": 70, "min_words": 8},
        None)
    joined = "\n".join(reqs)
    # No verified context: never thank a question for being "feedback",
    # never invent products/prices/availability.
    assert "never thank the reviewer" in joined.lower()
    assert "do NOT invent" in joined
    reqs2 = build_requirements(
        _plain_analysis(sentiment="neutral", intent=["question"], issue_type="pricing"),
        [], [], [], {"label": "question", "max_sentences": 3, "max_words": 70, "min_words": 8},
        "Our prices reflect small-batch sourcing.")
    joined2 = "\n".join(reqs2)
    # With context: answer directly from it — still no thanks-for-review.
    assert "answer it directly" in joined2.lower()
    assert "not thank the reviewer" in joined2.lower()
    assert "never state products" in joined2.lower()


# ── pricing objection → verified offer pipeline ──────────

def _pricing_no_product(**kw):
    base = dict(sentiment="neutral", emotion="frustration", intent=["complaint", "question"],
                issue_type="pricing", product_reference=None, urgency="low")
    base.update(kw)
    from app.modules.review_engine.schemas import ReviewAnalysis

    return ReviewAnalysis(**base)


def test_reg1_prices_too_high_offer_conditional():
    from app.modules.review_engine.issues import extract_issues
    from app.modules.review_engine.strategies import resolve_strategy_conflicts

    review = "It's great, but why are the prices so high?"
    analysis = _pricing_no_product()
    issues = extract_issues(review, analysis)
    assert "pricing" in [i.key for i in issues]
    matches = [_match("acknowledge_feedback", "Acknowledge", 90),
               _match("mention_relevant_offer", "Offer", 35)]
    active, suppressed = resolve_strategy_conflicts(matches, analysis, review)
    offer = next(s for s in active if s.strategy_id == "mention_relevant_offer")
    assert offer.conditional is True
    assert not [s for s in suppressed if s.strategy_id == "mention_relevant_offer"]


def test_reg2_costly_with_product_offer_conditional():
    from app.modules.review_engine.strategies import resolve_strategy_conflicts

    matches = [_match("mention_relevant_offer", "Offer", 35)]
    active, _ = resolve_strategy_conflicts(
        matches, _pricing_voice_analysis(), "The AI tool is great but costly.")
    assert active and active[0].conditional is True


def test_reg3_explicit_discount_unconditional():
    from app.modules.review_engine.strategies import resolve_strategy_conflicts

    matches = [_match("mention_relevant_offer", "Offer", 35)]
    active, suppressed = resolve_strategy_conflicts(
        matches, _pricing_no_product(), "Do you have any discount?")
    assert [s.strategy_id for s in active] == ["mention_relevant_offer"]
    assert active[0].conditional is False
    assert not suppressed


def test_reg4_billing_no_promo():
    from app.modules.review_engine.schemas import ReviewAnalysis
    from app.modules.review_engine.strategies import resolve_strategy_conflicts

    analysis = ReviewAnalysis(sentiment="negative", emotion="anger", intent=["complaint"],
                              issue_type="billing", urgency="high")
    matches = [_match("mention_relevant_offer", "Offer", 35)]
    active, suppressed = resolve_strategy_conflicts(
        matches, analysis, "I was charged twice.")
    assert not active
    assert [s.strategy_id for s in suppressed] == ["mention_relevant_offer"]


def test_reg5_cheaper_options_offer_and_recommend():
    from app.modules.review_engine.strategies import resolve_strategy_conflicts

    matches = [_match("mention_relevant_offer", "Offer", 35),
               _match("recommend_related_product", "Recommend", 40)]
    active, _ = resolve_strategy_conflicts(
        matches, _pricing_voice_analysis(),
        "It's too expensive. What cheaper options do you have?")
    assert "recommend_related_product" in [s.strategy_id for s in active]
    offer = next(s for s in active if s.strategy_id == "mention_relevant_offer")
    assert offer.conditional is True


def test_reg6_no_offer_data_pruned_silently():
    from app.modules.review_engine.strategies import prune_unsatisfiable

    matches = [_match("mention_relevant_offer", "Offer", 35)]
    matches[0] = matches[0].model_copy(update={"conditional": True})
    active, suppressed = prune_unsatisfiable(
        matches, [], has_offer_data=False, has_product_data=False,
        product_ref=None, offer_texts=[])
    assert not active
    assert "no verified offer" in suppressed[0].reason.lower()


def test_reg7_matching_offer_survives_prune():
    from app.modules.review_engine.strategies import prune_unsatisfiable

    matches = [_match("mention_relevant_offer", "Offer", 35)]
    matches[0] = matches[0].model_copy(update={"conditional": True})
    # Product-less pricing objection + pricing-relevant offer → kept.
    active, suppressed = prune_unsatisfiable(
        matches, [], has_offer_data=True, has_product_data=False,
        product_ref=None, offer_texts=["Annual plans now 20% off"])
    assert [s.strategy_id for s in active] == ["mention_relevant_offer"]
    assert not suppressed
    # Same, but unrelated offer → pruned.
    active, suppressed = prune_unsatisfiable(
        matches, [], has_offer_data=True, has_product_data=False,
        product_ref=None, offer_texts=["Free onboarding call"])
    assert not active


def test_pricing_rationale_fails_grounding():
    result = validate_response(
        _resp("We understand the price feels too high and want to assure you that "
              "our pricing reflects the quality and service we provide."),
        _dissat_analysis(), {"max_length": 500, "public": True},
        review_text="Why are the prices so high?",
        business_context=None,
    )
    assert result.checks["claim_grounding"] is False
    assert result.passed is False


# ── reply-language tests (Arabic review → Arabic reply) ──

def _ar_analysis():
    return ReviewAnalysis(
        sentiment="positive", emotion="joy", intent=["praise"],
        issue_type=None, product_reference=None, urgency="low",
        customer_request="الطعام رائع والمكان جميل", language="ar",
    )


def test_validate_arabic_praise_reply_passes_without_english_lexicons():
    """Arabic replies skip English lexicons — subject engagement governs."""
    result = validate_response(
        _resp("شكراً لك على كلماتك الرائعة! سعدنا بزيارتك ونتطلع لرؤيتك مرة أخرى."),
        _ar_analysis(), {"max_length": 500, "public": True},
        review_text="الطعام رائع والمكان جميل",
        active_strategies=[_match("show_appreciation", "Show appreciation", 80)],
    )
    assert result.checks["specificity"] is True
    assert result.checks["strategy_fulfillment"] is True
    assert result.passed is True


def test_validate_arabic_complaint_reply_with_covered_facts_passes():
    from app.modules.review_engine.schemas import ExtractedIssue

    analysis = ReviewAnalysis(
        sentiment="negative", emotion="frustration", intent=["complaint"],
        issue_type="service_quality", product_reference=None, urgency="medium",
        customer_request="الانتظار كان طويلاً", language="ar",
    )
    issues = [ExtractedIssue(
        key="wait_time", label="Wait time", detail="الانتظار",
        keywords=["الانتظار"], semantic=["تأخر"],
    )]
    result = validate_response(
        _resp("نعتذر عن الانتظار الطويل، هذا ليس المستوى الذي نسعى إليه، وسنعمل على تحسينه."),
        analysis, {"max_length": 500, "public": True},
        review_text="الانتظار كان طويلاً جداً",
        issues=issues,
        active_strategies=[_match("apologize_for_issue", "Apologize", 90)],
    )
    assert result.checks["issue_coverage"] is True
    assert result.checks["specificity"] is True
    assert result.checks["strategy_fulfillment"] is True
    assert result.passed is True


def test_generator_adds_binding_language_instruction():
    import asyncio
    from app.modules.review_engine import generator as gen

    captured = {}

    class _FakeProvider:
        async def complete(self, req):
            captured["user_msg"] = req.messages[0].content
            from app.modules.llm.providers.base import LLMResponse, LLMUsage
            return LLMResponse(
                content='{"response_text": "شكراً لك!"}',
                provider="test", model="test/m",
                usage=LLMUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                finish_reason="stop",
            )

    orig_get = gen.get_provider_for_model
    orig_resolve = gen._resolve_model
    gen.get_provider_for_model = lambda model: _FakeProvider()
    gen._resolve_model = lambda model: ("test/m", {})
    try:
        out, _usage = asyncio.run(gen.generate_response(
            analysis=_ar_analysis(),
            strategies=[_match("show_appreciation", "Show appreciation", 80)],
            channel_policy={"max_length": 500, "public": True},
            brand_voice={},
            business_context=None,
            model="test:m",
            review_text="الطعام رائع والمكان جميل",
        ))
    finally:
        gen.get_provider_for_model = orig_get
        gen._resolve_model = orig_resolve

    assert out.response_text == "شكراً لك!"
    assert "LANGUAGE (binding)" in captured["user_msg"]
    assert "Arabic" in captured["user_msg"]


# ── localization + marketing prefs ───────

def _seed_dialects(db):
    from app.modules.review_engine.models import Dialect

    rows = [
        ("egyptian", "Egyptian Arabic", "اللهجة المصرية", ["أهلاً", "إزيك؟"]),
        ("najdi", "Najdi Arabic", "اللهجة النجدية", ["هلا", "وشلونك؟"]),
    ]
    for code, en, ar, examples in rows:
        db.add(Dialect(code=code, dialect_en=en, dialect_ar=ar, examples=examples))


@pytest.mark.asyncio
async def test_dialect_catalog_db_backed(db):
    from app.modules.review_engine.dialects import (
        AUTO,
        get_dialect,
        is_valid_dialect_db,
        list_dialects,
    )

    _seed_dialects(db)
    await db.commit()

    rows = await list_dialects(db)
    assert {r["code"] for r in rows} == {"egyptian", "najdi"}
    assert (await get_dialect("egyptian", db))["dialect_ar"] == "اللهجة المصرية"
    assert await get_dialect("auto", db) is None
    assert await get_dialect("klingon", db) is None
    assert await is_valid_dialect_db("auto", db) is True
    assert await is_valid_dialect_db("najdi", db) is True
    assert await is_valid_dialect_db("klingon", db) is False
    assert await is_valid_dialect_db(None, db) is False
    assert AUTO == "auto"


def test_marketing_requirements_off_by_default():
    from app.modules.review_engine.service import marketing_requirements

    assert marketing_requirements({
        "promo_product_mentions": False, "promo_links": False,
        "promo_only_relevant": True, "promo_max_ctas": 1,
    }) == []


def test_marketing_requirements_permission_lines():
    from app.modules.review_engine.service import marketing_requirements

    reqs = marketing_requirements({
        "promo_product_mentions": True, "promo_links": True,
        "promo_only_relevant": True, "promo_max_ctas": 1,
    })
    assert len(reqs) == 2
    assert any("exact name" in r for r in reqs)
    assert any("at most 1 link" in r for r in reqs)
    assert any("directly relevant" in r for r in reqs)


@pytest.mark.asyncio
async def test_resolve_reply_prefs_channel_config(db, user_id):
    """Channel config wins; explicit request fields override it."""
    from app.modules.channels.models import AutoReplyConfig
    from app.modules.review_engine.schemas import ReviewEngineRequest
    from app.modules.review_engine.service import _resolve_reply_prefs

    _seed_dialects(db)
    db.add(AutoReplyConfig(
        channel_id="pref-ch-1", dialect="egyptian", reply_language="ar",
        promo_product_mentions=True, promo_links=True,
        promo_only_relevant=False, promo_max_ctas=2,
    ))
    await db.commit()

    base = ReviewEngineRequest(review_text="good", rating=5, channel_id="pref-ch-1")
    prefs = await _resolve_reply_prefs(base, user_id, db)
    assert prefs["dialect"] == "egyptian"
    assert prefs["reply_language"] == "ar"
    assert prefs["promo_product_mentions"] is True
    assert prefs["promo_links"] is True
    assert prefs["promo_only_relevant"] is False
    assert prefs["promo_max_ctas"] == 2

    over = ReviewEngineRequest(
        review_text="good", rating=5, channel_id="pref-ch-1",
        dialect="najdi", reply_language="en",
    )
    prefs2 = await _resolve_reply_prefs(over, user_id, db)
    assert prefs2["dialect"] == "najdi"
    assert prefs2["reply_language"] == "en"


@pytest.mark.asyncio
async def test_resolve_reply_prefs_bad_dialect_raises(db, channel_id, user_id):
    from app.modules.review_engine.schemas import ReviewEngineRequest
    from app.modules.review_engine.service import _resolve_reply_prefs

    req = ReviewEngineRequest(review_text="good", rating=5, dialect="klingon")
    with pytest.raises(ValueError, match="Unknown dialect"):
        await _resolve_reply_prefs(req, user_id, db)


def test_promo_cta_cap_enforced():
    reply = _resp("Thanks! See our deal https://a.example/x and also https://b.example/y today.")
    result = validate_response(
        reply, _neg_analysis(), {"max_length": 500, "public": True},
        review_text="ok", promo_max_ctas=1,
    )
    assert result.checks["promo_cta"] is False
    assert result.passed is False
    assert any("promotional links" in i for i in result.issues)


def test_promo_cta_cap_passes_within_limit():
    reply = _resp("Thanks! See our deal https://a.example/x today.")
    result = validate_response(
        reply, _neg_analysis(), {"max_length": 500, "public": True},
        review_text="ok", promo_max_ctas=2,
    )
    assert result.checks["promo_cta"] is True


def test_promo_cta_unset_means_no_restriction():
    reply = _resp("Thanks! See https://a.example/x and https://b.example/y and https://c.example/z.")
    result = validate_response(
        reply, _neg_analysis(), {"max_length": 500, "public": True},
        review_text="ok",
    )
    assert result.checks["promo_cta"] is True


def test_generator_adds_dialect_instruction():
    import asyncio
    from app.modules.review_engine import generator as gen

    captured = {}
    egyptian = {
        "code": "egyptian", "dialect_en": "Egyptian Arabic",
        "dialect_ar": "اللهجة المصرية", "examples": ["أهلاً", "إزيك؟"],
    }

    class _FakeProvider:
        async def complete(self, req):
            captured["user_msg"] = req.messages[0].content
            from app.modules.llm.providers.base import LLMResponse, LLMUsage
            return LLMResponse(
                content='{"response_text": "done"}',
                provider="test", model="test/m",
                usage=LLMUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                finish_reason="stop",
            )

    orig_get = gen.get_provider_for_model
    orig_resolve = gen._resolve_model
    gen.get_provider_for_model = lambda model: _FakeProvider()
    gen._resolve_model = lambda model: ("test/m", {})
    try:
        out, _usage = asyncio.run(gen.generate_response(
            analysis=_ar_analysis(),
            strategies=[_match("show_appreciation", "Show appreciation", 80)],
            channel_policy={"max_length": 500, "public": True},
            brand_voice={},
            business_context=None,
            model="test:m",
            review_text="review",
            dialect=egyptian,
            reply_language="match",
        ))
    finally:
        gen.get_provider_for_model = orig_get
        gen._resolve_model = orig_resolve

    assert out.response_text == "done"
    assert "DIALECT (binding)" in captured["user_msg"]
    assert "Egyptian Arabic" in captured["user_msg"]
    assert "Copy this flavor" in captured["user_msg"]


def test_generator_forced_english_over_arabic():
    import asyncio
    from app.modules.review_engine import generator as gen

    captured = {}

    class _FakeProvider:
        async def complete(self, req):
            captured["user_msg"] = req.messages[0].content
            from app.modules.llm.providers.base import LLMResponse, LLMUsage
            return LLMResponse(
                content='{"response_text": "Thanks!"}',
                provider="test", model="test/m",
                usage=LLMUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                finish_reason="stop",
            )

    orig_get = gen.get_provider_for_model
    orig_resolve = gen._resolve_model
    gen.get_provider_for_model = lambda model: _FakeProvider()
    gen._resolve_model = lambda model: ("test/m", {})
    try:
        asyncio.run(gen.generate_response(
            analysis=_ar_analysis(),
            strategies=[_match("show_appreciation", "Show appreciation", 80)],
            channel_policy={"max_length": 500, "public": True},
            brand_voice={},
            business_context=None,
            model="test:m",
            review_text="review",
            reply_language="en",
        ))
    finally:
        gen.get_provider_for_model = orig_get
        gen._resolve_model = orig_resolve

    assert "ENTIRE reply in English" in captured["user_msg"]
    assert "DIALECT" not in captured["user_msg"]

@pytest.mark.asyncio
async def test_admin_dialect_crud(db):
    """Admin can add and remove dialect rows; validation is enforced."""
    from fastapi import HTTPException

    from app.modules.admin.router import (
        DialectCreate,
        admin_dialect_create,
        admin_dialect_delete,
    )
    from app.modules.review_engine.dialects import get_dialect

    created = await admin_dialect_create(
        DialectCreate(
            code="Test-Dialect",
            dialect_en="Test Arabic",
            dialect_ar="اللهجة التجريبية",
            examples=["مرحبا"],
        ),
        _admin={},
        _rate_limit=None,
        db=db,
    )
    assert created.code == "test-dialect"
    assert (await get_dialect("test-dialect", db))["dialect_en"] == "Test Arabic"

    with pytest.raises(HTTPException) as dup:
        await admin_dialect_create(
            DialectCreate(
                code="test-dialect", dialect_en="Dup",
                dialect_ar="مكرر", examples=[],
            ),
            _admin={},
            _rate_limit=None,
            db=db,
        )
    assert dup.value.status_code == 409

    with pytest.raises(HTTPException) as reserved:
        await admin_dialect_create(
            DialectCreate(
                code="auto", dialect_en="Auto",
                dialect_ar="تلقائي", examples=[],
            ),
            _admin={},
            _rate_limit=None,
            db=db,
        )
    assert reserved.value.status_code == 422

    await admin_dialect_delete(
        "test-dialect", _admin={}, _rate_limit=None, db=db,
    )
    assert await get_dialect("test-dialect", db) is None

    with pytest.raises(HTTPException) as missing:
        await admin_dialect_delete(
            "nope", _admin={}, _rate_limit=None, db=db,
        )
    assert missing.value.status_code == 404

@pytest.mark.asyncio
async def test_tone_catalog_db_backed(db):
    from app.modules.review_engine.models import Tone
    from app.modules.review_engine.tones import (
        get_tone,
        is_valid_tone_db,
        list_tones,
    )

    db.add(Tone(code="friendly", label="Friendly", description="warm and casual"))
    db.add(Tone(code="formal", label="Formal", description="polished"))
    await db.commit()

    rows = await list_tones(db)
    assert [r["code"] for r in rows] == ["formal", "friendly"]
    assert (await get_tone("friendly", db))["label"] == "Friendly"
    assert await get_tone("nope", db) is None
    assert await get_tone(None, db) is None
    assert await is_valid_tone_db("formal", db) is True
    assert await is_valid_tone_db("Formal", db) is True
    assert await is_valid_tone_db("nope", db) is False
    assert await is_valid_tone_db("", db) is False


@pytest.mark.asyncio
async def test_admin_tone_crud(db):
    from fastapi import HTTPException

    from app.modules.admin.router import (
        ToneCreate,
        admin_tone_create,
        admin_tone_delete,
    )
    from app.modules.review_engine.tones import get_tone

    created = await admin_tone_create(
        ToneCreate(code="Bold", label="Bold", description="direct"),
        _admin={},
        _rate_limit=None,
        db=db,
    )
    assert created.code == "bold"
    assert (await get_tone("bold", db))["label"] == "Bold"

    with pytest.raises(HTTPException) as dup:
        await admin_tone_create(
            ToneCreate(code="bold", label="Dup", description=""),
            _admin={},
            _rate_limit=None,
            db=db,
        )
    assert dup.value.status_code == 409

    await admin_tone_delete("bold", _admin={}, _rate_limit=None, db=db)
    assert await get_tone("bold", db) is None

    with pytest.raises(HTTPException) as missing:
        await admin_tone_delete("nope", _admin={}, _rate_limit=None, db=db)
    assert missing.value.status_code == 404

@pytest.mark.asyncio
async def test_admin_tone_update(db):
    from fastapi import HTTPException

    from app.modules.admin.router import (
        ToneCreate,
        ToneUpdate,
        admin_tone_create,
        admin_tone_delete,
        admin_tone_update,
    )
    from app.modules.review_engine.tones import get_tone

    await admin_tone_create(
        ToneCreate(code="warm", label="Warm", description="cozy"),
        _admin={},
        _rate_limit=None,
        db=db,
    )
    updated = await admin_tone_update(
        "warm",
        ToneUpdate(label="Very Warm", description="extra cozy"),
        _admin={},
        _rate_limit=None,
        db=db,
    )
    assert updated.label == "Very Warm"
    assert (await get_tone("warm", db))["description"] == "extra cozy"

    partial = await admin_tone_update(
        "warm",
        ToneUpdate(label="Warm Again"),
        _admin={},
        _rate_limit=None,
        db=db,
    )
    assert partial.label == "Warm Again"
    assert partial.description == "extra cozy"

    with pytest.raises(HTTPException) as missing:
        await admin_tone_update(
            "nope", ToneUpdate(label="Ghost"), _admin={}, _rate_limit=None, db=db,
        )
    assert missing.value.status_code == 404

    await admin_tone_delete("warm", _admin={}, _rate_limit=None, db=db)


# -- question detection + question-aware generation requirements --

def test_looks_like_question_arabic_and_english():
    from app.modules.review_engine.understanding import looks_like_question

    assert looks_like_question("?? ?????? ???????") is True
    assert looks_like_question("????? ??????") is True  # dialect opener, no mark
    assert looks_like_question("Do you sell shawarma?") is True
    assert looks_like_question("what time do you close") is True
    assert looks_like_question("Great product") is False
    assert looks_like_question("I have used multiple platforms and this one wins.") is False
    assert looks_like_question(None) is False


def test_rule_based_analysis_flags_question_intent():
    from app.modules.review_engine.understanding import _rule_based_analysis

    analysis = _rule_based_analysis("?? ?????? ???????", 5)
    assert "question" in analysis.intent


def test_build_requirements_question_without_context_bans_invention():
    from app.modules.review_engine.schemas import ReviewAnalysis
    from app.modules.review_engine.service import build_requirements

    analysis = ReviewAnalysis(
        sentiment="positive", emotion="joy", intent=["question"],
        urgency="low", language="ar",
    )
    reqs = build_requirements(analysis, [], [], [], tier=None, business_context=None)
    joined = "\n".join(reqs)
    assert "never thank the reviewer" in joined.lower()
    assert "do NOT invent" in joined
    # With verified context the reply should answer directly instead.
    reqs_ctx = build_requirements(
        analysis, [], [], [], tier=None, business_context="We sell shawarma.",
    )
    joined_ctx = "\n".join(reqs_ctx)
    assert "answer it directly" in joined_ctx.lower()
    assert "not thank the reviewer" in joined_ctx.lower()


# ── model resolution: explicit > channel > tenant default, never hardcoded ──

async def _enable_model(db, model_id="groq:oss-120b"):
    from app.modules.channels.service import encrypt_token
    from app.modules.llm.models import ModelConfig, ProviderConfig

    db.add(ProviderConfig(
        provider="groq", key_encrypted=encrypt_token("gsk_test"), enabled=True,
    ))
    db.add(ModelConfig(model_id=model_id, enabled=True))
    await db.commit()


@pytest.mark.asyncio
async def test_engine_model_explicit_validated(db, user_id, channel_id):
    """Explicit request model must be admin-enabled, else loud ValueError."""
    from app.modules.review_engine.schemas import ReviewEngineRequest
    from app.modules.review_engine.service import _resolve_engine_model

    await _enable_model(db)
    req = ReviewEngineRequest(review_text="Hi", rating=5, model="groq:oss-120b")
    model, source = await _resolve_engine_model(req, user_id, db)
    assert (model, source) == ("groq:oss-120b", "request")

    req = ReviewEngineRequest(review_text="Hi", rating=5, model="openai:nope")
    with pytest.raises(ValueError, match="not enabled"):
        await _resolve_engine_model(req, user_id, db)


@pytest.mark.asyncio
async def test_engine_model_channel_then_tenant_default(db, user_id):
    """Channel explicit choice wins when enabled; NULL falls to tenant default."""
    from sqlalchemy import select as _select

    from app.modules.channels.models import AutoReplyConfig, Channel
    from app.modules.review_engine.schemas import ReviewEngineRequest
    from app.modules.review_engine.service import _resolve_engine_model

    await _enable_model(db, "groq:oss-120b")
    db.add(Channel(id="ch-model-1", user_id=user_id, platform="google_reviews",
                   platform_user_id="x", display_name="M", status="active"))
    db.add(AutoReplyConfig(id="cfg-model-1", channel_id="ch-model-1",
                           model="groq:oss-120b"))
    await db.commit()
    req = ReviewEngineRequest(review_text="Hi", rating=5, channel_id="ch-model-1")
    # Explicit channel choice → channel source.
    model, source = await _resolve_engine_model(req, user_id, db)
    assert (model, source) == ("groq:oss-120b", "channel")

    # NULL = tenant default: first enabled model, no hardcode.
    config = (await db.execute(
        _select(AutoReplyConfig).where(AutoReplyConfig.id == "cfg-model-1")
    )).scalar_one()
    config.model = None
    await db.commit()
    model, source = await _resolve_engine_model(req, user_id, db)
    assert (model, source) == ("groq:oss-120b", "tenant-default")


@pytest.mark.asyncio
async def test_engine_model_none_enabled_raises(db, user_id):
    from app.modules.review_engine.schemas import ReviewEngineRequest
    from app.modules.review_engine.service import _resolve_engine_model

    req = ReviewEngineRequest(review_text="Hi", rating=5)
    with pytest.raises(ValueError, match="No AI model is enabled"):
        await _resolve_engine_model(req, user_id, db)


# ── databank override: owned banks only ──

@pytest.mark.asyncio
async def test_bank_override_ownership(db, user_id):
    import uuid

    from app.modules.rag.models import Databank
    from app.modules.review_engine.service import _resolve_bank_override

    mine = f"bank-{uuid.uuid4().hex[:8]}"
    db.add(Databank(id=mine, user_id=user_id, name="Mine"))
    await db.commit()

    assert await _resolve_bank_override(db, user_id, mine) == mine
    assert await _resolve_bank_override(db, user_id, "bank-foreign") is None
    assert await _resolve_bank_override(db, user_id, None) is None
    assert await _resolve_bank_override(db, None, mine) is None


@pytest.mark.asyncio
async def test_engine_run_uses_override_bank(monkeypatch, tmp_path, db, user_id):
    """End-to-end: databank_id override feeds CSV evidence into generation."""
    import json as _json
    import uuid
    from types import SimpleNamespace

    from app.config import settings as _settings
    from app.core.storage import put_doc
    from app.modules.rag.models import Databank, Document
    from app.modules.review_engine.schemas import ReviewEngineRequest
    import app.modules.review_engine.service as eng
    import app.modules.review_engine.understanding as und
    import app.modules.review_engine.generator as gen

    monkeypatch.setattr("app.config.settings.GOOGLE_REVIEWS_MOCK", False)
    monkeypatch.setattr(_settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(eng, "_async_session",
                        _shim_test_session_factory(db))

    bank_id = f"bank-{uuid.uuid4().hex[:8]}"
    doc_id = f"doc-{uuid.uuid4().hex[:8]}"
    db.add(Databank(id=bank_id, user_id=user_id, name="Menu"))
    db.add(Document(id=doc_id, databank_id=bank_id, user_id=user_id,
                    filename="menu.csv", source_type="upload",
                    file_type="csv", status="completed"))
    from app.modules.review_engine.models import ResponseStrategy

    db.add(ResponseStrategy(
        id="recommend_related_product", name="Recommend",
        description="Recommend", category="recommend", priority=40,
        conditions={"sentiments": ["positive", "very_positive"],
                    "has_product_reference": True},
        enabled=True,
    ))
    await db.commit()
    put_doc(bank_id, f"{doc_id}.csv",
            b"name,record_type,category\nTruffle Pasta,product,Mains\n")

    analysis = _json.dumps({"sentiment": "positive", "emotion": "joy",
                            "intent": ["praise"], "issue_type": None,
                            "product_reference": "truffle pasta",
                            "urgency": "low", "customer_request": None,
                            "language": "en"})

    def _usage():
        return SimpleNamespace(prompt_tokens=10, completion_tokens=20,
                               total_tokens=30)

    class _Analysis:
        async def complete(self, req):
            return SimpleNamespace(content=analysis, finish_reason="stop",
                                   usage=_usage())

    seen = {}

    class _Gen:
        async def complete(self, req):
            seen["prompt"] = "\n".join(m.content for m in req.messages)
            return SimpleNamespace(
                content=_json.dumps({"response_text": "Our truffle pasta, glad you loved it!"}),
                finish_reason="stop", usage=_usage())

    async def _models(db):
        return [(SimpleNamespace(id="custom:model"), None)]

    monkeypatch.setattr(und, "get_provider_for_model", lambda mid: _Analysis())
    monkeypatch.setattr(und, "_resolve_model", lambda mid: ("api-x", "groq"))
    monkeypatch.setattr(gen, "get_provider_for_model", lambda mid: _Gen())
    monkeypatch.setattr(gen, "_resolve_model", lambda mid: ("api-x", "groq"))
    monkeypatch.setattr(
        "app.modules.llm.providers.registry.list_tenant_models", _models)

    req = ReviewEngineRequest(
        review_text="Loved the truffle pasta!", rating=5,
        reviewer_name="Sam", model="custom:model", databank_id=bank_id)
    resp = await eng.process_review(req, user_id, db)
    assert "truffle pasta" in resp.response_text.lower()
    assert "Truffle Pasta" in seen["prompt"]


def _shim_test_session_factory(session):
    class _Factory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            return False

    return _Factory()

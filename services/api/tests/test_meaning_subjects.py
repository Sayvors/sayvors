"""The enforcement layer for review meaning.

These tests exist because a language model turned the Arabic review
"you need to fix your building" into "bank account corrections" and then
propagated that fabrication into a theme, an opportunity and a business
action. The prompt already forbade inventing topics. It did it anyway, so the
rules moved into code and are pinned here.
"""
import pytest

from app.modules.analytics import subjects as S

# The real complaint that started all this.
AR_REVIEW = "يحتاج تصلحون مبناكم"          # "you need to fix your building"
AR_WITH_DIACRITICS = "يَحْتَاجُ تَصْلِحُونَ مَبْنَاكُمْ"
AR_ALEF_VARIANT = "مبنآكم"               # same word, ا written as آ
AR_NO_PROBLEM = "ما في مشكلة"              # "there is no problem"  (negated)
AR_HAS_PROBLEM = "فيه مشكلة"              # "there is a problem"   (affirmed)
EN_NEGATED = "The food was not fresh and the staff were rude."
EN_PLAIN = "The food was fresh and the staff were helpful."


# ── Language detection ──────────────────────────────────────────

def test_detects_arabic_and_english():
    assert S.detect_language(AR_REVIEW) == "ar"
    assert S.detect_language(EN_PLAIN) == "en"
    assert S.detect_language("") == "und"


def test_non_latin_flag_stops_the_english_only_fallback():
    """Arabic must abstain rather than return empty lists that look valid."""
    assert S.is_non_latin(AR_REVIEW) is True
    assert S.is_non_latin(EN_PLAIN) is False


# ── Normalisation: a correct reading must survive the check ─────

def test_evidence_matches_arabic_review():
    assert S.evidence_is_verbatim("مبناكم", AR_REVIEW) is True


def test_diacritics_do_not_break_a_correct_quote():
    """Reviewers omit harakat freely; folding them keeps valid quotes valid."""
    assert S.evidence_is_verbatim("مبناكم", AR_WITH_DIACRITICS) is True
    assert S.evidence_is_verbatim(AR_WITH_DIACRITICS, AR_REVIEW) is True


def test_interchangeable_arabic_letter_forms_fold():
    assert S.evidence_is_verbatim("مبناكم", AR_ALEF_VARIANT) is True


def test_latin_accents_fold():
    assert S.evidence_is_verbatim("cafe", "the café was great") is True


def test_whitespace_runs_collapse():
    assert S.evidence_is_verbatim("fix your building", "fix   your\n building") is True


# ── The core guarantee: a fabrication cannot be evidenced ───────

def test_the_bank_account_fabrication_is_rejected():
    """The exact claim that reached the CEO dashboard, with no span behind it."""
    assert S.evidence_is_verbatim("bank account", AR_REVIEW) is False
    assert S.evidence_is_verbatim("bank account corrections", AR_REVIEW) is False
    assert S.filter_evidence(["bank account"], AR_REVIEW) == []


def test_filter_evidence_keeps_only_real_spans():
    kept = S.filter_evidence(["مبناكم", "bank account", "تصلحون"], AR_REVIEW)
    assert kept == ["مبناكم", "تصلحون"]


def test_filter_evidence_dedupes_after_normalisation():
    assert len(S.filter_evidence(["مبناكم", "مَبْنَاكُم"], AR_REVIEW)) == 1


def test_too_short_a_span_is_not_evidence():
    """One character matches almost anything; it cannot support a claim."""
    assert S.evidence_is_verbatim("ا", AR_REVIEW) is False


# ── Negation ────────────────────────────────────────────────────

def test_negation_detected_in_english():
    assert S.has_negation(EN_NEGATED) is True
    assert S.has_negation(EN_PLAIN) is False


def test_negation_detected_in_arabic():
    """ما في مشكلة and فيه مشكلة differ by a few characters."""
    assert S.has_negation(AR_NO_PROBLEM) is True
    assert S.has_negation(AR_HAS_PROBLEM) is False


# ── Closed vocabulary: the other half of the guarantee ──────────

def test_invented_subject_is_refused():
    """This is what makes 'Account Issues' unrepresentable."""
    assert S.coerce_subject("Account Issues") is None
    assert S.coerce_subject("bank account") is None
    assert S.coerce_subject("Payment Account Troubleshooting") is None
    assert S.coerce_subject(None) is None
    assert S.coerce_subject(42) is None


def test_legal_subjects_pass():
    assert S.coerce_subject("facility_premises") == "facility_premises"
    assert S.coerce_subject("Facility Premises") == "facility_premises"
    assert S.coerce_subject("  FACILITY-PREMISES ") == "facility_premises"


def test_near_miss_aliases_are_forgiven():
    assert S.coerce_subject("facility") == "facility_premises"
    assert S.coerce_subject("premises") == "facility_premises"
    assert S.coerce_subject("billing") == "billing_payments"


def test_every_alias_target_is_a_real_subject():
    """An alias pointing at a non-existent key would silently drop meaning."""
    from app.modules.analytics.subjects import SUBJECTS

    for alias, target in {
        "facility": "facility_premises", "premises": "facility_premises",
        "support": "communication_response", "pricing": "value_pricing",
        "billing": "billing_payments", "account": "account_access",
    }.items():
        assert S.coerce_subject(alias) in SUBJECTS


def test_facility_catches_the_makkah_review():
    """The building complaint must land on premises, not payments."""
    subject = S.coerce_subject("facility_premises")
    assert subject is not None
    assert subject != "billing_payments"


def test_financial_subject_is_rejected_for_arabic_building_review():
    """A genuine quote cannot rescue a semantically unrelated category."""
    assert S.subject_conflicts_with_text("billing_payments", AR_REVIEW)
    assert S.subject_conflicts_with_text("account_access", AR_REVIEW)


def test_financial_subject_is_allowed_when_review_names_a_payment():
    text = "تم خصم المبلغ من حسابي البنكي"
    assert not S.subject_conflicts_with_text("billing_payments", text)
    assert not S.subject_conflicts_with_text("account_access", text)


def test_building_with_explicit_payment_context_is_not_auto_rejected():
    text = "The building repair charge was taken from my bank account twice."
    assert not S.subject_conflicts_with_text("billing_payments", text)


def test_financial_subject_is_rejected_for_arabic_building_review():
    """A genuine quote cannot rescue a semantically unrelated category."""
    assert S.subject_conflicts_with_text("billing_payments", AR_REVIEW)
    assert S.subject_conflicts_with_text("account_access", AR_REVIEW)


def test_financial_subject_is_allowed_when_review_names_a_payment():
    text = "تم خصم المبلغ من حسابي البنكي"
    assert not S.subject_conflicts_with_text("billing_payments", text)
    assert not S.subject_conflicts_with_text("account_access", text)


def test_building_with_explicit_payment_context_is_not_auto_rejected():
    text = "The building repair charge was taken from my bank account twice."
    assert not S.subject_conflicts_with_text("billing_payments", text)


# ── Confidence ──────────────────────────────────────────────────

def test_out_of_range_confidence_is_not_clamped():
    """Clamping 1.7 into 1.0 would invent certainty the model never claimed."""
    assert S.coerce_confidence(1.7) == 0.0
    assert S.coerce_confidence(-0.3) == 0.0
    assert S.coerce_confidence("nope") == 0.0
    assert S.coerce_confidence(None) == 0.0


def test_valid_confidence_passes_through():
    assert S.coerce_confidence(0.82) == 0.82
    assert S.coerce_confidence(0) == 0.0
    assert S.coerce_confidence(1) == 1.0
    assert S.coerce_confidence("0.5") == 0.5


def test_auto_accept_threshold_is_sane():
    assert 0 < S.AUTO_ACCEPT_CONFIDENCE < 1
    # A clear, evidenced complaint clears the bar; a vague one does not.
    assert 0.85 > S.AUTO_ACCEPT_CONFIDENCE
    assert 0.3 < S.AUTO_ACCEPT_CONFIDENCE

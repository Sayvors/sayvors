"""Citation grounding and deterministic branch outcomes."""
import pytest

from app.modules.ai_visibility import research, validation


def _source(label="S1", url="https://example.com", excerpt="Acme phone is +966 11 111 1111."):
    return {"id": label, "label": label, "url": url, "excerpt": excerpt}


def test_fabricated_answer_citation_is_rejected():
    payload = research.ResearchPayload(
        answer="Acme is recommended [S9].",
        claims=[],
        mentioned=True,
        cited=False,
        recommended=True,
        incorrect=False,
    )
    with pytest.raises(validation.CitationValidationError):
        validation.validate(payload, [_source()], {"name": "Acme"})


def test_claim_quote_must_exist_in_cited_source():
    payload = research.ResearchPayload(
        answer="Acme is open [S1].",
        claims=[
            research.ResearchClaim(
                claim="Acme is open",
                quote="invented quote",
                source_ids=["S1"],
                status="supported",
            )
        ],
        mentioned=True,
        cited=False,
        recommended=False,
        incorrect=False,
    )
    with pytest.raises(validation.CitationValidationError):
        validation.validate(
            payload, [_source(excerpt="Acme is closed.")], {"name": "Acme"}
        )


def test_wrong_branch_phone_is_contradicted():
    payload = research.ResearchPayload(
        answer="Acme phone is +966 22 222 2222 [S1].",
        claims=[
            research.ResearchClaim(
                claim="Acme phone is +966 22 222 2222",
                quote="Acme phone is +966 22 222 2222",
                source_ids=["S1"],
                status="supported",
            )
        ],
        mentioned=True,
        cited=False,
        recommended=False,
        incorrect=False,
    )
    validated = validation.validate(
        payload,
        [_source(excerpt="Acme phone is +966 22 222 2222.")],
        {"name": "Acme", "phone": "+966 11 111 1111"},
    )
    assert validated.claims[0].status == "contradicted"
    assert validated.incorrect is True


def test_uncited_factual_answer_is_rejected():
    payload = research.ResearchPayload(
        answer="Acme is the best coffee shop in Riyadh.",
        claims=[],
        mentioned=True,
        cited=False,
        recommended=True,
        incorrect=False,
    )
    with pytest.raises(validation.CitationValidationError):
        validation.validate(payload, [_source(excerpt="Acme is a coffee shop.")], {"name": "Acme"})


def test_unfetched_answer_url_is_rejected():
    payload = research.ResearchPayload(
        answer="Acme is recommended [S1]. See https://evil.example.",
        claims=[],
        mentioned=True,
        cited=False,
        recommended=True,
        incorrect=False,
    )
    with pytest.raises(validation.CitationValidationError):
        validation.validate(payload, [_source()], {"name": "Acme"})


def test_unrelated_quote_does_not_support_a_claim():
    payload = research.ResearchPayload(
        answer="Acme is a coffee shop [S1].",
        claims=[
            research.ResearchClaim(
                claim="Acme is ranked number one",
                quote="The park opens at nine",
                source_ids=["S1"],
                status="supported",
            )
        ],
        mentioned=True,
        cited=False,
        recommended=True,
        incorrect=False,
    )
    validated = validation.validate(
        payload,
        [_source(excerpt="The park opens at nine. Acme is a coffee shop.")],
        {"name": "Acme"},
    )
    assert validated.claims[0].status == "unsupported"
    assert validated.recommended is False


def test_model_cannot_self_declare_recommendation_or_incorrect():
    payload = research.ResearchPayload(
        answer="Acme is a coffee shop [S1].",
        claims=[
            research.ResearchClaim(
                claim="Acme is a coffee shop",
                quote="Acme is a coffee shop",
                source_ids=["S1"],
                status="supported",
            )
        ],
        mentioned=True,
        cited=False,
        recommended=True,
        incorrect=True,
    )
    validated = validation.validate(
        payload, [_source(excerpt="Acme is a coffee shop.")], {"name": "Acme"}
    )
    assert validated.recommended is False
    assert validated.incorrect is False


def test_citation_requires_an_owned_source_cited_in_the_answer():
    payload = research.ResearchPayload(
        answer="Acme is nearby [S1].",
        claims=[],
        mentioned=True,
        cited=True,
        recommended=False,
        incorrect=False,
    )
    validated = validation.validate(
        payload,
        [
            _source(label="S1", excerpt="Acme is nearby."),
            _source(
                label="S2",
                url="https://acme.example/menu",
                excerpt="Acme menu.",
            ),
        ],
        {"name": "Acme", "website": "https://acme.example"},
    )
    assert validated.cited is False


def test_claim_with_any_unknown_source_is_unsupported():
    payload = research.ResearchPayload(
        answer="Acme is nearby [S1].",
        claims=[
            research.ResearchClaim(
                claim="Acme is nearby",
                quote="Acme is nearby",
                source_ids=["S1", "S9"],
                status="supported",
            )
        ],
        mentioned=True,
        cited=False,
        recommended=False,
        incorrect=False,
    )
    validated = validation.validate(
        payload,
        [_source(label="S1", excerpt="Acme is nearby.")],
        {"name": "Acme"},
    )
    assert validated.claims[0].status == "unsupported"


def test_claim_text_and_quote_must_be_supported_by_the_same_source():
    payload = research.ResearchPayload(
        answer="Acme is ranked first [S1].",
        claims=[
            research.ResearchClaim(
                claim="Acme is ranked first",
                quote="Acme is nearby",
                source_ids=["S1", "S2"],
                status="supported",
            )
        ],
        mentioned=True,
        cited=False,
        recommended=True,
        incorrect=False,
    )
    validated = validation.validate(
        payload,
        [
            _source(label="S1", excerpt="Acme is ranked first."),
            _source(label="S2", excerpt="Acme is nearby."),
        ],
        {"name": "Acme"},
    )
    assert validated.claims[0].status == "unsupported"
    assert validated.recommended is False


def test_owned_domain_counts_as_citation():
    payload = research.ResearchPayload(
        answer="Acme Coffee is recommended [S1].",
        claims=[],
        mentioned=True,
        cited=False,
        recommended=True,
        incorrect=False,
    )
    validated = validation.validate(
        payload,
        [_source(url="https://acme.example/menu", excerpt="Acme Coffee is recommended.")],
        {"name": "Acme Coffee", "website": "https://acme.example"},
    )
    assert validated.mentioned is True
    assert validated.cited is True


def test_unknown_claim_source_is_unsupported():
    payload = research.ResearchPayload(
        answer="Acme is nearby [S1].",
        claims=[
            research.ResearchClaim(
                claim="Acme is nearby",
                quote="Acme is nearby",
                source_ids=["S9"],
                status="supported",
            )
        ],
        mentioned=True,
        cited=False,
        recommended=False,
        incorrect=False,
    )
    validated = validation.validate(
        payload, [_source(excerpt="Acme is nearby.")], {"name": "Acme"}
    )
    assert validated.claims[0].status == "unsupported"


def test_competitor_name_must_appear_in_its_supporting_quote():
    payload = research.ResearchPayload(
        answer="Acme is nearby [S1].",
        claims=[],
        mentioned=True,
        cited=False,
        recommended=False,
        incorrect=False,
        competitors=[
            research.CompetitorMention(
                name="Invented Rival",
                quote="Acme is nearby",
                source_ids=["S1"],
            )
        ],
    )
    validated = validation.validate(
        payload, [_source(excerpt="Acme is nearby.")], {"name": "Acme"}
    )
    assert validated.competitors == []


def test_competitor_quote_must_exist_in_cited_source():
    payload = research.ResearchPayload(
        answer="Acme is nearby [S1].",
        claims=[],
        mentioned=True,
        cited=False,
        recommended=False,
        incorrect=False,
        competitors=[
            research.CompetitorMention(
                name="Rival",
                quote="Rival has the largest location in Riyadh",
                source_ids=["S1"],
            )
        ],
    )
    validated = validation.validate(
        payload, [_source(excerpt="Acme is nearby.")], {"name": "Acme"}
    )
    assert validated.competitors == []


def test_wrong_phone_in_answer_marks_branch_information_incorrect():
    payload = research.ResearchPayload(
        answer="Acme phone is +966 22 222 2222 [S1].",
        claims=[],
        mentioned=True,
        cited=False,
        recommended=False,
        incorrect=False,
    )
    validated = validation.validate(
        payload,
        [_source(excerpt="Acme phone is +966 22 222 2222.")],
        {"name": "Acme", "phone": "+966 11 111 1111"},
    )
    assert validated.incorrect is True


def test_quote_match_ignores_case_and_repeated_whitespace():
    payload = research.ResearchPayload(
        answer="Acme is nearby [S1].",
        claims=[
            research.ResearchClaim(
                claim="Acme is nearby",
                quote="  ACME   is nearby. ",
                source_ids=["S1"],
                status="unsupported",
            )
        ],
        mentioned=True,
        cited=False,
        recommended=False,
        incorrect=False,
    )
    validated = validation.validate(
        payload, [_source(excerpt="Acme is nearby.")], {"name": "Acme"}
    )
    assert validated.claims[0].status == "supported"

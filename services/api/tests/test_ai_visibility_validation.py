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
    validated = validation.validate(
        payload, [_source(excerpt="Acme is closed.")], {"name": "Acme"}
    )
    assert validated.claims[0].status == "unsupported"


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
        [_source(url="https://acme.example/menu")],
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

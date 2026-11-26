"""Evidence-linked, deterministic fix-next actions."""
from app.modules.ai_visibility import decisions, research


def test_contradicted_fact_is_p0_and_links_to_locations():
    payload = research.ResearchPayload(
        answer="Acme phone is wrong [S1].",
        claims=[
            research.ResearchClaim(
                claim="Acme phone is wrong",
                quote="wrong phone",
                source_ids=["S1"],
                status="contradicted",
            )
        ],
        mentioned=True,
        cited=True,
        recommended=False,
        incorrect=True,
    )
    actions = decisions.build_actions(payload, branch={"name": "Acme"})
    assert actions[0]["priority"] == "P0"
    assert actions[0]["category"] == "fact_correction"
    assert actions[0]["deep_link"] == "/dashboard/locations?tab=details"


def test_missing_citation_produces_source_action():
    payload = research.ResearchPayload(
        answer="Acme is mentioned [S1].",
        claims=[],
        mentioned=True,
        cited=False,
        recommended=False,
        incorrect=False,
    )
    actions = decisions.build_actions(payload, branch={"name": "Acme"})
    assert any(row["category"] == "source_weakness" for row in actions)


def test_competitor_advantage_produces_action():
    payload = research.ResearchPayload(
        answer="Rival is recommended [S1].",
        claims=[],
        mentioned=False,
        cited=False,
        recommended=False,
        incorrect=False,
        competitors=[
            research.CompetitorMention(
                name="Rival",
                quote="Rival is recommended",
                source_ids=["S1"],
            )
        ],
    )
    actions = decisions.build_actions(payload, branch={"name": "Acme"})
    assert any(row["category"] == "competitor_gap" for row in actions)


def test_actions_are_sorted_by_priority_then_effort_then_title():
    payload = research.ResearchPayload(
        answer="Acme is mentioned [S1].",
        claims=[
            research.ResearchClaim(
                claim="Acme is open",
                quote="Acme is open",
                source_ids=["S1"],
                status="unsupported",
            ),
            research.ResearchClaim(
                claim="Acme phone is wrong",
                quote="Acme phone is wrong",
                source_ids=["S1"],
                status="contradicted",
            ),
        ],
        mentioned=True,
        cited=False,
        recommended=False,
        incorrect=True,
        competitors=[
            research.CompetitorMention(
                name="Rival",
                quote="Rival is recommended",
                source_ids=["S1"],
            )
        ],
    )
    actions = decisions.build_actions(payload, branch={"name": "Acme"})
    assert [row["priority"] for row in actions] == ["P0", "P1", "P1", "P1"]
    assert [row["effort"] for row in actions[1:]] == ["low", "medium", "medium"]
    assert actions == decisions.build_actions(payload, branch={"name": "Acme"})


def test_healthy_grounded_result_has_no_fix_next_action():
    payload = research.ResearchPayload(
        answer="Acme is recommended [S1].",
        claims=[
            research.ResearchClaim(
                claim="Acme is recommended",
                quote="Acme is recommended",
                source_ids=["S1"],
                status="supported",
            )
        ],
        mentioned=True,
        cited=True,
        recommended=True,
        incorrect=False,
    )
    assert decisions.build_actions(payload, branch={"name": "Acme"}) == []

"""Evidence-linked, deterministic owner actions. No invented uplift."""
from __future__ import annotations

from .research import ResearchPayload

PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2}
EFFORT_RANK = {"low": 0, "medium": 1, "high": 2}


def _action(
    *,
    priority: str,
    category: str,
    title: str,
    rationale: str,
    deep_link: str,
    effort: str = "medium",
    evidence: dict | None = None,
) -> dict:
    return {
        "priority": priority,
        "category": category,
        "title": title,
        "rationale": rationale,
        "deep_link": deep_link,
        "effort": effort,
        "evidence": evidence or {},
    }


def build_actions(payload: ResearchPayload, *, branch: dict) -> list[dict]:
    """Rank evidence-backed fixes; model-suggested actions never enter this list."""
    actions: list[dict] = []
    contradicted = [
        (index, claim)
        for index, claim in enumerate(payload.claims)
        if claim.status == "contradicted"
    ]
    for index, claim in contradicted:
        actions.append(
            _action(
                priority="P0",
                category="fact_correction",
                title=f"Correct the branch fact: {claim.claim[:120]}",
                rationale=(
                    "A fetched source contradicts the branch information currently held by Sayvors."
                ),
                deep_link="/dashboard/locations?tab=details",
                effort="low",
                evidence={"claim_index": index, "source_ids": claim.source_ids},
            )
        )

    if payload.incorrect and not contradicted:
        actions.append(
            _action(
                priority="P0",
                category="verification",
                title="Verify incorrect business information in the answer",
                rationale=(
                    "The grounded answer contains information that conflicts with the selected branch."
                ),
                deep_link="/dashboard/locations?tab=details",
                effort="low",
            )
        )

    if payload.mentioned and not payload.cited:
        actions.append(
            _action(
                priority="P1",
                category="source_weakness",
                title="Strengthen an owned source for this branch",
                rationale=(
                    "The branch is mentioned, but the answer does not cite an owned website or listing source."
                ),
                deep_link="/dashboard/posts-media",
                effort="medium",
            )
        )

    if payload.competitors and not payload.recommended:
        actions.append(
            _action(
                priority="P1",
                category="competitor_gap",
                title="Address the competitor advantage in the answer",
                rationale=(
                    "Named competitors appear with supporting sources while this branch is not recommended."
                ),
                deep_link="/dashboard/posts-media",
                effort="medium",
                evidence={"competitors": [row.name for row in payload.competitors]},
            )
        )

    unsupported = [
        index
        for index, claim in enumerate(payload.claims)
        if claim.status == "unsupported"
    ]
    if unsupported:
        actions.append(
            _action(
                priority="P1",
                category="verification",
                title="Review unsupported claims before acting",
                rationale=(
                    "Some generated claims could not be matched to the fetched source text."
                ),
                deep_link="/dashboard/ai-visibility",
                effort="low",
                evidence={"claim_indexes": unsupported},
            )
        )

    if not payload.mentioned:
        actions.append(
            _action(
                priority="P2",
                category="content_gap",
                title="Create content that answers this prompt with verifiable facts",
                rationale=(
                    "The branch does not appear in the validated grounded answer."
                ),
                deep_link="/dashboard/posts-media",
                effort="medium",
            )
        )

    return sorted(
        actions,
        key=lambda row: (
            PRIORITY_RANK[row["priority"]],
            EFFORT_RANK[row["effort"]],
            row["title"],
        ),
    )

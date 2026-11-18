"""Pure scoring for the RAG retrieval eval set (P2).

No database, no LLM, no Redis here: given the chunk ids a search returned and
the facts the prompt block actually contained, these functions produce the
metrics. The CLI in scripts/rag_eval.py owns I/O. Keeping the two apart means
a metric change is a unit test, not a live run against customer data.

The golden set is deliberately not committed with invented questions. Real
questions per vertical have to come from the support team; this module only
defines the schema contract and the scoring.
"""
from __future__ import annotations

from typing import Any

# Minimum schema version accepted by the loader. A bump means old golden sets
# must be reviewed, not silently scored with different semantics.
GOLDEN_SCHEMA_VERSION = 1


def recall_at_k(expected: list[str], retrieved: list[str], k: int) -> float | None:
    """Fraction of expected chunk ids found in the top k.

    Returns None when a case names no expected chunks: "we did not label this
    case" is different from "retrieval missed everything" and must not drag
    the average down.
    """
    if not expected:
        return None
    if k <= 0:
        return 0.0
    wanted = set(expected)
    found = set(retrieved[:k])
    return len(wanted & found) / len(wanted)


def evidence_present(block: str, expected_facts: list[str]) -> bool | None:
    """True when every labelled fact made it into the grounding prompt.

    This is the retrieval-side half of "answered from evidence": if the fact
    never reached the prompt, any answer using it was a guess. The generation-
    side half (did the answer actually use it?) needs the purpose-tagged
    llm_usage_events join and is reported separately by the CLI.
    """
    if not expected_facts:
        return None
    return all(fact in block for fact in expected_facts)


def score_case(case: dict[str, Any], *, retrieved: list[str], prompt_block: str, k: int) -> dict[str, Any]:
    """Score one golden-set case. Tolerant of missing optional labels."""
    expected_ids = [str(x) for x in case.get("expected_chunk_ids") or []]
    expected_facts = [str(x) for x in case.get("expected_facts") or []]
    recall = recall_at_k(expected_ids, retrieved, k)
    evidence = evidence_present(prompt_block, expected_facts)
    return {
        "id": case.get("id") or "unlabelled",
        "vertical": case.get("vertical") or "unlabelled",
        "recall_at_k": recall,
        "evidence_in_prompt": evidence,
        "labelled": recall is not None or evidence is not None,
    }


def summarize(scored: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate labelled cases overall and per vertical.

    Unlabelled cases are counted but never included in an average.
    """
    labelled = [row for row in scored if row["labelled"]]
    by_vertical: dict[str, list[dict[str, Any]]] = {}
    for row in labelled:
        by_vertical.setdefault(row["vertical"], []).append(row)

    def _block(rows: list[dict[str, Any]]) -> dict[str, Any]:
        recalls = [r["recall_at_k"] for r in rows if r["recall_at_k"] is not None]
        evidence = [r["evidence_in_prompt"] for r in rows if r["evidence_in_prompt"] is not None]
        return {
            "cases": len(rows),
            "recall_at_k": round(sum(recalls) / len(recalls), 4) if recalls else None,
            "evidence_rate": round(sum(1 for x in evidence if x) / len(evidence), 4) if evidence else None,
        }

    return {
        "overall": _block(labelled),
        "verticals": {name: _block(rows) for name, rows in sorted(by_vertical.items())},
        "unlabelled": len(scored) - len(labelled),
    }

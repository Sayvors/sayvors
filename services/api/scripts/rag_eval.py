"""Run a labelled RAG golden set and print retrieval metrics.

Usage (from services/api):
    python -m scripts.rag_eval --golden scripts/rag_golden.example.json --top-k 4

The golden set is a JSON object with a schema version and a list of cases:

    {
      "version": 1,
      "cases": [
        {
          "id": "coffee-price-ar",
          "vertical": "coffee",
          "databank_id": "<uuid>",
          "question": "كم سعر القهوة؟",
          "expected_chunk_ids": ["<chunk uuid>"],
          "expected_facts": ["15 ريال"]
        }
      ]
    }

Only `question`, `databank_id` and at least one of the `expected_*` fields
carry a score. This script never writes to the database and never calls the
chat LLM — it measures retrieval only, so a run is cheap and repeatable.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from app.config import settings
from app.database import async_session
from app.modules.rag.eval import GOLDEN_SCHEMA_VERSION, score_case, summarize
from app.modules.rag.grounding import _render
from app.modules.rag.search import hybrid_search


def load_golden(path: str) -> list[dict[str, Any]]:
    """Validate the file before touching the database. Fail loudly on drift."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != GOLDEN_SCHEMA_VERSION:
        raise ValueError(
            f"golden set must be an object with version={GOLDEN_SCHEMA_VERSION}"
        )
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("golden set needs a non-empty 'cases' list")
    for index, case in enumerate(cases):
        if not isinstance(case, dict) or not case.get("question") or not case.get("databank_id"):
            raise ValueError(f"case {index} needs 'question' and 'databank_id'")
    return cases


async def _vector_for(query: str) -> tuple[list[float] | None, str | None]:
    if not settings.embeddings_enabled:
        return None, None
    try:
        from app.modules.rag.embeddings import embed_query

        return await embed_query(query)
    except Exception as exc:  # keyword side still scores
        print(f"warning: embedding unavailable ({exc}); keyword-only", file=sys.stderr)
        return None, None


async def run(cases: list[dict[str, Any]], top_k: int) -> dict[str, Any]:
    scored: list[dict[str, Any]] = []
    async with async_session() as db:
        for case in cases:
            vector, model = await _vector_for(case["question"])
            hits = await hybrid_search(
                databank_id=case["databank_id"],
                query_vector=vector,
                query_text=case["question"],
                top_k=top_k,
                db=db,
                query_model=model,
            )
            scored.append(
                score_case(
                    case,
                    retrieved=[str(hit["id"]) for hit in hits],
                    prompt_block=_render(hits),
                    k=top_k,
                )
            )
    return {"top_k": top_k, **summarize(scored), "cases": scored}


def main(argv: list[str] | None = None) -> int:
    # The golden set contains Arabic; Windows consoles default to cp1252 and
    # would crash printing either --help or the report. Force UTF-8 at the
    # boundary, leaving all internal strings untouched.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--golden", required=True, help="path to the golden-set JSON")
    parser.add_argument("--top-k", type=int, default=4, help="retrieval depth to score (default 4)")
    args = parser.parse_args(argv)

    try:
        cases = load_golden(args.golden)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"golden set error: {exc}", file=sys.stderr)
        return 2

    report = asyncio.run(run(cases, args.top_k))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

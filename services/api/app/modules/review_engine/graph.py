"""LangGraph orchestration for the review -> ticket -> handoff pipeline.

Why a graph at all, when Phases A-C work as plain function calls? Because the
pipeline has three properties a linear function cannot express:

1. **Resumability.** The reviews worker is a poll loop that can be killed
   mid-flight (deploy, crash, rebalance). A checkpointed graph can resume from
   the last completed node instead of re-running the LLM classification, which
   is the expensive step and the reason a retry loop would otherwise cost the
   tenant money.
2. **Branching on classification, not on rating.** `needs_review_handoff` picks
   the next node. A 5-star complaint and a 1-star compliment take different
   paths through the same graph, which is the whole point of Phase A.
3. **One observable trace.** Each node's outcome lands in the final state, so
   "why did this review get a ticket?" is answerable from one record instead of
   reconstructed from log lines.

What it deliberately does NOT do: reimplement anything. Every node is a thin
adapter over the already-tested functions in `classification.py`,
`classifier.py`, `tickets.py` and `handoff.py`. The graph is orchestration, not
logic, so the Phase A-C unit tests still pin the behaviour.

Lazily imported. `langgraph` is a real dependency, but importing it at module
scope would make every consumer of these helpers pay for it, and would turn a
missing optional extra into an ImportError on the reviews worker's hot path.
"""

import logging
from contextvars import ContextVar
from typing import Any, Optional, TypedDict

logger = logging.getLogger(__name__)

# Per-task AsyncSession for the nodes that need DB access. See _db_of for why
# this is not on the graph state.
_SESSION: ContextVar = ContextVar("review_pipeline_session", default=None)


class ReviewPipelineState(TypedDict, total=False):
    """Everything the graph carries between nodes.

    `total=False` so a node returning a partial dict only overwrites the keys it
    actually changed — which is how LangGraph merges node results.
    """

    tenant_id: str
    channel_id: str
    review_id: str
    rating: int
    review_text: Optional[str]
    reviewer_name: Optional[str]
    model: Optional[str]
    tenant_subcategories: list[str]

    # Filled in by `classify`.
    classification: Any
    classification_error: str

    # Filled in by `assign_ticket`.
    issue_id: str
    ticket_number: Optional[str]

    # Filled in by `handoff`.
    handoff_code: Optional[str]
    handoff_eligible: bool

    # Set by whichever node actually persisted.
    issue_created: bool
    skipped_reason: str


async def _classify(state: ReviewPipelineState) -> ReviewPipelineState:
    from .classifier import classify_review

    try:
        result = await classify_review(
            state.get("review_text"),
            state.get("rating", 0),
            state.get("reviewer_name"),
            model=state.get("model"),
            tenant_subcategories=state.get("tenant_subcategories") or [],
            channel_id=state.get("channel_id"),
            tenant_id=state.get("tenant_id"),
        )
    except Exception as e:
        # The whole point: degrade, do not propagate. The caller already treats a
        # missing issue row as "retry next poll".
        logger.warning(
            "graph: classify failed for %s: %s: %s",
            state.get("review_id"), type(e).__name__, str(e)[:200],
        )
        return {
            "classification_error": f"{type(e).__name__}: {str(e)[:200]}",
            "classification": None,
        }
    return {"classification": result, "classification_error": ""}


async def _assign_ticket(state: ReviewPipelineState) -> ReviewPipelineState:
    """Node: persist the issue and mint its ticket number."""
    from .tickets import persist_issue

    classification = state.get("classification")
    if classification is None:
        return {"skipped_reason": "no classification"}

    try:
        issue = await persist_issue(
            _db_of(state),
            tenant_id=state["tenant_id"],
            channel_id=state["channel_id"],
            review_id=state["review_id"],
            rating=state.get("rating", 0),
            classification=classification,
            reviewer_name=state.get("reviewer_name"),
            review_text=state.get("review_text"),
        )
    except Exception as e:
        logger.warning(
            "graph: ticket assignment failed for %s: %s: %s",
            state.get("review_id"), type(e).__name__, str(e)[:200],
        )
        return {"skipped_reason": f"persist failed: {str(e)[:200]}"}

    if issue is None:
        return {"issue_created": False, "skipped_reason": "not stored"}
    return {
        "issue_created": True,
        "issue_id": issue.id,
        "ticket_number": issue.ticket_number,
    }


async def _handoff(state: ReviewPipelineState) -> ReviewPipelineState:
    """Node: decide whether to invite a private conversation, and mint a code."""
    from sqlalchemy import select

    from .classification import needs_review_handoff
    from .handoff import ensure_handoff_code
    from ..channels.models import ReviewIssue

    classification = state.get("classification")
    if classification is None:
        return {"handoff_eligible": False}

    eligible = needs_review_handoff(classification)
    if not eligible:
        return {"handoff_eligible": False}

    db = _db_of(state)
    try:
        issue = (
            await db.execute(
                select(ReviewIssue).where(ReviewIssue.id == state["issue_id"])
            )
        ).scalar_one_or_none()
        code = (
            await ensure_handoff_code(
                db, tenant_id=state["tenant_id"], issue=issue
            )
            if issue is not None
            else None
        )
    except Exception as e:
        # A missing code only costs the customer a generic reply; never fatal.
        logger.warning(
            "graph: handoff code mint failed for %s: %s: %s",
            state.get("issue_id"), type(e).__name__, str(e)[:200],
        )
        return {"handoff_eligible": True}

    return {"handoff_eligible": True, "handoff_code": code}


def _route_after_classify(state: ReviewPipelineState) -> str:
    return "ticket" if state.get("classification") is not None else "end"


def _route_after_ticket(state: ReviewPipelineState) -> str:
    return "handoff" if state.get("issue_created") else "end"


def _db_of(state: ReviewPipelineState):
    """The session is carried in a ContextVar, NOT on the state.

    First attempt put it on the state as `_db`, and the graph silently dropped
    it: LangGraph filters state to the keys declared in the TypedDict, so an
    undeclared key vanishes before any node sees it. Declaring it would work,
    but a live AsyncSession in the state would make it unserializable, which
    defeats resumability — the main reason for a graph here.

    A ContextVar keeps the state checkpointable while still giving nodes the
    session. Safe because the reviews worker runs one review per asyncio task,
    and each task gets its own context copy.
    """
    db = _SESSION.get()
    if db is None:
        raise RuntimeError(
            "no AsyncSession bound; run this through run_review_pipeline()"
        )
    return db


def build_graph():
    """Build the review pipeline graph.

    Raises ImportError with an actionable message if langgraph is missing,
    rather than an opaque failure deep inside the reviews worker.
    """
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            "langgraph is required for the review pipeline graph. "
            "Install it with: uv pip install 'langgraph>=1.0'"
        ) from e

    g = StateGraph(ReviewPipelineState)
    g.add_node("classify", _classify)
    g.add_node("ticket", _assign_ticket)
    g.add_node("handoff", _handoff)

    g.add_edge(START, "classify")
    g.add_conditional_edges(
        "classify", _route_after_classify, {"ticket": "ticket", "end": END}
    )
    g.add_conditional_edges(
        "ticket", _route_after_ticket, {"handoff": "handoff", "end": END}
    )
    g.add_edge("handoff", END)
    return g.compile()


_GRAPH = None


def get_graph():
    """Cached compiled graph. Building it is cheap but not free, and the worker
    calls this per review."""
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH


async def run_review_pipeline(db, **state) -> ReviewPipelineState:
    """Entry point: run one review through classify -> ticket -> handoff.

    `db` is bound to the task's ContextVar rather than put on the state, so the
    state stays serializable (see `_db_of`). The caller keeps ownership of the
    session; this never commits or closes it beyond what the nodes already do.

    Falls back to running the same nodes sequentially when langgraph is not
    importable. That is deliberate: without it, deploying an image that predates
    the langgraph dependency would make the reviews worker fail every
    classification, and because failures are swallowed per-review ("retry next
    poll") that degradation would be completely silent.
    """
    token = _SESSION.set(db)
    try:
        try:
            graph = get_graph()
        except ImportError as e:
            logger.warning(
                "langgraph unavailable (%s) — running review pipeline inline",
                str(e)[:120],
            )
            return await _run_inline(db, dict(state))
        return await graph.ainvoke(dict(state))  # type: ignore[return-value]
    finally:
        _SESSION.reset(token)


async def _run_inline(db, state: ReviewPipelineState) -> ReviewPipelineState:
    """Same nodes, same edges, no graph. The conditional routing is reproduced
    explicitly so behaviour is identical with and without langgraph.

    Takes the session and binds the ContextVar itself rather than assuming a
    caller already did: when this ran only under `run_review_pipeline` the
    binding was implicit, and calling it directly failed with "no AsyncSession
    bound" — a trap for the next person.
    """
    token = _SESSION.set(db)
    try:
        state.update(await _classify(state))
        if _route_after_classify(state) != "ticket":
            return state
        state.update(await _assign_ticket(state))
        if _route_after_ticket(state) != "handoff":
            return state
        state.update(await _handoff(state))
        return state
    finally:
        _SESSION.reset(token)
"""AI tools that the review engine agent can call to retrieve business context.

Single source of truth: TOOL_DEFINITIONS is GENERATED from the function
signatures below (via @tool + Annotated descriptions). The schema the model
sees can never drift from the Python signature it calls.
"""
import inspect
import logging
from typing import Annotated, get_args, get_origin, get_type_hints

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Params injected by the engine — never exposed to the model.
INJECTED = {"tenant_id", "db", "databank_id"}

_TYPE_MAP = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array", dict: "object"}

_TOOL_REGISTRY: dict[str, dict] = {}


def tool(name: str, description: str):
    """Register a function as an agent-callable tool."""
    def wrapper(fn):
        _TOOL_REGISTRY[name] = {"fn": fn, "description": description}
        return fn
    return wrapper


def _schema_for(name: str, fn) -> dict:
    sig = inspect.signature(fn)
    try:
        hints = get_type_hints(fn, include_extras=True)
    except Exception:
        hints = {}
    parameters: dict[str, dict] = {}
    required: list[str] = []
    for pname, param in sig.parameters.items():
        if pname in INJECTED:
            continue
        hint = hints.get(pname, str)
        desc = ""
        base = hint
        if get_origin(hint) is Annotated:
            base, *meta = get_args(hint)
            desc = next((m for m in meta if isinstance(m, str)), "")
        # Unwrap Optional[X] / X | None
        origin = get_origin(base)
        args = [a for a in get_args(base) if a is not type(None)]
        if origin is not None and args:
            base = args[0]
        ptype = _TYPE_MAP.get(base, "string")
        entry: dict = {"type": ptype}
        if desc:
            entry["description"] = desc
        parameters[pname] = entry
        if param.default is inspect.Parameter.empty:
            required.append(pname)
    return {"name": name, "description": _TOOL_REGISTRY[name]["description"],
            "parameters": {"type": "object", "properties": parameters, "required": required}}


def _build_definitions() -> list[dict]:
    return [_schema_for(name, meta["fn"]) for name, meta in _TOOL_REGISTRY.items()]


async def _rag_search(
    tenant_id: str,
    query: str,
    db: AsyncSession,
    top_k: int = 5,
    databank_id: str | None = None,
) -> list[dict]:
    """Search the tenant's Databank via RAG hybrid search.

    Prefers the channel's linked databank; falls back to the tenant's first.
    """
    try:
        from ..rag.service import search as rag_search
        from ..rag.schemas import SearchRequest

        if not databank_id:
            # Fall back to the tenant's primary databank
            from sqlalchemy import select
            from ..rag.models import Databank

            result = await db.execute(
                select(Databank.id).where(Databank.user_id == tenant_id).limit(1)
            )
            databank_id = result.scalar_one_or_none()
        if not databank_id:
            return []

        results, _degraded = await rag_search(
            databank_id,
            SearchRequest(query=query[:500], top_k=top_k),
            None,  # type: ignore[arg-type]
            db,
        )
        return results or []
    except Exception as e:
        logger.warning("RAG search failed: %s", e)
        return []


@tool(name="search_products",
      description="Search products, services, or items from the business Databank. Use when the review mentions a specific product, or the customer asks for alternatives or recommendations.")
async def search_products(
    query: Annotated[str, "Search keywords — product name, complaint topic, or feature (e.g. 'pizza', 'billing', 'laptop')"],
    tenant_id: str,
    category: Annotated[str | None, "Optional category filter (e.g. 'products', 'services')"] = None,
    db: AsyncSession | None = None,
    databank_id: str | None = None,
    limit: Annotated[int, "Max results (default 5)"] = 5,
) -> dict:
    """Search products/services by keyword from the business Databank."""
    if not db:
        return {"results": [], "count": 0, "tool_name": "search_products"}

    results = await _rag_search(tenant_id, query, db, top_k=limit, databank_id=databank_id)
    return {
        "results": [r.get("content", "") for r in results],
        "count": len(results),
        "tool_name": "search_products",
    }


@tool(name="get_product",
      description="Get a specific product/service by its ID. Use when you have a known product ID from the review or a previous tool call.")
async def get_product(
    product_id: Annotated[str, "The product ID to look up"],
    tenant_id: str,
    db: AsyncSession | None = None,
    databank_id: str | None = None,
) -> dict:
    """Get a specific product/row by its ID from the Databank."""
    if not db:
        return {"results": [], "count": 0, "tool_name": "get_product"}

    results = await _rag_search(tenant_id, product_id, db, top_k=1, databank_id=databank_id)
    return {
        "results": [r.get("content", "") for r in results],
        "count": len(results),
        "tool_name": "get_product",
    }


@tool(name="find_offers",
      description="Find active promotions, discounts, or deals from the Databank. ONLY use when the customer explicitly asks for compensation, a discount, or a deal — never for serious complaints otherwise.")
async def find_offers(
    tenant_id: str,
    category: Annotated[str | None, "Optional category to filter offers"] = None,
    product_id: Annotated[str | None, "Optional specific product ID"] = None,
    db: AsyncSession | None = None,
    databank_id: str | None = None,
    limit: Annotated[int, "Max results (default 5)"] = 5,
) -> dict:
    """Find active promotions, discounts, or deals from the Databank."""
    if not db:
        return {"results": [], "count": 0, "tool_name": "find_offers"}

    query = "offers promotions discounts deals"
    if category:
        query += f" {category}"
    if product_id:
        query += f" {product_id}"

    results = await _rag_search(tenant_id, query, db, top_k=limit, databank_id=databank_id)
    return {
        "results": [r.get("content", "") for r in results],
        "count": len(results),
        "tool_name": "find_offers",
    }


@tool(name="get_business_profile",
      description="Get business information (name, hours, location, policies) from the Databank. Use when the review asks about business details.")
async def get_business_profile(
    tenant_id: str,
    db: AsyncSession | None = None,
    databank_id: str | None = None,
) -> dict:
    """Get business information from the Databank."""
    if not db:
        return {"results": [], "count": 0, "tool_name": "get_business_profile"}

    results = await _rag_search(tenant_id, "business profile name hours location policies contact", db, top_k=5, databank_id=databank_id)
    return {
        "results": [r.get("content", "") for r in results],
        "count": len(results),
        "tool_name": "get_business_profile",
    }


# ── Generated registry (import-time, from signatures) ────

TOOL_DEFINITIONS: list[dict] = _build_definitions()

TOOL_MAP: dict[str, object] = {name: meta["fn"] for name, meta in _TOOL_REGISTRY.items()}

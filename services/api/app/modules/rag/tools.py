"""Agentic RAG tools: the 6 retrieval instruments the answer agent can call.

Every tool returns JSON-serializable observations shaped as passages:
  {"content": str, "origin": "snapshot:<filename>" | "live:<db>/<table>", "score": float}

Live-database rows exist only inside the request: tools return row *content*
for the prompt, but nothing here writes tenant rows to our tables, disk,
logs, or Kafka. Audit-worthy metadata (SQL text, row counts) is returned
to the agent for citation, never the other way into storage.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..llm.providers.base import ToolDefinition, ToolParameter

logger = logging.getLogger(__name__)

MAX_OBSERVATION_CHARS = 4000


def tool_definitions() -> list[ToolDefinition]:
    s = lambda desc: ToolParameter(type="string", description=desc)  # noqa: E731
    i = lambda desc: ToolParameter(type="integer", description=desc)  # noqa: E731
    return [
        ToolDefinition(
            name="vector_search",
            description=(
                "Semantic search over the databank's embedded documents. "
                "Best for meaning-level questions, paraphrases, and 'how/why' queries."
            ),
            parameters={"query": s("The search query, rephrased for retrieval if helpful."),
                        "top_k": i("How many chunks to return (1-10).")},
            required=["query"],
        ),
        ToolDefinition(
            name="keyword_search",
            description=(
                "Exact-term full-text search over documents. Best for SKUs, names, "
                "error codes, IDs, and rare words that semantic search fumbles."
            ),
            parameters={"query": s("Exact terms to match."),
                        "top_k": i("How many chunks to return (1-10).")},
            required=["query"],
        ),
        ToolDefinition(
            name="read_around",
            description=(
                "Read the chunks surrounding a previous hit to recover cut-off context. "
                "Use when a passage looks like a cliffhanger."
            ),
            parameters={"chunk_id": s("The chunk id from an earlier hit."),
                        "window": i("Chunks to each side (1-3).")},
            required=["chunk_id"],
        ),
        ToolDefinition(
            name="db_schema",
            description=(
                "List the live database sources on this databank and their tables. "
                "Call this before db_query when you don't know the schema."
            ),
            parameters={},
            required=[],
        ),
        ToolDefinition(
            name="db_query",
            description=(
                "Run a read-only SELECT/WITH query against a connected live database. "
                "Use for questions about current rows (orders, users, inventory). "
                "Rows come back live — cite them as live data."
            ),
            parameters={"source_id": s("Database source id from db_schema."),
                        "sql": s("Single SELECT or WITH statement."),
                        "limit": i("Max rows (1-50).")},
            required=["source_id", "sql"],
        ),
        ToolDefinition(
            name="get_document",
            description=(
                "Fetch a full document's text when chunks aren't enough "
                "(long policies, manuals, price lists)."
            ),
            parameters={"document_id": s("The document id from an earlier hit."),
                        "max_chars": i("Max characters (500-12000).")},
            required=["document_id"],
        ),
    ]


class ToolContext:
    """Per-request state shared by all tools (request-scoped DB session)."""

    def __init__(self, databank_id: str, user_id: str, db: AsyncSession):
        self.databank_id = databank_id
        self.user_id = user_id
        self.db = db
        self._doc_names: dict[str, str] | None = None

    async def doc_names(self) -> dict[str, str]:
        if self._doc_names is None:
            from .models import Document

            result = await self.db.execute(
                text("SELECT id, filename FROM documents WHERE databank_id = :b"),
                {"b": self.databank_id},
            )
            self._doc_names = {str(r[0]): r[1] for r in result.fetchall()}
        return self._doc_names


def _clip(text: str, limit: int = MAX_OBSERVATION_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n…[clipped {len(text) - limit} chars]"


async def vector_search(ctx: ToolContext, query: str, top_k: int = 5) -> dict:
    from .embeddings import get_embedding_provider
    from .search import hybrid_search

    top_k = max(1, min(int(top_k or 5), 10))
    try:
        provider = await get_embedding_provider()
        vectors = await provider.embed([query])
        query_vector = vectors[0]
    except Exception:
        return {"passages": [], "notice": "vector_unavailable"}

    results = await hybrid_search(
        databank_id=ctx.databank_id, query_vector=query_vector,
        query_text=query, top_k=top_k, db=ctx.db,
    )
    names = await ctx.doc_names()
    return {
        "passages": [
            {"content": _clip(r["content"], 1200),
             "origin": f"snapshot:{names.get(str(r['document_id']), str(r['document_id']))}",
             "score": round(r["score"], 4),
             "chunk_id": str(r.get("id", "")),
             "document_id": str(r["document_id"])}
            for r in results
        ]
    }


async def keyword_search(ctx: ToolContext, query: str, top_k: int = 5) -> dict:
    top_k = max(1, min(int(top_k or 5), 10))
    rows = await ctx.db.execute(
        text("""
            SELECT id, content, document_id,
                   ts_rank(to_tsvector('english', content),
                           plainto_tsquery('english', :q)) AS score
            FROM document_chunks
            WHERE databank_id = :b
              AND to_tsvector('english', content) @@ plainto_tsquery('english', :q)
            ORDER BY score DESC
            LIMIT :limit
        """),
        {"q": query, "b": ctx.databank_id, "limit": top_k},
    )
    names = await ctx.doc_names()
    passages = [
        {"content": _clip(r.content, 1200),
         "origin": f"snapshot:{names.get(str(r.document_id), str(r.document_id))}",
         "score": round(float(r.score or 0), 4),
         "chunk_id": str(r.id),
         "document_id": str(r.document_id)}
        for r in rows.fetchall()
    ]
    return {"passages": passages}


async def read_around(ctx: ToolContext, chunk_id: str, window: int = 1) -> dict:
    window = max(1, min(int(window or 1), 3))
    anchor = await ctx.db.execute(
        text("SELECT document_id, seq FROM document_chunks WHERE id = :c AND databank_id = :b"),
        {"c": chunk_id, "b": ctx.databank_id},
    )
    row = anchor.first()
    if not row:
        return {"passages": [], "notice": "chunk_not_found"}
    doc_id, seq = str(row[0]), int(row[1])
    neighbors = await ctx.db.execute(
        text("""
            SELECT content FROM document_chunks
            WHERE document_id = :d AND seq BETWEEN :lo AND :hi
            ORDER BY seq
        """),
        {"d": doc_id, "lo": seq - window, "hi": seq + window},
    )
    names = await ctx.doc_names()
    texts = [r[0] for r in neighbors.fetchall()]
    return {
        "passages": [{
            "content": _clip("\n".join(texts), 3000),
            "origin": f"snapshot:{names.get(doc_id, doc_id)}",
            "score": 1.0,
            "document_id": doc_id,
        }]
    }


async def db_schema(ctx: ToolContext) -> dict:
    from .service import _config_from_source, list_sources
    from .connectors import list_tables

    bank_row = await ctx.db.execute(
        text("SELECT id FROM databanks WHERE id = :b AND user_id = :u"),
        {"b": ctx.databank_id, "u": ctx.user_id},
    )
    if not bank_row.first():
        return {"sources": [], "notice": "databank_not_found"}

    class _User:
        id = ctx.user_id

    sources = await list_sources(ctx.databank_id, _User(), ctx.db)
    out = []
    for s in sources:
        try:
            from .service import _config_from_source

            tables = await list_tables(_config_from_source(s))
            out.append({
                "source_id": s.id, "name": s.name, "db_type": s.db_type,
                "database": s.database, "tables": [t["name"] for t in tables],
            })
        except ValueError as e:
            out.append({"source_id": s.id, "name": s.name, "error": str(e)[:200]})
    return {"sources": out}


async def db_query(ctx: ToolContext, source_id: str, sql: str, limit: int = 50) -> dict:
    from .connectors import run_query
    from .service import _config_from_source, get_source

    limit = max(1, min(int(limit or 50), 50))

    class _User:
        id = ctx.user_id

    source = await get_source(source_id, _User(), ctx.db)
    if not source or source.databank_id != ctx.databank_id:
        return {"passages": [], "notice": "source_not_found"}
    try:
        result = await run_query(_config_from_source(source), sql, limit)
    except ValueError as e:
        return {"passages": [], "notice": f"query_rejected: {e}"}

    stamped = datetime.now(timezone.utc).strftime("%H:%M:%S")
    header = f"Live rows from {source.db_type}://{source.database} at {stamped} UTC"
    lines = [" | ".join(result["columns"])]
    lines += [" | ".join("" if v is None else str(v) for v in row) for row in result["rows"]]
    return {
        "passages": [{
            "content": _clip(header + "\n" + "\n".join(lines), 3500),
            "origin": f"live:{source.database}",
            "score": 1.0,
        }],
        "row_count": result["row_count"],
        "truncated": result["truncated"],
    }


async def get_document(ctx: ToolContext, document_id: str, max_chars: int = 6000) -> dict:
    max_chars = max(500, min(int(max_chars or 6000), 12000))
    rows = await ctx.db.execute(
        text("""
            SELECT content FROM document_chunks
            WHERE document_id = :d AND databank_id = :b
            ORDER BY seq
        """),
        {"d": document_id, "b": ctx.databank_id},
    )
    texts = [r[0] for r in rows.fetchall()]
    if not texts:
        return {"passages": [], "notice": "document_empty"}
    names = await ctx.doc_names()
    return {
        "passages": [{
            "content": _clip("\n".join(texts), max_chars),
            "origin": f"snapshot:{names.get(document_id, document_id)}",
            "score": 1.0,
            "document_id": document_id,
        }]
    }


TOOL_RUNNERS = {
    "vector_search": vector_search,
    "keyword_search": keyword_search,
    "read_around": read_around,
    "db_schema": db_schema,
    "db_query": db_query,
    "get_document": get_document,
}

"""One knowledge layer for every Sayvors brain.

Each surface (the WhatsApp/Instagram assistant, Google review replies, Ask
Sayvors) used to assemble its own prompt context by hand. That is how the
review engine once answered "we don't have details about other branches"
while the WhatsApp assistant listed them: every surface could silently
forget a knowledge source, and nothing logged which sources were present.

This module is the single place that knows WHICH sources exist and HOW to
fetch them; a surface only declares what it includes. Policy stays where it
belongs: persona, tickets, leads, conversation history and voice live with
the WhatsApp consumer; strategies, the validator and the scorecard live with
the review engine; page context and navigation live with Ask Sayvors.
Knowledge is shared; judgement is not.

Every source is best-effort: a failing or empty source is skipped with a
warning and never costs the reply. ``sizes`` is the audit trail — one log
line per call answers "why didn't it know X?".
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

IDENTITY = "identity"
FACTS = "facts"
GROUNDING = "grounding"
CATALOG = "catalog"
MEMORY = "memory"

ALL_SOURCES = (IDENTITY, FACTS, GROUNDING, CATALOG, MEMORY)

# Per-surface defaults. Review replies deliberately exclude catalog and
# memory: a public Google reply must not commit to prices that can go stale,
# and approved memory is private conversation history — quoting it in a
# public reply would leak it.
SURFACE_SOURCES: dict[str, tuple[str, ...]] = {
    "whatsapp": (IDENTITY, FACTS, GROUNDING, CATALOG, MEMORY),
    "reviews": (FACTS,),
    "dashboard": (IDENTITY, FACTS, GROUNDING, CATALOG, MEMORY),
}

# Review replies always carry the operational slices: a reply may need the
# branch list or the hours even when the review text never mentions them.
REVIEW_FACT_TOPICS = ("locations", "hours", "contact", "website", "services")


@dataclass
class ReplyContext:
    blocks: list[str] = field(default_factory=list)
    sizes: dict[str, int] = field(default_factory=dict)

    def render(self) -> str:
        return "\n\n".join(b for b in self.blocks if b)


async def build_reply_context(
    db,
    *,
    tenant_id: str,
    surface: str,
    query: str | None = None,
    channel_id: str | None = None,
    include: tuple[str, ...] | None = None,
    facts_topics: tuple[str, ...] | None = None,
    facts_tool_framing: bool = False,
    allow_catalog_image: bool = False,
    memory_enabled: bool = True,
) -> ReplyContext:
    """Assemble the shared knowledge blocks for one reply.

    ``facts_topics`` overrides query-based topic detection (the review engine
    needs the operational slices unconditionally); ``None`` detects topics
    from ``query`` so a casual message pays only for what it asks about.
    ``facts_tool_framing`` renders the detected slices as if the model had
    called ``get_business_facts`` itself — the WhatsApp assistant's existing
    presentation, which tells the model to answer those slices directly.
    """
    sources = include if include is not None else SURFACE_SOURCES.get(surface, ())
    ctx = ReplyContext()

    if IDENTITY in sources:
        block = ""
        try:
            from ..profile.business_profile import prompt_block

            block = (await prompt_block(tenant_id, db)) or ""
        except Exception as e:  # noqa: BLE001 - never cost the reply
            logger.warning("context identity skipped surface=%s: %s", surface, e)
        if block:
            ctx.blocks.append(block)
            ctx.sizes[IDENTITY] = len(block)

    if FACTS in sources:
        block = ""
        try:
            from ..profile.facts_store import get_facts, render_core
            from ..profile.facts_tool import detect_topics, render_topic

            facts = await get_facts(db, tenant_id)
            parts = [render_core(facts)]
            topics = list(facts_topics) if facts_topics else detect_topics(query)
            if facts_tool_framing and topics:
                slices = []
                for topic in topics:
                    slice_text = render_topic(facts, topic)
                    if slice_text:
                        slices.append(f'[get_business_facts(topic="{topic}")]\n{slice_text}')
                if slices:
                    parts.append(
                        "BUSINESS FACTS TOOL RESULTS (answer these directly):\n"
                        + "\n\n".join(slices)
                    )
            else:
                for topic in topics:
                    parts.append(render_topic(facts, topic))
            block = "\n\n".join(p for p in parts if p)
        except Exception as e:  # noqa: BLE001 - never cost the reply
            logger.warning("context facts skipped surface=%s: %s", surface, e)
        if block:
            ctx.blocks.append(block)
            ctx.sizes[FACTS] = len(block)

    if GROUNDING in sources and query:
        block = ""
        try:
            from ..rag.grounding import reply_block

            block = await reply_block(
                db, tenant_id=tenant_id, channel_id=channel_id, query=query
            )
        except Exception as e:  # noqa: BLE001 - never cost the reply
            logger.warning("context grounding skipped surface=%s: %s", surface, e)
        if block:
            ctx.blocks.append(block)
            ctx.sizes[GROUNDING] = len(block)

    if CATALOG in sources:
        block = ""
        try:
            from ..catalog.service import catalog_block

            block = await catalog_block(
                db,
                tenant_id=tenant_id,
                query=query,
                allow_image=allow_catalog_image,
            )
        except Exception as e:  # noqa: BLE001 - never cost the reply
            logger.warning("context catalog skipped surface=%s: %s", surface, e)
        if block:
            ctx.blocks.append(block)
            ctx.sizes[CATALOG] = len(block)

    if MEMORY in sources:
        block = ""
        try:
            from ..memory.service import reply_block as memory_reply_block

            block = await memory_reply_block(
                db, tenant_id=tenant_id, query=query, enabled=memory_enabled
            )
        except Exception as e:  # noqa: BLE001 - never cost the reply
            logger.warning("context memory skipped surface=%s: %s", surface, e)
        if block:
            ctx.blocks.append(block)
            ctx.sizes[MEMORY] = len(block)

    return ctx

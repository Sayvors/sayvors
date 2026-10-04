"""Business profile card: LLM-distilled tenant facts from the databank.

Flow: a successful ingest job (app.modules.rag.jobs) or the manual
"Regenerate" button asks the tenant's enabled LLM to distill sampled
databank chunks + the owner's profile answers into five fields (summary,
domain, offers, not-offered/policies, audience & languages). The card is
shown on the Databank screen, editable, and injected into every AI prompt
(see prompt_block + get_business_context) so the assistant can answer
"what can you do for me?" without crawling the databank.

User edits always win: once source == "edited" the auto hook never
touches the row, and even a forced regeneration only fills EMPTY fields.
"""

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import BusinessProfile

logger = logging.getLogger(__name__)

PROFILE_FIELDS = (
    "summary",
    "domain",
    "products_services",
    "not_offered_and_policies",
    "audience_languages",
)

# Auto-refresh debounce: uploading 10 files fires 10 completed jobs — only
# the first should trigger a regeneration within this window.
AUTO_REFRESH_COOLDOWN = timedelta(seconds=60)

# Sampling caps — a full databank would blow the context window for no gain.
_MAX_CHUNKS = 80
_MAX_MATERIAL_CHARS = 12_000

_GENERATE_SYSTEM_PROMPT = """You distill a business's knowledge base into a short business profile card.
Return STRICT JSON with exactly these keys and no others:
{"summary": "...", "domain": "...", "products_services": "...", "not_offered_and_policies": "...", "audience_languages": "..."}
Rules:
- summary: 2-3 sentences on what the business does and is known for.
- domain: the industry/category in 1-4 words (e.g. "Food & Restaurant").
- products_services: what the business sells or offers — specific items/services, comma-separated.
- not_offered_and_policies: things it does NOT offer plus policies worth knowing (halal, refunds, delivery radius). Empty string if unknown.
- audience_languages: who the customers are and which languages they use, one short line.
- Use ONLY the provided material. Never invent prices, hours, stock or policies.
- Plain text values, no markdown, no quotes around the JSON. At most 60 words per value."""


def _iso(dt):
    return dt.isoformat() if dt else None


def _as_aware(dt):
    """SQLite returns naive datetimes; Postgres returns aware. Cooldown math
    needs a single convention — treat naive as UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def serialize_profile(row: BusinessProfile) -> dict:

    return {
        "id": row.id,
        "summary": row.summary,
        "domain": row.domain,
        "products_services": row.products_services,
        "not_offered_and_policies": row.not_offered_and_policies,
        "audience_languages": row.audience_languages,
        "source": row.source,
        "generated_at": _iso(row.generated_at),
        "updated_at": _iso(row.updated_at),
    }


async def get_business_profile_row(user_id: str, db: AsyncSession) -> BusinessProfile | None:
    return (
        await db.execute(
            select(BusinessProfile).where(BusinessProfile.user_id == user_id)
        )
    ).scalar_one_or_none()


async def save_business_profile(user_id: str, fields: dict, db: AsyncSession) -> dict:
    """User saved the card from the UI — their text wins, source becomes "edited"."""
    patch = {k: (v or "").strip() or None for k, v in fields.items() if k in PROFILE_FIELDS}
    if not any(patch.values()):
        # An all-empty save would create an "edited" (i.e. generation-proof)
        # row with nothing in it — reject instead.
        raise ValueError("No profile fields to save")

    row = await get_business_profile_row(user_id, db)
    if row is None:
        row = BusinessProfile(user_id=user_id)
        db.add(row)
    for field, value in patch.items():
        setattr(row, field, value)
    row.source = "edited"
    await db.commit()
    await db.refresh(row)
    return serialize_profile(row)


async def generate_business_profile(
    user_id: str, db: AsyncSession, *, force: bool = False
) -> dict:
    """(Re)generate the card from the databank + owner profile answers.

    Raises ValueError when there is nothing to generate from or no model is
    enabled — callers turn that into a 4xx; the auto hook just logs it.

    force=False (ingest hook): refresh "auto" cards, never touch "edited".
    force=True (manual button): an edited card keeps its text — only empty
    fields are filled, so user edits survive regeneration.
    """
    row = await get_business_profile_row(user_id, db)
    now = datetime.now(timezone.utc)
    if row is not None and row.source == "edited" and not force:
        return serialize_profile(row)
    if (
        row is not None
        and row.source == "auto"
        and not force
        and _as_aware(row.generated_at) is not None
        and now - _as_aware(row.generated_at) < AUTO_REFRESH_COOLDOWN
    ):
        # Fresh enough — another job in the same upload batch just made it.
        return serialize_profile(row)

    material = await _collect_material(user_id, db)
    if not material:
        raise ValueError(
            "Nothing to generate from yet — upload documents to your databank "
            "or fill in your business details first."
        )

    fields = await _ask_llm(material, user_id, db)

    if row is None:
        row = BusinessProfile(user_id=user_id)
        db.add(row)
    for field in PROFILE_FIELDS:
        value = (fields.get(field) or "").strip()
        if not value:
            continue
        if row.source == "edited" and getattr(row, field):
            continue  # user text wins, even over a forced regeneration
        setattr(row, field, value[:2000])
    # source stays as-is: "auto" rows (and new rows, via the model default)
    # remain "auto"; an "edited" row keeps its badge even when regeneration
    # only filled empty fields.
    row.generated_at = now
    await db.commit()
    await db.refresh(row)
    return serialize_profile(row)


async def _collect_material(user_id: str, db: AsyncSession) -> str:
    """Databank sample + file names + the owner's profile answers."""
    from ..rag.models import Databank, Document, DocumentChunk
    from ..users.models import User

    parts: list[str] = []

    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        return ""
    facts = {
        "Business name": user.business_name,
        "Business type": user.business_type,
        "Sells": user.business_sells,
        "Does not sell": user.business_doesnt_sell,
        "About": user.business_description,
    }
    fact_lines = [f"- {k}: {v}" for k, v in facts.items() if (v or "").strip()]
    if fact_lines:
        parts.append("Owner-configured business details:\n" + "\n".join(fact_lines))

    files = (
        (
            await db.execute(
                select(Document.filename)
                .where(Document.user_id == user_id)
                .order_by(Document.created_at.desc())
                .limit(30)
            )
        )
        .scalars()
        .all()
    )
    if files:
        parts.append("Files in the knowledge base: " + ", ".join(f[:80] for f in files))

    chunks = (
        (
            await db.execute(
                select(DocumentChunk.content)
                .join(Databank, Databank.id == DocumentChunk.databank_id)
                .where(Databank.user_id == user_id)
                .order_by(DocumentChunk.document_id, DocumentChunk.seq)
                .limit(_MAX_CHUNKS)
            )
        )
        .scalars()
        .all()
    )
    if chunks:
        parts.append("Sampled knowledge-base content:\n" + "\n---\n".join(chunks))

    material = "\n\n".join(parts)
    return material[:_MAX_MATERIAL_CHARS]


async def _ask_llm(material: str, user_id: str, db: AsyncSession) -> dict:
    from ..llm.providers.base import LLMMessage, LLMRequest
    from ..llm.providers.registry import get_provider_for_model
    from ..llm.service import _resolve_model, resolve_tenant_model

    model_id = await resolve_tenant_model(db)  # ValueError when nothing enabled
    api_model, _provider = _resolve_model(model_id)
    provider = get_provider_for_model(model_id)

    resp = await provider.complete(
        LLMRequest(
            model=api_model,
            messages=[LLMMessage(role="user", content=material)],
            system_prompt=_GENERATE_SYSTEM_PROMPT,
            temperature=0.3,
            max_tokens=600,
            stream=False,
            tenant_id=user_id,
            model_id=model_id,
            purpose="databank.business_profile",
        )
    )
    return _parse_profile_json(resp.content or "")


def _parse_profile_json(text: str) -> dict:
    """Extract the five fields from the model's reply — models love to wrap
    JSON in prose or code fences, so slice the outermost braces first."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("Model did not return a JSON profile")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        raise ValueError("Model returned malformed JSON profile")
    if not isinstance(data, dict):
        raise ValueError("Model returned malformed JSON profile")
    return {k: str(v) for k, v in data.items() if k in PROFILE_FIELDS}


async def prompt_block(user_id: str | None, db) -> str:
    """Prompt-ready card text for AI system prompts. Never raises and never
    poisons the caller's session (savepoint-isolated) — AI paths must
    survive a missing table/row exactly like get_business_context."""
    if not user_id:
        return ""
    try:
        async with db.begin_nested():
            row = await get_business_profile_row(user_id, db)
    except Exception:
        return ""
    return _render_block(row)


def _render_block(row: BusinessProfile | None) -> str:
    if row is None:
        return ""
    lines = [
        "Business profile (distilled from this business's knowledge base — "
        "treat as ground truth):"
    ]
    if (row.summary or "").strip():
        lines.append(f"- Summary: {row.summary.strip()[:700]}")
    if (row.domain or "").strip():
        lines.append(f"- Domain: {row.domain.strip()[:200]}")
    if (row.products_services or "").strip():
        lines.append(f"- Offers: {row.products_services.strip()[:800]}")
    if (row.not_offered_and_policies or "").strip():
        lines.append(
            f"- Does NOT offer / policies: {row.not_offered_and_policies.strip()[:500]}"
        )
    if (row.audience_languages or "").strip():
        lines.append(f"- Audience & languages: {row.audience_languages.strip()[:300]}")
    return "\n".join(lines) if len(lines) > 1 else ""

"""Business-intake cascade: resolve a vertical, serve its questions, store answers.

The owner picks a vertical, then a sub-focus, then taps chips. Google already
supplies hours/address/phone and a set of boolean attributes; those questions
are tagged ``google`` and never shown, and ``google_partial`` ones are shown
with Google's value for one-tap confirmation.

Answers live in ``tenant_intake_answers`` — a merchant-owned source, never in
the rebuildable ``TenantFacts`` cache.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..verticals import (
    VERTICALS,
    google_vertical,
    questions_for,
    resolve_vertical,
)
from .models import TenantIntakeAnswer

logger = logging.getLogger(__name__)

# Question key -> (Google attribute key, label shown when true).
# Only explicitly-true attributes are surfaced: on Google's attributes
# endpoint absence is ambiguous (not set vs. false), and claiming "No" from a
# missing value would put a false fact in front of the customer.
_GOOGLE_ATTRIBUTES: dict[str, tuple[str, str]] = {
    "delivery": ("has_delivery", "Yes, delivery"),
    "takeout": ("has_takeout", "Yes, takeaway"),
    "outdoor_seating": ("has_outdoor_seating", "Yes, outdoor seating"),
    "dine_in": ("has_dine_in", "Yes, dine-in"),
}

_PAYMENT_ATTRIBUTES = {
    "accepts_credit_cards": "Credit card",
    "accepts_debit_cards": "Debit card",
    "accepts_cash_only": "Cash",
}

_ACCESSIBILITY_ATTRIBUTES = {
    "wheelchair_accessible_entrance": "Step-free entrance",
    "wheelchair_accessible_parking": "Accessible parking",
    "wheelchair_accessible_restroom": "Accessible restroom",
    "wheelchair_accessible_seating": "Accessible seating",
}


async def _google_context(db: AsyncSession, tenant_id: str) -> dict[str, Any]:
    """Read already-parsed Google fields locally — no extra API quota spent."""
    try:
        from ..locations.models import LocationProfile

        profiles = (
            await db.execute(
                select(LocationProfile)
                .where(LocationProfile.user_id == tenant_id)
                .order_by(LocationProfile.updated_at.desc())
                .limit(1)
            )
        ).scalars().first()
        if profiles is None:
            return {}
        attributes = profiles.attributes or {}
        categories = profiles.categories or {}
        primary = categories.get("primary") if isinstance(categories, dict) else None
        return {
            "attributes": attributes if isinstance(attributes, dict) else {},
            "categories": categories if isinstance(categories, dict) else {},
            "primary_category": str(primary or "").strip(),
        }
    except Exception as e:  # noqa: BLE001 - facts path must degrade, never fail onboarding
        logger.warning("intake google context failed tenant=%s: %s", tenant_id, e)
        return {}


def _google_value(question_key: str, ctx: dict[str, Any]) -> str | None:
    """A human-readable 'Google says...' value, or None when Google has none."""
    if question_key == "hours":
        # Hours are a structured object; the UI reads them from Locations
        # rather than duplicating them as a chip.
        return None
    attributes = ctx.get("attributes") or {}
    if question_key == "payments":
        labels = [
            label for key, label in _PAYMENT_ATTRIBUTES.items()
            if attributes.get(key) is True
        ]
        return ", ".join(labels) if labels else None
    if question_key == "accessibility":
        labels = [
            label for key, label in _ACCESSIBILITY_ATTRIBUTES.items()
            if attributes.get(key) is True
        ]
        return ", ".join(labels) if labels else None
    mapping = _GOOGLE_ATTRIBUTES.get(question_key)
    if mapping:
        key, label = mapping
        return label if attributes.get(key) is True else None
    return None


async def get_intake(user, db: AsyncSession) -> dict[str, Any]:
    """Build the intake view for the owner, including Google confirmations."""
    tenant_id = str(user.id)
    google = await _google_context(db, tenant_id)
    stored_key = (getattr(user, "vertical_key", None) or "").strip() or None
    stored_label = (getattr(user, "business_type", None) or "").strip() or None
    # The authenticated principal can be a JWT-derived projection that predates
    # these columns. Fall back to the persisted row rather than showing a
    # first-time picker to an owner who already answered.
    if not stored_key and not stored_label:
        try:
            from ..users.models import User

            persisted = await db.get(User, tenant_id)
            if persisted is not None:
                stored_key = (persisted.vertical_key or "").strip() or None
                stored_label = (persisted.business_type or "").strip() or None
        except Exception as e:  # noqa: BLE001
            logger.warning("intake user lookup failed tenant=%s: %s", tenant_id, e)
    vertical_key = resolve_vertical(stored_key) or resolve_vertical(stored_label)
    suggestion_key = google_vertical(google.get("primary_category"))
    suggestion = None
    if suggestion_key and suggestion_key != vertical_key:
        suggestion = {
            "vertical_key": suggestion_key,
            "vertical_label": VERTICALS[suggestion_key].label,
            "google_category": google.get("primary_category"),
        }

    vertical = VERTICALS.get(vertical_key) if vertical_key else None
    sub_focus = (getattr(user, "intake_sub_focus", None) or "").strip() or None
    if vertical and sub_focus not in {f.key for f in vertical.sub_focuses}:
        sub_focus = vertical.sub_focuses[0].key if vertical.sub_focuses else None

    answer_rows = (
        await db.execute(
            select(TenantIntakeAnswer).where(TenantIntakeAnswer.tenant_id == tenant_id)
        )
    ).scalars().all()
    effective_vertical = vertical_key or suggestion_key
    by_key = {r.question_key: r for r in answer_rows if r.vertical_key == effective_vertical}

    questions: list[dict[str, Any]] = []
    if effective_vertical:
        for q in questions_for(effective_vertical, sub_focus):
            row = by_key.get(q.key)
            questions.append({
                "key": q.key,
                "label": q.label,
                "source": q.source,
                "options": list(q.options),
                "multiple": q.multiple,
                "fact_key": q.fact_key,
                "answer": (row.answer or {}) if row else {},
                "skipped": bool(row.skipped) if row else False,
                "google_value": _google_value(q.key, google),
            })

    answered = sum(1 for q in questions if not q["skipped"] and q["answer"])
    skipped = sum(1 for q in questions if q["skipped"])
    return {
        "vertical_key": effective_vertical,
        "vertical_label": VERTICALS[effective_vertical].label if effective_vertical else None,
        "sub_focus": sub_focus,
        "sub_focuses": (
            [{"key": f.key, "label": f.label} for f in vertical.sub_focuses]
            if vertical else []
        ),
        "verticals": [
            {"key": k, "label": v.label} for k, v in VERTICALS.items()
        ],
        "questions": questions,
        "answered": answered,
        "skipped": skipped,
        "total": len(questions),
        "google_suggestion": suggestion,
    }


async def save_intake(user, body, db: AsyncSession) -> dict[str, Any]:
    """Persist the vertical pick and answers, then refresh the facts cache.

    A Google confirmation must never overwrite a merchant answer: the caller
    only stores what the owner explicitly tapped.
    """
    tenant_id = str(user.id)
    requested = (body.vertical_key or "").strip() or None
    vertical_key = resolve_vertical(requested) or resolve_vertical(
        getattr(user, "vertical_key", None)
    ) or resolve_vertical(getattr(user, "business_type", None)) or "other"

    vertical = VERTICALS[vertical_key]
    valid_focuses = {f.key for f in vertical.sub_focuses}
    sub_focus = (body.sub_focus or "").strip() or None
    if sub_focus not in valid_focuses:
        sub_focus = vertical.sub_focuses[0].key if vertical.sub_focuses else None

    user.vertical_key = vertical_key
    user.intake_sub_focus = sub_focus
    user.business_type = vertical.label

    allowed = {q.key for q in questions_for(vertical_key, sub_focus)}
    existing = (
        await db.execute(
            select(TenantIntakeAnswer).where(
                TenantIntakeAnswer.tenant_id == tenant_id,
                TenantIntakeAnswer.vertical_key == vertical_key,
            )
        )
    ).scalars().all()
    by_key = {r.question_key: r for r in existing}

    for item in body.answers:
        if item.question_key not in allowed:
            logger.warning(
                "ignoring unknown intake question %s for tenant %s",
                item.question_key, tenant_id,
            )
            continue
        answer = item.answer or []
        if not isinstance(answer, (list, dict)):
            answer = str(answer)
        row = by_key.get(item.question_key)
        if row is None:
            row = TenantIntakeAnswer(
                tenant_id=tenant_id,
                vertical_key=vertical_key,
                question_key=item.question_key,
            )
            db.add(row)
        row.answer = answer
        row.skipped = bool(item.skipped)
        row.source = item.source if item.source in ("manual", "google_confirmed") else "manual"

    # A vertical change leaves the old rows alone: if the owner switches back,
    # their earlier answers are still there. Only the current vertical is read.
    await db.flush()

    from .facts_store import rebuild_facts

    await rebuild_facts(db, tenant_id, user)
    return await get_intake(user, db)


async def intake_facts(db: AsyncSession, tenant_id: str, vertical_key: str | None) -> dict[str, Any]:
    """Answers shaped for the AI facts document. Skipped answers are omitted."""
    if not vertical_key:
        return {}
    rows = (
        await db.execute(
            select(TenantIntakeAnswer).where(
                TenantIntakeAnswer.tenant_id == tenant_id,
                TenantIntakeAnswer.vertical_key == vertical_key,
                TenantIntakeAnswer.skipped.is_(False),
            )
        )
    ).scalars().all()
    out: dict[str, Any] = {}
    for row in rows:
        answer = row.answer
        if isinstance(answer, dict):
            value = answer.get("value")
        else:
            value = answer
        if value in (None, "", [], {}):
            continue
        out[row.question_key] = value
    return out

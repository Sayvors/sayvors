"""Idempotent seed for the catalogs the application cannot run without.

Migrations insert these rows, but the models are the schema source of truth:
a database rebuilt with ``Base.metadata.create_all`` has empty catalog tables.
With an empty ``tones`` table every tone is invalid; with no
``response_strategies`` strategy matching returns nothing.

The seeder only inserts missing rows. It never updates or deletes, so an
admin's edit to a seeded row survives every restart. It is safe to run from
several API workers at once: both PostgreSQL and SQLite use
``INSERT ... ON CONFLICT DO NOTHING``.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..tts.models import VoiceModelConfig
from .models import Dialect, ResponseStrategy, Tone

TONES: list[dict] = [
    {"code": "friendly", "label": "Friendly", "description": "warm and casual"},
    {"code": "professional", "label": "Professional", "description": "formal and polished"},
    {"code": "apologetic", "label": "Apologetic", "description": "extra empathetic"},
    {"code": "playful", "label": "Playful", "description": "light and fun"},
]

DIALECTS: list[dict] = [
    {"code": "egyptian", "dialect_en": "Egyptian Arabic", "dialect_ar": "اللهجة المصرية", "examples": ["أهلاً", "إزيك؟"]},
    {"code": "syrian", "dialect_en": "Syrian Arabic", "dialect_ar": "اللهجة الشامية السورية", "examples": ["أهلاً", "شلونك؟"]},
    {"code": "lebanese", "dialect_en": "Lebanese Arabic", "dialect_ar": "اللهجة اللبنانية", "examples": ["أهلا", "كيفك؟"]},
    {"code": "palestinian", "dialect_en": "Palestinian Arabic", "dialect_ar": "اللهجة الفلسطينية", "examples": ["أهلاً", "كيفك؟"]},
    {"code": "jordanian", "dialect_en": "Jordanian Arabic", "dialect_ar": "اللهجة الأردنية", "examples": ["أهلاً وسهلاً", "كيفك؟"]},
    {"code": "iraqi-baghdadi", "dialect_en": "Baghdadi Iraqi Arabic", "dialect_ar": "اللهجة العراقية البغدادية", "examples": ["هلا", "شلونك؟"]},
    {"code": "iraqi-southern", "dialect_en": "Southern Iraqi Arabic", "dialect_ar": "اللهجة العراقية الجنوبية", "examples": ["هلا بيك", "شلونك؟"]},
    {"code": "najdi", "dialect_en": "Najdi Arabic", "dialect_ar": "اللهجة النجدية", "examples": ["هلا", "وشلونك؟"]},
    {"code": "hejazi", "dialect_en": "Hejazi Arabic", "dialect_ar": "اللهجة الحجازية", "examples": ["أهلاً", "كيفك؟"]},
    {"code": "eastern-saudi", "dialect_en": "Eastern Saudi Arabic", "dialect_ar": "اللهجة السعودية الشرقية", "examples": ["هلا", "شلونك؟"]},
    {"code": "kuwaiti", "dialect_en": "Kuwaiti Arabic", "dialect_ar": "اللهجة الكويتية", "examples": ["هلا", "شلونك؟"]},
    {"code": "bahraini", "dialect_en": "Bahraini Arabic", "dialect_ar": "اللهجة البحرينية", "examples": ["هلا", "شلونك؟"]},
    {"code": "qatari", "dialect_en": "Qatari Arabic", "dialect_ar": "اللهجة القطرية", "examples": ["هلا", "شلونك؟"]},
    {"code": "emirati", "dialect_en": "Emirati Arabic", "dialect_ar": "اللهجة الإماراتية", "examples": ["مرحبا", "شخبارك؟"]},
    {"code": "omani", "dialect_en": "Omani Arabic", "dialect_ar": "اللهجة العُمانية", "examples": ["هلا", "كيف حالك؟"]},
    {"code": "yemeni-sanaani", "dialect_en": "Sanaani Yemeni Arabic", "dialect_ar": "اللهجة اليمنية الصنعانية", "examples": ["هلا", "كيف حالك؟"]},
    {"code": "yemeni-hadhrami", "dialect_en": "Hadhrami Arabic", "dialect_ar": "اللهجة الحضرمية", "examples": ["مرحبا", "كيف حالك؟"]},
    {"code": "sudanese", "dialect_en": "Sudanese Arabic", "dialect_ar": "اللهجة السودانية", "examples": ["سلام", "كيفنك؟"]},
    {"code": "libyan", "dialect_en": "Libyan Arabic", "dialect_ar": "اللهجة الليبية", "examples": ["هلا", "شن حالك؟"]},
    {"code": "tunisian", "dialect_en": "Tunisian Arabic", "dialect_ar": "اللهجة التونسية", "examples": ["عسلامة", "شنوّة أحوالك؟"]},
    {"code": "algerian", "dialect_en": "Algerian Arabic", "dialect_ar": "اللهجة الجزائرية", "examples": ["سلام", "واش راك؟"]},
    {"code": "moroccan", "dialect_en": "Moroccan Arabic (Darija)", "dialect_ar": "اللهجة المغربية", "examples": ["سلام", "كيداير؟"]},
    {"code": "hassaniya", "dialect_en": "Hassaniya Arabic", "dialect_ar": "اللهجة الموريتانية الحسانية", "examples": ["السلام عليكم", "كيف حالك؟"]},
]

STRATEGIES: list[dict] = [
    {
        "id": "acknowledge_feedback",
        "name": "Acknowledge Feedback",
        "description": "Recognize what the customer actually said. Reference the specific subject of the review.",
        "category": "engagement",
        "conditions": {"sentiments": ["neutral", "positive", "negative", "very_negative", "very_positive"], "min_length": 10},
        "instructions": ["Reference the specific subject of the review, not a generic 'your feedback'.", "Show that the review was read and understood."],
        "compatible_strategies": ["show_appreciation", "apologize_for_issue", "address_specific_issue", "keep_response_minimal"],
        "priority": 90,
    },
    {
        "id": "apologize_for_issue",
        "name": "Apologize for Issue",
        "description": "Acknowledge the problem and apologize naturally when the customer reports a negative experience.",
        "category": "recovery",
        "conditions": {"sentiments": ["negative", "very_negative"], "issue_types": ["product_quality", "product_dissatisfaction", "service_quality", "delivery", "wait_time", "cleanliness", "staff_behavior", "billing", "technical_issue", "general_complaint"]},
        "instructions": ["Acknowledge the specific problem mentioned.", "Apologize naturally without excessive repetition.", "Do not argue with the customer.", "Avoid generic apologies that don't address the issue.", "Do not make unsupported promises about fixes."],
        "compatible_strategies": ["acknowledge_feedback", "address_specific_issue", "reassure_customer", "invite_private_conversation"],
        "priority": 80,
    },
    {
        "id": "show_appreciation",
        "name": "Show Appreciation",
        "description": "Thank the reviewer for positive reviews, constructive feedback, or detailed reviews.",
        "category": "engagement",
        "conditions": {"sentiments": ["positive", "very_positive"]},
        "instructions": ["Thank the reviewer warmly but proportionally.", "If the review is detailed, acknowledge something specific.", "Do not be overly effusive for a simple 'great'."],
        "compatible_strategies": ["acknowledge_feedback", "encourage_another_visit", "keep_response_minimal"],
        "priority": 85,
    },
    {
        "id": "address_specific_issue",
        "name": "Address Specific Issue",
        "description": "Directly address the primary issue mentioned in the review rather than giving a generic response.",
        "category": "engagement",
        "conditions": {"sentiments": ["negative", "very_negative", "neutral"], "has_text": True},
        "instructions": ["Identify the primary issue from the review.", "Discuss the specific issue in the response.", "Do not deflect or redirect to unrelated topics."],
        "compatible_strategies": ["acknowledge_feedback", "apologize_for_issue", "reassure_customer"],
        "priority": 75,
    },
    {
        "id": "reassure_customer",
        "name": "Reassure Customer",
        "description": "Provide reasonable reassurance without making unsupported claims about fixes or changes.",
        "category": "recovery",
        "conditions": {"sentiments": ["negative", "very_negative"], "issue_types": ["product_quality", "service_quality", "staff_behavior", "cleanliness", "technical_issue"]},
        "instructions": ["Express that the feedback is taken seriously.", "Do not claim the issue has been fixed unless there is evidence.", "Keep reassurance proportional to the complaint."],
        "compatible_strategies": ["acknowledge_feedback", "apologize_for_issue", "invite_private_conversation"],
        "priority": 60,
    },
    {
        "id": "recommend_related_product",
        "name": "Recommend Related Product",
        "description": "Recommend another product or service when genuinely relevant to the customer's complaint.",
        "category": "growth",
        "conditions": {"sentiments": ["negative", "very_negative", "neutral"], "has_product_reference": True},
        "instructions": ["Only recommend products that actually exist in the business catalog.", "Frame the recommendation as a genuine alternative, not a sales pitch.", "Connect the recommendation to what the customer didn't like."],
        "compatible_strategies": ["acknowledge_feedback", "mention_relevant_offer", "encourage_another_visit"],
        "priority": 40,
    },
    {
        "id": "mention_relevant_offer",
        "name": "Mention Relevant Offer",
        "description": "Retrieve and mention an existing active promotion when appropriate. Must never invent offers.",
        "category": "growth",
        "conditions": {"sentiments": ["negative", "very_negative", "neutral"]},
        "instructions": ["Retrieve relevant active offers from the business before responding.", "Only mention offers that actually exist and are publicly mentionable.", "Integrate the offer naturally into the response.", "If no relevant offer exists, do NOT mention any offer.", "Never invent a discount, coupon, or promotion."],
        "compatible_strategies": ["acknowledge_feedback", "apologize_for_issue", "encourage_another_visit", "recommend_related_product"],
        "priority": 35,
    },
    {
        "id": "encourage_another_visit",
        "name": "Encourage Another Visit",
        "description": "Invite the customer to give the business another opportunity when appropriate.",
        "category": "recovery",
        "conditions": {"sentiments": ["negative", "very_negative"], "min_rating": 1, "max_rating": 3},
        "instructions": ["Frame the invitation as genuine, not aggressive or salesy.", "Do not pressure the customer.", "Keep it brief and proportional."],
        "compatible_strategies": ["acknowledge_feedback", "apologize_for_issue", "mention_relevant_offer"],
        "priority": 45,
    },
    {
        "id": "invite_private_conversation",
        "name": "Invite Private Conversation",
        "description": "Direct the customer to a private channel when the review contains sensitive or complex issues.",
        "category": "recovery",
        "conditions": {"sentiments": ["negative", "very_negative"], "intent_keywords": ["refund", "money back", "stolen", "scam", "lawsuit", "lawyer", "card", "charged", "wrong order", "account"]},
        "instructions": ["Acknowledge the concern briefly.", "Invite them to contact the business privately.", "Do not share any personal or account information publicly.", "Do not mention specific phone numbers or emails."],
        "compatible_strategies": ["acknowledge_feedback", "apologize_for_issue"],
        "priority": 70,
    },
    {
        "id": "keep_response_minimal",
        "name": "Keep Response Minimal",
        "description": "For simple reviews, keep the response short and proportional. No unnecessary promotions or length.",
        "category": "style",
        "conditions": {"sentiments": ["positive", "very_positive", "neutral"], "max_review_length": 30},
        "instructions": ["Keep the response to 1-2 sentences.", "Do not add promotions, recommendations, or lengthy explanations.", "Match the effort of the review."],
        "compatible_strategies": ["show_appreciation", "acknowledge_feedback"],
        "priority": 65,
    },
]

VOICE_MODELS: list[dict] = [
    {
        "id": "voice-edge-simple-0001",
        "label": "Natural voices (simple)",
        "provider": "edge",
        "api_url": None,
        "api_model": None,
        "reference_id": None,
        "tier": "simple",
        "languages": "*",
        "enabled": True,
    },
    {
        "id": "voice-fish-advanced-001",
        "label": "Fish Audio (advanced)",
        "provider": "fish",
        "api_url": "https://api.fish.audio/v1/tts",
        "api_model": "s2.1-pro-free",
        "reference_id": "933563129e564b19a115bedd57b7406a",
        "tier": "advanced",
        "languages": "*",
        "enabled": True,
    },
]


async def _insert_missing(db: AsyncSession, model, rows: list[dict]) -> int:
    """Insert only rows whose primary key is not present yet.

    Returns the number of rows actually inserted. ``ON CONFLICT DO NOTHING``
    makes concurrent starts safe: two workers can race and only one insert
    wins, with no error and no overwrite.
    """
    if not rows:
        return 0

    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
    else:  # pragma: no cover - only PostgreSQL and SQLite are supported
        pk = next(iter(model.__table__.primary_key.columns)).name
        existing = set((await db.execute(select(getattr(model, pk)))).scalars())
        missing = [row for row in rows if row[pk] not in existing]
        if missing:
            await db.execute(model.__table__.insert(), missing)
        return len(missing)

    result = await db.execute(
        dialect_insert(model).values(rows).on_conflict_do_nothing()
    )
    return result.rowcount or 0


async def seed_catalogs(db: AsyncSession) -> dict[str, int]:
    """Fill every empty catalog row without touching existing ones.

    Callers own the session. The commit is part of the operation so a caller
    cannot forget it and leave the rows invisible to other workers.
    """
    counts = {
        "tones": await _insert_missing(db, Tone, TONES),
        "dialects": await _insert_missing(db, Dialect, DIALECTS),
        "response_strategies": await _insert_missing(db, ResponseStrategy, STRATEGIES),
        "voice_model_configs": await _insert_missing(db, VoiceModelConfig, VOICE_MODELS),
    }
    await db.commit()
    return counts

"""Generate scored, deduplicated customer questions from business facts."""
from __future__ import annotations

import re
from dataclasses import dataclass

from ...core.language import detect_language
from ...core.text import normalize_text
from .taxonomy import IndustryMatch, IntentSpec, classify_industry, select_intents

MAX_INITIAL_QUESTIONS = 8
MAX_GENERATED_QUESTION_CHARS = 240
INDUSTRY_SCORE_WEIGHT = 0.5
SERVICE_SCORE_WEIGHT = 0.3
GEOGRAPHY_SCORE_WEIGHT = 0.2
SAUDI_GEOGRAPHY_TOKENS = {
    "saudi",
    "saudi arabia",
    "riyadh",
    "makkah",
    "medina",
    "jeddah",
    "dammam",
    "khobar",
    "dhahran",
    "qassim",
    "buraydah",
    "taif",
    "tabuk",
    "abha",
    "hail",
    "jubail",
    "yanbu",
    "najran",
    "jazan",
}


@dataclass(frozen=True)
class GeneratedQuestion:
    question_text: str
    language: str
    intent: str
    industry_relevance: int
    service_relevance: int
    geographic_context: str
    business_relevance_score: int
    priority: str


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _customer_intent(text: str) -> str:
    normalized = normalize_text(text)
    rules = (
        (("price", "cost", "fee", "cheap", "afford", "سعر", "رسوم"), "price"),
        (("book", "appointment", "reserve", "حجز", "موعد"), "booking"),
        (("deliver", "shipping", "توصيل", "شحن"), "delivery"),
        (("near", "where", "address", "location", "أين", "عنوان"), "location"),
        (("best", "recommend", "أفضل", "أنصح"), "recommendation"),
        (("review", "rating", "quality", "تقييم", "جودة"), "reputation"),
        (("service", "provide", "خدمة", "يقدم"), "service_specific"),
    )
    for terms, intent in rules:
        if any(term in normalized for term in terms):
            return intent
    return "customer_question"


def _is_unoffered(text: str, not_offered: str) -> bool:
    question_tokens = set(re.findall(r"\w{3,}", normalize_text(text)))
    for phrase in re.split(r"[,;،؛]|\band\b|\n", not_offered.casefold()):
        tokens = set(re.findall(r"\w{3,}", normalize_text(phrase)))
        if len(tokens) >= 2 and len(tokens & question_tokens) >= 2:
            return True
    return False


def _geography(profile: dict) -> str:
    locality = str(profile.get("locality") or "").strip()
    if locality:
        return locality
    address = str(profile.get("address") or "").strip()
    if address:
        return address.split(",", 1)[0].strip()
    areas = profile.get("service_area") or []
    if isinstance(areas, list) and areas:
        return str(areas[0]).strip()
    return ""


def _preferred_languages(profile: dict) -> tuple[str, ...]:
    text = " ".join(
        str(profile.get(key) or "")
        for key in ("address", "locality", "service_area", "description", "services")
    ).casefold()
    if any(token in text for token in SAUDI_GEOGRAPHY_TOKENS):
        return ("ar", "en")
    if re.search(r"[\u0600-\u06ff]", text):
        return ("ar", "en")
    return ("en",)


def _matching_service(profile: dict, intent: IntentSpec) -> str:
    if not intent.required_service:
        return ""
    services = profile.get("services") or []
    if isinstance(services, list):
        for service in services:
            label = str(service).strip()
            if intent.required_service.casefold() in label.casefold():
                return label
    return intent.required_service


def _render(template: str, profile: dict, intent: IntentSpec, geography: str) -> str:
    service = _matching_service(profile, intent)
    areas = profile.get("service_area") or []
    area = str(areas[0]).strip() if isinstance(areas, list) and areas else geography
    return template.format(
        name=str(profile.get("name") or "this business").strip(),
        locality=geography or "the local area",
        service=service or "services",
        area=area or "the local area",
    ).strip()


def _scores(match: IndustryMatch, intent: IntentSpec, geography: str) -> tuple[int, int, int]:
    industry = round(match.confidence * 100)
    service = 100 if intent.required_service else 85
    geo = 100 if geography else 60
    total = round(
        industry * INDUSTRY_SCORE_WEIGHT
        + service * SERVICE_SCORE_WEIGHT
        + geo * GEOGRAPHY_SCORE_WEIGHT
    )
    return industry, service, max(0, min(100, total))


def generate_questions(
    profile: dict, *, limit: int = MAX_INITIAL_QUESTIONS
) -> list[GeneratedQuestion]:
    """Generate customer questions unique to this branch and its services."""
    match = classify_industry(profile)
    intents = select_intents(match)
    languages = _preferred_languages(profile)
    geography = _geography(profile)
    out: list[GeneratedQuestion] = []
    seen: set[str] = set()
    not_offered = str(profile.get("not_offered") or "")
    for raw in profile.get("customer_questions") or []:
        text = str(raw).strip()
        key = _normalize(text)
        if (
            not text
            or len(text) > MAX_GENERATED_QUESTION_CHARS
            or key in seen
            or _is_unoffered(text, not_offered)
        ):
            continue
        seen.add(key)
        industry = round(match.confidence * 100)
        service = 95
        geo = 100 if geography else 60
        score = round(
            industry * INDUSTRY_SCORE_WEIGHT
            + service * SERVICE_SCORE_WEIGHT
            + geo * GEOGRAPHY_SCORE_WEIGHT
        )
        out.append(
            GeneratedQuestion(
                question_text=text,
                language="ar" if detect_language(text).code.startswith("ar") else "en",
                intent=_customer_intent(text),
                industry_relevance=industry,
                service_relevance=service,
                geographic_context=geography,
                business_relevance_score=max(0, min(100, score)),
                priority="P1",
            )
        )
        if len(out) >= max(1, limit):
            return out
    max_templates = max(
        (len(getattr(intent, language)) for intent in intents for language in languages),
        default=0,
    )
    # Language-major, intent round-robin: every relevant intent gets a
    # question in the preferred language before a second template is used.
    for language in languages:
        for index in range(max_templates):
            for intent in intents:
                templates = getattr(intent, language)
                if index >= len(templates):
                    continue
                text = _render(templates[index], profile, intent, geography)
                key = _normalize(text)
                if not text or len(text) > MAX_GENERATED_QUESTION_CHARS or key in seen:
                    continue
                seen.add(key)
                industry, service, score = _scores(match, intent, geography)
                out.append(
                    GeneratedQuestion(
                        question_text=text,
                        language=language,
                        intent=intent.key,
                        industry_relevance=industry,
                        service_relevance=service,
                        geographic_context=geography,
                        business_relevance_score=score,
                        priority=intent.priority,
                    )
                )
                if len(out) >= max(1, limit):
                    return out
    return out

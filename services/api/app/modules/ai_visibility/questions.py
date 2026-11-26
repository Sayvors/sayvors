"""Generate scored, deduplicated customer questions from business facts."""
from __future__ import annotations

import re
from dataclasses import dataclass

from ...core.language import detect_language
from ...core.text import normalize_text
from .taxonomy import IndustryMatch, IntentSpec, classify_industry, select_intents

MAX_INITIAL_QUESTIONS = 8
MAX_GENERATED_QUESTION_CHARS = 240
MAX_CUSTOMER_VOICE_QUESTIONS = 3
MIN_CUSTOMER_VOICE_RELEVANCE = 0.35
CUSTOMER_NAME_WEIGHT = 0.45
CUSTOMER_LOCALITY_WEIGHT = 0.25
CUSTOMER_SERVICE_WEIGHT = 0.35
CUSTOMER_INTENT_WEIGHT = 0.15
GENERIC_SUPPORT_TERMS = {
    "update",
    "mobile number",
    "google maps",
    "login",
    "password",
    "account",
    "subscription",
    "invoice",
    "bill",
    "app",
    "otp",
    "verify",
}
GENERIC_NAME_WORDS = {"company", "branch", "business", "location", "store", "shop", "office"}
PII_PLACEHOLDERS = {"customer", "email", "phone", "link", "number", "address"}
PROTECTED_PLATFORM_PHRASES = {
    "google maps", "google business", "whatsapp", "facebook", "instagram",
    "youtube", "tiktok", "linkedin", "chatgpt", "gemini", "perplexity",
}
SERVICE_ALIAS_GROUPS = (
    ("finance", "financing", "financial"),
    ("deliver", "delivery", "shipping"),
    ("book", "booking", "reservation"),
    ("recruit", "recruitment", "recruiting"),
    ("manage", "management"),
    ("rent", "rental"),
    ("insure", "insurance"),
    ("repair", "maintenance"),
    ("bridal", "bride", "wedding"),
)
SERVICE_TOKEN_ROOTS = {
    alias: group[0]
    for group in SERVICE_ALIAS_GROUPS
    for alias in group
}
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
    normalized = normalize_text(value)
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    return " ".join(normalized.split())


def _customer_intent(text: str) -> str:
    normalized = normalize_text(text)
    rules = (
        (("price", "cost", "fee", "cheap", "afford", "سعر", "رسوم"), "price"),
        (("book", "appointment", "reserve", "حجز", "موعد"), "booking"),
        (("deliver", "shipping", "توصيل", "شحن"), "delivery"),
        (("near", "where", "address", "location", "أين", "عنوان"), "location"),
        (("best", "recommend", "أفضل", "أنصح"), "recommendation"),
        (("review", "rating", "quality", "تقييم", "جودة"), "reputation"),
        (("licens", "مرخص"), "licensing"),
        (("service", "provide", "خدمة", "يقدم"), "service_specific"),
    )
    for terms, intent in rules:
        if any(term in normalized for term in terms):
            return intent
    return "customer_question"


def _is_unoffered(text: str, not_offered: str) -> bool:
    question_tokens = _tokens(text)
    question_roots = _roots(question_tokens)
    for phrase in re.split(r"[,;،؛]|\band\b|\n", not_offered.casefold()):
        tokens = _tokens(phrase)
        phrase_roots = _roots(tokens)
        if len(tokens) == 1:
            token = next(iter(tokens))
            root = SERVICE_TOKEN_ROOTS.get(token, token)
            if root in question_roots or any(
                question == token
                or (len(token) >= 4 and (question.startswith(token) or token.startswith(question)))
                for question in question_tokens
            ):
                return True
        if len(tokens) >= 2 and len(phrase_roots & question_roots) >= 2:
            return True
    return False


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"\w{3,}", normalize_text(value))) - PII_PLACEHOLDERS


def _roots(tokens: set[str]) -> set[str]:
    return {SERVICE_TOKEN_ROOTS.get(token, token) for token in tokens}


def _service_match(text: str, profile: dict) -> bool:
    question_tokens = _tokens(text)
    services = profile.get("services") or []
    products = profile.get("products") or []
    labels = [str(item) for item in services if isinstance(item, str)]
    labels.extend(
        str(item.get("name") or "")
        for item in products
        if isinstance(item, dict)
    )
    description = str(profile.get("description") or "").strip()
    if description:
        labels.append(description)
    for label in labels:
        service_tokens = _tokens(label)
        if not service_tokens:
            continue
        service_roots = _roots(service_tokens)
        question_roots = _roots(question_tokens)
        matches = sum(
            any(
                question == token
                or question.startswith(token)
                or token.startswith(question)
                or root in question_roots
                for question in question_tokens
            )
            for token, root in zip(service_tokens, service_roots)
        )
        if (len(service_tokens) == 1 and matches) or matches >= 2:
            return True
    return False


def _customer_voice_score(text: str, profile: dict, geography: str) -> float:
    question_tokens = _tokens(text)
    name_tokens = _tokens(str(profile.get("name") or "")) - GENERIC_NAME_WORDS
    locality_tokens = _tokens(geography)
    name_match = bool(question_tokens & name_tokens)
    locality_match = bool(question_tokens & locality_tokens)
    service_match = _service_match(text, profile)
    normalized = normalize_text(text)
    generic_support = any(term in normalized for term in GENERIC_SUPPORT_TERMS)
    if generic_support and not (name_match or service_match):
        return 0.0
    score = (
        (CUSTOMER_NAME_WEIGHT if name_match else 0.0)
        + (CUSTOMER_LOCALITY_WEIGHT if locality_match else 0.0)
        + (CUSTOMER_SERVICE_WEIGHT if service_match else 0.0)
        + (
            CUSTOMER_INTENT_WEIGHT
            if _customer_intent(text) != "customer_question"
            else 0.0
        )
    )
    return min(1.0, score)


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
    audience = str(profile.get("audience_languages") or "").casefold()
    if any(
        token in audience
        for token in ("arabic", "عربي", "العربية")
    ):
        return ("ar", "en")
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
    intents = select_intents(match, str(profile.get("not_offered") or ""))
    languages = _preferred_languages(profile)
    geography = _geography(profile)
    out: list[GeneratedQuestion] = []
    seen: set[str] = set()
    not_offered = str(profile.get("not_offered") or "")
    voice_candidates: list[tuple[float, str]] = []
    for raw in profile.get("customer_questions") or []:
        text = str(raw).strip()
        if (
            not text
            or len(text) > MAX_GENERATED_QUESTION_CHARS
            or _is_unoffered(text, not_offered)
        ):
            continue
        score = _customer_voice_score(text, profile, geography)
        if score >= MIN_CUSTOMER_VOICE_RELEVANCE:
            voice_candidates.append((score, text))
    voice_candidates.sort(key=lambda item: (-item[0], item[1]))
    for _score, text in voice_candidates[:MAX_CUSTOMER_VOICE_QUESTIONS]:
        key = _normalize(text)
        if key in seen:
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

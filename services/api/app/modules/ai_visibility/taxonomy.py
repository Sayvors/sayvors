"""Industry taxonomy for business-specific customer research questions.

The taxonomy is deliberately data-driven: a branch never receives a universal
question list. Classification combines multiple weak signals, and intent
selection removes service-specific questions when the service is not present
in the branch's own facts.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IndustryMatch:
    industry: str
    business_type: str
    subcategories: tuple[str, ...]
    confidence: float
    matched_signals: tuple[str, ...]
    uncertainties: tuple[str, ...]
    service_text: str = ""


@dataclass(frozen=True)
class IntentSpec:
    key: str
    priority: str
    en: tuple[str, ...]
    ar: tuple[str, ...]
    required_service: str | None = None

    def __post_init__(self) -> None:
        # Single-string templates are common in data declarations; normalize
        # them to tuples so callers can always iterate both languages safely.
        object.__setattr__(
            self, "en", (self.en,) if isinstance(self.en, str) else tuple(self.en)
        )
        object.__setattr__(
            self, "ar", (self.ar,) if isinstance(self.ar, str) else tuple(self.ar)
        )


# Explicit business fields outrank incidental words in reviews or marketing
# copy. The numbers are weights, not probabilities; they only rank industries.
CATEGORY_SIGNAL_WEIGHT = 5
NAME_SIGNAL_WEIGHT = 3
DESCRIPTION_SIGNAL_WEIGHT = 2
REVIEW_SIGNAL_WEIGHT = 1
BASE_INDUSTRY_CONFIDENCE = 0.35
CONFIDENCE_SCORE_DIVISOR = 20
MULTI_ALIAS_CONFIDENCE_BONUS = 0.75
MAX_MULTI_ALIAS_BONUSES = 2
MAX_INDUSTRY_CONFIDENCE = 0.95
LOW_INDUSTRY_CONFIDENCE = 0.6
UNKNOWN_INDUSTRY_CONFIDENCE = 0.2


# A generic word such as "shop" is not enough to classify a business; the
# classifier must see a real category, service, or product signal.
INDUSTRY_ALIASES: dict[str, tuple[str, ...]] = {
    "software_company": (
        "software",
        "ai lab",
        "ai research",
        "technology company",
        "software development",
        "research lab",
    ),
    "restaurant": (
        "restaurant",
        "cafe",
        "coffee shop",
        "mandi",
        "grill",
        "food delivery",
    ),
    "hospital": (
        "hospital",
        "medical center",
        "medical city",
        "clinic",
        "dental",
        "emergency care",
        "maternity",
        "diagnostic",
    ),
    "school": (
        "school",
        "college",
        "university",
        "academy",
        "curriculum",
        "admissions",
    ),
    "hotel": (
        "hotel",
        "resort",
        "accommodation",
        "guest house",
        "hospitality",
    ),
    "ecommerce": (
        "ecommerce",
        "e-commerce",
        "online store",
        "online shop",
        "shipping",
        "returns",
    ),
    "real_estate": (
        "real estate",
        "property",
        "realtor",
        "estate agency",
        "rental",
    ),
    "law_firm": (
        "law firm",
        "law office",
        "legal services",
        "attorney",
        "lawyer",
    ),
    "salon": (
        "salon",
        "beauty",
        "barber",
        "hair",
        "spa",
    ),
    "automobile_dealership": (
        "car dealership",
        "auto dealer",
        "vehicle dealership",
        "car sales",
        "automobile",
    ),
    "retail_store": (
        "retail",
        "electronics store",
        "clothing store",
        "furniture store",
        "supermarket",
        "pharmacy",
    ),
    "recruitment": (
        "recruitment",
        "manpower",
        "labor office",
        "labour office",
        "domestic worker",
        "employment agency",
        "استقدام",
        "مكتب استقدام",
    ),
}


INDUSTRY_INTENTS: dict[str, tuple[IntentSpec, ...]] = {
    "software_company": (
        IntentSpec(
            "product_discovery",
            "P1",
            ("What does {name} build?", "What products does {name} offer?"),
            ("ماذا يبني {name}؟", "ما المنتجات التي يقدمها {name}؟"),
        ),
        IntentSpec(
            "use_cases",
            "P1",
            ("What problems does {name} solve?",),
            ("ما المشكلات التي يحلها {name}؟"),
        ),
        IntentSpec(
            "alternatives",
            "P2",
            ("What are the best alternatives to {name}?",),
            ("ما أفضل البدائل لـ {name}؟"),
        ),
    ),
    "restaurant": (
        IntentSpec(
            "cuisine",
            "P1",
            ("What cuisine does {name} serve?",),
            ("ما نوع المطبخ الذي يقدمه {name}؟"),
        ),
        IntentSpec(
            "delivery",
            "P1",
            ("Does {name} deliver near {locality}?",),
            ("هل يوصل {name} إلى منطقة {locality}؟"),
            required_service="delivery",
        ),
        IntentSpec(
            "family_dining",
            "P2",
            ("Is {name} good for families in {locality}?",),
            ("هل يناسب {name} العائلات في {locality}؟"),
            required_service="family",
        ),
    ),
    "hospital": (
        IntentSpec(
            "specialties",
            "P1",
            ("What medical specialties does {name} provide?",),
            ("ما التخصصات الطبية التي يقدمها {name}؟"),
        ),
        IntentSpec(
            "emergency_care",
            "P0",
            ("Does {name} provide emergency care in {locality}?",),
            ("هل يقدم {name} رعاية طارئة في {locality}؟"),
            required_service="emergency",
        ),
        IntentSpec(
            "maternity",
            "P1",
            ("Does {name} provide maternity and pediatric services?",),
            ("هل يقدم {name} خدمات الولادة والأطفال؟"),
            required_service="maternity",
        ),
        IntentSpec(
            "diagnostics",
            "P1",
            ("What diagnostic services are available at {name}?",),
            ("ما خدمات التشخيص المتاحة في {name}؟"),
            required_service="diagnostic",
        ),
    ),
    "school": (
        IntentSpec(
            "admissions",
            "P0",
            ("What are the admission requirements at {name}?",),
            ("ما شروط القبول في {name}؟"),
        ),
        IntentSpec(
            "curriculum",
            "P1",
            ("What curriculum and grade levels does {name} offer?",),
            ("ما المناهج والمراحل الدراسية التي يقدمها {name}؟"),
        ),
        IntentSpec(
            "tuition",
            "P1",
            ("What is the tuition at {name}?",),
            ("ما رسوم الدراسة في {name}؟"),
        ),
        IntentSpec(
            "facilities",
            "P2",
            ("What facilities and extracurricular activities are available at {name}?",),
            ("ما المرافق والأنشطة اللامنهجية المتاحة في {name}؟"),
        ),
    ),
    "hotel": (
        IntentSpec(
            "booking",
            "P0",
            ("How can I book a room at {name} in {locality}?",),
            ("كيف يمكنني حجز غرفة في {name} في {locality}؟"),
        ),
        IntentSpec(
            "accommodation",
            "P1",
            ("What room types and amenities does {name} offer?",),
            ("ما أنواع الغرف والمرافق التي يقدمها {name}؟"),
        ),
        IntentSpec(
            "pricing",
            "P1",
            ("What are typical room rates at {name}?",),
            ("ما أسعار الغرف المعتادة في {name}؟"),
        ),
        IntentSpec(
            "family_stays",
            "P2",
            ("Is {name} suitable for families and business travelers?",),
            ("هل يناسب {name} العائلات ومسافري العمل؟"),
        ),
    ),
    "ecommerce": (
        IntentSpec(
            "product_discovery",
            "P1",
            ("What products does {name} sell online?",),
            ("ما المنتجات التي يبيعها {name} عبر الإنترنت؟"),
        ),
        IntentSpec(
            "authenticity",
            "P1",
            ("Are products from {name} authentic?",),
            ("هل منتجات {name} أصلية؟"),
        ),
        IntentSpec(
            "shipping",
            "P0",
            ("Does {name} ship to my area and how long does delivery take?",),
            ("هل يشحن {name} إلى منطقتي وكم يستغرق التوصيل؟"),
        ),
        IntentSpec(
            "returns",
            "P1",
            ("What is the return and refund policy at {name}?",),
            ("ما سياسة الإرجاع والاسترداد في {name}؟"),
        ),
        IntentSpec(
            "payments",
            "P2",
            ("What payment options does {name} accept?",),
            ("ما خيارات الدفع التي يقبلها {name}؟"),
        ),
    ),
    "real_estate": (
        IntentSpec(
            "property_types",
            "P1",
            ("What types of properties does {name} handle in {locality}?",),
            ("ما أنواع العقارات التي يتعامل معها {name} في {locality}؟"),
        ),
        IntentSpec(
            "rental_prices",
            "P1",
            ("What are typical rental prices in the areas served by {name}?",),
            ("ما أسعار الإيجار المعتادة في المناطق التي يخدمها {name}؟"),
        ),
        IntentSpec(
            "buying",
            "P1",
            ("Does {name} help buyers find homes in {locality}?",),
            ("هل يساعد {name} المشترين على إيجاد منازل في {locality}؟"),
        ),
        IntentSpec(
            "property_management",
            "P2",
            ("Does {name} offer property management services?",),
            ("هل يقدم {name} خدمات إدارة العقارات؟"),
            required_service="management",
        ),
    ),
    "law_firm": (
        IntentSpec(
            "legal_specialties",
            "P1",
            ("What legal specialties does {name} practice?",),
            ("ما التخصصات القانونية التي يمارسها {name}؟"),
        ),
        IntentSpec(
            "consultation",
            "P0",
            ("How can I book a legal consultation with {name}?",),
            ("كيف يمكنني حجز استشارة قانونية مع {name}؟"),
        ),
        IntentSpec(
            "business_legal",
            "P1",
            ("Does {name} provide business and corporate legal services?",),
            ("هل يقدم {name} خدمات قانونية للشركات والأعمال؟"),
            required_service="business",
        ),
        IntentSpec(
            "expertise",
            "P2",
            ("What experience and credentials does {name} have?",),
            ("ما الخبرات والمؤهلات التي يتمتع بها {name}؟"),
        ),
    ),
    "salon": (
        IntentSpec(
            "salon_services",
            "P1",
            ("What beauty and hair services does {name} offer?",),
            ("ما خدمات التجميل والشعر التي يقدمها {name}؟"),
        ),
        IntentSpec(
            "appointments",
            "P0",
            ("How can I book an appointment at {name}?",),
            ("كيف يمكنني حجز موعد في {name}؟"),
        ),
        IntentSpec(
            "pricing",
            "P1",
            ("What are typical service prices at {name}?",),
            ("ما أسعار الخدمات المعتادة في {name}؟"),
        ),
        IntentSpec(
            "bridal",
            "P2",
            ("Does {name} offer bridal makeup and styling?",),
            ("هل يقدم {name} مكياج وتنسيق العرائس؟"),
            required_service="bridal",
        ),
    ),
    "automobile_dealership": (
        IntentSpec(
            "vehicle_inventory",
            "P1",
            ("What vehicles and brands are available at {name}?",),
            ("ما السيارات والماركات المتاحة لدى {name}؟"),
        ),
        IntentSpec(
            "pricing",
            "P1",
            ("How are vehicles priced at {name}?",),
            ("كيف يتم تسعير السيارات لدى {name}؟"),
        ),
        IntentSpec(
            "financing",
            "P0",
            ("Does {name} offer vehicle financing?",),
            ("هل يقدم {name} تمويل السيارات؟"),
            required_service="financ",
        ),
        IntentSpec(
            "service",
            "P2",
            ("Does {name} provide after-sales service and maintenance?",),
            ("هل يقدم {name} خدمة ما بعد البيع والصيانة؟"),
            required_service="service",
        ),
    ),
    "retail_store": (
        IntentSpec(
            "product_availability",
            "P1",
            ("What products are in stock at {name} in {locality}?",),
            ("ما المنتجات المتوفرة في {name} في {locality}؟"),
        ),
        IntentSpec(
            "pricing",
            "P1",
            ("How do prices at {name} compare with nearby stores?",),
            ("كيف تقارن أسعار {name} بالمتاجر القريبة؟"),
        ),
        IntentSpec(
            "location",
            "P0",
            ("Where is the nearest {name} store in {locality}?",),
            ("أين أقرب فرع لـ {name} في {locality}؟"),
        ),
        IntentSpec(
            "returns",
            "P2",
            ("What is the return policy at {name}?",),
            ("ما سياسة الإرجاع في {name}؟"),
            required_service="return",
        ),
    ),
    "recruitment": (
        IntentSpec(
            "services",
            "P1",
            ("What recruitment services does {name} provide?",),
            ("ما خدمات الاستقدام التي يقدمها {name}؟"),
        ),
        IntentSpec(
            "licensing",
            "P0",
            ("Is {name} a licensed recruitment office in {locality}?",),
            ("هل {name} مكتب استقدام مرخص في {locality}؟"),
        ),
        IntentSpec(
            "job_seekers",
            "P1",
            ("How can job seekers contact {name}?",),
            ("كيف يمكن للباحثين عن عمل التواصل مع {name}؟"),
        ),
        IntentSpec(
            "employers",
            "P1",
            ("Does {name} help employers hire workers?",),
            ("هل يساعد {name} أصحاب العمل في توظيف العمالة؟"),
        ),
        IntentSpec(
            "fees",
            "P1",
            ("What fees and requirements apply when using {name}?",),
            ("ما الرسوم والمتطلبات عند التعامل مع {name}؟"),
        ),
    ),
    "local_services": (
        IntentSpec(
            "discovery",
            "P1",
            ("What services does {name} provide?",),
            ("ما الخدمات التي يقدمها {name}؟"),
        ),
        IntentSpec(
            "location",
            "P1",
            ("Where is {name} in {locality}?",),
            ("أين يقع {name} في {locality}؟"),
        ),
    ),
}


def _field_text(profile: dict, field: str) -> str:
    value = profile.get(field)
    if isinstance(value, (list, tuple, set)):
        return " ".join(str(item) for item in value)
    return str(value or "")


PUBLISHING_CATALOG = {
    "google_business": (
        "Google Business Profile",
        "https://business.google.com/",
        "Create a verified local listing with the exact branch name, address, hours, and services.",
    ),
    "linkedin": (
        "LinkedIn",
        "https://www.linkedin.com/company/setup/new/",
        "Publish company updates and expertise where professional customers and partners research you.",
    ),
    "youtube": (
        "YouTube",
        "https://www.youtube.com/creators/",
        "Publish demonstrations, explainers, and customer proof that AI assistants can cite.",
    ),
    "medium": (
        "Medium",
        "https://medium.com/new-story",
        "Publish in-depth industry articles that establish expertise and earn independent citations.",
    ),
    "substack": (
        "Substack",
        "https://substack.com/start",
        "Build a recurring newsletter for customer education and industry visibility.",
    ),
    "reddit": (
        "Reddit",
        "https://www.reddit.com/submit",
        "Share useful, non-promotional expertise in relevant communities and reference your public website.",
    ),
    "facebook": (
        "Facebook Page",
        "https://www.facebook.com/pages/create",
        "Maintain a public business page with current services, locality, and contact information.",
    ),
    "instagram": (
        "Instagram Business",
        "https://business.instagram.com/",
        "Publish visual proof, offers, and locality signals for customer discovery.",
    ),
    "tiktok": (
        "TikTok Business",
        "https://www.tiktok.com/business/",
        "Publish short demonstrations and educational content for new customer audiences.",
    ),
    "pinterest": (
        "Pinterest Business",
        "https://business.pinterest.com/",
        "Publish visual product and service collections that attract discovery traffic.",
    ),
    "tripadvisor": (
        "TripAdvisor",
        "https://www.tripadvisor.com/Owners",
        "Keep a verified hospitality listing with accurate amenities, location, and guest information.",
    ),
    "booking": (
        "Booking.com",
        "https://partner.booking.com/",
        "Maintain an accurate accommodation listing with rates, amenities, and availability.",
    ),
    "musaned": (
        "Musaned",
        "https://www.musaned.com.sa/",
        "Maintain the official recruitment-office presence and licensed service information.",
    ),
    "apple_business": (
        "Apple Business Connect",
        "https://businessconnect.apple.com/",
        "Keep Apple Maps business information accurate for local discovery.",
    ),
}

INDUSTRY_PUBLISHING = {
    "software_company": ("linkedin", "youtube", "medium", "substack", "reddit"),
    "restaurant": ("google_business", "instagram", "facebook", "tiktok", "reddit"),
    "hospital": ("google_business", "facebook", "linkedin", "youtube"),
    "school": ("google_business", "facebook", "linkedin", "youtube"),
    "hotel": ("google_business", "booking", "tripadvisor", "instagram", "facebook"),
    "ecommerce": ("instagram", "pinterest", "youtube", "tiktok", "facebook"),
    "real_estate": ("google_business", "linkedin", "facebook", "instagram", "youtube"),
    "law_firm": ("google_business", "linkedin", "youtube", "medium"),
    "salon": ("google_business", "instagram", "tiktok", "facebook"),
    "automobile_dealership": ("google_business", "facebook", "youtube", "instagram"),
    "retail_store": ("google_business", "instagram", "facebook", "pinterest"),
    "recruitment": ("google_business", "musaned", "linkedin", "facebook"),
    "local_services": ("google_business", "facebook", "apple_business"),
}


def publishing_recommendations(industry: str) -> list[dict]:
    """Return only channels relevant to the classified business type."""
    keys = INDUSTRY_PUBLISHING.get(industry, INDUSTRY_PUBLISHING["local_services"])
    return [
        {
            "platform": PUBLISHING_CATALOG[key][0],
            "setup_url": PUBLISHING_CATALOG[key][1],
            "reason": PUBLISHING_CATALOG[key][2],
        }
        for key in keys
    ]


def classify_industry(profile: dict) -> IndustryMatch:
    """Classify from combined signals, returning explicit uncertainty."""
    fields = (
        ("categories", CATEGORY_SIGNAL_WEIGHT),
        ("name", NAME_SIGNAL_WEIGHT),
        ("description", DESCRIPTION_SIGNAL_WEIGHT),
        ("services", DESCRIPTION_SIGNAL_WEIGHT),
        ("products", DESCRIPTION_SIGNAL_WEIGHT),
        ("website_title", DESCRIPTION_SIGNAL_WEIGHT),
        ("website_description", DESCRIPTION_SIGNAL_WEIGHT),
        ("audience_languages", REVIEW_SIGNAL_WEIGHT),
        ("offering_text", DESCRIPTION_SIGNAL_WEIGHT),
        ("business_description", DESCRIPTION_SIGNAL_WEIGHT),
        ("review_themes", REVIEW_SIGNAL_WEIGHT),
        ("customer_questions", REVIEW_SIGNAL_WEIGHT),
        ("customer_intents", REVIEW_SIGNAL_WEIGHT),
    )
    scores: dict[str, float] = {}
    signals: dict[str, list[str]] = {}
    for field, weight in fields:
        text = _field_text(profile, field).casefold()
        for industry, aliases in INDUSTRY_ALIASES.items():
            matched = [alias for alias in aliases if alias in text]
            if matched:
                bonus = min(
                    len(matched) - 1, MAX_MULTI_ALIAS_BONUSES
                ) * MULTI_ALIAS_CONFIDENCE_BONUS
                scores[industry] = scores.get(industry, 0.0) + weight + bonus
                signals.setdefault(industry, []).extend(
                    f"{field}:{alias}" for alias in matched
                )
    if not scores:
        return IndustryMatch(
            "local_services",
            "unknown",
            (),
            UNKNOWN_INDUSTRY_CONFIDENCE,
            (),
            ("industry_unclear",),
            service_text=" ".join(
                _field_text(profile, field)
                for field in (
                    "description",
                    "website_description",
                    "services",
                    "products",
                    "offering_text",
                    "business_description",
                )
            ).casefold(),
        )
    industry = max(scores, key=scores.get)
    confidence = min(
        MAX_INDUSTRY_CONFIDENCE,
        BASE_INDUSTRY_CONFIDENCE + scores[industry] / CONFIDENCE_SCORE_DIVISOR,
    )
    return IndustryMatch(
        industry,
        industry,
        (),
        confidence,
        tuple(signals[industry]),
        ("industry_confidence_low",) if confidence < LOW_INDUSTRY_CONFIDENCE else (),
        service_text=" ".join(
            _field_text(profile, field)
            for field in (
                "description",
                "website_description",
                "services",
                "products",
                "offering_text",
                "business_description",
            )
        ).casefold(),
    )


def select_intents(
    match: IndustryMatch, not_offered: str = ""
) -> tuple[IntentSpec, ...]:
    """Keep only intents supported by known services and not excluded."""
    excluded = not_offered.casefold()
    intents = INDUSTRY_INTENTS.get(match.industry, INDUSTRY_INTENTS["local_services"])
    return tuple(
        intent
        for intent in intents
        if (not intent.required_service or intent.required_service.casefold() in match.service_text)
        and not (
            (intent.required_service and intent.required_service.casefold() in excluded)
            or intent.key.casefold() in excluded
        )
    )

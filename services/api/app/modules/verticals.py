"""Canonical business verticals — one taxonomy, three consumers.

A vertical is the answer to "what kind of business is this?". It is the seed
for (1) the owner's onboarding questions, (2) the review subcategories the AI
may assign, and (3) benchmark peer grouping. Keeping one catalog means a
tenant's category choice can never make those three disagree.

The old lookup in ``review_engine.classification`` matched business-type
*labels* by substring. That silently sent "E-commerce" and "Non-profit" to
``other`` (punctuation/underscore mismatches) and had no retail entry at all.
Keys here are canonical and the label → key map is explicit, so resolution is
exact rather than fuzzy.

Google's Business Profile has ~4,000 category display names. We do not try to
mirror them: ``google_hints`` are keyword fragments matched against the
category Google returns, and the raw display name is kept by the caller.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# Canonical sections used to group questions on the dashboard and to deep-link
# back into the flow. Keys are stable; labels are display copy and may change.
SECTIONS: tuple[tuple[str, str], ...] = (
    ("offering", "What you offer"),
    ("orders", "Orders & booking"),
    ("payments", "Payments & pricing"),
    ("access", "Access & facilities"),
)
SECTION_LABELS: dict[str, str] = dict(SECTIONS)

# Grouping is by ``fact_key``, not question key. ``support`` is support
# channels for a SaaS but donation options for a non-profit; those belong in
# different sections, and only the fact key distinguishes them.
SECTION_BY_FACT_KEY: dict[str, str] = {
    # What the business sells, serves or does.
    "menu_highlights": "offering",
    "dietary": "offering",
    "products": "offering",
    "brands": "offering",
    "extra_services": "offering",
    "pharmacy_services": "offering",
    "stock": "offering",
    "services": "offering",
    "specialties": "offering",
    "facilities": "offering",
    "classes": "offering",
    "programs": "offering",
    "age_groups": "offering",
    "event_types": "offering",
    "occasions": "offering",
    "turnaround": "offering",
    "credentials": "offering",
    "integrations": "offering",
    "mission": "offering",
    "support_options": "offering",
    "support_channels": "offering",
    "process": "offering",
    "about": "offering",
    # How a customer orders, books or receives.
    "delivery": "orders",
    "takeout": "orders",
    "ordering": "orders",
    "booking": "orders",
    "reservations": "orders",
    "service_area_detail": "orders",
    "shipping": "orders",
    "returns": "orders",
    "min_order": "orders",
    "walk_in": "orders",
    "enrollment": "orders",
    "emergency": "orders",
    # What it costs and how it is paid for.
    "payments": "payments",
    "price_range": "payments",
    "pricing_model": "payments",
    "insurance": "payments",
    "fees": "payments",
    "membership": "payments",
    "cash_services": "payments",
    # Physical and language access.
    "parking": "access",
    "accessibility": "access",
    "outdoor_seating": "access",
    "workspace": "access",
    "languages_spoken": "access",
    "hours": "access",
    "address": "access",
    "phone": "access",
}


@dataclass(frozen=True)
class IntakeQuestion:
    """One question the owner can answer by tapping, never by typing.

    ``source`` decides whether we ask at all:
      google         - already read from Google, never shown
      google_partial - Google may have it; show its value for confirmation
      ask            - Google has no such field; this is what we ask
    """

    key: str
    label: str
    source: str = "ask"
    options: tuple[str, ...] = ()
    multiple: bool = True
    # Where the answer lands in the materialised facts row.
    fact_key: str = ""
    # Dashboard grouping. Foreign-key-ish value from SECTION_LABELS.
    section: str = "offering"


@dataclass(frozen=True)
class SubFocus:
    key: str
    label: str
    questions: tuple[IntakeQuestion, ...] = ()
    google_hints: tuple[str, ...] = ()


@dataclass(frozen=True)
class Vertical:
    key: str
    label: str
    review_subcategories: tuple[str, ...]
    google_hints: tuple[str, ...] = ()
    sub_focuses: tuple[SubFocus, ...] = field(default_factory=tuple)


def _q(
    key: str,
    label: str,
    *options: str,
    source: str = "ask",
    multiple: bool = True,
    fact_key: str = "",
) -> IntakeQuestion:
    resolved_fact_key = fact_key or key
    return IntakeQuestion(
        key=key,
        label=label,
        source=source,
        options=tuple(options),
        multiple=multiple,
        fact_key=resolved_fact_key,
        section=SECTION_BY_FACT_KEY.get(resolved_fact_key, "offering"),
    )


# Questions that come straight from Google. They exist in the catalog so the
# UI can render "already known from Google" instead of an empty gap, but the
# client never asks the owner to re-enter them.
_GOOGLE_CORE = (
    _q("hours", "Opening hours", source="google", fact_key="hours"),
    _q("address", "Address", source="google", fact_key="address"),
    _q("phone", "Phone number", source="google", fact_key="phone"),
)

_DELIVERY = _q(
    "delivery", "Do you offer delivery?", "Yes", "No", "Coming soon", "Not sure",
    source="google_partial", multiple=False, fact_key="delivery",
)
_TAKEOUT = _q(
    "takeout", "Do you offer takeaway?", "Yes", "No", "Not sure",
    source="google_partial", multiple=False, fact_key="takeout",
)
_OUTDOOR = _q(
    "outdoor_seating", "Outdoor seating?", "Yes", "No", "Not sure",
    source="google_partial", multiple=False, fact_key="outdoor_seating",
)
_PAYMENT = _q(
    "payments", "How can customers pay?", "Cash", "Credit card", "Debit card",
    "Mobile wallet", source="google_partial", fact_key="payments",
)
_ACCESSIBILITY = _q(
    "accessibility", "Accessibility", "Step-free entrance", "Accessible parking",
    "Accessible restroom", source="google_partial", fact_key="accessibility",
)
_NOT_SURE_NOTE = "Not sure"  # valid everywhere; recorded as unknown, never as a fact

_PRICE = _q(
    "price_range", "Typical price", "Under 50", "50–100", "100–200", "200+",
    multiple=False, fact_key="price_range",
)
_PARKING = _q(
    "parking", "Parking", "Free parking", "Paid parking", "Street parking",
    "Valet", "No parking", fact_key="parking",
)
_LANGUAGES = _q(
    "languages_spoken", "Languages your team speaks", "English", "Arabic",
    "French", "Spanish", "Hindi", "Other", fact_key="languages_spoken",
)
_BOOKING = _q(
    "booking", "How do customers book?", "Online", "By phone", "Walk-in only",
    "WhatsApp", "Email", fact_key="booking",
)
_SERVICE_AREA = _q(
    "service_area_detail", "Where do you serve?", "City centre", "North district",
    "South district", "Nationwide", "Pickup only", fact_key="service_area_detail",
)


VERTICALS: dict[str, Vertical] = {
    "restaurant": Vertical(
        key="restaurant",
        label="Food & Restaurant",
        google_hints=("restaurant", "pizza", "italian", "sushi", "burger", "steakhouse",
                      "seafood", "indian", "chinese", "thai", "mediterranean", "grill",
                      "barbecue", "bistro", "brasserie"),
        review_subcategories=("food_temperature", "food_taste", "wait_time", "service",
                              "parking", "cleanliness", "portions", "allergen"),
        sub_focuses=(
            SubFocus(
                key="dine_in", label="Dine-in restaurant",
                google_hints=("restaurant", "bistro", "brasserie", "steakhouse"),
                questions=_GOOGLE_CORE + (
                    _q("signature_dishes", "Signature dishes", fact_key="menu_highlights"),
                    _q("dietary", "Dietary options", "Halal", "Vegetarian", "Vegan",
                       "Gluten-free", "Nut-free", fact_key="dietary"),
                    _PRICE,
                    _q("reservations", "Reservations", "Online booking", "By phone",
                       "Walk-in only", "Not needed", fact_key="reservations"),
                    _q("occasions", "Good for", "Families", "Date night", "Groups",
                       "Business lunch", fact_key="occasions"),
                    _PARKING, _PAYMENT, _OUTDOOR, _ACCESSIBILITY, _LANGUAGES,
                ),
            ),
            SubFocus(
                key="cafe", label="Cafe / coffee shop", google_hints=("coffee", "cafe", "tea"),
                questions=_GOOGLE_CORE + (
                    _q("drinks", "What do you serve?", "Coffee", "Tea", "Smoothies",
                       "Bakery items", "Light meals", fact_key="menu_highlights"),
                    _q("workspace", "Workspace", "Free wifi", "Power sockets",
                       "Quiet area", "Outdoor seating", fact_key="workspace"),
                    _PRICE, _PAYMENT, _LANGUAGES,
                ),
            ),
            SubFocus(
                key="takeaway", label="Fast food / takeaway",
                google_hints=("fast food", "takeout", "delivery", "pizza delivery"),
                questions=_GOOGLE_CORE + (
                    _q("popular_items", "Most popular items", fact_key="menu_highlights"),
                    _q("ordering", "How to order", "Online", "By phone", "WhatsApp",
                       "In person", fact_key="ordering"),
                    _DELIVERY, _TAKEOUT, _SERVICE_AREA, _PRICE, _PAYMENT,
                ),
            ),
            SubFocus(
                key="bakery", label="Bakery", google_hints=("bakery", "bread", "pastry"),
                questions=_GOOGLE_CORE + (
                    _q("baked_items", "What do you bake?", "Bread", "Pastries", "Cakes",
                       "Custom orders", fact_key="menu_highlights"),
                    _PRICE, _TAKEOUT, _PAYMENT, _LANGUAGES,
                ),
            ),
            SubFocus(
                key="catering", label="Catering", google_hints=("catering", "event catering"),
                questions=_GOOGLE_CORE + (
                    _q("cuisine", "Cuisine", fact_key="menu_highlights"),
                    _q("event_types", "Event types", "Weddings", "Corporate", "Parties",
                       "Funerals", fact_key="event_types"),
                    _SERVICE_AREA, _q("min_order", "Minimum order", fact_key="min_order"),
                    _LANGUAGES,
                ),
            ),
        ),
    ),
    "cafe": Vertical(
        key="cafe", label="Cafe & Bakery", google_hints=("coffee", "cafe", "bakery", "tea house"),
        review_subcategories=("coffee_quality", "wait_time", "service", "seating", "menu"),
        sub_focuses=(
            SubFocus(key="general", label="Cafe & bakery", questions=_GOOGLE_CORE + (
                _q("menu", "What do you serve?", "Coffee", "Tea", "Pastries", "Cakes",
                   "Breakfast", "Light meals", fact_key="menu_highlights"),
                _q("dietary", "Dietary options", "Halal", "Vegetarian", "Vegan",
                   "Gluten-free", fact_key="dietary"),
                _q("workspace", "Workspace", "Free wifi", "Power sockets", "Quiet area",
                   fact_key="workspace"),
                _PRICE, _TAKEOUT, _OUTDOOR, _PAYMENT, _LANGUAGES,
            )),
        ),
    ),
    "retail": Vertical(
        key="retail", label="Retail & Shops",
        google_hints=("store", "shop", "retail", "clothing", "grocery", "hardware",
                      "electronics store", "furniture store", "book store"),
        review_subcategories=("stock", "price", "staff_help", "queue_time", "returns", "cleanliness"),
        sub_focuses=(
            SubFocus(key="general", label="Retail store", questions=_GOOGLE_CORE + (
                _q("products", "What do you sell?", fact_key="products"),
                _q("brands", "Brands you carry", fact_key="brands"),
                _q("services", "Extra services", "Delivery", "Gift wrapping", "Returns",
                   "Repairs", "Custom orders", fact_key="extra_services"),
                _PRICE, _PAYMENT, _PARKING, _LANGUAGES,
            )),
        ),
    ),
    "ecommerce": Vertical(
        key="ecommerce", label="E-commerce",
        google_hints=("online store", "e-commerce", "online shop"),
        review_subcategories=("shipping_time", "lost_package", "damaged_item", "wrong_item",
                              "returns_process", "payment_failed", "product_quality"),
        sub_focuses=(
            SubFocus(key="general", label="Online store", questions=_GOOGLE_CORE + (
                _q("catalogue", "What do you sell?", fact_key="products"),
                _q("shipping", "Delivery options", "Local pickup", "Nationwide shipping",
                   "International shipping", "Same-day", fact_key="shipping"),
                _q("returns", "Returns policy", "Within 7 days", "Within 14 days",
                   "Within 30 days", "No returns", fact_key="returns"),
                _PAYMENT, _LANGUAGES,
            )),
        ),
    ),
    "pharmacy": Vertical(
        key="pharmacy", label="Pharmacy", google_hints=("pharmacy", "drug store", "chemist"),
        review_subcategories=("availability", "price", "service_speed", "consultation", "stock"),
        sub_focuses=(
            SubFocus(key="general", label="Pharmacy", questions=_GOOGLE_CORE + (
                _q("prescriptions", "Prescription service", "Accept e-prescriptions",
                   "Prescription delivery", "Consultation", "Refill reminders",
                   fact_key="pharmacy_services"),
                _q("stock", "What do you stock?", "Prescription medicines", "Over-the-counter",
                   "Vitamins", "Medical devices", "Baby care", fact_key="stock"),
                _q("insurance", "Insurance", fact_key="insurance"),
                _DELIVERY, _PARKING, _PAYMENT, _LANGUAGES,
            )),
        ),
    ),
    "bank": Vertical(
        key="bank", label="Bank / Finance",
        google_hints=("bank", "atm", "credit union", "financial", "loan"),
        review_subcategories=("card_issue", "transaction_error", "account_fees", "queue_time", "app_outage"),
        sub_focuses=(
            SubFocus(key="general", label="Bank branch", questions=_GOOGLE_CORE + (
                _q("products", "What do you offer?", "Personal accounts", "Business accounts",
                   "Loans", "Cards", "Investments", "Currency exchange", fact_key="products"),
                _q("appointment", "Appointments", "Walk-in welcome", "By appointment only",
                   "Online", fact_key="booking"),
                _q("cash", "Cash services", "ATM on site", "Cash desk", "Cashless only",
                   fact_key="cash_services"),
                _ACCESSIBILITY, _PARKING, _LANGUAGES,
            )),
        ),
    ),
    "saas": Vertical(
        key="saas", label="AI / SaaS / Software",
        google_hints=("software", "saas", "technology", "computer", "it company", "web design"),
        review_subcategories=("billing", "login", "integrations", "performance", "onboarding", "support"),
        sub_focuses=(
            SubFocus(key="general", label="Software company", questions=_GOOGLE_CORE + (
                _q("product", "What is your main product?", fact_key="products"),
                _q("pricing_model", "Pricing model", "Free trial", "Freemium", "Subscription",
                   "One-time purchase", "Custom quote", fact_key="pricing_model"),
                _q("support", "Support channels", "Email", "Live chat", "WhatsApp", "Phone",
                   "Dedicated manager", fact_key="support_channels"),
                _q("integrations", "Integrations", fact_key="integrations"),
                _LANGUAGES,
            )),
        ),
    ),
    "agency": Vertical(
        key="agency", label="Agency",
        google_hints=("agency", "marketing", "advertising", "consulting"),
        review_subcategories=("project_timeline", "deliverable", "billing", "communication"),
        sub_focuses=(
            SubFocus(key="general", label="Agency", questions=_GOOGLE_CORE + (
                _q("services", "What do you do?", "Marketing", "Design", "Development",
                   "Consulting", "Recruitment", "PR", fact_key="products"),
                _q("process", "How a project starts", "Free consultation", "Discovery call",
                   "Brief form", "Proposal", fact_key="process"),
                _q("pricing_model", "Pricing", "Hourly", "Fixed project", "Retainer",
                   "Custom quote", fact_key="pricing_model"),
                _LANGUAGES,
            )),
        ),
    ),
    "healthcare": Vertical(
        key="healthcare", label="Healthcare & Clinics",
        google_hints=("clinic", "hospital", "doctor", "dentist", "medical", "dental",
                      "physiotherapy", "veterinary", "eye", "dermatolog"),
        review_subcategories=("wait_time", "diagnosis_quality", "billing", "staff_attitude", "facility"),
        sub_focuses=(
            SubFocus(key="clinic", label="Medical clinic",
                     google_hints=("clinic", "doctor", "medical"), questions=_GOOGLE_CORE + (
                _q("specialties", "Specialties", fact_key="specialties"),
                _q("insurance", "Insurance accepted", fact_key="insurance"),
                _BOOKING,
                _q("walk_in", "Walk-ins", "Welcome", "By appointment only", "Emergency only",
                   multiple=False, fact_key="walk_in"),
                _LANGUAGES, _ACCESSIBILITY, _PARKING,
            )),
            SubFocus(key="dental", label="Dental clinic", google_hints=("dentist", "dental"),
                     questions=_GOOGLE_CORE + (
                _q("treatments", "Treatments", "Cleaning", "Fillings", "Implants",
                   "Orthodontics", "Whitening", fact_key="services"),
                _q("insurance", "Insurance accepted", fact_key="insurance"),
                _BOOKING, _PAYMENT, _LANGUAGES,
            )),
            SubFocus(key="hospital", label="Hospital", google_hints=("hospital",),
                     questions=_GOOGLE_CORE + (
                _q("departments", "Departments", fact_key="specialties"),
                _q("emergency", "Emergency department", "24/7", "Daytime only", "None",
                   multiple=False, fact_key="emergency"),
                _q("insurance", "Insurance accepted", fact_key="insurance"),
                _ACCESSIBILITY, _PARKING, _LANGUAGES,
            )),
        ),
    ),
    "beauty": Vertical(
        key="beauty", label="Beauty & Salon",
        google_hints=("salon", "hair", "beauty", "spa", "nail", "barber"),
        review_subcategories=("service_quality", "wait_time", "smoothness", "staff", "booking"),
        sub_focuses=(
            SubFocus(key="general", label="Salon & spa", questions=_GOOGLE_CORE + (
                _q("services", "Services", "Haircut", "Colouring", "Manicure", "Pedicure",
                   "Massage", "Facial", fact_key="services"),
                _BOOKING, _PRICE, _PAYMENT, _LANGUAGES,
            )),
        ),
    ),
    "fitness": Vertical(
        key="fitness", label="Gym & Fitness",
        google_hints=("gym", "fitness", "crossfit", "yoga", "pilates", "swimming"),
        review_subcategories=("equipment", "trainers", "cleanliness", "scheduling", "billing"),
        sub_focuses=(
            SubFocus(key="general", label="Gym", questions=_GOOGLE_CORE + (
                _q("facilities", "Facilities", "Weights", "Cardio machines", "Classes",
                   "Pool", "Sauna", "Personal training", fact_key="facilities"),
                _q("membership", "Membership", "Monthly", "Annual", "Day pass", "No contract",
                   fact_key="membership"),
                _q("classes", "Classes", "Yoga", "Pilates", "HIIT", "Spinning", "Strength",
                   fact_key="classes"),
                _PARKING, _PAYMENT, _LANGUAGES,
            )),
        ),
    ),
    "education": Vertical(
        key="education", label="Education",
        google_hints=("school", "university", "college", "academy", "tutoring", "training",
                      "preschool", "kindergarten"),
        review_subcategories=("course_content", "scheduling", "instructor", "materials", "billing"),
        sub_focuses=(
            SubFocus(key="general", label="School / training centre", questions=_GOOGLE_CORE + (
                _q("programs", "Programs", fact_key="programs"),
                _q("age_groups", "Age groups", "Preschool", "Primary", "Secondary",
                   "University", "Adults", fact_key="age_groups"),
                _q("enrollment", "Enrollment", "Open all year", "Term intake", "Waitlist",
                   "Application required", fact_key="enrollment"),
                _q("fees", "Fees", fact_key="fees"),
                _LANGUAGES, _ACCESSIBILITY, _PARKING,
            )),
        ),
    ),
    "media": Vertical(
        key="media", label="Media / Content",
        google_hints=("media", "publisher", "content", "photography", "studio", "printing"),
        review_subcategories=("content_quality", "ad_relevance", "functionality", "billing"),
        sub_focuses=(
            SubFocus(key="general", label="Media company", questions=_GOOGLE_CORE + (
                _q("services", "What do you produce?", "Photography", "Video", "Design",
                   "Writing", "Printing", "Social media", fact_key="products"),
                _q("turnaround", "Typical turnaround", fact_key="turnaround"),
                _LANGUAGES,
            )),
        ),
    ),
    "professional": Vertical(
        key="professional", label="Professional Services",
        google_hints=("lawyer", "accountant", "consultant", "notary", "real estate", "insurance agency"),
        review_subcategories=("communication", "billing", "deliverable_quality", "timeliness"),
        sub_focuses=(
            SubFocus(key="general", label="Professional services", questions=_GOOGLE_CORE + (
                _q("services", "What do you offer?", fact_key="products"),
                _q("credentials", "Qualifications", fact_key="credentials"),
                _BOOKING, _LANGUAGES, _PARKING,
            )),
        ),
    ),
    "non_profit": Vertical(
        key="non_profit", label="Non-profit",
        google_hints=("non-profit", "nonprofit", "charity", "foundation", "association", "ngo"),
        review_subcategories=("program_quality", "accessibility", "staff", "facility"),
        sub_focuses=(
            SubFocus(key="general", label="Non-profit", questions=_GOOGLE_CORE + (
                _q("mission", "Your mission", fact_key="mission"),
                _q("programs", "Programs", fact_key="programs"),
                _q("support", "How people can help", "Donate", "Volunteer", "Partnership",
                   "Spread the word", fact_key="support_options"),
                _LANGUAGES, _ACCESSIBILITY,
            )),
        ),
    ),
    "other": Vertical(
        key="other", label="Other",
        review_subcategories=("general",),
        sub_focuses=(
            SubFocus(key="general", label="My business", questions=_GOOGLE_CORE + (
                _q("business_description", "What does your business do?", fact_key="about"),
                _q("products", "What do you sell or offer?", fact_key="products"),
                _BOOKING, _PRICE, _PAYMENT, _LANGUAGES, _PARKING,
            )),
        ),
    ),
}

# Exact label -> key. The frontend stores these labels verbatim in
# users.business_type, so this map is the migration path to canonical keys.
LABEL_TO_KEY: dict[str, str] = {v.label.lower(): k for k, v in VERTICALS.items()}
LABEL_TO_KEY.update({
    "non-profit": "non_profit",
    "non profit": "non_profit",
    "e-commerce": "ecommerce",
    "ecommerce": "ecommerce",
    "it / saas / software": "saas",
    "bank / finance": "bank",
})


def resolve_vertical(value: str | None) -> str | None:
    """Resolve a canonical key, stored label, or Google category to a key.

    Exact-key and exact-label lookups come first. Only then do we fall back to
    Google hint fragments — an ordered scan, so "coffee shop" resolves to the
    cafe vertical rather than to restaurant's "cafe" sub-focus.
    """
    if not value or not value.strip():
        return None
    raw = value.strip()
    lowered = raw.lower()
    if lowered in VERTICALS:
        return lowered
    if lowered in LABEL_TO_KEY:
        return LABEL_TO_KEY[lowered]
    # Most specific verticals first: a Google category "Coffee shop" must not
    # be swallowed by restaurant's generic "cafe" hint.
    ordered = [k for k in VERTICALS if k != "other"]
    for key in ordered:
        for hint in VERTICALS[key].google_hints:
            if hint in lowered:
                return key
    return "other"


def google_vertical(category_display_name: str | None) -> str | None:
    """Map Google's primaryCategory displayName to a canonical vertical key."""
    return resolve_vertical(category_display_name)


def questions_for(vertical_key: str, sub_focus: str | None) -> tuple[IntakeQuestion, ...]:
    """Questions shown to the owner: only those Google cannot already supply."""
    vertical = VERTICALS.get(vertical_key) or VERTICALS["other"]
    focus = next(
        (f for f in vertical.sub_focuses if f.key == sub_focus),
        vertical.sub_focuses[0] if vertical.sub_focuses else None,
    )
    if focus is None:
        return ()
    return tuple(q for q in focus.questions if q.source != "google")


def review_subcategories(vertical_key: str | None) -> list[str]:
    key = resolve_vertical(vertical_key) or "other"
    return list(VERTICALS[key].review_subcategories)

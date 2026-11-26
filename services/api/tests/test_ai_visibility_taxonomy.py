"""Business-aware industry classification and intent selection."""

from app.modules.ai_visibility.taxonomy import (
    INDUSTRY_INTENTS,
    classify_industry,
    publishing_recommendations,
    select_intents,
)


def test_classification_combines_name_category_and_description():
    match = classify_industry(
        {
            "name": "MenteE",
            "categories": ["Software company"],
            "description": (
                "AI research lab building language models and recruitment software"
            ),
            "services": ["AI research", "software engineering"],
        }
    )
    assert match.industry == "software_company"
    assert match.confidence >= 0.8
    assert match.matched_signals


def test_restaurant_and_hospital_receive_different_intents():
    restaurant = select_intents(
        classify_industry(
            {
                "name": "Al Narjes Restaurant",
                "categories": ["Restaurant"],
                "description": "Mandi and grilled dishes with family dining and delivery",
            }
        )
    )
    hospital = select_intents(
        classify_industry(
            {
                "name": "Noor Medical City",
                "categories": ["Hospital"],
                "description": "Emergency care, maternity, pediatrics and diagnostics",
            }
        )
    )
    restaurant_keys = {row.key for row in restaurant}
    hospital_keys = {row.key for row in hospital}
    assert "cuisine" in restaurant_keys
    assert "emergency_care" in hospital_keys
    assert "cuisine" not in hospital_keys


def test_service_specific_intent_is_skipped_without_the_service():
    match = classify_industry(
        {
            "name": "Smile Dental",
            "categories": ["Dental clinic"],
            "description": "General dentistry and teeth cleaning",
        }
    )
    assert "maternity" not in {row.key for row in select_intents(match)}


def test_low_information_profile_is_marked_uncertain():
    match = classify_industry({"name": "Local Shop"})
    assert match.industry == "local_services"
    assert match.confidence < 0.5
    assert "industry_unclear" in match.uncertainties


def test_workspace_offering_text_can_classify_a_branch_without_category():
    match = classify_industry(
        {
            "name": "MenteE",
            "offering_text": "AI research and software development for recruitment teams",
        }
    )
    assert match.industry == "software_company"
    assert match.confidence > 0.5


def test_website_description_can_classify_a_sparse_profile():
    match = classify_industry(
        {"name": "MenteE", "website_description": "AI research lab and software development"}
    )
    assert match.industry == "software_company"


def test_publishing_recommendations_are_industry_specific():
    software = publishing_recommendations("software_company")
    hotel = publishing_recommendations("hotel")
    assert {row["platform"] for row in software} >= {"LinkedIn", "Medium", "Substack"}
    assert {row["platform"] for row in hotel} >= {"Booking.com", "TripAdvisor"}
    assert all(row["setup_url"].startswith("https://") for row in software + hotel)


def test_each_required_industry_has_its_own_customer_intents():
    cases = (
        ("school", "International School", "admissions"),
        ("hotel", "Grand Hotel", "booking"),
        ("ecommerce", "Online Store", "shipping"),
        ("real_estate", "Real Estate Agency", "property_types"),
        ("law_firm", "Law Firm", "legal_specialties"),
        ("salon", "Beauty Salon", "salon_services"),
        ("automobile_dealership", "Car Dealership", "vehicle_inventory"),
        ("retail_store", "Electronics Store", "product_availability"),
        ("recruitment", "Recruitment Office", "licensing"),
    )
    for industry, name, expected_intent in cases:
        match = classify_industry({"name": name, "categories": [name]})
        assert match.industry == industry
        assert expected_intent in {row.key for row in select_intents(match)}


def test_every_intent_has_natural_english_and_arabic_templates():
    for intents in INDUSTRY_INTENTS.values():
        for intent in intents:
            assert intent.en and intent.ar
            assert all("{name}" in template for template in intent.en + intent.ar)

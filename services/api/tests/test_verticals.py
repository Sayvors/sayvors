"""The vertical catalog is the seed for onboarding, reviews and benchmarks.

These tests pin the three label resolutions the old substring matcher got
wrong, plus the contract that Google-sourced questions are never asked twice.
"""
from app.modules.profile.facts_tool import render_topic
from app.modules.review_engine.classification import default_subcategories
from app.modules.verticals import (
    SECTIONS,
    SECTION_LABELS,
    VERTICALS,
    google_vertical,
    questions_for,
    resolve_vertical,
    review_subcategories,
)


def test_all_front_end_labels_resolve_to_a_key():
    labels = [
        "Food & Restaurant", "Cafe & Bakery", "Retail & Shops", "E-commerce",
        "Pharmacy", "Bank / Finance", "AI / SaaS / Software", "Agency",
        "Healthcare & Clinics", "Beauty & Salon", "Gym & Fitness", "Education",
        "Media / Content", "Professional Services", "Non-profit", "Other",
    ]
    for label in labels:
        assert resolve_vertical(label) in VERTICALS, label


def test_three_previously_broken_labels():
    assert resolve_vertical("E-commerce") == "ecommerce"
    assert resolve_vertical("Non-profit") == "non_profit"
    assert resolve_vertical("Retail & Shops") == "retail"
    assert default_subcategories("Retail & Shops") == list(VERTICALS["retail"].review_subcategories)
    assert default_subcategories("E-commerce") == list(VERTICALS["ecommerce"].review_subcategories)
    assert default_subcategories("Non-profit") == list(VERTICALS["non_profit"].review_subcategories)


def test_canonical_key_and_case_insensitive():
    assert resolve_vertical("restaurant") == "restaurant"
    assert resolve_vertical("  PHARMACY ") == "pharmacy"
    assert resolve_vertical(None) is None
    assert resolve_vertical("") is None
    assert resolve_vertical("something unrecognised") == "other"


def test_google_category_maps_to_vertical():
    assert google_vertical("Italian restaurant") == "restaurant"
    assert google_vertical("Coffee shop") == "cafe"
    assert google_vertical("Dental clinic") == "healthcare"
    assert google_vertical("Pharmacy") == "pharmacy"
    assert google_vertical("Bakery") == "cafe"


def test_google_sourced_questions_are_never_shown():
    for key in VERTICALS:
        focus = VERTICALS[key].sub_focuses[0].key
        shown = questions_for(key, focus)
        assert all(q.source != "google" for q in shown), key
        # Every vertical still has something to ask.
        assert shown, key


def test_sub_focus_changes_question_set():
    dine_in = {q.key for q in questions_for("restaurant", "dine_in")}
    takeaway = {q.key for q in questions_for("restaurant", "takeaway")}
    assert "reservations" in dine_in
    assert "reservations" not in takeaway
    assert "service_area_detail" in takeaway
    assert "service_area_detail" not in dine_in


def test_review_subcategories_never_empty():
    for key in VERTICALS:
        assert review_subcategories(key), key


def test_every_shown_question_has_a_known_section():
    for key in VERTICALS:
        for focus in VERTICALS[key].sub_focuses:
            for q in questions_for(key, focus.key):
                assert q.section in SECTION_LABELS, (key, focus.key, q.key)
                assert q.section != "", (key, focus.key, q.key)


def test_sections_follow_the_canonical_order():
    keys = [key for key, _ in SECTIONS]
    assert keys == ["offering", "orders", "payments", "access"]
    # Spot-check that roles, not question names, decide the section.
    dine_in = {q.key: q for q in questions_for("restaurant", "dine_in")}
    assert dine_in["dietary"].section == "offering"
    assert dine_in["reservations"].section == "orders"
    assert dine_in["price_range"].section == "payments"
    assert dine_in["parking"].section == "access"


def test_section_grouping_uses_fact_key_when_keys_collide():
    # Both verticals have a "support" question; the fact keys differ and the
    # same key must not force them into one bucket.
    saas = {q.key: q for q in questions_for("saas", "general")}
    non_profit = {q.key: q for q in questions_for("non_profit", "general")}
    assert saas["support"].fact_key == "support_channels"
    assert non_profit["support"].fact_key == "support_options"


def test_owner_answers_are_rendered_to_the_reply_path():
    facts = {
        "business": {
            "intake": {
                "dietary": ["Halal", "Vegan"],
                "parking": "Free parking",
                "skipped_question": None,
            }
        }
    }
    text = render_topic(facts, "services")
    assert "confirmed by the owner" in text
    assert "Halal, Vegan" in text
    assert "Free parking" in text
    assert "skipped_question" not in text
    assert render_topic({"business": {}}, "details") == ""

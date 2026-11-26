"""Dynamic customer questions generated from a branch's real business profile."""

from app.modules.ai_visibility.questions import generate_questions


def test_software_company_gets_software_customer_questions():
    questions = generate_questions(
        {
            "name": "MenteE",
            "categories": {"category": "Software company"},
            "description": "AI research lab building language models and recruitment software",
            "services": ["AI research", "software engineering"],
            "address": "Mingora, Swat, Pakistan",
        },
        limit=6,
    )
    assert questions
    assert all("restaurant" not in row.question_text.casefold() for row in questions)
    assert any("product" in row.question_text.casefold() or "build" in row.question_text.casefold() for row in questions)
    assert all(row.intent in {"product_discovery", "use_cases", "alternatives"} for row in questions)


def test_saudi_profile_generates_arabic_first_and_english_second():
    questions = generate_questions(
        {
            "name": "Sayvors Company Branch-Makkah",
            "categories": {"category": "Recruitment office"},
            "description": "Licensed manpower and domestic worker recruitment",
            "services": ["Domestic worker recruitment", "Manpower supply"],
            "address": "Azziziya, Makkah, 11432",
            "service_area": ["Makkah", "Jeddah"],
        },
        limit=6,
    )
    languages = [row.language for row in questions]
    assert "ar" in languages and "en" in languages
    assert languages[0] == "ar"
    assert any("مكة" in row.question_text or "Makkah" in row.question_text for row in questions)


def test_questions_include_metadata_and_are_deduplicated():
    questions = generate_questions(
        {
            "name": "Noor Medical City",
            "categories": {"category": "Hospital"},
            "description": "Emergency care, maternity, pediatrics and diagnostics in Riyadh",
            "address": "Riyadh",
        },
        limit=8,
    )
    assert 1 <= len(questions) <= 8
    assert len({row.question_text.casefold() for row in questions}) == len(questions)
    for row in questions:
        assert row.intent
        assert row.language in {"ar", "en"}
        assert row.geographic_context
        assert 0 <= row.industry_relevance <= 100
        assert 0 <= row.service_relevance <= 100
        assert 0 <= row.business_relevance_score <= 100
        assert row.priority in {"P0", "P1", "P2"}


def test_unsupported_service_question_is_not_generated():
    questions = generate_questions(
        {
            "name": "Smile Dental",
            "categories": {"category": "Dental clinic"},
            "description": "General dentistry and teeth cleaning",
            "address": "Jeddah",
        },
        limit=8,
    )
    assert not any("maternity" in row.question_text.casefold() for row in questions)


def test_real_customer_questions_are_prioritized_and_labelled():
    questions = generate_questions(
        {
            "name": "Sayvors Company Branch-Makkah",
            "categories": {"category": "Recruitment office"},
            "description": "Licensed manpower and domestic worker recruitment",
            "address": "Makkah",
            "customer_questions": [
                "Are you licensed in Makkah?",
                "Do you handle domestic workers?",
            ],
        },
        limit=6,
    )
    texts = [row.question_text for row in questions]
    assert "Are you licensed in Makkah?" in texts
    assert "Do you handle domestic workers?" in texts
    voice = next(row for row in questions if row.question_text == "Are you licensed in Makkah?")
    assert voice.service_relevance >= 90
    assert voice.business_relevance_score >= 80


def test_customer_question_about_explicitly_unoffered_service_is_removed():
    questions = generate_questions(
        {
            "name": "Sayvors Branch",
            "categories": {"category": "Recruitment office"},
            "description": "Recruitment services",
            "address": "Makkah",
            "not_offered": "real estate sales",
            "customer_questions": ["Do you sell real estate in Makkah?"],
        },
        limit=8,
    )
    assert not any("real estate" in row.question_text.casefold() for row in questions)


def test_generic_support_chatter_is_not_treated_as_branch_customer_intent():
    questions = generate_questions(
        {
            "name": "Sayvors Company Branch-Makkah",
            "categories": {"category": "Software company"},
            "description": "Google review automation software",
            "services": ["Review automation", "Software development"],
            "address": "Makkah",
            "customer_questions": [
                "Update your mobile number please",
                "What is Google Maps?",
                "Do you have other branches?",
            ],
        },
        limit=8,
    )
    texts = [row.question_text for row in questions]
    assert "Update your mobile number please" not in texts
    assert "What is Google Maps?" not in texts
    assert "Do you have other branches?" not in texts


def test_relevant_customer_question_is_kept_ahead_of_templates():
    questions = generate_questions(
        {
            "name": "Sayvors",
            "categories": {"category": "Software company"},
            "description": "Google review automation software",
            "services": ["Review automation"],
            "address": "Makkah",
            "customer_questions": ["Does Sayvors automate Google review replies?"],
        },
        limit=8,
    )
    assert questions[0].question_text == "Does Sayvors automate Google review replies?"
    assert questions[0].service_relevance >= 90

"""Business profile assembly for dynamic AI Visibility questions."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.modules.ai_visibility import profile as profile_module
from app.modules.ai_visibility.profile import build_branch_facts
from app.modules.analytics.models import ConversationInsight, ReviewInsight
from app.modules.catalog.models import CatalogItem
from app.modules.channels.models import BusinessService, Channel
from app.modules.locations.models import LocationBusinessOverride, LocationProfile
from app.modules.profile.models import BusinessProfile
from app.modules.users.models import User


def test_branch_facts_include_override_services_and_service_area():
    channel = SimpleNamespace(
        display_name="Google Name",
        metadata_json=(
            '{"address":"Azziziya, Makkah", "locality":"Makkah", '
            '"phone":"+966 50 000 0000", "website":"https://sayvors.com", '
            '"maps_url":"https://maps.google.com/?cid=123", "location_id":"loc-1"}'
        ),
        listing_key="loc-1",
    )
    profile = SimpleNamespace(
        categories={"category": "Recruitment office", "subcategories": ["Manpower"]},
        description="Recruitment and manpower services",
        hours={"monday": ["09:00", "17:00"]},
        service_area=["Makkah", "Jeddah"],
        attributes={"languages": ["Arabic", "English"]},
        opening_date=None,
    )
    override = SimpleNamespace(
        name="Sayvors Company Branch-Makkah",
        categories={"category": "Labor office", "subcategories": ["Domestic workers"]},
        services=[{"label": "Domestic worker recruitment"}, "Manpower supply"],
        hours={},
    )

    facts = build_branch_facts(channel, profile, override)
    assert facts["name"] == "Sayvors Company Branch-Makkah"
    assert facts["address"] == "Azziziya, Makkah"
    assert facts["service_area"] == ["Makkah", "Jeddah"]
    assert facts["attributes"]["languages"] == ["Arabic", "English"]
    assert "Domestic worker recruitment" in facts["services"]
    assert "Manpower supply" in facts["services"]
    assert facts["categories"]["category"] == "Labor office"


def test_branch_facts_handle_google_category_shape_and_metadata_fallbacks():
    channel = SimpleNamespace(
        display_name="Al Narjes",
        metadata_json=(
            '{"address":"Al Malqa, Riyadh","city":"Riyadh","country":"SA",'
            '"description":"Family restaurant with delivery",'
            '"categories":{"primary":"Restaurant","additional":["Cafe"]},'
            '"service_area":["Riyadh"],"attributes":{"Delivery":"yes"}}'
        ),
        listing_key="loc-3",
    )
    profile = SimpleNamespace(
        categories={"primary": "Restaurant", "additional": ["Cafe"]},
        description=None,
        hours={},
        service_area=[],
        attributes={},
        opening_date=None,
    )
    facts = build_branch_facts(channel, profile, None)
    assert facts["categories"]["primary"] == "Restaurant"
    assert facts["categories"]["additional"] == ["Cafe"]
    assert facts["description"] == "Family restaurant with delivery"
    assert facts["service_area"] == ["Riyadh"]
    assert facts["attributes"] == {"Delivery": "yes"}
    assert facts["locality"] == "Riyadh"
    assert facts["country"] == "SA"


def test_branch_facts_ignore_postal_codes_when_deriving_locality():
    channel = SimpleNamespace(
        display_name="Sayvors Branch",
        metadata_json='{"address":"Azziziya, Makkah, 11432"}',
        listing_key="loc-4",
    )
    facts = build_branch_facts(channel, None, None)
    assert facts["locality"] == "Makkah"


def test_branch_facts_fall_back_to_google_values_without_override():
    channel = SimpleNamespace(
        display_name="MenteE",
        metadata_json='{"address":"Mingora, Swat", "website":"https://menteeai.org"}',
        listing_key="loc-2",
    )
    profile = SimpleNamespace(
        categories={"category": "Software company"},
        description="AI research lab",
        hours={},
        service_area=[],
        attributes={},
        opening_date=None,
    )
    facts = build_branch_facts(channel, profile, None)
    assert facts["name"] == "MenteE"
    assert facts["categories"]["category"] == "Software company"
    assert facts["services"] == []
    assert facts["description"] == "AI research lab"


@pytest.mark.asyncio
async def test_load_branch_facts_uses_tenant_scoped_override(
    db, user_id, channel_id, other_user_id
):
    channel = await db.get(Channel, channel_id)
    channel.metadata_json = (
        '{"location_id":"demo-loc-456","address":"Makkah",'
        '"website":"https://sayvors.com","maps_url":"https://maps.google.com/?cid=1"}'
    )
    db.add(
        LocationProfile(
            user_id=user_id,
            listing_id="demo-loc-456",
            description="Recruitment office",
            categories={"category": "Recruitment office"},
            service_area=["Makkah", "Jeddah"],
            attributes={"languages": ["Arabic", "English"]},
        )
    )
    db.add(
        LocationBusinessOverride(
            user_id=user_id,
            listing_id="demo-loc-456",
            name="Sayvors Branch",
            categories={"category": "Labor office"},
            services=[{"label": "Domestic worker recruitment"}],
        )
    )
    await db.commit()

    facts = await profile_module.load_branch_facts(db, user_id, channel_id)
    assert facts["name"] == "Sayvors Branch"
    assert facts["categories"]["category"] == "Labor office"
    assert facts["services"] == ["Domestic worker recruitment"]
    assert facts["service_area"] == ["Makkah", "Jeddah"]
    assert "service_area" in facts["source_fields"]

    with pytest.raises(ValueError, match="channel_not_owned"):
        await profile_module.load_branch_facts(db, other_user_id, channel_id)


@pytest.mark.asyncio
async def test_load_branch_facts_adds_workspace_services_products_and_customer_voice(
    db, user_id, channel_id
):
    from datetime import date

    db.add(
        User(
            id=user_id,
            first_name="Owner",
            last_name="Test",
            email="owner@example.com",
            password_hash="x",
            business_name="Sayvors Group",
            business_type="Recruitment",
            vertical_key="recruitment",
            business_description="Recruitment and manpower services",
            business_sells="Domestic worker recruitment",
            business_doesnt_sell="Real estate",
        )
    )
    db.add(
        BusinessProfile(
            user_id=user_id,
            summary="Licensed recruitment office",
            domain="Recruitment",
            products_services="Manpower supply and recruitment",
            not_offered_and_policies="No property sales",
        )
    )
    db.add_all(
        [
            BusinessService(
                channel_id=channel_id,
                name="Domestic worker recruitment",
                declared=True,
                is_offered=True,
            ),
            BusinessService(
                channel_id=channel_id,
                name="Undeclared suggestion",
                declared=False,
                is_offered=True,
            ),
        ]
    )
    db.add_all(
        [
            CatalogItem(
                id="active-product",
                tenant_id=user_id,
                name="Recruitment package",
                description="Domestic worker recruitment package",
                active=True,
            ),
            CatalogItem(
                id="inactive-product",
                tenant_id=user_id,
                name="Old package",
                active=False,
            ),
        ]
    )
    db.add(
        ReviewInsight(
            user_id=user_id,
            channel_id=channel_id,
            review_id="review-1",
            reviewer_name="Private Person",
            rating=5,
            review_text="Private review text",
            enrichment_status="done",
            topics=[{"name": "fast service"}],
            products=[{"name": "recruitment package"}],
            problems=[{"name": "none"}],
            meaning={"asks": ["Do you handle domestic workers?"]},
        )
    )
    db.add(
        ConversationInsight(
            tenant_id=user_id,
            window_start=date(2026, 11, 1),
            window_end=date(2026, 11, 26),
            message_count=10,
            insights={
                "top_questions": [{"question": "Are you licensed in Makkah?", "count": 3}],
                "topics": [{"topic": "recruitment"}],
                "intents": [{"intent": "hiring"}],
            },
        )
    )
    await db.commit()

    facts = await profile_module.load_branch_facts(db, user_id, channel_id)
    assert facts["workspace_business_type"] == "Recruitment"
    assert [row["name"] for row in facts["declared_services"]] == [
        "Domestic worker recruitment"
    ]
    assert [row["name"] for row in facts["products"]] == ["Recruitment package"]
    assert "fast service" in facts["review_themes"]
    assert "Are you licensed in Makkah?" in facts["customer_questions"]
    assert "Do you handle domestic workers?" in facts["customer_questions"]
    assert "recruitment" in facts["review_themes"]
    assert facts["customer_intents"] == ["hiring"]
    assert "Real estate" in facts["not_offered"]
    serialized = str(facts)
    assert "Private Person" not in serialized
    assert "Private review text" not in serialized


@pytest.mark.asyncio
async def test_customer_voice_scrubs_pii_and_known_reviewer_name(db, user_id, channel_id):
    from datetime import date

    db.add(
        ReviewInsight(
            user_id=user_id,
            channel_id=channel_id,
            review_id="review-pii",
            reviewer_name="Jane Doe",
            rating=5,
            enrichment_status="done",
            meaning={
                "asks": [
                    "Can JANE DOE email jane.doe@example.com or call "
                    "+966 50 123 4567 about order 123456789?"
                ]
            },
        )
    )
    db.add(
        ConversationInsight(
            tenant_id=user_id,
            window_start=date(2026, 11, 1),
            window_end=date(2026, 11, 26),
            message_count=10,
            insights={
                "top_questions": [
                    {"question": "Can sam.lee@example.com call +966 55 987 6543?"}
                ]
            },
        )
    )
    await db.commit()

    facts = await profile_module.load_branch_facts(db, user_id, channel_id)

    assert facts["customer_questions"] == [
        "Can [customer] email [email] or call [phone] about order [phone]?",
        "Can [email] call [phone]?",
    ]
    serialized = str(facts)
    assert "Jane Doe" not in serialized
    assert "JANE DOE" not in serialized
    assert "jane.doe@example.com" not in serialized
    assert "sam.lee@example.com" not in serialized
    assert "+966 50 123 4567" not in serialized
    assert "+966 55 987 6543" not in serialized
    assert "123456789" not in serialized


@pytest.mark.asyncio
async def test_load_business_profile_adds_public_website_context(monkeypatch, db, user_id, channel_id):
    async def _context(_tenant, _branch):
        return {
            "website": {
                "url": "https://sayvors.com",
                "title": "Sayvors review automation",
                "description": "AI review replies",
                "excerpt": "Sayvors reads Google reviews.",
            },
            "public_results": [],
            "uncertainties": [],
        }

    monkeypatch.setattr(profile_module, "collect_public_context", _context)
    profile = await profile_module.load_business_profile(db, user_id, channel_id)
    assert profile["website_title"] == "Sayvors review automation"
    assert profile["website_description"] == "AI review replies"
    assert profile["public_context"]["website"]["url"] == "https://sayvors.com"


@pytest.mark.asyncio
async def test_collect_public_context_reads_owned_website_and_relevant_results(monkeypatch):
    from app.modules.ai_visibility import sources
    from app.modules.ai_visibility.models import AiVisibilitySource
    from app.modules.ai_visibility.search import SearchResult

    async def _search(_tenant, _query, **_kwargs):
        return [
            SearchResult("https://sayvors.com/", "Sayvors", "Review automation"),
            SearchResult(
                "https://reviews.example/sayvors",
                "Sayvors reviews",
                "Sayvors review automation",
            ),
            SearchResult("https://translate.google.com/", "Translate", ""),
        ]

    async def _fetch(_run_id, _position, result):
        return (
            AiVisibilitySource(
                url=result.url,
                canonical_url=result.url,
                title="Sayvors — Google review automation",
                snippet="AI review replies in Arabic and English",
                excerpt="Sayvors reads Google reviews and replies automatically. " * 100,
            ),
            {"read": True},
        )

    monkeypatch.setattr(profile_module.search, "search_public_web", _search)
    monkeypatch.setattr(sources, "fetch_source", _fetch)
    context = await profile_module.collect_public_context(
        "tenant-1",
        {
            "name": "Sayvors Company Branch-Makkah",
            "address": "Makkah",
            "website": "https://sayvors.com",
        },
    )
    assert context["website"]["title"] == "Sayvors — Google review automation"
    assert context["website"]["description"] == "AI review replies in Arabic and English"
    assert context["public_results"]
    assert all("translate.google" not in row["url"] for row in context["public_results"])
    assert len(context["website"]["excerpt"]) <= 4000


@pytest.mark.asyncio
async def test_collect_public_context_records_website_failure(monkeypatch):
    from app.modules.ai_visibility import sources
    from app.modules.ai_visibility.models import AiVisibilitySource

    async def _search(*_args, **_kwargs):
        return []

    async def _fetch(*_args, **_kwargs):
        return (
            AiVisibilitySource(url="https://example.com", fetch_error="empty_extracted_text"),
            {"read": False},
        )

    monkeypatch.setattr(profile_module.search, "search_public_web", _search)
    monkeypatch.setattr(sources, "fetch_source", _fetch)
    context = await profile_module.collect_public_context(
        "tenant-1",
        {"name": "Example", "website": "https://example.com"},
    )
    assert context["website"] is None
    assert "website_unavailable" in context["uncertainties"]

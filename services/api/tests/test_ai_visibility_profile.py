"""Business profile assembly for dynamic AI Visibility questions."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.modules.ai_visibility import profile as profile_module
from app.modules.ai_visibility.profile import build_branch_facts
from app.modules.channels.models import Channel
from app.modules.locations.models import LocationBusinessOverride, LocationProfile


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

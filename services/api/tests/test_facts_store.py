"""The central facts store and the `get_business_facts` tool.

One row per tenant, built from the same sources the reply used to query one by
one. The interesting part is hours: several locations, some sharing a
schedule, some not — the assistant must be able to say that in one sentence.
"""
import pytest

from app.modules.profile.facts_store import (
    build_facts,
    compress_schedule,
    get_facts,
    normalise_schedule,
    rebuild_facts,
    render_locations,
)
from app.modules.profile.facts_tool import (
    detect_topics,
    render_topic,
    run_facts_tool,
)

TENANT = "facts-tenant-1"
WEEKDAY = {
    "Monday": {"open": "09:00", "close": "17:00"},
    "Tuesday": {"open": "09:00", "close": "17:00"},
    "Wednesday": {"open": "09:00", "close": "17:00"},
    "Thursday": {"open": "09:00", "close": "17:00"},
    "Friday": {"closed": True},
    "Saturday": {"open": "09:00", "close": "17:00"},
    "Sunday": {"open": "09:00", "close": "17:00"},
}
LATE = {day: {"open": "10:00", "close": "22:00"} for day in (
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
)}


async def _seed(db, *, late_branch: bool = True, locations: bool = True, legacy: bool = False):
    from app.modules.channels.models import BusinessService, Channel
    from app.modules.channels.meta.models import MetaAsset, MetaConnection
    from app.modules.localith.models import LocalithConnection
    from app.modules.locations.models import LocationProfile
    from app.modules.team.models import TeamMember, TeamRole
    from app.modules.users.models import User

    db.add(User(
        id=TENANT, email="facts@example.com", first_name="Shah", last_name="Khan",
        password_hash="x", email_verified=True,
        business_name="Sayvors", business_type="Software services",
        business_description="We build websites and software.",
        business_sells="Websites, e-commerce, mobile apps",
        business_doesnt_sell="Hardware",
    ))
    channel = Channel(
        id="facts-channel", user_id=TENANT, platform="whatsapp",
        platform_user_id="facts-phone", display_name="Sayvors", status="active",
    )
    db.add(channel)
    db.add_all([
        BusinessService(id="facts-svc-1", channel_id=channel.id, name="Websites", is_offered=True),
        BusinessService(id="facts-svc-2", channel_id=channel.id, name="SEO", is_offered=False),
    ])
    role = TeamRole(id="facts-role", tenant_id=TENANT, name="Founder", is_system=True, permissions=[])
    member = User(
        id="facts-member", email="syab@example.com", first_name="Syed",
        last_name="Syab", password_hash="x", email_verified=True,
    )
    db.add_all([role, member])
    await db.flush()
    db.add(TeamMember(
        id="facts-tm", tenant_id=TENANT, user_id=member.id,
        email="syab@example.com", role_id=role.id, status="active",
    ))

    if locations:
        specs = [
            ("loc-a", "Al-Malaz", "Riyadh", WEEKDAY),
            ("loc-b", "Olaya", "Riyadh", WEEKDAY),
            ("loc-c", "Dammam", "Dammam", LATE if late_branch else WEEKDAY),
        ]
        for listing_id, name, address, schedule in specs:
            db.add(LocationProfile(
                id=f"facts-{listing_id}", user_id=TENANT, listing_id=listing_id,
                hours={"regular": schedule},
            ))
            db.add(LocalithConnection(
                id=f"facts-conn-{listing_id}", user_id=TENANT, listing_id=listing_id,
                listing_name=name, address=address,
            ))

    conn = MetaConnection(
        id="facts-meta-conn", tenant_id=TENANT, provider="whatsapp",
        status="active", access_token_encrypted="enc",
    )
    db.add(conn)
    await db.flush()
    db.add(MetaAsset(
        id="facts-asset", tenant_id=TENANT, connection_id=conn.id,
        provider="whatsapp", asset_type="phone_number",
        external_asset_id="facts-phone", active=True, phone="+1555", status="connected",
        asset_metadata={"business_profile": {
            "address": "Al-Malaz, Riyadh",
            "websites": ["https://sayvors.com"],
            "email": "it@sayvors.com",
            **({"hours": {"mon": [{"start": "09:00", "end": "17:00"}],
                          "fri": []}} if legacy else {}),
        }},
    ))
    await db.commit()
    return channel


def test_compress_groups_consecutive_days():
    assert compress_schedule(normalise_schedule({"regular": WEEKDAY})) == (
        "Mon–Thu 09:00–17:00, Fri closed, Sat–Sun 09:00–17:00"
    )


def test_three_locations_two_schedules_are_listed_per_branch():
    locations = [
        {"name": "Al-Malaz", "address": "Riyadh", "schedule": "Mon–Thu 09:00–17:00"},
        {"name": "Olaya", "address": "Riyadh", "schedule": "Mon–Thu 09:00–17:00"},
        {"name": "Dammam", "address": "Dammam", "schedule": "Mon–Sun 10:00–22:00"},
    ]
    text = render_locations(locations)
    assert text.startswith("We have 3 locations:")
    assert "- Al-Malaz (Riyadh): Mon–Thu 09:00–17:00" in text
    assert "- Dammam: Mon–Sun 10:00–22:00" in text


def test_identical_schedules_collapse_to_all_locations():
    same = [
        {"name": "Al-Malaz", "address": "Riyadh", "schedule": "Mon–Sun 09:00–17:00"},
        {"name": "Olaya", "address": "Riyadh", "schedule": "Mon–Sun 09:00–17:00"},
    ]
    text = render_locations(same)
    assert text.startswith("All 2 locations")
    assert "Mon–Sun 09:00–17:00" in text


@pytest.mark.asyncio
async def test_build_facts_collects_every_source(db):
    await _seed(db)

    facts = await build_facts(db, TENANT)

    assert facts["business"]["name"] == "Sayvors"
    assert facts["business"]["owner"] == "Shah Khan"
    assert facts["contact"]["websites"] == ["https://sayvors.com"]
    assert facts["services"]["offered"] == ["Websites"]
    assert facts["services"]["not_offered"] == ["SEO"]
    assert facts["team"] == [{"name": "Syed Syab", "role": "Founder"}]
    assert len(facts["locations"]) == 3


@pytest.mark.asyncio
async def test_legacy_whatsapp_hours_become_a_location(db):
    await _seed(db, locations=False, legacy=True)

    facts = await build_facts(db, TENANT)

    assert len(facts["locations"]) == 1
    assert facts["locations"][0]["schedule"] == "Mon 09:00–17:00, Tue–Sun closed"
    # Rendering is what the assistant sees: it must contain the real hours.
    text = render_locations(facts["locations"])
    assert "09:00–17:00" in text


@pytest.mark.asyncio
async def test_facts_are_persisted_and_refreshed(db):
    await _seed(db)

    await rebuild_facts(db, TENANT)
    first = await get_facts(db, TENANT)
    assert first["business"]["name"] == "Sayvors"

    # A change in a source is picked up by a rebuild.
    from app.modules.users.models import User

    user = await db.get(User, TENANT)
    user.business_name = "Sayvors Labs"
    await db.commit()

    await rebuild_facts(db, TENANT)
    second = await get_facts(db, TENANT)
    assert second["business"]["name"] == "Sayvors Labs"


@pytest.mark.asyncio
async def test_missing_row_is_rebuilt_on_read(db):
    await _seed(db)
    facts = await get_facts(db, TENANT)
    assert facts["locations"]


@pytest.mark.asyncio
async def test_tool_topics(db):
    await _seed(db)

    hours = await run_facts_tool(db, TENANT, "hours")
    assert "Al-Malaz" in hours and "10:00–22:00" in hours

    website = await run_facts_tool(db, TENANT, "website")
    assert "https://sayvors.com" in website

    services = await run_facts_tool(db, TENANT, "services")
    assert "Websites" in services and "SEO" in services

    team = await run_facts_tool(db, TENANT, "team")
    assert "Shah Khan" in team and "Syed Syab (Founder)" in team

    assert await run_facts_tool(db, TENANT, "nonsense") == ""


def test_render_topic_aliases_are_accepted():
    facts = {"business": {"owner": "Shah Khan"}, "locations": []}
    assert render_topic(facts, "ceo") == "Owner: Shah Khan"
    assert render_topic(facts, "opening_hours") == ""


@pytest.mark.parametrize(
    "text,expected",
    [
        ("What are the business hours?", ["hours"]),
        ("Where are you located?", ["locations"]),
        ("Give me your website link", ["website"]),
        ("What services do you offer?", ["services"]),
        ("Who is your CEO?", ["team"]),
        ("Can I get your email?", ["contact"]),
        ("What are your hours and where are you?", ["hours", "locations"]),
        ("I want to build an e-commerce store", []),
    ],
)
def test_topic_detection(text, expected):
    assert detect_topics(text) == expected


@pytest.mark.asyncio
async def test_facts_are_tenant_scoped(db):
    from app.modules.users.models import User

    await _seed(db)
    db.add(User(
        id="facts-tenant-2", email="other@example.com", first_name="Other",
        last_name="Co", password_hash="x", email_verified=True,
        business_name="Other Co", business_sells="Nothing",
    ))
    await db.commit()

    text = await run_facts_tool(db, "facts-tenant-2", "all")
    assert "Other Co" in text
    assert "Sayvors" not in text
    assert "Al-Malaz" not in text

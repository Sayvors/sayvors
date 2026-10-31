"""The public-facts block: hours, address, website, services, owner profile.

The assistant is the shopfront. Everything here is owner-configured and must
be answered directly; the databank remains the fallback for anything else.
Opening hours are the physical visiting hours — the prompt must never confuse
them with the assistant's 24/7 availability.
"""
import pytest

from app.modules.profile.public_facts import public_facts_block


async def _seed(db, *, hours: bool = True, services: bool = True, profile: bool = True):
    from app.modules.channels.models import BusinessService, Channel
    from app.modules.channels.meta.models import MetaAsset, MetaConnection
    from app.modules.locations.models import LocationProfile
    from app.modules.users.models import User

    tenant = "facts-tenant-1"
    db.add(User(
        id=tenant, email="facts@example.com", first_name="F", last_name="T",
        password_hash="x", email_verified=True,
        business_name="Aster Coffee", business_type="Coffee shop",
        business_description="Specialty coffee and pastries.",
        business_sells="Espresso, filter coffee, croissants",
        business_doesnt_sell="Alcohol",
    ))
    channel = Channel(
        id="facts-channel-1", user_id=tenant, platform="whatsapp",
        platform_user_id="facts-phone-1", display_name="Aster Coffee", status="active",
    )
    db.add(channel)
    if services:
        db.add_all([
            BusinessService(id="svc-1", channel_id=channel.id, name="Espresso", is_offered=True),
            BusinessService(id="svc-2", channel_id=channel.id, name="Catering", is_offered=True),
            BusinessService(id="svc-3", channel_id=channel.id, name="Alcohol", is_offered=False),
        ])
    if hours:
        db.add(LocationProfile(
            id="facts-loc-1", user_id=tenant, listing_id="loc-1",
            hours={"regular": {"Monday": {"open": "07:00", "close": "15:00"}}},
        ))
    if profile:
        conn = MetaConnection(
            id="facts-conn-1", tenant_id=tenant, provider="whatsapp",
            status="active", access_token_encrypted="enc",
        )
        db.add(conn)
        await db.flush()
        db.add(MetaAsset(
            id="facts-asset-1", tenant_id=tenant, connection_id=conn.id,
            provider="whatsapp", asset_type="phone_number",
            external_asset_id="facts-phone-1", active=True,
            phone="+15550000009", status="connected",
            asset_metadata={
                "business_profile": {
                    "address": "12 Main Street, Riyadh",
                    "websites": ["https://aster.example"],
                    "email": "hello@aster.example",
                }
            },
        ))
    await db.commit()

    return channel, await db.get(User, tenant)


@pytest.mark.asyncio
async def test_block_contains_every_public_fact(db):
    channel, user = await _seed(db)

    block = await public_facts_block(
        db, tenant_id=user.id, channel_id=channel.id, user=user, timezone_name="Asia/Riyadh"
    )

    assert "PUBLIC BUSINESS FACTS" in block
    assert "Aster Coffee (Coffee shop)" in block
    assert "Specialty coffee" in block
    assert "https://aster.example" in block
    assert "12 Main Street" in block
    assert "hello@aster.example" in block
    assert "Services offered: Catering, Espresso" in block
    assert "Services NOT offered: Alcohol" in block
    assert "- Monday: 07:00-15:00" in block
    assert "Asia/Riyadh" in block
    assert "DATABANK" in block


@pytest.mark.asyncio
async def test_hours_are_labelled_physical_not_availability(db):
    channel, user = await _seed(db)

    block = await public_facts_block(
        db, tenant_id=user.id, channel_id=channel.id, user=user
    )

    assert "physical" in block.lower()
    assert "OPENING HOURS" in block


@pytest.mark.asyncio
async def test_empty_tenant_yields_no_block(db):
    from app.modules.users.models import User

    db.add(User(
        id="facts-empty", email="empty@example.com", first_name="E", last_name="T",
        password_hash="x", email_verified=True,
    ))
    await db.commit()
    user = await db.get(User, "facts-empty")

    block = await public_facts_block(
        db, tenant_id=user.id, channel_id="no-channel", user=user
    )
    assert block == ""


@pytest.mark.asyncio
async def test_legacy_whatsapp_hours_are_still_answered(db):
    """Pre-removal tenants keep their hours until they re-save in Locations."""
    from app.modules.channels.meta.models import MetaAsset
    from app.modules.profile.public_facts import public_facts_block

    channel, user = await _seed(db, hours=False)
    asset = await db.get(MetaAsset, "facts-asset-1")
    asset.asset_metadata = {
        **(asset.asset_metadata or {}),
        "business_profile": {
            **(asset.asset_metadata or {}).get("business_profile", {}),
            "hours": {
                "mon": [{"start": "09:00", "end": "17:00"}],
                "fri": [],
            },
        },
    }
    await db.commit()

    block = await public_facts_block(
        db, tenant_id=user.id, channel_id=channel.id, user=user
    )

    assert "- Monday: 09:00-17:00" in block
    assert "- Friday: closed" in block


@pytest.mark.asyncio
async def test_partial_facts_still_render(db):
    channel, user = await _seed(db, hours=False, services=False, profile=False)

    block = await public_facts_block(
        db, tenant_id=user.id, channel_id=channel.id, user=user
    )

    assert "Aster Coffee" in block
    assert "Website:" not in block
    assert "Services offered:" not in block
    assert "OPENING HOURS" not in block

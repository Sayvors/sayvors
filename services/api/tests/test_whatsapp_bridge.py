"""Instagram -> WhatsApp bridge: link generation, matching, and the merge.

See readiness-report §17, HAND-1/HAND-3. WhatsApp forbids a business from
messaging a number first, so the move is a customer-initiated wa.me link. The
tests here cover the two identity keys (token, phone), single use, tenant
isolation, and that the merge carries the Instagram context into the live
WhatsApp thread.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.modules.channels.models import (
    Channel,
    ConversationContext,
    Lead,
)
from app.modules.channels.meta import whatsapp_bridge
from app.modules.channels.meta.models import MetaAsset, MetaConnection
from app.modules.channels.service import (
    decrypt_message_content,
    encrypt_message_content,
    hash_contact_phone,
)
from app.modules.users.models import User

IGSID = "17841400000000001"
IG_PHONE = "+966500000101"
WA_PHONE = "+966500000102"


async def _seed(db, *, merge_lead: bool = True):
    uid = f"bridge-user-{uuid.uuid4().hex[:8]}"
    db.add(User(
        id=uid, first_name="B", last_name="R",
        email=f"{uid}@example.com", password_hash="x",
    ))
    conn = MetaConnection(
        id=f"bridge-conn-{uuid.uuid4().hex[:8]}", tenant_id=uid,
        provider="whatsapp", status="active",
    )
    db.add(conn)
    await db.flush()
    wa_asset = MetaAsset(
        id=f"bridge-wa-{uuid.uuid4().hex[:8]}", tenant_id=uid,
        connection_id=conn.id, provider="whatsapp",
        asset_type="phone_number", external_asset_id="pn-bridge",
        phone=WA_PHONE, active=True,
    )
    db.add(wa_asset)
    ig_channel = Channel(
        id=f"bridge-ig-{uuid.uuid4().hex[:8]}", user_id=uid,
        platform="instagram", platform_user_id="ig-bridge",
        display_name="Bridge IG", status="active",
    )
    wa_channel = Channel(
        id=f"bridge-wachan-{uuid.uuid4().hex[:8]}", user_id=uid,
        platform="whatsapp", platform_user_id="pn-bridge",
        display_name="Bridge WA", status="active",
    )
    db.add_all([ig_channel, wa_channel])
    await db.flush()

    ig_lead = None
    if merge_lead:
        ig_lead = Lead(
            id=f"bridge-iglead-{uuid.uuid4().hex[:8]}", tenant_id=uid,
            channel_id=ig_channel.id, platform="instagram",
            contact_id=IGSID, contact_name="Luke", contact_username="luke.q",
            language="ar", intent="buying", request="20kg of beans",
            stage="qualified", phone_number=IG_PHONE,
            thread_key=IGSID, summary="Wants a wholesale quote.",
        )
        db.add(ig_lead)
    wa_lead = Lead(
        id=f"bridge-walead-{uuid.uuid4().hex[:8]}", tenant_id=uid,
        channel_id=wa_channel.id, platform="whatsapp",
        contact_id=WA_PHONE, stage="new", thread_key=WA_PHONE,
    )
    db.add(wa_lead)
    await db.commit()
    return ig_lead, wa_lead, ig_channel, wa_channel, wa_asset, uid


@pytest.mark.asyncio
async def test_the_link_points_at_our_number_and_carries_the_token():
    link = whatsapp_bridge.wa_link("+966 50 000 0102", "K7M2QX")
    assert link.startswith("https://wa.me/966500000102?text=")
    # The token must survive URL encoding intact.
    assert "SV-K7M2QX" in link.replace("%2D", "-")


@pytest.mark.asyncio
async def test_pending_bridge_is_created_once_and_not_resent(db):
    _, _, ig_channel, _, wa_asset, uid = await _seed(db)

    first = await whatsapp_bridge.pending_bridge(
        db, tenant_id=uid, channel_id=ig_channel.id, contact_id=IGSID,
        phone=IG_PHONE, target_asset_id=wa_asset.id,
    )
    assert first is not None
    assert first.token and len(first.token) == whatsapp_bridge.TOKEN_LENGTH

    # A second ask before the DM is delivered must reuse the same row, not
    # mint a competing token.
    again = await whatsapp_bridge.pending_bridge(
        db, tenant_id=uid, channel_id=ig_channel.id, contact_id=IGSID,
        phone=IG_PHONE, target_asset_id=wa_asset.id,
    )
    assert again is not None and again.id == first.id

    first.sent_at = datetime.now(timezone.utc)
    await db.commit()
    assert await whatsapp_bridge.pending_bridge(
        db, tenant_id=uid, channel_id=ig_channel.id, contact_id=IGSID,
        phone=IG_PHONE, target_asset_id=wa_asset.id,
    ) is None, "a delivered link must not be re-sent every turn"


@pytest.mark.asyncio
async def test_a_failed_send_is_retried(db):
    _, _, ig_channel, _, wa_asset, uid = await _seed(db)
    await whatsapp_bridge.pending_bridge(
        db, tenant_id=uid, channel_id=ig_channel.id, contact_id=IGSID,
        phone=IG_PHONE, target_asset_id=wa_asset.id,
    )
    # sent_at stays NULL when the DM failed, so the next turn gets it back.
    retry = await whatsapp_bridge.pending_bridge(
        db, tenant_id=uid, channel_id=ig_channel.id, contact_id=IGSID,
        phone=IG_PHONE, target_asset_id=wa_asset.id,
    )
    assert retry is not None


@pytest.mark.asyncio
async def test_find_by_token_tolerates_how_people_type_it(db):
    _, _, ig_channel, _, wa_asset, uid = await _seed(db)
    bridge = await whatsapp_bridge.pending_bridge(
        db, tenant_id=uid, channel_id=ig_channel.id, contact_id=IGSID,
        phone=IG_PHONE, target_asset_id=wa_asset.id,
    )

    for text in (
        f"SV-{bridge.token}",
        f"sv {bridge.token.lower()}",
        f"hi! SV{bridge.token}",
    ):
        found = await whatsapp_bridge.find_bridge(
            db, tenant_id=uid, text=text, phone=WA_PHONE
        )
        assert found is not None and found.id == bridge.id, text


@pytest.mark.asyncio
async def test_find_by_phone_when_the_customer_deletes_the_text(db):
    _, _, ig_channel, _, wa_asset, uid = await _seed(db)
    bridge = await whatsapp_bridge.pending_bridge(
        db, tenant_id=uid, channel_id=ig_channel.id, contact_id=IGSID,
        phone=IG_PHONE, target_asset_id=wa_asset.id,
    )

    # Meta sends the sender without the leading +.
    found = await whatsapp_bridge.find_bridge(
        db, tenant_id=uid, text="hello?", phone=IG_PHONE.lstrip("+")
    )
    assert found is not None and found.id == bridge.id


@pytest.mark.asyncio
async def test_another_tenants_token_does_not_match(db):
    _, _, ig_channel, _, wa_asset, uid = await _seed(db)
    bridge = await whatsapp_bridge.pending_bridge(
        db, tenant_id=uid, channel_id=ig_channel.id, contact_id=IGSID,
        phone=IG_PHONE, target_asset_id=wa_asset.id,
    )

    other_tenant = f"bridge-other-{uuid.uuid4().hex[:8]}"
    found = await whatsapp_bridge.find_bridge(
        db, tenant_id=other_tenant, text=f"SV-{bridge.token}",
        phone=IG_PHONE,
    )
    assert found is None, "a token must never bridge across tenants"


@pytest.mark.asyncio
async def test_expired_and_used_bridges_do_not_match(db):
    _, _, ig_channel, _, wa_asset, uid = await _seed(db)
    bridge = await whatsapp_bridge.pending_bridge(
        db, tenant_id=uid, channel_id=ig_channel.id, contact_id=IGSID,
        phone=IG_PHONE, target_asset_id=wa_asset.id,
    )
    bridge.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db.commit()
    assert await whatsapp_bridge.find_bridge(
        db, tenant_id=uid, text=f"SV-{bridge.token}", phone=IG_PHONE
    ) is None

    bridge.expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    bridge.used_at = datetime.now(timezone.utc)
    await db.commit()
    assert await whatsapp_bridge.find_bridge(
        db, tenant_id=uid, text=f"SV-{bridge.token}", phone=IG_PHONE
    ) is None, "a single-use link must not work twice"


@pytest.mark.asyncio
async def test_link_merges_the_leads_and_carries_the_context(db):
    ig_lead, wa_lead, ig_channel, wa_channel, wa_asset, uid = await _seed(db)
    db.add(ConversationContext(
        id=str(uuid.uuid4()), tenant_id=uid, channel_id=ig_channel.id,
        contact_phone=IGSID,
        contact_phone_hash=hash_contact_phone(IGSID),
        summary=encrypt_message_content(
            "Customer: Luke, cafe owner.\nOpen: delivery date."
        ),
        message_count=6, reason="resolve",
    ))
    await db.commit()
    bridge = await whatsapp_bridge.pending_bridge(
        db, tenant_id=uid, channel_id=ig_channel.id, contact_id=IGSID,
        phone=IG_PHONE, target_asset_id=wa_asset.id,
    )

    consumed = await whatsapp_bridge.link_bridge(
        db, bridge=bridge, lead=wa_lead, contact_phone=WA_PHONE
    )
    await db.commit()
    assert consumed is True

    await db.refresh(wa_lead)
    assert wa_lead.contact_name == "Luke"
    assert wa_lead.contact_username == "luke.q"
    assert wa_lead.request == "20kg of beans"
    assert wa_lead.stage == "qualified", "progress must survive the move"
    assert wa_lead.language == "ar"

    await db.refresh(ig_lead)
    assert ig_lead.merged_into_id == wa_lead.id
    assert ig_lead.priority == "normal", "the merged row must stop escalating"

    contexts = (await db.execute(
        select(ConversationContext).where(
            ConversationContext.channel_id == wa_channel.id,
            ConversationContext.contact_phone_hash
            == hash_contact_phone(WA_PHONE),
        )
    )).scalars().all()
    assert len(contexts) == 1, "one carried summary, not one per read"
    summary = decrypt_message_content(contexts[0].summary) or ""
    assert "From an Instagram conversation" in summary
    assert "20kg of beans" in summary, "the Instagram request must be carried"
    assert "delivery date" in summary, "the stored IG summary must be carried"
    assert contexts[0].reason == "cross_channel"

    await db.refresh(bridge)
    assert bridge.used_at is not None
    assert bridge.used_by_lead_id == wa_lead.id


@pytest.mark.asyncio
async def test_a_bridge_is_consumed_only_once(db):
    _, wa_lead, ig_channel, _, wa_asset, uid = await _seed(db)
    bridge = await whatsapp_bridge.pending_bridge(
        db, tenant_id=uid, channel_id=ig_channel.id, contact_id=IGSID,
        phone=IG_PHONE, target_asset_id=wa_asset.id,
    )
    assert await whatsapp_bridge.link_bridge(
        db, bridge=bridge, lead=wa_lead, contact_phone=WA_PHONE
    ) is True
    assert await whatsapp_bridge.link_bridge(
        db, bridge=bridge, lead=wa_lead, contact_phone=WA_PHONE
    ) is False, "a replayed link must not merge again"


@pytest.mark.asyncio
async def test_the_merge_never_overwrites_known_fields(db):
    _, wa_lead, ig_channel, _, wa_asset, uid = await _seed(db)
    wa_lead.contact_name = "Already Known"
    wa_lead.request = "Their own words"
    wa_lead.stage = "follow_up"
    await db.commit()
    bridge = await whatsapp_bridge.pending_bridge(
        db, tenant_id=uid, channel_id=ig_channel.id, contact_id=IGSID,
        phone=IG_PHONE, target_asset_id=wa_asset.id,
    )

    await whatsapp_bridge.link_bridge(
        db, bridge=bridge, lead=wa_lead, contact_phone=WA_PHONE
    )
    await db.commit()
    await db.refresh(wa_lead)
    assert wa_lead.contact_name == "Already Known"
    assert wa_lead.request == "Their own words"
    assert wa_lead.stage == "follow_up", "the live lead keeps its own progress"

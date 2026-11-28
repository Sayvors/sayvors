"""Provider status pricing evidence and sent-status quota reconciliation."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.modules.channels.meta.webhooks import parser
from app.modules.users.models import User


def _status_payload():
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "waba-1", "changes": [{
            "field": "messages",
            "value": {
                "metadata": {"phone_number_id": "pn-1"},
                "statuses": [{
                    "id": "wamid-1", "status": "sent", "timestamp": "1793491200",
                    "billable": True,
                    "pricing_model": {"category": "UTILITY", "type": "REGULAR"},
                    "pricing_category": "UTILITY",
                    "pricing_type": "REGULAR",
                    "pricing_subtype": "standard",
                }],
            },
        }]}],
    }


def test_status_parser_retains_pricing_fields():
    _, events = parser.parse(_status_payload())
    data = events[0]["data"]
    assert data["billable"] is True
    assert data["pricing_model"] == {"category": "UTILITY", "type": "REGULAR"}
    assert data["pricing_category"] == "UTILITY"
    assert data["pricing_type"] == "REGULAR"
    assert data["pricing_subtype"] == "standard"


@pytest.mark.asyncio
async def test_sent_status_persists_pricing_and_reconciles_usage_once(db, monkeypatch):
    from app.modules.channels.meta import consumer
    from app.modules.channels.meta.spend_models import (
        WhatsAppMonthlyUsage, WhatsAppQuotaReservation,
    )
    from app.modules.channels.models import Channel, ChannelMessage

    monkeypatch.setattr(consumer, "async_session", lambda: _Borrowed(db))
    uid = f"status-{uuid.uuid4().hex[:8]}"
    db.add(User(
        id=uid, first_name="Status", last_name="Test",
        email=f"{uid}@example.com", password_hash="x",
    ))
    channel = Channel(
        id=f"chan-{uid}", user_id=uid, platform="whatsapp",
        platform_user_id="pn-1", status="active",
    )
    db.add(channel)
    await db.flush()
    row = ChannelMessage(
        id=f"msg-{uid}", channel_id=channel.id,
        platform_message_id="wamid-1", direction="outbound",
        content="hello", status="sent",
    )
    db.add(row)
    await db.commit()
    event = {"external_event_id": "wamid-1", "external_asset_id": "pn-1"}
    data = parser.parse(_status_payload())[1][0]["data"]

    await consumer._handle_message_status(event, data)
    await consumer._handle_message_status(event, data)

    stored = await db.get(ChannelMessage, row.id)
    assert stored.pricing_billable is True
    assert stored.pricing_category == "UTILITY"
    assert stored.pricing_type == "REGULAR"
    assert stored.pricing_subtype == "standard"
    assert stored.provider_confirmed_at is not None
    usage = (await db.execute(
        select(WhatsAppMonthlyUsage).where(WhatsAppMonthlyUsage.tenant_id == uid)
    )).scalar_one()
    assert usage.used_count == 1
    reservations = (await db.execute(
        select(WhatsAppQuotaReservation).where(WhatsAppQuotaReservation.tenant_id == uid)
    )).scalars().all()
    assert len(reservations) == 1
    assert reservations[0].status == "consumed"


class _Borrowed:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *args):
        return False

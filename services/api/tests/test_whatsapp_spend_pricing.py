"""Meta pricing analytics: exact request shape and honest cost parsing."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.channels.meta.providers.whatsapp import WhatsAppAdapter


def _payload(*, cost=4.6, currency="SAR"):
    point = {
        "start": 1793491200,  # 2026-11-01T00:00:00Z
        "end": 1793577600,
        "phone_number": "966500000001",
        "country": "SA",
        "pricing_category": "UTILITY",
        "pricing_type": "REGULAR",
        "tier": "0:750000",
        "volume": 2,
    }
    if cost is not ...:
        point["cost"] = cost
    return {
        "pricing_analytics": {
            "currency": currency,
            "funding_mode": "shared_credit_line",
            "timezone": "Asia/Riyadh",
            "messaging_account_id": "ma-1",
            "data": [{"data_points": [point]}],
        }
    }


@pytest.mark.asyncio
async def test_fetch_uses_current_waba_daily_cost_volume_and_all_dimensions():
    adapter = WhatsAppAdapter()
    calls = []

    async def fake_graph(method, path, token, **kwargs):
        calls.append((method, path, token, kwargs))
        return SimpleNamespace(json=lambda: _payload())

    adapter._graph = fake_graph
    try:
        result = await adapter.get_pricing_analytics(
            "waba-current", "secret", start=date(2026, 11, 1), end=date(2026, 11, 8)
        )
    finally:
        await adapter.close()

    method, path, token, kwargs = calls[0]
    assert (method, path, token) == ("GET", "/waba-current", "secret")
    assert kwargs["params"]["fields"] == (
        "pricing_analytics.start(1793491200).end(1794096000)"
        ".granularity(DAILY)"
        ".dimensions(COUNTRY,PHONE,PRICING_CATEGORY,PRICING_TYPE,TIER)"
        ".metric_types(COST,VOLUME)"
    )
    assert result["currency"] == "SAR"
    assert result["funding_mode"] == "shared_credit_line"
    assert result["waba_timezone"] == "Asia/Riyadh"
    assert result["messaging_account_id"] == "ma-1"
    assert result["points"][0]["spend_date"] == date(2026, 11, 1)
    assert result["points"][0]["cost"] == Decimal("4.6")
    assert result["points"][0]["cost_status"] == "available"


@pytest.mark.parametrize("cost", [..., None])
def test_missing_cost_is_explicitly_unavailable_never_estimated(cost):
    point = WhatsAppAdapter.parse_pricing_analytics(_payload(cost=cost))["points"][0]
    assert point["cost"] is None
    assert point["cost_status"] == "unavailable"
    assert point["volume"] == 2


def test_zero_cost_is_available_and_dimensions_are_preserved():
    point = WhatsAppAdapter.parse_pricing_analytics(_payload(cost=0))["points"][0]
    assert point["cost"] == 0
    assert point["cost_status"] == "available"
    assert point["phone"] == "966500000001"
    assert point["country"] == "SA"
    assert point["pricing_category"] == "UTILITY"
    assert point["pricing_type"] == "REGULAR"
    assert point["tier"] == "0:750000"

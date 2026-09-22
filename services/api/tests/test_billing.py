"""Billing profiles + card-on-file records (no network, no gateway)."""
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.billing.schemas import BillingProfileIn, PaymentMethodIn
from app.modules.billing import service


def _card(**over):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    data = dict(brand="visa", last4="4242", exp_month=12,
                exp_year=now.year + 2, holder_name="Sara")
    data.update(over)
    return PaymentMethodIn(**data)


@pytest.mark.asyncio
async def test_profile_upsert_roundtrip(db, user_id):
    assert await service.get_profile(user_id, db) is None
    out = await service.save_profile(
        user_id,
        BillingProfileIn(full_name="Sara", city="Riyadh", country="SA",
                         tax_id="300123456700003"),
        db,
    )
    assert out["full_name"] == "Sara"
    assert out["tax_id"] == "300123456700003"
    out2 = await service.save_profile(
        user_id, BillingProfileIn(city="Jeddah"), db)
    assert out2["city"] == "Jeddah"
    assert out2["id"] == out["id"]


@pytest.mark.asyncio
async def test_first_card_becomes_default(db, user_id):
    a = await service.add_method(user_id, _card(), db)
    assert a["is_default"] is True
    assert a["verified"] is False
    assert a["expired"] is False
    b = await service.add_method(user_id, _card(last4="0005"), db)
    assert b["is_default"] is False
    c = await service.set_default(b["id"], user_id, db)
    assert c["is_default"] is True
    rows = await service.list_methods(user_id, db)
    assert [r["id"] for r in rows if r["is_default"]] == [b["id"]]


@pytest.mark.asyncio
async def test_remove_default_promotes_newest(db, user_id):
    a = await service.add_method(user_id, _card(), db)
    b = await service.add_method(user_id, _card(last4="0005"), db)
    await service.remove_method(a["id"], user_id, db)
    rows = await service.list_methods(user_id, db)
    assert len(rows) == 1
    assert rows[0]["id"] == b["id"]
    assert rows[0]["is_default"] is True


@pytest.mark.asyncio
async def test_expired_card_rejected(db, user_id):
    with pytest.raises(ValueError, match="expired"):
        await service.add_method(user_id, _card(exp_month=1, exp_year=2001), db)


@pytest.mark.asyncio
async def test_foreign_rows_are_invisible(db, user_id):
    other = "user-foreign-0000-0000-000000000099"
    row = await service.add_method(other, _card(), db)
    with pytest.raises(ValueError, match="not found"):
        await service.set_default(row["id"], user_id, db)
    with pytest.raises(ValueError, match="not found"):
        await service.remove_method(row["id"], user_id, db)
    assert await service.list_methods(user_id, db) == []


@pytest.mark.asyncio
async def test_gateway_provider_rejected_loudly(db, user_id):
    with pytest.raises(NotImplementedError, match="No payment gateway"):
        await service.add_method(
            user_id,
            PaymentMethodIn(brand="visa", last4="4242", exp_month=12,
                            exp_year=2030, provider="moyasar"),
            db,
        )


@pytest.mark.asyncio
async def test_stub_tokenize_and_charge_endpoints(client, db, user_id):
    host = {"host": "localhost"}
    r = client.post(
        "/api/v1/billing/gateway/tokenize",
        json={"brand": "visa", "last4": "4242", "exp_month": 12,
              "exp_year": 2030, "holder_name": "Sara"},
        headers=host,
    )
    assert r.status_code == 200, r.text[:200]
    tok = r.json()
    assert tok["token"].startswith("pm_stub_")
    assert tok["provider"] == "stub"
    assert tok["last4"] == "4242"

    r = client.post(
        "/api/v1/billing/gateway/charge",
        json={"token": tok["token"], "amount_cents": 500,
              "description": "test top-up"},
        headers=host,
    )
    assert r.status_code == 200, r.text[:200]
    ch = r.json()
    assert ch["status"] == "succeeded"
    assert ch["id"].startswith("ch_stub_")
    assert ch["amount_cents"] == 500

    r = client.post(
        "/api/v1/billing/gateway/charge",
        json={"token": "pm_evil_not_stub", "amount_cents": 100},
        headers=host,
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_stub_tokenized_card_is_verified(db, user_id):
    from app.modules.billing.providers import get_payment_provider

    tok = get_payment_provider("stub").tokenize(
        brand="visa", last4="4242", exp_month=12, exp_year=2030)
    row = await service.add_method(
        user_id, _card(provider="stub", provider_token=tok["token"]), db)
    assert row["provider"] == "stub"
    assert row["verified"] is True


@pytest.mark.asyncio
async def test_stub_without_token_auto_tokenizes(db, user_id):
    row = await service.add_method(user_id, _card(provider="stub"), db)
    assert row["provider"] == "stub"
    assert row["verified"] is True


@pytest.mark.asyncio
async def test_stub_bad_token_rejected(db, user_id):
    with pytest.raises(ValueError, match="Invalid stub"):
        await service.add_method(
            user_id, _card(provider="stub", provider_token="pm_evil"), db)


@pytest.mark.asyncio
async def test_billing_endpoints_roundtrip(client, db, user_id):
    host = {"host": "localhost"}
    r = client.get("/api/v1/billing/profile", headers=host)
    assert r.status_code == 200
    assert r.json() is None
    r = client.put("/api/v1/billing/profile",
                   json={"full_name": "Sara", "country": "SA"},
                   headers=host)
    assert r.status_code == 200, r.text[:200]
    assert r.json()["full_name"] == "Sara"
    r = client.post("/api/v1/billing/methods",
                    json={"brand": "mada", "last4": "0006",
                          "exp_month": 6, "exp_year": 2030},
                    headers=host)
    assert r.status_code == 200, r.text[:200]
    mid = r.json()["id"]
    assert r.json()["is_default"] is True
    r = client.post(f"/api/v1/billing/methods/{mid}/default", headers=host)
    assert r.status_code == 200
    r = client.delete(f"/api/v1/billing/methods/{mid}", headers=host)
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    r = client.post("/api/v1/billing/methods/nope/default", headers=host)
    assert r.status_code == 404

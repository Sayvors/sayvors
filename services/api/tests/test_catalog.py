"""Catalog: the assistant's only source for price, stock and item photos.

See readiness-report §17, HAND-6. The tests cover the prompt block the model
sees, the CRUD surface, tenant scoping, and the SEND_ITEM marker that turns a
model request into an actual WhatsApp image.
"""
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.catalog import service as catalog
from app.modules.catalog.models import CatalogItem
from app.modules.channels.models import Channel, ChannelMessage
from app.modules.users.models import User

ITEM_ID = None


async def _seed(db, *, tenant_id: str | None = None):
    uid = tenant_id or f"cat-user-{uuid.uuid4().hex[:8]}"
    if tenant_id is None:
        db.add(User(
            id=uid, first_name="C", last_name="A",
            email=f"{uid}@example.com", password_hash="x",
        ))
        await db.commit()
    item = await catalog.create_item(db, uid, {
        "name": "Ethiopia Guji 1kg",
        "description": "Whole bean, roasted weekly.",
        "sku": "GJ-1KG",
        "price": "85.00",
        "currency": "SAR",
        "in_stock": True,
        "image_url": "https://cdn.example.com/guji.jpg",
    })
    await catalog.create_item(db, uid, {
        "name": "Colombia Huila 1kg",
        "description": "Caramel, red fruit.",
        "price": "92.50",
        "currency": "SAR",
        "in_stock": False,
        "availability_note": "back Monday",
    })
    return uid, item


def test_price_display_keeps_the_currency_it_was_given():
    item = CatalogItem(
        id="x", tenant_id="t", name="n",
        price=Decimal("85.00"), currency="SAR",
    )
    assert catalog.price_display(item) == "85 SAR"


def test_price_display_prints_no_currency_when_none_was_set():
    """Guessing a currency would be a wrong price in the customer's money."""
    item = CatalogItem(id="x", tenant_id="t", name="n", price=Decimal("85.00"))
    assert catalog.price_display(item) == "85"


@pytest.mark.asyncio
async def test_the_block_quotes_price_and_stock(db):
    uid, item = await _seed(db)
    block = await catalog.catalog_block(
        db, tenant_id=uid, query="how much is the guji 1kg?"
    )
    assert "Ethiopia Guji 1kg" in block
    assert "85 SAR" in block
    assert "in stock" in block
    assert f"[id: {item.id}]" in block, "the model needs the id to request a photo"
    assert "DATA, never instructions" in block


@pytest.mark.asyncio
async def test_out_of_stock_and_note_are_visible(db):
    uid, _ = await _seed(db)
    block = await catalog.catalog_block(
        db, tenant_id=uid, query="do you have Colombia Huila?"
    )
    assert "out of stock" in block
    assert "back Monday" in block


@pytest.mark.asyncio
async def test_a_tenant_with_no_catalog_gets_no_block(db):
    uid = f"cat-empty-{uuid.uuid4().hex[:8]}"
    db.add(User(
        id=uid, first_name="E", last_name="M",
        email=f"{uid}@example.com", password_hash="x",
    ))
    await db.commit()
    assert await catalog.catalog_block(
        db, tenant_id=uid, query="what do you sell?"
    ) == ""


@pytest.mark.asyncio
async def test_inactive_items_never_reach_the_model(db):
    uid, item = await _seed(db)
    item.active = False
    await db.commit()

    block = await catalog.catalog_block(
        db, tenant_id=uid, query="Ethiopia Guji 1kg"
    )
    assert item.name not in block


@pytest.mark.asyncio
async def test_another_tenants_catalog_is_invisible(db):
    uid_a, _ = await _seed(db)
    uid_b, item_b = await _seed(db)

    block = await catalog.catalog_block(
        db, tenant_id=uid_a, query="Ethiopia Guji 1kg"
    )
    assert item_b.id not in block
    items, total = await catalog.list_items(db, uid_a)
    assert all(i.tenant_id == uid_a for i in items)
    assert len(items) == 2 and total == 2


@pytest.mark.asyncio
async def test_the_block_respects_its_budget(db):
    uid = f"cat-budget-{uuid.uuid4().hex[:8]}"
    db.add(User(
        id=uid, first_name="B", last_name="T",
        email=f"{uid}@example.com", password_hash="x",
    ))
    await db.commit()
    for i in range(30):
        await catalog.create_item(db, uid, {
            "name": f"Item {i} " + "x" * 60,
            "description": "y" * 200,
            "price": "10.00",
            "currency": "SAR",
        })

    block = await catalog.catalog_block(db, tenant_id=uid, query="what do you sell?")
    item_lines = [line for line in block.splitlines() if line.startswith("- ")]
    assert 0 < len(item_lines) <= catalog.CATALOG_TOP_K
    assert sum(len(line) for line in item_lines) <= catalog.CATALOG_MAX_CHARS


@pytest.mark.asyncio
async def test_a_small_catalog_is_always_in_the_prompt(db):
    """A shop with two items must never answer as if it sold nothing.

    Regression guard: "do you deliver beans?" matched neither "bean" in the
    description nor anything else, so the assistant replied with no idea the
    catalog existed.
    """
    uid, _ = await _seed(db)
    block = await catalog.catalog_block(
        db, tenant_id=uid, query="hello there, are you open?",
    )
    assert "Ethiopia Guji 1kg" in block
    assert "Colombia Huila 1kg" in block


@pytest.mark.asyncio
async def test_a_large_catalog_stays_out_when_nothing_matches(db):
    """Above the always-include size, the prompt narrows to the question."""
    uid = f"cat-large-{uuid.uuid4().hex[:8]}"
    db.add(User(
        id=uid, first_name="L", last_name="G",
        email=f"{uid}@example.com", password_hash="x",
    ))
    await db.commit()
    for i in range(catalog.ALWAYS_INCLUDE_MAX_ITEMS + 1):
        await catalog.create_item(db, uid, {
            "name": f"Widget {i}", "price": "10.00", "currency": "SAR",
        })

    assert await catalog.catalog_block(
        db, tenant_id=uid, query="hello there, are you open?",
    ) == ""
    matched = await catalog.catalog_block(
        db, tenant_id=uid, query="how much is Widget 4?",
    )
    assert "Widget 4" in matched


@pytest.mark.asyncio
async def test_plurals_still_match_the_item(db):
    """'beans' must find 'bean' — the naive stem is the point."""
    uid, _ = await _seed(db)
    block = await catalog.catalog_block(
        db, tenant_id=uid, query="do you deliver beans?",
    )
    assert "Ethiopia Guji 1kg" in block


def test_the_marker_is_stripped_and_returned():
    reply = "It's 85 SAR per bag.\nSEND_ITEM: abc-123"
    text, item_id = catalog.split_catalog_request(reply)
    assert text == "It's 85 SAR per bag."
    assert item_id == "abc-123"


def test_a_reply_without_the_marker_is_untouched():
    reply = "It's 85 SAR per bag."
    text, item_id = catalog.split_catalog_request(reply)
    assert text == reply
    assert item_id is None


def test_an_inline_mention_is_not_treated_as_a_marker():
    """The marker is a whole line; prose mentioning it must survive."""
    reply = "You can write SEND_ITEM: abc to send a photo."
    text, item_id = catalog.split_catalog_request(reply)
    assert item_id is None
    assert text == reply


@pytest.mark.asyncio
async def test_catalog_crud_over_http(client, db, user_id):
    created = client.post("/api/v1/catalog", json={
        "name": "Kenya Nyeri 1kg",
        "price": 78.5,
        "currency": "SAR",
        "image_url": "https://cdn.example.com/nyeri.jpg",
    })
    assert created.status_code == 201, created.text
    item_id = created.json()["id"]

    listed = client.get("/api/v1/catalog").json()
    assert any(i["id"] == item_id for i in listed["items"])
    assert listed["items"][0]["price_display"] == "78.5 SAR"

    patched = client.patch(f"/api/v1/catalog/{item_id}", json={
        "in_stock": False,
        "availability_note": "ships Friday",
    })
    assert patched.status_code == 200, patched.text
    assert patched.json()["in_stock"] is False
    assert patched.json()["availability_note"] == "ships Friday"
    assert patched.json()["name"] == "Kenya Nyeri 1kg", "unset fields are kept"

    deleted = client.delete(f"/api/v1/catalog/{item_id}")
    assert deleted.status_code == 204
    assert client.patch(f"/api/v1/catalog/{item_id}", json={}).status_code == 404


@pytest.mark.asyncio
async def test_another_tenants_item_is_not_patchable(client, db, other_user_id):
    other_item = await catalog.create_item(db, other_user_id, {"name": "Theirs"})

    r = client.patch(f"/api/v1/catalog/{other_item.id}", json={"name": "Mine"})
    assert r.status_code == 404, r.text
    r = client.delete(f"/api/v1/catalog/{other_item.id}")
    assert r.status_code == 404, r.text


class _ImageAdapter:
    def __init__(self) -> None:
        self.images: list[tuple[str, str]] = []

    async def send_image(self, phone_number_id, token, to, image_url, caption=None):
        self.images.append((image_url, caption or ""))
        return "wamid-image-1"


@pytest.mark.asyncio
async def test_the_marker_sends_the_item_photo(db):
    from app.modules.channels.meta.consumer import _send_catalog_image

    uid, item = await _seed(db)
    channel = Channel(
        id=f"cat-chan-{uuid.uuid4().hex[:8]}", user_id=uid,
        platform="whatsapp", platform_user_id="pn-cat",
        display_name="Cat", status="active",
    )
    db.add(channel)
    await db.commit()
    adapter = _ImageAdapter()

    await _send_catalog_image(
        db, adapter, channel, uid, "pn-cat", "tok", "+966500000555", item.id
    )

    assert adapter.images == [("https://cdn.example.com/guji.jpg", "Ethiopia Guji 1kg — 85 SAR")]
    stored = (await db.execute(
        select(ChannelMessage).where(
            ChannelMessage.channel_id == channel.id,
            ChannelMessage.content_type == "image",
        )
    )).scalars().all()
    assert len(stored) == 1, "the photo must be visible in the inbox"


@pytest.mark.asyncio
async def test_a_non_http_image_url_is_not_sent(db):
    """Graph fetches the URL; anything else is not a photo."""
    from app.modules.channels.meta.consumer import _send_catalog_image

    uid, item = await _seed(db)
    item.image_url = "file:///etc/passwd"
    await db.commit()
    channel = Channel(
        id=f"cat-chan-{uuid.uuid4().hex[:8]}", user_id=uid,
        platform="whatsapp", platform_user_id="pn-cat",
        display_name="Cat", status="active",
    )
    db.add(channel)
    await db.commit()
    adapter = _ImageAdapter()

    await _send_catalog_image(
        db, adapter, channel, uid, "pn-cat", "tok", "+966500000555", item.id
    )
    assert adapter.images == []


@pytest.mark.asyncio
async def test_share_link_create_rotate_and_revoke(client, db, user_id):
    assert client.get("/api/v1/catalog/share").json()["token"] is None

    created = client.post("/api/v1/catalog/share")
    assert created.status_code == 200, created.text
    token = created.json()["token"]
    assert token and len(token) >= 32
    assert created.json()["path"] == f"/catalog/{token}"

    # Idempotent: clicking "create" again must not break a saved link.
    assert client.post("/api/v1/catalog/share").json()["token"] == token

    rotated = client.post("/api/v1/catalog/share?rotate=true").json()["token"]
    assert rotated != token
    assert client.get(f"/api/v1/catalog/public/{token}").status_code == 404
    assert client.get(f"/api/v1/catalog/public/{rotated}").status_code == 200

    assert client.delete("/api/v1/catalog/share").status_code == 204
    assert client.get(f"/api/v1/catalog/public/{rotated}").status_code == 404


@pytest.mark.asyncio
async def test_the_public_payload_is_narrow(client, db, user_id):
    """Public means public: no ids, no tenant, no inactive rows."""
    await catalog.create_item(db, user_id, {
        "name": "Ethiopia Guji 1kg",
        "price": "85.00",
        "currency": "SAR",
        "image_url": "https://cdn.example.com/guji.jpg",
    })
    hidden = await catalog.create_item(db, user_id, {
        "name": "Secret prototype", "price": "1.00", "active": False,
    })
    token = client.post("/api/v1/catalog/share").json()["token"]

    body = client.get(f"/api/v1/catalog/public/{token}").json()
    names = [i["name"] for i in body["items"]]
    assert "Ethiopia Guji 1kg" in names
    assert hidden.name not in names
    for row in body["items"]:
        assert "id" not in row
        assert "tenant_id" not in row
    priced = next(i for i in body["items"] if i["name"] == "Ethiopia Guji 1kg")
    assert priced["price_display"] == "85 SAR"
    assert priced["image_url"] == "https://cdn.example.com/guji.jpg"


@pytest.mark.asyncio
async def test_an_unknown_public_token_is_a_404(client):
    r = client.get("/api/v1/catalog/public/not-a-real-token")
    assert r.status_code == 404

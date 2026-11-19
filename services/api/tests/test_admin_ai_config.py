"""Admin AI config (vision model) + tenant-facing media check uses it."""
import io

import pytest
from PIL import Image

from app.config import settings

pytestmark = pytest.mark.asyncio

# bcrypt(4 rounds) of "test-admin-pass" — fast for tests, never production.
TEST_ADMIN_HASH = "$2b$04$JYhUM7dKG7CjHsWtPoyNvuHgI.uZcJoMA8JruWs3DhtQxc2susyAy"
_HOST = {"host": "localhost"}


@pytest.fixture
def admin_headers(client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_PASSWORD_HASH", TEST_ADMIN_HASH)
    r = client.post(
        "/api/v1/admin/login", json={"username": "admin", "password": "test-admin-pass"}, headers=_HOST
    )
    assert r.status_code == 200
    return {**_HOST, "X-Requested-With": "XMLHttpRequest"}


def _png_bytes(width=1200, height=675):
    img = Image.new("RGB", (width, height))
    for x in range(0, width, 6):
        for y in range(0, height, 6):
            img.putpixel((x, y), (0, 0, 0))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


async def test_admin_ai_config_get_put_default(client, db, admin_headers):
    res = client.get("/api/v1/admin/config/ai", headers=admin_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert "banner_vision_model" in body
    assert body["banner_vision_model"] is None

    put = client.put(
        "/api/v1/admin/config/ai", headers=admin_headers,
        json={"banner_vision_model": "gemini:gemini-2.0-flash"},
    )
    assert put.status_code == 200, put.text
    assert put.json()["banner_vision_model"] == "gemini:gemini-2.0-flash"

    get2 = client.get("/api/v1/admin/config/ai", headers=admin_headers)
    assert get2.json()["banner_vision_model"] == "gemini:gemini-2.0-flash"

    clear = client.put(
        "/api/v1/admin/config/ai", headers=admin_headers,
        json={"banner_vision_model": ""},
    )
    assert clear.json()["banner_vision_model"] is None


async def test_analyze_banner_calls_vision_with_admin_model(client, db, monkeypatch, admin_headers):
    """The tenant endpoint uses the admin-configured model, without revealing it."""
    from app.modules.media import router as media_router

    client.put(
        "/api/v1/admin/config/ai", headers=admin_headers,
        json={"banner_vision_model": "test:vision"},
    )

    calls = {}
    async def _fake_verdict(data, model):
        calls["model"] = model
        return {"suitable": "yes", "confidence": 91, "reasons": ["sharp"]}

    monkeypatch.setattr(media_router, "_vision_verdict", _fake_verdict)
    res = client.post(
        "/api/v1/media/analyze-banner",
        files={"file": ("banner.png", _png_bytes(), "image/png")},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert calls.get("model") == "test:vision"
    assert body["ai_verdict"]["suitable"] == "yes"
    assert "test:vision" not in str(body)  # model id never leaks to the tenant

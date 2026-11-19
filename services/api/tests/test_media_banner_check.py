"""Banner/promotion photo suitability rules + analyze-banner endpoint."""
import io

import pytest
from PIL import Image

from app.modules.media.image_check import analyze_banner_image

pytestmark = pytest.mark.asyncio


def _png_bytes(width: int, height: int, color=(120, 120, 120), noise_edges=False):
    """PNG. Edges carry the sharpness signal, so a 'good' photo needs them."""
    img = Image.new("RGB", (width, height), color)
    if noise_edges:
        # A checkerboard adds strong edge energy (sharp-looking).
        for x in range(0, width, 8):
            for y in range(0, height, 8):
                img.putpixel((x, y), (0, 0, 0))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _good_banner_png(width=1200, height=675):
    """Real-ish banner: gradient + sharp checkerboard so blur passes."""
    img = Image.new("RGB", (width, height))
    for x in range(width):
        for y in range(height):
            img.putpixel((x, y), (x % 255, y % 255, (x + y) % 255))
    for x in range(0, width, 6):
        for y in range(0, height, 6):
            img.putpixel((x, y), (0, 0, 0))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _solid_blur_png(width=1200, height=675):
    """A truly flat image: no edges -> flagged blurry."""
    return _png_bytes(width, height, color=(140, 140, 140))


async def test_good_banner_passes_all_rules():
    result = analyze_banner_image(_good_banner_png())
    assert result["suitable"] == "yes"
    assert result["confidence"] >= 90
    assert all(check["pass"] for check in result["checks"])


async def test_portrait_image_is_maybe_not_blocked():
    result = analyze_banner_image(_png_bytes(600, 1000))
    assert result["suitable"] == "maybe"
    assert result["confidence"] < 100
    aspect = next(c for c in result["checks"] if c["key"] == "aspect")
    assert aspect["pass"] is False


async def test_tiny_image_is_blocked():
    result = analyze_banner_image(_png_bytes(200, 150))
    assert result["suitable"] == "no"
    dims = next(c for c in result["checks"] if c["key"] == "dimensions")
    assert dims["pass"] is False


async def test_flat_image_flagged_blurry():
    result = analyze_banner_image(_solid_blur_png())
    blur = next(c for c in result["checks"] if c["key"] == "blur")
    assert blur["pass"] is False


async def test_garbage_bytes_are_rejected():
    result = analyze_banner_image(b"not-an-image")
    assert result["suitable"] == "no"
    assert result["checks"][0]["pass"] is False


async def test_analyze_banner_endpoint(client):
    res = client.post(
        "/api/v1/media/analyze-banner",
        files={"file": ("banner.png", _good_banner_png(), "image/png")},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["suitable"] == "yes"
    assert 0 <= body["confidence"] <= 100
    assert body["ai_verdict"] is None  # no vision model configured in tests
    assert len(body["checks"]) == 5


async def test_analyze_banner_endpoint_rejects_garbage(client):
    res = client.post(
        "/api/v1/media/analyze-banner",
        files={"file": ("x.png", b"garbage", "image/png")},
    )
    assert res.status_code == 200
    assert res.json()["suitable"] == "no"

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


async def test_banner_check_queue_end_to_end(client, db, monkeypatch, tmp_path):
    """Enqueue → realtime-lane handler → polled payload, the full path."""
    from sqlalchemy import select

    from app.config import settings
    from app.modules.jobs.models import Job
    from app.modules.media import service
    from app.modules.media.models import BannerCheck

    monkeypatch.setattr(settings, "MEDIA_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "S3_MEDIA_BUCKET", "")
    monkeypatch.setattr(settings, "AWS_S3_BUCKET", "")
    monkeypatch.setattr(settings, "GCS_PUBLIC_BUCKET", "")

    res = client.post(
        "/api/v1/media/banner-checks",
        files={"file": ("banner.png", _good_banner_png(), "image/png")},
        headers={"host": "localhost"},
    )
    assert res.status_code == 200, res.text
    check_id = res.json()["id"]
    assert res.json()["status"] == "queued"

    # The durable job row exists on the realtime lane, idempotent per check.
    jobs = (
        await db.execute(
            select(Job).where(
                Job.subject_type == "banner_check",
                Job.subject_id == check_id,
            )
        )
    ).scalars().all()
    assert len(jobs) == 1
    assert jobs[0].job_type == "media.banner_check"
    assert jobs[0].lane == "realtime"

    # The handler (what the realtime runner executes) completes the check.
    outcome = await service.run_banner_check(
        db, check_id=check_id, tenant_id=jobs[0].tenant_id,
    )
    assert outcome["status"] == "done"

    row = await db.get(BannerCheck, check_id)
    assert row.status == "done"
    assert row.suitable == "yes"

    # The poll payload matches the synchronous endpoint's shape.
    poll = client.get(f"/api/v1/media/banner-checks/{check_id}", headers={"host": "localhost"})
    assert poll.status_code == 200, poll.text
    body = poll.json()
    assert body["status"] == "done"
    assert body["suitable"] == "yes"
    assert len(body["checks"]) == 5
    assert body["ai_verdict"] is None

    # Idempotent: a retried job never re-analyses a finished check.
    outcome2 = await service.run_banner_check(
        db, check_id=check_id, tenant_id=jobs[0].tenant_id,
    )
    assert outcome2["status"] == "done"


async def test_banner_check_accepts_library_url(client, db, monkeypatch, tmp_path):
    """Library media has no local File: the check must accept the stored URL."""
    from app.config import settings
    from app.modules.media import service

    monkeypatch.setattr(settings, "MEDIA_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "S3_MEDIA_BUCKET", "")
    monkeypatch.setattr(settings, "AWS_S3_BUCKET", "")
    monkeypatch.setattr(settings, "GCS_PUBLIC_BUCKET", "")

    up = client.post(
        "/api/v1/media/upload",
        files={"file": ("banner.png", _good_banner_png(), "image/png")},
        headers={"host": "localhost"},
    )
    assert up.status_code == 200, up.text

    res = client.post(
        "/api/v1/media/banner-checks",
        data={"url": up.json()["image_url"]},
        headers={"host": "localhost"},
    )
    assert res.status_code == 200, res.text
    check_id = res.json()["id"]

    from sqlalchemy import select

    from app.modules.jobs.models import Job

    job = (
        await db.execute(
            select(Job).where(Job.subject_id == check_id, Job.subject_type == "banner_check")
        )
    ).scalar_one()
    outcome = await service.run_banner_check(db, check_id=check_id, tenant_id=job.tenant_id)
    assert outcome["status"] == "done"


async def test_banner_check_queue_rejects_lying_file(client, tmp_path, monkeypatch):
    """The picker normalises; a lying file that slips through is rejected here."""
    from app.config import settings

    monkeypatch.setattr(settings, "MEDIA_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "S3_MEDIA_BUCKET", "")
    monkeypatch.setattr(settings, "AWS_S3_BUCKET", "")
    monkeypatch.setattr(settings, "GCS_PUBLIC_BUCKET", "")
    res = client.post(
        "/api/v1/media/banner-checks",
        files={"file": ("photo.jpg", b"definitely-not-jpeg-bytes", "image/jpeg")},
        headers={"host": "localhost"},
    )
    assert res.status_code == 400
    # Merchant-facing wording, not the storage layer's internals.
    assert "doesn't match its file name" in res.json()["detail"]


async def test_banner_check_poll_unknown_id(client):
    res = client.get("/api/v1/media/banner-checks/nope", headers={"host": "localhost"})
    assert res.status_code == 404

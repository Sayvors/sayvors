"""Profile avatar sources, device uploads, and the cover image.

The profile page lets a tenant switch between the Google picture, the
Facebook picture and a device upload. These tests pin the two invariants that
make that safe:

1. A device upload is never replaced by a later provider sign-in.
2. Only a stored picture can become the effective avatar - a provider that
   never supplied one cannot be selected.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.config import settings
from app.modules.auth.service import google_login
from app.modules.profile import service as profile_service
from app.modules.users.models import User

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff" + b"\x00" * 64
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 32


@pytest.fixture(autouse=True)
def _isolated_profile_state(monkeypatch, tmp_path):
    """Keep uploads in tmp and keep the shared Redis cache out of tests."""
    monkeypatch.setattr(settings, "MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.setattr(settings, "MEDIA_PUBLIC_PATH", "/media-files")
    monkeypatch.setattr(settings, "GCS_PUBLIC_BUCKET", "")
    monkeypatch.setattr(settings, "GCS_PRIVATE_BUCKET", "")
    monkeypatch.setattr(settings, "AWS_S3_BUCKET", "")
    monkeypatch.setattr(settings, "S3_MEDIA_BUCKET", "")
    monkeypatch.setattr(settings, "S3_DOCS_BUCKET", "")

    async def _no_cache(_key):
        return None

    async def _ignore(*_args, **_kwargs):
        return None

    monkeypatch.setattr(profile_service, "_cache_get", _no_cache)
    monkeypatch.setattr(profile_service, "_cache_set", _ignore)
    monkeypatch.setattr(profile_service, "_cache_delete", _ignore)
    monkeypatch.setattr(profile_service, "_emit", AsyncMock())
    return tmp_path


async def _seed(db, user_id, **overrides):
    email = overrides.pop("email", "test@sayvors.com")
    user = User(
        id=user_id,
        email=email,
        first_name="Test",
        last_name="User",
        password_hash="x",
        onboarded=True,
        **overrides,
    )
    db.add(user)
    await db.commit()
    return user


def _upload(client, path: str, name: str, data: bytes, content_type: str):
    return client.post(path, files={"file": (name, data, content_type)})


# ── read shape ────────────────────────────────────────────────────

async def test_profile_exposes_every_avatar_source(client, db, user_id):
    await _seed(
        db,
        user_id,
        google_sub="g-1",
        avatar_source="google",
        avatar_url="https://img.example/google.png",
        google_avatar_url="https://img.example/google.png",
        cover_url="https://img.example/cover.jpg",
    )

    body = client.get("/api/v1/profile").json()

    assert body["avatar_url"] == "https://img.example/google.png"
    assert body["avatar_source"] == "google"
    assert body["google_avatar_url"] == "https://img.example/google.png"
    assert body["facebook_avatar_url"] is None
    assert body["cover_url"] == "https://img.example/cover.jpg"
    assert body["google_connected"] is True
    assert body["facebook_connected"] is False


# ── source switching ──────────────────────────────────────────────

async def test_switch_avatar_source_uses_the_stored_url(client, db, user_id):
    await _seed(
        db,
        user_id,
        google_sub="g-1",
        facebook_id="fb-1",
        avatar_source="google",
        avatar_url="https://img.example/google.png",
        google_avatar_url="https://img.example/google.png",
        facebook_avatar_url="https://img.example/facebook.png",
    )

    res = client.put("/api/v1/profile/avatar-source", json={"source": "facebook"})

    assert res.status_code == 200, res.text
    assert res.json()["avatar_source"] == "facebook"
    assert res.json()["avatar_url"] == "https://img.example/facebook.png"


async def test_switch_to_a_missing_provider_is_rejected(client, db, user_id):
    await _seed(
        db,
        user_id,
        google_sub="g-1",
        avatar_source="google",
        avatar_url="https://img.example/google.png",
        google_avatar_url="https://img.example/google.png",
    )

    res = client.put("/api/v1/profile/avatar-source", json={"source": "facebook"})

    assert res.status_code == 400
    assert "not available" in res.json()["detail"]


async def test_remove_avatar_keeps_the_snapshots(client, db, user_id):
    await _seed(
        db,
        user_id,
        google_sub="g-1",
        avatar_source="google",
        avatar_url="https://img.example/google.png",
        google_avatar_url="https://img.example/google.png",
    )

    res = client.delete("/api/v1/profile/avatar")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["avatar_url"] is None
    assert body["avatar_source"] == "none"
    assert body["google_avatar_url"] == "https://img.example/google.png"

    # And the user can switch the provider back without another login.
    back = client.put("/api/v1/profile/avatar-source", json={"source": "google"})
    assert back.status_code == 200
    assert back.json()["avatar_url"] == "https://img.example/google.png"


# ── device uploads ────────────────────────────────────────────────

@pytest.mark.parametrize(
    "name,data,content_type",
    [
        ("me.png", PNG, "image/png"),
        ("me.jpg", JPEG, "image/jpeg"),
        ("me.webp", WEBP, "image/webp"),
    ],
)
async def test_upload_avatar_sets_the_device_source(
    client, db, user_id, name, data, content_type
):
    await _seed(db, user_id)

    res = _upload(client, "/api/v1/profile/avatar", name, data, content_type)

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["avatar_source"] == "upload"
    assert body["avatar_upload_url"] == body["avatar_url"]
    assert body["avatar_url"].startswith("http")
    assert body["avatar_url"].endswith((".png", ".jpg", ".webp"))


async def test_upload_rejects_a_renamed_non_image(client, db, user_id):
    await _seed(db, user_id)

    res = _upload(
        client,
        "/api/v1/profile/avatar",
        "evil.png",
        b"<html><script>alert(1)</script></html>",
        "image/png",
    )

    assert res.status_code == 400
    assert "doesn't look like" in res.json()["detail"]


async def test_upload_rejects_svg_and_video(client, db, user_id):
    await _seed(db, user_id)

    svg = _upload(client, "/api/v1/profile/avatar", "x.svg", b"<svg/>", "image/svg+xml")
    mp4 = _upload(client, "/api/v1/profile/avatar", "x.mp4", b"....ftyp", "video/mp4")

    assert svg.status_code == 400
    assert mp4.status_code == 400


async def test_upload_cover_sets_and_clears_it(client, db, user_id):
    await _seed(db, user_id)

    uploaded = _upload(client, "/api/v1/profile/cover", "cover.jpg", JPEG, "image/jpeg")
    assert uploaded.status_code == 200, uploaded.text
    cover_url = uploaded.json()["cover_url"]
    assert cover_url and cover_url.startswith("http")

    removed = client.delete("/api/v1/profile/cover")
    assert removed.status_code == 200, removed.text
    assert removed.json()["cover_url"] is None


# ── provider sign-in must not clobber an explicit choice ─────────

async def test_google_login_does_not_replace_a_device_upload(db, user_id):
    await _seed(
        db,
        user_id,
        email="guser@sayvors.com",
        google_sub="google-sub-001",
        avatar_source="upload",
        avatar_url="https://cdn.example/device.png",
        avatar_upload_url="https://cdn.example/device.png",
    )

    claims = {
        "sub": "google-sub-001",
        "email": "guser@sayvors.com",
        "email_verified": True,
        "name": "G User",
        "picture": "https://img.example/google-new.png",
    }
    with patch("app.modules.auth.service.log_login", new_callable=AsyncMock):
        await google_login(claims, db, "UA", "1.2.3.4")

    user = await db.get(User, user_id)
    assert user.avatar_url == "https://cdn.example/device.png"
    assert user.avatar_source == "upload"
    # The provider snapshot still refreshes so the switch can offer it.
    assert user.google_avatar_url == "https://img.example/google-new.png"


async def test_google_login_updates_the_effective_avatar_when_google_is_chosen(db, user_id):
    await _seed(
        db,
        user_id,
        email="guser@sayvors.com",
        google_sub="google-sub-001",
        avatar_source="google",
        avatar_url="https://img.example/google-old.png",
        google_avatar_url="https://img.example/google-old.png",
    )

    claims = {
        "sub": "google-sub-001",
        "email": "guser@sayvors.com",
        "email_verified": True,
        "name": "G User",
        "picture": "https://img.example/google-new.png",
    }
    with patch("app.modules.auth.service.log_login", new_callable=AsyncMock):
        await google_login(claims, db, "UA", "1.2.3.4")

    user = await db.get(User, user_id)
    assert user.avatar_url == "https://img.example/google-new.png"
    assert user.google_avatar_url == "https://img.example/google-new.png"

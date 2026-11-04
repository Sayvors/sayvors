"""Facebook/Instagram connection flags gate new OAuth only."""
import pytest
from fastapi import HTTPException

from app.modules.channels.meta import router as meta_router


def test_meta_connect_flags_default_to_false(monkeypatch):
    monkeypatch.setattr(meta_router.settings, "META_FACEBOOK_CONNECT_ENABLED", False)
    monkeypatch.setattr(meta_router.settings, "META_INSTAGRAM_CONNECT_ENABLED", False)
    assert meta_router._connect_enabled("facebook") is False
    assert meta_router._connect_enabled("instagram") is False
    assert meta_router._connect_enabled("whatsapp") is True


def test_meta_connect_flags_can_be_enabled(monkeypatch):
    monkeypatch.setattr(meta_router.settings, "META_FACEBOOK_CONNECT_ENABLED", True)
    monkeypatch.setattr(meta_router.settings, "META_INSTAGRAM_CONNECT_ENABLED", True)
    assert meta_router._connect_enabled("facebook") is True
    assert meta_router._connect_enabled("instagram") is True


@pytest.mark.asyncio
async def test_start_connect_rejects_a_disabled_provider(monkeypatch):
    monkeypatch.setattr(meta_router.settings, "META_FACEBOOK_CONNECT_ENABLED", False)
    with pytest.raises(HTTPException) as err:
        await meta_router.start_connect(
            provider="facebook",
            request=None,
            next_path=None,
            ctx=None,
            user=None,
            db=None,
        )
    assert err.value.status_code == 403
    assert "paused" in err.value.detail.lower()

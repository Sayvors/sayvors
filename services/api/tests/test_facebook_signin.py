"""Tests for Continue with Facebook (token verify, service, endpoint, config)."""


def test_login_app_fallback(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "META_APP_ID", "app1")
    monkeypatch.setattr(settings, "META_APP_SECRET", "sec1")
    monkeypatch.setattr(settings, "META_LOGIN_APP_ID", "")
    monkeypatch.setattr(settings, "META_LOGIN_APP_SECRET", "")
    assert settings.facebook_login_app_id == "app1"
    assert settings.facebook_login_app_secret == "sec1"
    monkeypatch.setattr(settings, "META_LOGIN_APP_ID", "app2")
    monkeypatch.setattr(settings, "META_LOGIN_APP_SECRET", "sec2")
    assert settings.facebook_login_app_id == "app2"
    assert settings.facebook_login_app_secret == "sec2"

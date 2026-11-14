"""Notification email CTA handling (regression).

Billing decisions pass a site-relative CTA (e.g. "/dashboard/billing/topup");
send_notification_email used to reject that with ValueError, which the caller
swallowed as best-effort — the email was silently never sent. It must resolve
relative paths against FRONTEND_URL instead.
"""
import pytest

from app.modules.email import service as email_service


@pytest.mark.asyncio
async def test_send_notification_email_resolves_relative_cta(monkeypatch):
    captured: dict = {}

    async def fake_enqueue(to, subject, html, text, *, kind, tenant_id=None,
                           idempotency_key=None, headers=None):
        captured.update(to=to, subject=subject, html=html, text=text, kind=kind)
        return "outbox-id"

    monkeypatch.setattr(email_service, "_enqueue", fake_enqueue)
    monkeypatch.setattr(
        "app.config.settings.FRONTEND_URL", "https://dev-web.sayvors.com", raising=False
    )

    msg_id = await email_service.send_notification_email(
        "syab293@gmail.com",
        "Plan changed",
        "You are now on Enterprise",
        cta_url="/dashboard/billing/topup",
    )
    assert msg_id == "outbox-id"
    assert captured["kind"] == "notification"
    assert "https://dev-web.sayvors.com/dashboard/billing/topup" in captured["html"]


@pytest.mark.asyncio
async def test_send_notification_email_neutralizes_non_http_cta(monkeypatch):
    """javascript:/data: CTAs must never survive as-is — they resolve to an
    http(s) URL against FRONTEND_URL instead of being enqueued raw."""
    captured: dict = {}

    async def fake_enqueue(to, subject, html, text, *, kind, tenant_id=None,
                           idempotency_key=None, headers=None):
        captured.update(to=to, subject=subject, html=html, text=text, kind=kind)
        return "outbox-id"

    monkeypatch.setattr(email_service, "_enqueue", fake_enqueue)
    monkeypatch.setattr(
        "app.config.settings.FRONTEND_URL", "https://dev-web.sayvors.com", raising=False
    )

    await email_service.send_notification_email(
        "a@b.com", "x", "y", cta_url="javascript:alert(1)"
    )
    # The dangerous scheme is gone: the href is now an absolute https URL
    # against FRONTEND_URL (javascript: only survives as inert path text).
    assert "href='https://dev-web.sayvors.com/javascript:alert(1)'" in captured["html"]
    assert "href='javascript:" not in captured["html"]

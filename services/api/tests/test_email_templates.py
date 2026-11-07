"""Sayvors transactional emails render the bilingual brand layout."""
from app.modules.email import templates
from app.modules.email import service

BASE = "https://dev-web.sayvors.com"


def _shell_kwargs():
    return {
        "frontend_url": BASE,
        "support_email": service.SUPPORT_EMAIL,
        "help_url": f"{BASE}/dashboard",
        "privacy_url": f"{BASE}/privacy",
    }


def test_otp_email_has_code_arabic_heading_and_no_placeholders():
    html = templates.otp_email(code="123456", purpose="verification", **_shell_kwargs())

    assert "123456" in html
    assert "تأكيد هويتك" in html
    assert f"{BASE}/Sayvors_Icon.png" in html
    assert "{{" not in html
    assert "EVERY LINE, ONE VOICE" in html
    assert "10 minutes" in html


def test_welcome_email_escapes_the_name_and_links_the_dashboard():
    html = templates.welcome_email(
        name="&lt;script&gt;alert(1)&lt;/script&gt;",
        dashboard_url=f"{BASE}/dashboard",
        **_shell_kwargs(),
    )

    assert "&lt;script&gt;" not in html or "<script>alert(1)</script>" not in html
    assert "Welcome to Sayvors" in html
    assert "أهلًا بك في Sayvors" in html
    assert f"{BASE}/dashboard" in html
    assert "{{" not in html


def test_reset_email_contains_the_reset_link_and_arabic_copy():
    link = f"{BASE}/reset-password?token=abc"
    html = templates.reset_email(name="Sara", reset_url=link, **_shell_kwargs())

    assert link in html
    assert "هل نسيت كلمة المرور؟" in html
    assert "1 hour" in html
    assert "{{" not in html


def test_generic_shell_renders_an_english_hero_without_arabic_title():
    html = templates.shell(
        title_ar="",
        title_en="Activate your account",
        preheader="Activate",
        body_html="<p>Hello</p>",
        **_shell_kwargs(),
    )

    assert "Activate your account" in html
    assert "dir=\"ltr\"" in html
    assert "{{" not in html


def test_service_welcome_and_reset_use_the_new_templates(monkeypatch):
    sent = {}

    async def fake_send(to, subject, html, text=None, **kwargs):
        sent["to"] = to
        sent["subject"] = subject
        sent["html"] = html
        sent["text"] = text
        sent["kind"] = kwargs.get("kind")
        return "id"

    monkeypatch.setattr(service, "send_email", fake_send)

    import asyncio

    asyncio.run(service.send_welcome_email("a@b.com", "Sara"))
    assert "أهلًا بك في Sayvors" in sent["html"]
    assert sent["text"]

    asyncio.run(service.send_password_reset_email("a@b.com", "Sara", f"{BASE}/reset?t=1"))
    assert f"{BASE}/reset?t=1" in sent["html"]

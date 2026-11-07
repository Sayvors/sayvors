"""Email delivery service backed by Resend.

This module centralizes all server-side email sending for Sayvors. It keeps the
email provider credentials and sending logic away from the API layer and frontend,
while offering a small, predictable set of helpers for OTP flows and transactional
messages.

The service intentionally writes to Redis for transient OTP state and uses Resend's
HTTP API for delivery, which avoids introducing a separate dependency and keeps the
infrastructure simple.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import logging
import secrets

import httpx

from ...config import settings
from ..redis.client import get_redis
from . import templates as email_templates

logger = logging.getLogger(__name__)

OTP_TTL_SECONDS = 10 * 60
# Guessing budget per OTP before the code is invalidated. 6 digits x 5 tries
# keeps the per-OTP success probability at 5e-6 even without IP throttling.
OTP_MAX_ATTEMPTS = 5

LOGO_FILENAME = "Sayvors_Wordmark_Dark.png"
SUPPORT_EMAIL = "it@sayvors.com"


def _base_url() -> str:
    return (settings.FRONTEND_URL or "").rstrip("/")


def _help_url() -> str:
    return f"{_base_url()}/dashboard" if _base_url() else "https://sayvors.com"


def _privacy_url() -> str:
    return f"{_base_url()}/privacy" if _base_url() else "https://sayvors.com/privacy"


def _logo_url() -> str:
    """Absolute logo URL for email clients (they can't resolve relative paths)."""
    base = (settings.FRONTEND_URL or "").rstrip("/")
    return f"{base}/{LOGO_FILENAME}" if base else f"/{LOGO_FILENAME}"


def _shell(title: str, body_inner: str, logo_url: str | None = None) -> str:
    """Shared Sayvors layout (brand header, gradient hero, text footer)."""
    return email_templates.shell(
        title_ar="",
        title_en=title,
        preheader=title,
        body_html=body_inner,
        frontend_url=_base_url(),
        support_email=SUPPORT_EMAIL,
        help_url=_help_url(),
        privacy_url=_privacy_url(),
    )


def _cta_button(label: str, url: str) -> str:
    return email_templates._cta(label, url)


def _configured() -> bool:
    """Return True when the required Resend API key is configured."""

    return bool(settings.RESEND_API_KEY.strip())


async def send_email(
    to: str | list[str],
    subject: str,
    html: str,
    text: str | None = None,
    *,
    kind: str = "notification",
    tenant_id: str | None = None,
    idempotency_key: str | None = None,
    headers: dict | None = None,
) -> str:
    """Queue one email; delivery is handled by the outbox worker.

    Kept as the single entry point for callers: no request ever waits on the
    provider. A database failure still raises, because losing the row silently
    would lose the email.
    """
    if isinstance(to, list):
        # Legacy bulk API: one row per recipient, never a shared To header.
        last = ""
        for recipient in to:
            queued = await _enqueue(
                recipient, subject, html, text,
                kind=kind, tenant_id=tenant_id,
                idempotency_key=f"{idempotency_key}:{recipient}" if idempotency_key else None,
                headers=headers,
            )
            last = queued or last
        return last
    return await _enqueue(
        to, subject, html, text,
        kind=kind, tenant_id=tenant_id,
        idempotency_key=idempotency_key, headers=headers,
    ) or ""


async def _enqueue(
    to: str,
    subject: str,
    html: str,
    text: str | None,
    *,
    kind: str,
    tenant_id: str | None = None,
    idempotency_key: str | None = None,
    headers: dict | None = None,
) -> str | None:
    from ...database import async_session
    from .outbox import enqueue_email

    async with async_session() as db:
        return await enqueue_email(
            db,
            to=to,
            subject=subject,
            html=html,
            text=text,
            kind=kind,
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            headers=headers,
        )


# ── OTP ────────────────────────────────────────────────

def _otp_key(email: str) -> str:
    """Create the Redis key used to store a transient one-time password."""

    return f"otp:{email.strip().lower()}"


async def send_otp_email(email: str, purpose: str = "verification") -> None:
    """Create and send a one-time passcode for email verification.

    The generated code is stored in Redis for 10 minutes, then the HTML/plain-text
    version is sent through Resend. If the same email requests a new code, the
    newest value replaces the older one.

    The code lives ONLY in the body — never the subject — so it does not show up
    on lock screens / notification previews.
    """

    code = f"{secrets.randbelow(900000) + 100000}"
    redis = await get_redis()
    await redis.setex(_otp_key(email), OTP_TTL_SECONDS, code)
    await redis.delete(_otp_attempts_key(email))
    if not _configured():
        raise RuntimeError("Server is missing RESEND_API_KEY in .env.")
    html = email_templates.otp_email(
        code=code,
        purpose=purpose,
        frontend_url=_base_url(),
        support_email=SUPPORT_EMAIL,
        help_url=_help_url(),
        privacy_url=_privacy_url(),
    )
    await send_email(
        email,
        f"Your Sayvors {purpose} code · رمز التحقق",
        html,
        text=f"Your Sayvors {purpose} code is: {code} (expires in 10 minutes)",
        kind="auth.otp",
        idempotency_key=f"otp:{email.strip().lower()}:{code}",
    )


def _otp_attempts_key(email: str) -> str:
    return f"{_otp_key(email)}:attempts"


async def verify_otp(email: str, code: str) -> bool:
    """Validate a stored OTP and consume it on success.

    Returns True only when the provided code matches the Redis value for the email.
    A successful match deletes the underlying key so the OTP cannot be reused.

    Brute-force control: a per-email attempt counter invalidates the code after
    OTP_MAX_ATTEMPTS failed tries. Comparison is constant-time.
    """

    redis = await get_redis()
    otp_key = _otp_key(email)
    attempts_key = _otp_attempts_key(email)

    try:
        attempts = int(await redis.get(attempts_key) or 0)
    except (TypeError, ValueError):
        attempts = 0
    if attempts >= OTP_MAX_ATTEMPTS:
        # Budget exhausted: kill the code so even the correct answer fails.
        await redis.delete(otp_key)
        return False

    stored = await redis.get(otp_key)
    if stored and hmac.compare_digest(stored.strip().encode(), code.strip().encode()):
        await redis.delete(otp_key)
        await redis.delete(attempts_key)
        return True

    await redis.incr(attempts_key)
    await redis.expire(attempts_key, OTP_TTL_SECONDS)
    return False


# ── Templated mails ────────────────────────────────────

async def send_activation_email(email: str, name: str, activation_url: str) -> str:
    """Send a welcome/activation email with a direct account activation link."""
    display = name or "there"
    body = (
        f"<p style=\"margin:0 0 16px;font-size:15px;line-height:24px;color:#52525B;\">Hi {display},</p>"
        f"<p style=\"margin:0 0 16px;font-size:15px;line-height:24px;color:#52525B;\">Welcome to Sayvors! Please activate your account:</p>"
        f"{_cta_button('Activate my account', activation_url)}"
        f"<p style=\"margin:16px 0 0;font-size:14px;line-height:22px;color:#71717A;word-break:break-all;\">If the button doesn't work, paste this link: {activation_url}</p>"
    )
    return await send_email(
        email,
        "Activate your Sayvors account",
        _shell("Activate your account", body, _logo_url()),
        text=f"Hi {display}, activate your Sayvors account: {activation_url}",
        kind="activation",
        idempotency_key=f"activation:{email}:{hashlib.sha1(activation_url.encode()).hexdigest()[:20]}",
    )


async def send_team_invite_email(
    email: str, inviter_name: str, business_name: str, role_name: str, invite_url: str
) -> str:
    """Invite a person to a workspace's team. Link carries a single-use
    token; accepting either creates their account or attaches the existing
    one (never exposes a password-reset path — see team/service.accept)."""
    display = inviter_name or "Your team"
    brand = business_name or "a Sayvors workspace"
    body = (
        f"<p style=\"margin:0 0 16px;font-size:15px;line-height:24px;color:#52525B;\">Hi,</p>"
        f"<p style=\"margin:0 0 16px;font-size:15px;line-height:24px;color:#52525B;\">"
        f"{display} invited you to join <strong style=\"color:#1a1230;\">{brand}</strong> on Sayvors as "
        f"<strong style=\"color:#1a1230;\">{role_name}</strong>.</p>"
        f"<p style=\"margin:0 0 16px;font-size:15px;line-height:24px;color:#52525B;\">"
        f"Accept the invite to set up your access (link expires in <strong style=\"color:#52525B;\">7 days</strong>):</p>"
        f"{_cta_button('Join the team', invite_url)}"
        f"<p style=\"margin:16px 0 0;font-size:14px;line-height:22px;color:#71717A;word-break:break-all;\">If the button doesn't work, paste this link: {invite_url}</p>"
        f"<p style=\"margin:16px 0 0;font-size:14px;line-height:22px;color:#71717A;\">If you weren't expecting this, you can safely ignore this email.</p>"
    )
    return await send_email(
        email,
        f"{display} invited you to {brand} on Sayvors",
        _shell("Team invitation", body, _logo_url()),
        text=f"{display} invited you to {brand} on Sayvors as {role_name}: {invite_url}",
        kind="team_invite",
        idempotency_key=f"team:{email}:{hashlib.sha1(invite_url.encode()).hexdigest()[:20]}",
    )


async def send_password_reset_email(email: str, name: str, reset_url: str) -> str:
    """Send a password reset email containing a secure recovery URL."""
    import html as _html

    display = _html.escape(name or "there")
    html = email_templates.reset_email(
        name=display,
        reset_url=reset_url,
        frontend_url=_base_url(),
        support_email=SUPPORT_EMAIL,
        help_url=_help_url(),
        privacy_url=_privacy_url(),
    )
    return await send_email(
        email,
        "Reset your Sayvors password · إعادة تعيين كلمة المرور",
        html,
        text=f"Hi {display}, reset your Sayvors password (expires in 1 hour): {reset_url}",
        kind="password_reset",
        idempotency_key=f"reset:{email}:{hashlib.sha1(reset_url.encode()).hexdigest()[:20]}",
    )


async def send_password_reset_success_email(
    email: str,
    name: str,
    when: "datetime",
    ip: str,
    location: str,
    device: str,
) -> str:
    """Security notice: password was just reset — time, IP, location, device."""
    import html as _html

    display = _html.escape(name or "there")
    when_str = when.strftime("%Y-%m-%d %H:%M:%S UTC")
    safe_ip = _html.escape(ip or "")
    safe_location = _html.escape(location or "Unknown location")
    safe_device = _html.escape(device or "Unknown device")

    def _row(label: str, value: str) -> str:
        return (
            f"<tr>"
            f"<td style=\"padding:8px 0;color:#71717A;font-size:13px;width:100px;vertical-align:top;\">{label}</td>"
            f"<td style=\"padding:8px 0;color:#1F2937;font-size:13px;font-weight:600;\">{value}</td>"
            f"</tr>"
        )

    details = "".join(
        (
            _row("Time", when_str),
            _row("IP address", safe_ip),
            _row("Location", safe_location),
            _row("Device", safe_device),
        )
    )
    forgot_url = f"{(settings.FRONTEND_URL or '').rstrip('/')}/forgot-password"
    body = (
        f"<p style=\"margin:0 0 16px;font-size:15px;line-height:24px;color:#52525B;\">Hi {display},</p>"
        f"<p style=\"margin:0 0 8px;font-size:15px;line-height:24px;color:#52525B;\">Your Sayvors password was just changed successfully.</p>"
        f"<p style=\"margin:0 0 4px;font-size:13px;line-height:20px;color:#71717A;\">Here are the details of that activity:</p>"
        f"<table role=\"presentation\" cellpadding=\"0\" cellspacing=\"0\" style=\"width:100%;margin:12px 0;padding:4px 20px;background-color:#FAFAFA;border:1px solid #EEEEF0;border-radius:8px;\">{details}</table>"
        f"<p style=\"margin:16px 0 0;font-size:14px;line-height:22px;color:#52525B;\">If this was you, you're all set — no further action needed.</p>"
        f"<p style=\"margin:12px 0 0;font-size:14px;line-height:22px;color:#52525B;\">If this <strong>wasn't you</strong>, someone else may have access to your account — reset your password immediately:</p>"
        f"{_cta_button('Secure my account', forgot_url)}"
    )
    return await send_email(
        email,
        "Your Sayvors password was changed",
        _shell("Password changed", body, _logo_url()),
        text=(
            f"Hi {display}, your Sayvors password was changed.\n"
            f"Time: {when_str}\nIP: {safe_ip}\nLocation: {safe_location}\nDevice: {safe_device}\n"
            f"If this wasn't you, secure your account: {forgot_url}"
        ),
        kind="security",
        idempotency_key=f"pwd-changed:{email}:{when_str}",
    )


async def send_account_exists_email(email: str, name: str) -> str:
    """Tell the mailbox owner that a signup was attempted for an existing account.

    The signup endpoint returns the same response whether or not the email is
    registered. This message is the legitimate user's next step; an attacker
    who does not control the mailbox learns nothing.
    """
    import html as _html

    display = _html.escape(name or "there")
    login_url = f"{(settings.FRONTEND_URL or '').rstrip('/')}/login"
    body = (
        f"<p style=\"margin:0 0 16px;font-size:15px;line-height:24px;color:#52525B;\">Hi {display},</p>"
        f"<p style=\"margin:0 0 16px;font-size:15px;line-height:24px;color:#52525B;\">Someone tried to create a Sayvors account with this email, but an account already exists. If this was you, sign in instead:</p>"
        f"{_cta_button('Sign in to Sayvors', login_url)}"
        f"<p style=\"margin:16px 0 0;font-size:14px;line-height:22px;color:#71717A;\">If you didn't request this, you can safely ignore this email.</p>"
    )
    return await send_email(
        email,
        "Your Sayvors account already exists",
        _shell("Your account already exists", body, _logo_url()),
        text=(
            f"Hi {display}, an account already exists for this email. "
            f"Sign in: {login_url}"
        ),
        kind="account_exists",
        idempotency_key=f"exists:{email}:{datetime.now(timezone.utc):%Y-%m-%d}",
    )


async def send_welcome_email(email: str, name: str) -> str:
    """Send the bilingual welcome email after account creation."""
    import html as _html

    display = _html.escape(name or "there")
    dashboard_url = f"{_base_url()}/dashboard" if _base_url() else "https://app.sayvors.com/dashboard"
    html = email_templates.welcome_email(
        name=display,
        dashboard_url=dashboard_url,
        frontend_url=_base_url(),
        support_email=SUPPORT_EMAIL,
        help_url=_help_url(),
        privacy_url=_privacy_url(),
    )
    return await send_email(
        email,
        f"Welcome to Sayvors · أهلًا بك في Sayvors",
        html,
        text=(
            f"Hi {display}, your Sayvors account is ready.\n"
            f"Open your dashboard: {dashboard_url}\n"
            f"Need help? {SUPPORT_EMAIL}"
        ),
        kind="welcome",
        idempotency_key=f"welcome:{email}",
    )


async def send_notification_email(email: str, subject: str, message: str, cta_url: str | None = None) -> str:
    """Send a generic internal notification email to a user.

    This is intended for system notifications, alerts, and other non-public
    transactional communications. When provided, a CTA link is included in the HTML.

    `message` is plain text and is HTML-escaped before being embedded; callers
    must not rely on HTML markup surviving. `cta_url` must be an http(s) URL.
    """

    import html as _html
    from urllib.parse import urlparse as _urlparse

    full_subject = f"[Sayvors] {subject}"
    safe_message = _html.escape(message or "")
    cta = ""
    if cta_url:
        parsed = _urlparse(cta_url or "")
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("cta_url must be an absolute http(s) URL.")
        safe_cta = _html.escape(cta_url, quote=True)
        cta = f"<p><a href='{safe_cta}'>View in Sayvors</a></p>"
    body = (
        f"<p dir=\"ltr\" style=\"margin:0 0 16px;font-size:15px;line-height:24px;color:#4A4266;\">{safe_message}</p>"
        f"{cta}"
    )
    return await send_email(
        email,
        full_subject,
        _shell(subject, body),
        text=f"{full_subject}\n{message}" + (f"\n{cta_url}" if cta_url else ""),
        kind="notification",
    )

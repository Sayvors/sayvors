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

import logging
import secrets

import httpx

from ...config import settings
from ..redis.client import get_redis

logger = logging.getLogger(__name__)

OTP_TTL_SECONDS = 10 * 60

LOGO_FILENAME = "Sayvors_Wordmark_Dark.png"


def _logo_url() -> str:
    """Absolute logo URL for email clients (they can't resolve relative paths)."""
    base = (settings.FRONTEND_URL or "").rstrip("/")
    return f"{base}/{LOGO_FILENAME}" if base else f"/{LOGO_FILENAME}"


FOOTER_HTML = """<tr>
    <td style="padding:28px 40px;background-color:#FAFAFA;border-top:1px solid #EEEEF0;text-align:center;">
      <p style="margin:0 0 16px;font-size:13px;font-weight:600;color:#52525B;">Follow Sayvors</p>
      <table role="presentation" cellpadding="0" cellspacing="0" align="center" style="margin:0 auto;"><tr>
        <td style="padding:0 8px;">
          <a href="https://www.linkedin.com/company/Sayvors"><img src="https://cdn.jsdelivr.net/npm/simple-icons@v13/icons/linkedin.svg" width="40" height="40" alt="LinkedIn" style="display:block;border:0;border-radius:8px;"></a>
        </td>
        <td style="padding:0 8px;">
          <a href="https://twitter.com/Sayvors"><img src="https://cdn.jsdelivr.net/npm/simple-icons@v13/icons/x.svg" width="40" height="40" alt="X" style="display:block;border:0;border-radius:8px;"></a>
        </td>
        <td style="padding:0 8px;">
          <a href="https://www.facebook.com/Sayvors"><img src="https://cdn.jsdelivr.net/npm/simple-icons@v13/icons/facebook.svg" width="40" height="40" alt="Facebook" style="display:block;border:0;border-radius:8px;"></a>
        </td>
        <td style="padding:0 8px;">
          <a href="https://www.instagram.com/Sayvors"><img src="https://cdn.jsdelivr.net/npm/simple-icons@v13/icons/instagram.svg" width="40" height="40" alt="Instagram" style="display:block;border:0;border-radius:8px;"></a>
        </td>
      </tr></table>
      <p style="margin:16px 0 6px;font-size:12px;color:#A1A1AA;">
        <a href="https://Sayvors.com" style="color:#71717A;text-decoration:none;font-weight:600;">Sayvors.com</a>
      </p>
      <p style="margin:0;font-size:12px;color:#A1A1AA;">EVERY LINE, ONE VOICE</p>
      <p style="margin:6px 0 0;font-size:12px;color:#A1A1AA;">© Sayvors — Automated message, please do not reply.</p>
    </td>
  </tr>"""


def _shell(title: str, body_inner: str, logo_url: str) -> str:
    """Shared branded layout (same header/body/footer as the OTP email)."""
    return f"""<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#F4F4F5;padding:32px 16px;">
<tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background-color:#ffffff;border-radius:12px;overflow:hidden;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">

  <!-- Header -->
  <tr><td style="padding:28px 40px;border-bottom:1px solid #EEEEF0;">
    <img src="{logo_url}" alt="Sayvors" width="160" style="display:block;border:0;max-width:160px;height:auto;">
    <div style="margin-top:8px;font-size:11px;font-weight:600;letter-spacing:3px;color:#A1A1AA;">EVERY LINE, ONE VOICE</div>
  </td></tr>

  <!-- Body -->
  <tr><td style="padding:40px;color:#1F2937;">
    <h1 style="margin:0 0 12px;font-size:22px;font-weight:700;color:#1F2937;">{title}</h1>
    {body_inner}
  </td></tr>

  <!-- Footer with social icons -->
  {FOOTER_HTML}

</table>
</td></tr>
</table>"""


def _cta_button(label: str, url: str) -> str:
    return (
        f"<div style=\"margin:28px 0;text-align:center;\">"
        f"<a href=\"{url}\" style=\"display:inline-block;background-color:#5B2D8E;color:#ffffff;"
        f"font-size:15px;font-weight:700;text-decoration:none;padding:14px 32px;border-radius:10px;\">{label}</a>"
        f"</div>"
    )


def _configured() -> bool:
    """Return True when the required Resend API key is configured."""

    return bool(settings.RESEND_API_KEY.strip())


async def send_email(to: str | list[str], subject: str, html: str, text: str | None = None) -> str:
    """Send a single email using the Resend API.

    Args:
        to: One recipient or a list of recipients.
        subject: Email subject line.
        html: HTML content to send to Resend.
        text: Optional plain-text content used as a fallback.

    Returns:
        The Resend message identifier for the sent email.

    Raises:
        RuntimeError: If the API key is missing or Resend rejects the request.
    """

    if not _configured():
        raise RuntimeError("Server is missing RESEND_API_KEY in .env.")
    payload: dict = {
        "from": settings.RESEND_FROM,
        "to": [to] if isinstance(to, str) else to,
        "subject": subject,
        "html": html,
    }
    if text:
        payload["text"] = text
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            settings.RESEND_URL,
            headers={
                "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
    if resp.status_code >= 400:
        logger.warning("Resend rejected email: %s %s", resp.status_code, resp.text[:300])
        raise RuntimeError(f"Resend error {resp.status_code}: {resp.text[:200]}")
    return resp.json().get("id", "")


# ── OTP ────────────────────────────────────────────────

def _otp_key(email: str) -> str:
    """Create the Redis key used to store a transient one-time password."""

    return f"otp:{email.strip().lower()}"


OTP_HTML = """<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#F4F4F5;padding:32px 16px;">
<tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background-color:#ffffff;border-radius:12px;overflow:hidden;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">

  <!-- Header -->
  <tr><td style="padding:28px 40px;border-bottom:1px solid #EEEEF0;">
    <img src="{logo_url}" alt="Sayvors" width="160" style="display:block;border:0;max-width:160px;height:auto;">
    <div style="margin-top:8px;font-size:11px;font-weight:600;letter-spacing:3px;color:#A1A1AA;">EVERY LINE, ONE VOICE</div>
  </td></tr>

  <!-- Body -->
  <tr><td style="padding:40px;color:#1F2937;">
    <h1 style="margin:0 0 12px;font-size:22px;font-weight:700;color:#1F2937;">Your verification code</h1>
    <p style="margin:0 0 28px;font-size:15px;line-height:24px;color:#52525B;">Your Sayvors {purpose} code is:</p>
    <div style="background-color:#FFF7ED;border:1px solid #FED7AA;border-radius:10px;padding:20px;text-align:center;">
      <span style="font-size:32px;font-weight:700;letter-spacing:8px;color:#1F2937;font-family:'Courier New',Courier,monospace;">{code}</span>
    </div>
    <p style="margin:28px 0 0;font-size:14px;line-height:22px;color:#71717A;">This code expires in <strong style="color:#52525B;">10 minutes</strong>. If you didn't request it, you can safely ignore this email.</p>
  </td></tr>

  <!-- Footer with social icons -->
  <tr>
    <td style="padding:28px 40px;background-color:#FAFAFA;border-top:1px solid #EEEEF0;text-align:center;">
      <p style="margin:0 0 16px;font-size:13px;font-weight:600;color:#52525B;">Follow Sayvors</p>
      <table role="presentation" cellpadding="0" cellspacing="0" align="center" style="margin:0 auto;"><tr>
        <td style="padding:0 8px;">
          <a href="https://www.linkedin.com/company/Sayvors"><img src="https://cdn.jsdelivr.net/npm/simple-icons@v13/icons/linkedin.svg" width="40" height="40" alt="LinkedIn" style="display:block;border:0;border-radius:8px;"></a>
        </td>
        <td style="padding:0 8px;">
          <a href="https://twitter.com/Sayvors"><img src="https://cdn.jsdelivr.net/npm/simple-icons@v13/icons/x.svg" width="40" height="40" alt="X" style="display:block;border:0;border-radius:8px;"></a>
        </td>
        <td style="padding:0 8px;">
          <a href="https://www.facebook.com/Sayvors"><img src="https://cdn.jsdelivr.net/npm/simple-icons@v13/icons/facebook.svg" width="40" height="40" alt="Facebook" style="display:block;border:0;border-radius:8px;"></a>
        </td>
        <td style="padding:0 8px;">
          <a href="https://www.instagram.com/Sayvors"><img src="https://cdn.jsdelivr.net/npm/simple-icons@v13/icons/instagram.svg" width="40" height="40" alt="Instagram" style="display:block;border:0;border-radius:8px;"></a>
        </td>
      </tr></table>
      <p style="margin:16px 0 6px;font-size:12px;color:#A1A1AA;">
        <a href="https://Sayvors.com" style="color:#71717A;text-decoration:none;font-weight:600;">Sayvors.com</a>
      </p>
      <p style="margin:0;font-size:12px;color:#A1A1AA;">EVERY LINE, ONE VOICE</p>
      <p style="margin:6px 0 0;font-size:12px;color:#A1A1AA;">© Sayvors — Automated message, please do not reply.</p>
    </td>
  </tr>

</table>
</td></tr>
</table>"""


async def send_otp_email(email: str, purpose: str = "verification") -> None:
    """Create and send a one-time passcode for email verification.

    The generated code is stored in Redis for 10 minutes, then the HTML/plain-text
    version is sent through Resend. If the same email requests a new code, the
    newest value replaces the older one.
    """

    code = f"{secrets.randbelow(900000) + 100000}"
    redis = await get_redis()
    await redis.setex(_otp_key(email), OTP_TTL_SECONDS, code)
    html = (
        OTP_HTML.replace("{logo_url}", _logo_url())
        .replace("{purpose}", purpose)
        .replace("{code}", code)
    )
    await send_email(
        email,
        f"Your Sayvors {purpose} code: {code}",
        html,
        text=f"Your Sayvors {purpose} code is: {code} (expires in 10 minutes)",
    )


async def verify_otp(email: str, code: str) -> bool:
    """Validate a stored OTP and consume it on success.

    Returns True only when the provided code matches the Redis value for the email.
    A successful match deletes the underlying key so the OTP cannot be reused.
    """

    redis = await get_redis()
    stored = await redis.get(_otp_key(email))
    if stored and stored.strip() == code.strip():
        await redis.delete(_otp_key(email))
        return True
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
    )


async def send_password_reset_email(email: str, name: str, reset_url: str) -> str:
    """Send a password reset email containing a secure recovery URL."""
    display = name or "there"
    body = (
        f"<p style=\"margin:0 0 16px;font-size:15px;line-height:24px;color:#52525B;\">Hi {display},</p>"
        f"<p style=\"margin:0 0 16px;font-size:15px;line-height:24px;color:#52525B;\">We received a request to reset your Sayvors password. Click below to choose a new one (link expires in <strong style=\"color:#52525B;\">1 hour</strong>):</p>"
        f"{_cta_button('Reset my password', reset_url)}"
        f"<p style=\"margin:16px 0 0;font-size:14px;line-height:22px;color:#71717A;word-break:break-all;\">If the button doesn't work, paste this link: {reset_url}</p>"
        f"<p style=\"margin:16px 0 0;font-size:14px;line-height:22px;color:#71717A;\">If you didn't request this, you can safely ignore this email.</p>"
    )
    return await send_email(
        email,
        "Reset your Sayvors password",
        _shell("Reset your password", body, _logo_url()),
        text=f"Hi {display}, reset your Sayvors password (expires in 1 hour): {reset_url}",
    )


async def send_password_reset_success_email(
    email: str,
    name: str,
    when: "datetime",
    ip: str,
    location: str,
    device: str,
) -> str:
    """Security notice: password was just reset â€” time, IP, location, device."""
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
        f"<p style=\"margin:16px 0 0;font-size:14px;line-height:22px;color:#52525B;\">If this was you, you're all set â€” no further action needed.</p>"
        f"<p style=\"margin:12px 0 0;font-size:14px;line-height:22px;color:#52525B;\">If this <strong>wasn't you</strong>, someone else may have access to your account â€” reset your password immediately:</p>"
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
    )


async def send_welcome_email(email: str, name: str) -> str:
    """Send a branded onboarding email after account creation."""
    display = name or "there"
    channels_url = f"{(settings.FRONTEND_URL or '').rstrip('/')}/dashboard/channels"
    body = (
        f"<p style=\"margin:0 0 16px;font-size:15px;line-height:24px;color:#52525B;\">Hi {display},</p>"
        f"<p style=\"margin:0 0 16px;font-size:15px;line-height:24px;color:#52525B;\">Congrats — your Sayvors account is ready!</p>"
        f"<p style=\"margin:0 0 16px;font-size:15px;line-height:24px;color:#52525B;\">Connect your Google Business Profile and let our AI handle your reviews.</p>"
        f"{_cta_button('Connect your first channel', channels_url)}"
    )
    return await send_email(
        email,
        f"Welcome to Sayvors, {display}! 🎉",
        _shell("Welcome to Sayvors", body, _logo_url()),
        text=f"Hi {display}, your Sayvors account is ready! Connect a channel: {channels_url}",
    )


async def send_notification_email(email: str, subject: str, message: str, cta_url: str | None = None) -> str:
    """Send a generic internal notification email to a user.

    This is intended for system notifications, alerts, and other non-public
    transactional communications. When provided, a CTA link is included in the HTML.
    """

    cta = f"<p><a href='{cta_url}'>View in Sayvors</a></p>" if cta_url else ""
    return await send_email(
        email,
        f"[Sayvors] {subject}",
        f"<p>{message}</p>{cta}",
        text=f"[Sayvors] {subject}\n{message}" + (f"\n{cta_url}" if cta_url else ""),
    )

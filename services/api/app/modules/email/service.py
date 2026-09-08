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

RESEND_URL = "https://api.resend.com/emails"
OTP_TTL_SECONDS = 10 * 60


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
            RESEND_URL,
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
    <div style="font-size:20px;font-weight:700;color:#1F2937;">Sayvors</div>
    <div style="margin-top:4px;font-size:11px;font-weight:600;letter-spacing:3px;color:#A1A1AA;">EVERY LINE, ONE VOICE</div>
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
    html = OTP_HTML.replace("{purpose}", purpose).replace("{code}", code)
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

    return await send_email(
        email,
        "Activate your Sayvors account",
        f"<p>Hi {name},</p>"
        f"<p>Welcome to Sayvors! Please activate your account:</p>"
        f"<p><a href='{activation_url}'>Activate my account</a></p>"
        f"<p>If the button doesn't work, paste this link: {activation_url}</p>",
        text=f"Hi {name}, activate your Sayvors account: {activation_url}",
    )


async def send_password_reset_email(email: str, name: str, reset_url: str) -> str:
    """Send a password reset email containing a secure recovery URL."""

    return await send_email(
        email,
        "Reset your Sayvors password",
        f"<p>Hi {name},</p>"
        f"<p>Click below to reset your password (link expires soon):</p>"
        f"<p><a href='{reset_url}'>Reset my password</a></p>"
        f"<p>If you didn't request this, ignore this email.</p>",
        text=f"Hi {name}, reset your Sayvors password: {reset_url}",
    )


async def send_welcome_email(email: str, name: str) -> str:
    """Send a branded onboarding email after account creation."""

    return await send_email(
        email,
        f"Welcome to Sayvors, {name}! 🎉",
        f"<p>Hi {name},</p>"
        f"<p>Congrats — your Sayvors account is ready!</p>"
        f"<p>Connect your Google Business Profile and let our AI handle your reviews.</p>"
        f"<p><a href='{settings.FRONTEND_URL}/dashboard/channels'>Connect your first channel</a></p>",
        text=f"Hi {name}, your Sayvors account is ready! Connect a channel: {settings.FRONTEND_URL}/dashboard/channels",
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

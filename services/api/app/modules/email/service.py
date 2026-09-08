"""Resend-based email service (server-side only).

Uses httpx directly against https://api.resend.com/emails so no extra
dependency is needed. The API key lives in RESEND_API_KEY and must
never be exposed to the frontend.

Covers: OTP codes, account activation, password reset, welcome /
greeting mails, and generic notifications.
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
    return bool(settings.RESEND_API_KEY.strip())


async def send_email(to: str | list[str], subject: str, html: str, text: str | None = None) -> str:
    """Send one email via Resend. Returns the Resend message id. Raises on failure."""
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
          <a href="https://www.linkedin.com/company/Sayvors"><img src="https://Sayvors.com/email-icons/linkedin.png" width="40" height="40" alt="LinkedIn" style="display:block;border:0;border-radius:8px;"></a>
        </td>
        <td style="padding:0 8px;">
          <a href="https://twitter.com/Sayvors"><img src="https://Sayvors.com/email-icons/twitter.png" width="40" height="40" alt="Twitter / X" style="display:block;border:0;border-radius:8px;"></a>
        </td>
        <td style="padding:0 8px;">
          <a href="https://www.facebook.com/Sayvors"><img src="https://Sayvors.com/email-icons/facebook.png" width="40" height="40" alt="Facebook" style="display:block;border:0;border-radius:8px;"></a>
        </td>
        <td style="padding:0 8px;">
          <a href="https://www.instagram.com/Sayvors"><img src="https://Sayvors.com/email-icons/instagram.png" width="40" height="40" alt="Instagram" style="display:block;border:0;border-radius:8px;"></a>
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
    """Generate a 6-digit code, store it in Redis for 10 min, and email it."""
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
    """True + consume the code on match, False otherwise."""
    redis = await get_redis()
    stored = await redis.get(_otp_key(email))
    if stored and stored.strip() == code.strip():
        await redis.delete(_otp_key(email))
        return True
    return False


# ── Templated mails ────────────────────────────────────

async def send_activation_email(email: str, name: str, activation_url: str) -> str:
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
    cta = f"<p><a href='{cta_url}'>View in Sayvors</a></p>" if cta_url else ""
    return await send_email(
        email,
        f"[Sayvors] {subject}",
        f"<p>{message}</p>{cta}",
        text=f"[Sayvors] {subject}\n{message}" + (f"\n{cta_url}" if cta_url else ""),
    )

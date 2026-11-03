"""Thirty-day personal-data deletion flow.

The owner asks to delete their personal data. The workspace's business records
(chats, posts, insights, customer records) are retained. The request is a
30-day grace period: signing in cancels it, a day-25 email reminds the owner,
and day 30 anonymizes the owner profile and redacts the owner's name/email/
phone from retained records.

This is deliberately **not** the old immediate hard-delete: that removed the
whole tenant. Here only the owner's personal data is erased; the business data
stays.
"""
from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AccountDeletionRequest, User

logger = logging.getLogger(__name__)

DELETION_GRACE_DAYS = 30
DELETION_REMINDER_DAYS = 5
# Workspace business records are retained for this long after closure. The
# value is policy, not a scheduler: a later admin purge can use it.
CLOSED_WORKSPACE_RETENTION_DAYS = 730

_REDACTION = "[deleted]"
_DELETED_EMAIL_DOMAIN = "invalid.sayvors.local"


async def get_pending(
    db: AsyncSession, tenant_id: str
) -> AccountDeletionRequest | None:
    return (
        await db.execute(
            select(AccountDeletionRequest)
            .where(
                AccountDeletionRequest.tenant_id == tenant_id,
                AccountDeletionRequest.status == "pending",
            )
            .order_by(AccountDeletionRequest.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def deletion_state(db: AsyncSession, tenant_id: str) -> dict:
    row = (
        await db.execute(
            select(AccountDeletionRequest)
            .where(AccountDeletionRequest.tenant_id == tenant_id)
            .order_by(AccountDeletionRequest.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return {"status": "none"}
    return {
        "status": row.status,
        "requested_at": _iso(row.requested_at),
        "scheduled_for": _iso(row.scheduled_for),
        "cancelled_at": _iso(row.cancelled_at),
        "completed_at": _iso(row.completed_at),
    }


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    # SQLite returns naive datetimes; Postgres is aware. Normalize so the
    # browser never interprets a UTC schedule as local time.
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


async def request_deletion(
    db: AsyncSession, user: User, *, reason: str | None = None
) -> AccountDeletionRequest:
    existing = await get_pending(db, user.id)
    if existing is not None:
        return existing

    now = datetime.now(timezone.utc)
    row = AccountDeletionRequest(
        tenant_id=user.id,
        requested_by=user.id,
        status="pending",
        requested_at=now,
        scheduled_for=now + timedelta(days=DELETION_GRACE_DAYS),
        reason=(reason or "")[:200] or None,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    await _send_deletion_email(
        user.email,
        "Your Sayvors personal data is scheduled for deletion",
        (
            "We received your request. Your personal data — name, email, phone "
            f"and login — will be deleted on {row.scheduled_for:%d %b %Y}.\n\n"
            "Sign in before that date to cancel. Business records are retained "
            "as business data as described in our Privacy Policy."
        ),
    )
    return row


async def cancel_pending(
    db: AsyncSession, tenant_id: str, *, commit: bool = True
) -> int:
    """Cancel every pending request. Called by sign-in and by the owner."""
    rows = (
        await db.execute(
            select(AccountDeletionRequest).where(
                AccountDeletionRequest.tenant_id == tenant_id,
                AccountDeletionRequest.status == "pending",
            )
        )
    ).scalars().all()
    now = datetime.now(timezone.utc)
    for row in rows:
        row.status = "cancelled"
        row.cancelled_at = now
        db.add(row)
    if commit and rows:
        await db.commit()
    return len(rows)


async def send_due_reminders(db: AsyncSession) -> int:
    """Email owners whose deletion is five days away (best-effort)."""
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=DELETION_REMINDER_DAYS)
    rows = (
        await db.execute(
            select(AccountDeletionRequest).where(
                AccountDeletionRequest.status == "pending",
                AccountDeletionRequest.reminder_sent_at.is_(None),
                AccountDeletionRequest.scheduled_for <= horizon,
                AccountDeletionRequest.scheduled_for > now,
            ).limit(100)
        )
    ).scalars().all()
    sent = 0
    for row in rows:
        user = await db.get(User, row.tenant_id)
        if user is None or "@" + _DELETED_EMAIL_DOMAIN in (user.email or ""):
            row.reminder_sent_at = now
            db.add(row)
            continue
        await _send_deletion_email(
            user.email,
            "Your personal data will be deleted in 5 days",
            (
                f"Your personal data will be deleted in {DELETION_REMINDER_DAYS} "
                f"days, on {row.scheduled_for:%d %b %Y}.\n\n"
                "Sign in before then to cancel. Business records are retained "
                "as business data as described in our Privacy Policy."
            ),
        )
        row.reminder_sent_at = now
        db.add(row)
        sent += 1
    if rows:
        await db.commit()
    return sent


async def process_due_deletions(db: AsyncSession, limit: int = 50) -> int:
    """Anonymize every pending request whose date has arrived."""
    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(AccountDeletionRequest).where(
                AccountDeletionRequest.status == "pending",
                AccountDeletionRequest.scheduled_for <= now,
            ).order_by(AccountDeletionRequest.scheduled_for).limit(limit)
        )
    ).scalars().all()
    completed = 0
    for row in rows:
        user = await db.get(User, row.tenant_id)
        if user is None:
            row.status = "completed"
            row.completed_at = now
            db.add(row)
            await db.commit()
            completed += 1
            continue
        try:
            await _anonymize_owner(db, user)
            row.status = "completed"
            row.completed_at = now
            db.add(row)
            await db.commit()
            completed += 1
            logger.info("Account personal data deleted tenant=%s", row.tenant_id[:8])
        except Exception as exc:  # noqa: BLE001 - keep other deletions running
            await db.rollback()
            logger.exception(
                "Account deletion failed tenant=%s: %s", row.tenant_id[:8], exc
            )
    return completed


async def _anonymize_owner(db: AsyncSession, user: User) -> None:
    from ..auth.models import EmailVerification, PasswordReset, RefreshToken
    from ..billing.models import TenantSubscription
    from ..notifications.models import Notification
    from ..team.models import TeamMember
    from ...core.storage import delete_media

    terms = _owner_terms(user)
    redacted = await _redact_owner_terms(db, user.id, terms)

    for key in (user.avatar_storage_key, user.cover_storage_key):
        if key:
            try:
                delete_media(user.id, key)
            except Exception as exc:  # noqa: BLE001 - DB deletion still wins
                logger.warning("Avatar/cover delete failed tenant=%s: %s", user.id[:8], exc)

    try:
        from ..auth.rate_limit import delete_all_sessions

        await delete_all_sessions(user.id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Session revoke failed tenant=%s: %s", user.id[:8], exc)

    await db.execute(delete(RefreshToken).where(RefreshToken.user_id == user.id))
    await db.execute(
        delete(EmailVerification).where(EmailVerification.user_id == user.id)
    )
    await db.execute(delete(PasswordReset).where(PasswordReset.user_id == user.id))
    await db.execute(delete(Notification).where(Notification.user_id == user.id))
    await db.execute(
        update(TeamMember)
        .where(TeamMember.tenant_id == user.id)
        .values(status="suspended")
    )
    await db.execute(
        update(TenantSubscription)
        .where(TenantSubscription.tenant_id == user.id)
        .values(status="canceled")
    )

    # Keep business_name / business_sells / business_description: those are
    # business data. Everything that identifies the owner personally goes.
    user.first_name = "Deleted"
    user.last_name = ""
    user.email = f"deleted+{user.id}@{_DELETED_EMAIL_DOMAIN}"
    user.password_hash = _unusable_password_hash()
    user.phone = None
    user.bio = None
    user.avatar_url = None
    user.avatar_source = "none"
    user.google_avatar_url = None
    user.facebook_avatar_url = None
    user.avatar_upload_url = None
    user.avatar_storage_key = None
    user.cover_url = None
    user.cover_storage_key = None
    user.google_sub = None
    user.facebook_id = None
    user.country = None
    user.email_verified = False
    user.onboarded = False
    user.newsletter = False
    user.token_version = (user.token_version or 0) + 1
    user.updated_at = datetime.now(timezone.utc)
    db.add(user)
    logger.info(
        "Owner profile anonymized tenant=%s redacted_records=%d",
        user.id[:8], redacted,
    )


def _owner_terms(user: User) -> list[str]:
    first = (user.first_name or "").strip()
    last = (user.last_name or "").strip()
    full = " ".join(part for part in (first, last) if part)
    phone = (user.phone or "").strip()
    phone_digits = re.sub(r"\D", "", phone)
    terms = {full, user.email or "", phone, phone_digits}
    terms.discard("")
    # Only redact very short names in owner-authored outbound rows; a bare
    # "Ali" in a customer message is usually the customer, not the owner.
    outbound_terms = {first, last} if len(full) >= 3 else set()
    return sorted(
        {t for t in terms if len(t) >= 3}
        | {t for t in outbound_terms if len(t) >= 3},
        key=len,
        reverse=True,
    )


def _replace_terms(text: str, terms: list[str]) -> str:
    out = text or ""
    for term in terms:
        out = re.sub(re.escape(term), _REDACTION, out, flags=re.IGNORECASE)
    return out


async def _redact_owner_terms(
    db: AsyncSession, tenant_id: str, terms: list[str]
) -> int:
    if not terms:
        return 0
    from ..channels.models import Channel, ChannelMessage, ReviewReply
    from ..channels.service import (
        decrypt_message_content,
        encrypt_message_content,
    )
    from ..posts.models import LocationPost

    channel_ids = (
        await db.execute(select(Channel.id).where(Channel.user_id == tenant_id))
    ).scalars().all()
    changed = 0

    if channel_ids:
        result = await db.stream(
            select(ChannelMessage)
            .where(ChannelMessage.channel_id.in_(channel_ids))
            .execution_options(yield_per=200)
        )
        async for msg in result.scalars():
            plain = decrypt_message_content(msg.content) or ""
            # Inbound messages are customer-authored; only replace the full
            # name/email/phone there, never a bare first name.
            row_terms = terms if msg.direction == "outbound" else [
                t for t in terms if " " in t or "@" in t or t.isdigit()
            ]
            redacted = _replace_terms(plain, row_terms)
            if redacted != plain:
                msg.content = encrypt_message_content(redacted)
                db.add(msg)
                changed += 1

        result = await db.stream(
            select(ReviewReply)
            .where(ReviewReply.channel_id.in_(channel_ids))
            .execution_options(yield_per=200)
        )
        async for reply in result.scalars():
            redacted = _replace_terms(reply.reply_text or "", terms)
            if redacted != (reply.reply_text or ""):
                reply.reply_text = redacted
                db.add(reply)
                changed += 1

    result = await db.stream(
        select(LocationPost)
        .where(LocationPost.user_id == tenant_id)
        .execution_options(yield_per=200)
    )
    async for post in result.scalars():
        for attr in ("title", "description"):
            value = getattr(post, attr) or ""
            redacted = _replace_terms(value, terms)
            if redacted != value:
                setattr(post, attr, redacted)
                db.add(post)
                changed += 1
    return changed


def _unusable_password_hash() -> str:
    try:
        from ..auth.service import hash_password

        return hash_password(secrets.token_urlsafe(48))
    except Exception:  # noqa: BLE001 - never leave a working login
        return "!"


async def _send_deletion_email(email: str, subject: str, body: str) -> None:
    if not email or "@" + _DELETED_EMAIL_DOMAIN in email:
        return
    try:
        from ..email.service import send_email

        html = (
            "<div style='font-family:Segoe UI,Arial,sans-serif;line-height:1.6'>"
            f"<p>{body.replace(chr(10), '</p><p>')}</p>"
            "<p style='color:#777;font-size:12px'>Sayvors</p></div>"
        )
        await send_email(to=email, subject=subject, html=html, text=body)
    except Exception as exc:  # noqa: BLE001 - the request still exists
        logger.warning("Deletion email failed to=%s: %s", email[:3] + "…", exc)

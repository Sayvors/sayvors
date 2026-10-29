"""Lead follow-up dispatcher: claims due actions, sends template nudges.

Replaces the old followup_worker. The database is the scheduler; this
process holds no state and, critically, makes ZERO LLM calls — nudge
text is a deterministic template over stored fields (lead_engine), and
every eligibility decision is plain logic. Multiple instances are safe:
claims use SELECT ... FOR UPDATE SKIP LOCKED (a no-op on SQLite, where
the unique constraints still hold) plus a short lease that a crashed
worker's peers reclaim after expiry.

Failure taxonomy:
- transient (5xx / 429) -> bounded backoff retries, same attempt
- permanent (4xx, config) -> failed, actionable error stored
- ambiguous (network timeout) -> NEVER resent (could double-text);
  parked for a human with the provider call recorded
"""
import asyncio
import logging
import os
import random
import socket
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select, update

from ....database import async_session
from ..models import Channel, ChannelMessage, Lead, LeadAction
from .providers.base import MetaAPIError

logger = logging.getLogger(__name__)

POLL_SECONDS = 15
LEASE_SECONDS = 120  # a claim older than this is stealable (crash recovery)
BATCH = 20
MAX_TRANSIENT_RETRIES = 5
_TRANSIENT_BASE = timedelta(minutes=5)


class _PermanentSendError(Exception):
    """Config/credential problem — retrying cannot help."""


class _AmbiguousSend(Exception):
    """Timeout-class failure: delivery unknown, a retry may double-send."""


async def _claim_due_actions(db, worker_id: str, limit: int = BATCH) -> list:
    """Atomically hand this worker up to `limit` due actions.

    Expired leases are released first, so a worker that died mid-send
    only delays its rows by LEASE_SECONDS. SKIP LOCKED means two workers
    scanning simultaneously never claim the same row (on Postgres); the
    (lead, guard, attempt) unique constraint backstops even engines
    without row locks.
    """
    now = datetime.now(timezone.utc)
    await db.execute(
        update(LeadAction)
        .where(LeadAction.status == "claimed", LeadAction.claimed_until < now)
        .values(
            status="pending", claimed_at=None, claimed_until=None, claimed_by=None
        )
    )
    rows = (await db.execute(
        select(LeadAction)
        .where(LeadAction.status == "pending", LeadAction.due_at <= now)
        .order_by(LeadAction.due_at.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )).scalars().all()
    for action in rows:
        action.status = "claimed"
        action.claimed_at = now
        action.claimed_until = now + timedelta(seconds=LEASE_SECONDS)
        action.claimed_by = worker_id[:64]
    return list(rows)


async def _send_nudge(db, action: LeadAction, text: str) -> str:
    """Deliver one nudge over the action's own channel. Returns the
    provider message id. Raises _PermanentSendError for config problems,
    propagates MetaAPIError / httpx errors for the caller's taxonomy."""
    from .consumer import _resolve_asset
    from .credentials import decrypt_connection_token
    from .service import get_adapter, get_instagram_page_credentials

    channel = (
        await db.execute(select(Channel).where(Channel.id == action.channel_id))
    ).scalar_one_or_none()
    if channel is None:
        raise _PermanentSendError(f"channel {action.channel_id} missing")

    if action.platform == "whatsapp":
        adapter = get_adapter("whatsapp")
        asset = await _resolve_asset(db, channel.platform_user_id)
        if asset is None:
            raise _PermanentSendError(f"asset {channel.platform_user_id} missing")
        if not asset.active:
            raise _PermanentSendError("asset deselected")
        token = (
            decrypt_connection_token(asset.connection) if asset.connection else None
        )
        if not token:
            raise _PermanentSendError("no access token on connection")
        return await adapter.send_text_message(
            channel.platform_user_id, token, action.contact_id, text
        )

    if action.platform == "instagram":
        from .providers.instagram import InstagramAdapter

        asset = await _resolve_asset(
            db, channel.platform_user_id, provider="instagram"
        )
        if asset is None:
            raise _PermanentSendError(f"asset {channel.platform_user_id} missing")
        if not asset.active:
            raise _PermanentSendError("asset deselected")
        page_id, page_token = await get_instagram_page_credentials(db, asset)
        if not page_id or not page_token:
            raise _PermanentSendError("no parent Page token for instagram asset")
        return await InstagramAdapter().send_text_message(
            page_id, page_token, action.contact_id, text
        )

    raise _PermanentSendError(
        f"platform {action.platform} has no messaging sender wired"
    )


def _requeue_transient(action: LeadAction, error: str) -> None:
    """Backoff + jitter, same attempt (nothing was sent). Bounded: after
    MAX_TRANSIENT_RETRIES the action fails as 'transient' — the next
    inbound customer message re-arms a fresh schedule anyway."""
    action.send_retries = (action.send_retries or 0) + 1
    if action.send_retries > MAX_TRANSIENT_RETRIES:
        action.status = "failed"
        action.error_category = "transient"
        action.last_error = f"retry cap: {error}"[:500]
        return
    delay = _TRANSIENT_BASE + timedelta(seconds=random.uniform(0, 60))
    action.status = "pending"
    action.due_at = datetime.now(timezone.utc) + delay
    action.error_category = "transient"
    action.last_error = error[:500]
    action.claimed_at = action.claimed_until = action.claimed_by = None


def _clear_claim(action: LeadAction) -> None:
    action.claimed_at = action.claimed_until = action.claimed_by = None


async def _send_window_template(db, action: LeadAction) -> bool:
    """Send an approved zero-variable utility template for a closed window.

    Zero variables on purpose: a follow-up nudge has no per-customer values to
    fill, and inventing arguments for a template Meta approved with different
    placeholders is how templates get rejected and numbers get flagged.

    Returns True only when the template actually went out, so the caller keeps
    the honest ``window_closed`` state otherwise.
    """
    from ...whatsapp_templates import service as templates

    try:
        eligible = await templates.eligible_templates(db, action.tenant_id)
    except Exception as e:  # noqa: BLE001 - never break the batch
        logger.warning("template lookup failed for action %s: %s", action.id, e)
        return False

    template = next((t for t in eligible if int(t.variables or 0) == 0), None)
    if template is None:
        return False

    try:
        row, _created = await templates.send_template(
            db,
            tenant_id=action.tenant_id,
            channel_id=action.channel_id,
            contact_phone=action.contact_id,
            template_id=template.id,
            variables=[],
            sent_by=None,
            idempotency_key=f"followup:{action.id}",
        )
    except ValueError as e:
        # No consent / opted out / number gone: the follow-up is not allowed,
        # and the caller records window_closed.
        logger.info("follow-up template blocked for action %s: %s", action.id, e)
        return False

    if row.status != "sent":
        action.last_error = (row.error or "")[:500]
        return False

    action.status = "sent"
    action.sent_at = datetime.now(timezone.utc)
    action.provider_message_id = (row.provider_message_id or "")[:200] or None
    action.error_category = None
    return True


async def _process_action(db, action: LeadAction) -> None:
    """All decisions here are deterministic — this function contains no
    model/LLM imports and must never gain any."""
    from .lead_engine import (
        _followup_gaps,
        _shift_out_of_quiet_hours,
        latest_inbound,
        normalize_lead_settings,
        nudge_text,
        window_open,
    )
    from ...users.models import User

    lead = (
        await db.execute(select(Lead).where(Lead.id == action.lead_id))
    ).scalar_one_or_none()
    if lead is None:
        action.status = "cancelled"
        action.ineligible_reason = "lead_missing"
        return
    if lead.opt_out:
        action.status = "ineligible"
        action.ineligible_reason = "opt_out"
        return
    if lead.stage in ("converted", "lost"):
        action.status = "ineligible"
        action.ineligible_reason = "stage_closed"
        return

    settings_row = (
        await db.execute(
            select(User.lead_settings).where(User.id == action.tenant_id)
        )
    ).first()
    settings = normalize_lead_settings(
        settings_row.lead_settings if settings_row else None
    )
    gaps = _followup_gaps(settings)
    if not settings["enabled"] or action.attempt > len(gaps):
        action.status = "ineligible"
        action.ineligible_reason = "attempt_cap"
        return

    # Quiet hours: slide the due time, keep the claim cost at zero — the
    # attempt is neither burned nor sent at 3am. (SQLite returns naive
    # datetimes; normalize before comparing.)
    due_at = action.due_at
    if due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=timezone.utc)
    due = _shift_out_of_quiet_hours(due_at, settings)
    if due > due_at:
        action.status = "pending"
        action.due_at = due
        _clear_claim(action)
        return

    # Staleness guard: the thread's newest inbound must still be the
    # message this nudge was armed against. A newer one means the customer
    # replied — the consumer normally cancels us; this is the backstop
    # for the cancel-vs-claim race.
    guard = await latest_inbound(db, action.channel_id, action.contact_id)
    if (action.guard_message_id or None) != ((guard[0] if guard else None) or None):
        action.status = "cancelled"
        action.ineligible_reason = "answered"
        return

    # Meta free-form messaging window (24h from the customer's last
    # message) — centralized at the outbound send layer, never bypassed.
    if not window_open(guard[1] if guard else None):
        # Outside the window only an approved template may be sent. If the
        # tenant has one and the customer's consent is on record, the follow-up
        # still reaches them instead of being dropped as ineligible.
        if await _send_window_template(db, action):
            return
        action.status = "ineligible"
        action.ineligible_reason = "window_closed"
        return

    text = nudge_text(action.question, action.language or lead.language)
    try:
        provider_msg_id = await _send_nudge(db, action, text)
    except _AmbiguousSend as e:
        # Delivery unknown. Resending could double-text the customer; the
        # honest terminal state is "ambiguous" + a log line a human can find.
        action.status = "ambiguous"
        action.error_category = "ambiguous"
        action.last_error = str(e)[:500]
        return
    except MetaAPIError as e:
        if "131047" in str(e):
            # WhatsApp's re-engagement error: the window closed between
            # our check and the send.
            action.status = "ineligible"
            action.ineligible_reason = "window_closed"
            action.last_error = str(e)[:500]
        elif e.status_code == 429 or e.status_code >= 500:
            _requeue_transient(action, f"{e.status_code}: {e}")
        else:
            action.status = "failed"
            action.error_category = "permanent"
            action.last_error = f"{e.status_code}: {e}"[:500]
        return
    except httpx.HTTPError as e:
        # Timeouts and connection resets: the request may have landed.
        action.status = "ambiguous"
        action.error_category = "ambiguous"
        action.last_error = f"{type(e).__name__}: {e}"[:500]
        return
    except Exception as e:  # noqa: BLE001 — a bug must not crashloop the batch
        logger.exception(
            "Lead action %s hit an unexpected send error", action.id
        )
        action.status = "failed"
        action.error_category = "permanent"
        action.last_error = f"{type(e).__name__}: {e}"[:500]
        return

    now = datetime.now(timezone.utc)
    action.status = "sent"
    action.sent_at = now
    action.provider_message_id = (provider_msg_id or None)[:200] or None
    action.error_category = None
    db.add(ChannelMessage(
        id=str(uuid.uuid4()),
        channel_id=action.channel_id,
        platform_message_id=(provider_msg_id or None)[:200] or None,
        direction="outbound",
        content=text,
        content_type="text",
        status="sent",
        contact_phone=action.contact_id,
        handled_by="ai",
    ))
    # Arm the NEXT attempt with its own gap — same durability rules as
    # attempt 1, same unique constraint, same lease machinery.
    if action.attempt < len(gaps):
        nxt = LeadAction(
            id=str(uuid.uuid4()),
            tenant_id=action.tenant_id,
            lead_id=action.lead_id,
            channel_id=action.channel_id,
            contact_id=action.contact_id,
            platform=action.platform,
            attempt=action.attempt + 1,
            question=action.question,
            language=action.language,
            guard_message_id=action.guard_message_id,
            due_at=_shift_out_of_quiet_hours(
                now + gaps[action.attempt], settings
            ),
        )
        db.add(nxt)
        lead.next_action_at = nxt.due_at
    else:
        lead.next_action_at = None
    db.add(lead)
    # Best-effort realtime ping so an open inbox shows the nudge live.
    try:
        from ...channels.realtime import publish_inbox_event

        await publish_inbox_event(action.tenant_id, {
            "type": "message",
            "channel_id": action.channel_id,
            "platform": action.platform,
            "direction": "outbound",
            "content": text,
            "content_type": "text",
            "status": "sent",
            "contact_phone": action.contact_id,
            "created_at": now,
        })
    except Exception:
        pass
    logger.info(
        "Lead follow-up sent lead=%s attempt=%d platform=%s contact=…%s",
        action.lead_id[:8], action.attempt, action.platform,
        action.contact_id[-6:],
    )


async def process_due_actions() -> int:
    """Claim + process one batch. Returns how many actions were handled."""
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        actions = await _claim_due_actions(db, worker_id)
        for action in actions:
            try:
                await _process_action(db, action)
            except Exception:  # noqa: BLE001 — one bad row never kills the batch
                logger.exception(
                    "Lead action %s crashed — releasing claim", action.id
                )
                action.status = "pending"
                _clear_claim(action)
            await db.commit()
        return len(actions)


async def run_lead_action_worker() -> None:
    logger.info("Lead action worker started (poll=%ds)", POLL_SECONDS)
    while True:
        try:
            handled = await process_due_actions()
            if handled:
                logger.info("Lead actions processed: %d", handled)
        except Exception:  # noqa: BLE001 — the loop outlives any single cycle
            logger.exception("Lead action worker cycle failed")
        await asyncio.sleep(POLL_SECONDS)

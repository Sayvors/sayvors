"""Per-tenant ticket identity for review issues.

A ticket number is what a human reads back to a customer ("that's TK-000042")
and what a customer can quote later. Two properties matter:

* **Sequential per tenant, never global.** A shared counter would let one
  tenant infer another's volume. Each tenant's numbering starts at 1.
* **Race-safe.** Two workers polling the same tenant can classify two reviews in
  the same instant; both would read MAX()=41 and both would write TK-000042.
  A per-tenant advisory lock serialises the read-then-insert on Postgres. The
  unique index on (tenant_id, ticket_number) sits behind it as the backstop.

Only issues that need attention are given a number. Praise and neutral chatter
stays NULL so the number keeps meaning "a human owes this customer something"
rather than counting every review the poller has ever seen. NULLs do not
collide: both Postgres and SQLite treat NULLs as distinct inside a unique
index, so any number of unnumbered issues coexist.

`review_id` remains the universal key for every review. `ticket_number` is the
human-facing handle on the subset that someone has to work.
"""

import logging
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..scheduling import release_lock, take_lock
from .classification import ReviewClassification

logger = logging.getLogger(__name__)

TICKET_PREFIX = "TK-"
TICKET_DIGITS = 6
_LOCK_NAMESPACE = "review_ticket"

# "tk-42", "TK-000042" and "TK-000000042" all normalise to TK-000042.
_TICKET_RE = re.compile(r"\bTK-(\d{1,9})\b", re.IGNORECASE)

# Handoff codes are what a customer actually types on WhatsApp, read off a
# screenshot by hand -- so no 0/O or 1/I, and no separators to mistype.
# Minting is Phase C; the shape is fixed here because the ladder already
# consumes it.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 6
_CODE_RE = re.compile(rf"^[A-HJ-NP-Z2-9]{{{CODE_LENGTH}}}$")


def _normalize_code(raw: str | None) -> Optional[str]:
    """Canonicalise a quoted handoff code: case and surrounding junk removed.

    A short customer-facing code is not a credential -- it only resolves within
    one tenant and only to the issue it was minted for. It is still rejected
    rather than guessed at when it is the wrong length or uses an excluded
    letter, because a near-miss must not silently match a different code.
    """
    if not raw:
        return None
    token = str(raw).strip().upper().replace(" ", "").replace("-", "")
    return token if _CODE_RE.match(token) else None


def format_ticket(number: int) -> str:
    """1 -> 'TK-000001'.

    Past 999999 the padding grows instead of truncating, so a very long-lived
    tenant keeps unique numbers rather than colliding with itself.
    """
    if number < 1:
        raise ValueError("ticket numbers start at 1")
    return f"{TICKET_PREFIX}{number:0{TICKET_DIGITS}d}"


def normalize_ticket(raw: str | None) -> Optional[str]:
    """Canonicalise one candidate token, or None when it is not a ticket."""
    if not raw:
        return None
    m = _TICKET_RE.search(str(raw))
    if not m:
        return None
    try:
        number = int(m.group(1))
    except ValueError:
        return None
    return format_ticket(number) if number >= 1 else None


def extract_ticket_refs(text: str | None) -> list[str]:
    """Every ticket a customer might have typed, in order, de-duplicated.

    Deliberately tolerant: customers paste 'my ticket is TK-000042 please' or
    lowercase it. Anything that does not parse is dropped rather than guessed
    at — a wrong number would attach a customer to a stranger's ticket.
    """
    if not text:
        return []
    out: list[str] = []
    for m in _TICKET_RE.finditer(str(text)):
        try:
            number = int(m.group(1))
        except ValueError:
            continue
        if number < 1:
            continue
        canon = format_ticket(number)
        if canon not in out:
            out.append(canon)
    return out


@asynccontextmanager
async def ticket_lock(db: AsyncSession, tenant_id: str):
    """Hold this tenant's ticket-number lock for the whole surrounding block.

    Read-then-insert is only safe if nothing else interleaves, and on Postgres
    an uncommitted row is invisible to the next lock holder — so the INSERT and
    its COMMIT must happen inside this block, not after it. Off Postgres the
    lock is a no-op, which is correct for the single-writer SQLite test suite.
    """
    held = await take_lock(db, True, _LOCK_NAMESPACE, tenant_id)
    try:
        yield held
    finally:
        if held:
            await release_lock(db, _LOCK_NAMESPACE, tenant_id)


async def _next_sequence(db: AsyncSession, tenant_id: str) -> int:
    """The next number for this tenant, from what is already committed.

    Parsed in Python, NOT with SQL CAST, on purpose. Postgres raises
    `invalid input syntax for type integer` on CAST('abc' AS INTEGER) while
    SQLite silently yields 0 -- so any hand-edited or malformed ticket_number
    ('TK-abc', or 'TK-' with no digits) would abort this function on Postgres
    only. That error propagates out of persist_issue into the reviews worker's
    broad except, which means one bad row silently stops EVERY future review
    for that tenant from getting a ticket, with nothing but a log line. SQLite
    hides it, so the test suite could never catch it.

    Cost is one narrow indexed column per tenant, after an LLM call that took
    seconds. Correctness and crash-safety win over shaving a millisecond.
    """
    from ..channels.models import ReviewIssue

    numbers = (
        await db.execute(
            select(ReviewIssue.ticket_number).where(
                ReviewIssue.tenant_id == tenant_id,
                ReviewIssue.ticket_number.isnot(None),
            )
        )
    ).scalars().all()

    highest = 0
    for raw in numbers:
        if not raw:
            continue
        m = _TICKET_RE.match(str(raw).strip())
        if not m:
            # Unparseable row: skip it. It cannot be handed to a customer, and
            # it must not wedge numbering for everyone else.
            logger.warning(
                "skipping malformed ticket_number %r for tenant %s", raw, tenant_id
            )
            continue
        highest = max(highest, int(m.group(1)))
    return highest + 1


async def persist_issue(
    db: AsyncSession,
    *,
    tenant_id: str,
    channel_id: str,
    review_id: str,
    rating: int,
    classification: ReviewClassification,
    reviewer_name: str | None = None,
    review_text: str | None = None,
    review_reply_id: str | None = None,
    extractor_version: str | None = None,
) -> Optional["ReviewIssue"]:
    """Store one classified review, with a ticket number if someone must act.

    Owns its own COMMIT, and does so while the ticket lock is still held — an
    uncommitted row would let the next lock holder re-issue the same number.
    Callers must not wrap this in a larger transaction they roll back.

    Returns the stored row. An issue that needs no attention is still stored --
    it just gets ticket_number=None, so a ticket number keeps meaning "a human
    owes this customer something".
    """
    from ..channels.models import ReviewIssue

    def _row(ticket_number: str | None) -> "ReviewIssue":
        return ReviewIssue(
            tenant_id=tenant_id,
            channel_id=channel_id,
            review_reply_id=review_reply_id,
            review_id=review_id,
            rating=rating,
            primary_category=classification.primary_category,
            subcategory=classification.subcategory,
            subcategory_detail=classification.subcategory_detail,
            intent=classification.intent,
            sentiment=classification.sentiment,
            priority=classification.priority,
            needs_attention=bool(classification.needs_attention),
            summary=classification.summary,
            status="new",
            reviewer_name=reviewer_name,
            review_text=review_text,
            extractor_version=extractor_version,
            ticket_number=ticket_number,
        )

    if classification.needs_attention:
        # The commit stays inside the lock: see ticket_lock's docstring.
        async with ticket_lock(db, tenant_id):
            row = _row(format_ticket(await _next_sequence(db, tenant_id)))
            db.add(row)
            await db.commit()
            await db.refresh(row)
        return row

    row = _row(None)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def find_by_ticket(
    db: AsyncSession, tenant_id: str, ticket_number: str
) -> Optional["ReviewIssue"]:
    """Tenant-scoped ticket lookup.

    The tenant filter is not optional: ticket numbers are only unique WITHIN a
    tenant, so an unscoped lookup would happily return another workspace's
    customer. Callers pass ctx.tenant_id, never a channel-derived guess.
    """
    from ..channels.models import ReviewIssue

    canon = normalize_ticket(ticket_number)
    if canon is None:
        return None
    return (
        await db.execute(
            select(ReviewIssue).where(
                ReviewIssue.tenant_id == tenant_id,
                ReviewIssue.ticket_number == canon,
            )
        )
    ).scalar_one_or_none()


async def open_issues(
    db: AsyncSession, tenant_id: str, channel_id: str | None = None
) -> list:
    """Every unresolved issue — the work queue.

    Needs-attention first, then by urgency, then oldest-first. An urgent
    complaint from last week outranks a 'normal' one from an hour ago.
    """
    from ..channels.models import ReviewIssue

    rank = case(
        {"urgent": 0, "high": 1, "normal": 2, "low": 3},
        value=ReviewIssue.priority,
    )
    stmt = select(ReviewIssue).where(
        ReviewIssue.tenant_id == tenant_id,
        ReviewIssue.status.notin_(("resolved", "closed")),
    )
    if channel_id:
        stmt = stmt.where(ReviewIssue.channel_id == channel_id)
    stmt = stmt.order_by(
        ReviewIssue.needs_attention.desc(), rank.asc(), ReviewIssue.created_at.asc()
    )
    return list((await db.execute(stmt)).scalars().all())


# --- the inbound lookup ladder -------------------------------------------


@dataclass(frozen=True)
class InboundMatch:
    """Which issue a returning customer's inbound message is about.

    `matched_by` records which rung fired, so the WhatsApp side can phrase its
    confirmation ("you're asking about TK-000042") instead of asserting a
    guess, and so a bad match is diagnosable after the fact.
    """

    issue: "ReviewIssue"
    matched_by: str  # "handoff_code" | "ticket_number"
    raw: str  # what the customer actually typed


async def resolve_inbound(
    db: AsyncSession,
    *,
    tenant_id: str,
    text: str | None = None,
    handoff_codes: list[str] | None = None,
) -> Optional[InboundMatch]:
    """Find the issue an inbound message refers to, walking strongest-first.

    Rungs, in order:
      1. handoff_code  -- short, single-purpose, minted for this exact customer.
      2. ticket_number -- "my ticket is TK-000042", padded or not.

    Within the ticket rung the FIRST ticket the customer mentions wins, and an
    unresolvable one is NOT skipped in favour of a later one. "TK-999999 or
    maybe TK-000042" quotes two businesses' tickets in one breath, and falling
    through would attach the customer to whichever one happens to exist here --
    which, inside a tenant, is still somebody else's complaint.

    Returns None when nothing resolves. The caller then treats the message as
    an ordinary new enquiry -- absence of a match must never block a reply.
    """
    from ..channels.models import ReviewIssue

    for code in handoff_codes or []:
        canon = _normalize_code(code)
        if canon is None:
            continue
        row = (
            await db.execute(
                select(ReviewIssue).where(
                    ReviewIssue.tenant_id == tenant_id,
                    ReviewIssue.handoff_code == canon,
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            return InboundMatch(issue=row, matched_by="handoff_code", raw=code)

    refs = extract_ticket_refs(text)
    if not refs:
        return None
    # First mention only -- see the docstring. Resolving the first that the
    # customer actually typed is predictable; hunting for one that happens to
    # exist is how the wrong ticket gets attached.
    first = refs[0]
    row = await find_by_ticket(db, tenant_id, first)
    if row is None:
        logger.info(
            "inbound quoted unknown ticket %s (tenant=%s) -- treating as new enquiry",
            first, tenant_id,
        )
        return None
    return InboundMatch(issue=row, matched_by="ticket_number", raw=first)
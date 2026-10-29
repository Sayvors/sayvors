import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...database import Base
from ...db_indexes import register_postgres_index_ddl


class Channel(Base):
    __tablename__ = "channels"
    __table_args__ = (
        # One row per location: (user, platform, listing_key). NULL keys
        # (channels with no location identity) never conflict — both
        # Postgres and SQLite treat NULLs as distinct here.
        UniqueConstraint("user_id", "platform", "listing_key", name="uq_channels_user_platform_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    platform: Mapped[str] = mapped_column(
        Enum(
            "facebook",
            "instagram",
            "x",
            "telegram",
            "whatsapp",
            "linkedin",
            "google_reviews",
            name="platform_type",
        )
    )
    platform_user_id: Mapped[str] = mapped_column(String(200))
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("active", "expired", "disconnected", "error", name="channel_status"),
        default="active",
    )
    avatar_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    webhook_secret: Mapped[str | None] = mapped_column(String(100), nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Stable dedupe key: Localith listing_id, or Google location_id for
    # native OAuth channels. NULL for channels with no location identity.
    # Uniqueness is enforced by a partial unique index
    # (user_id, platform, listing_key) WHERE listing_key IS NOT NULL, so a
    # race between workers can never twin a row — the loser reuses the
    # winner's row (get-or-create). Safe at any --workers count.
    listing_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    messages = relationship("ChannelMessage", back_populates="channel", cascade="all, delete-orphan")
    threads = relationship("ChannelThread", back_populates="channel", cascade="all, delete-orphan")
    threads = relationship("ChannelThread", back_populates="channel", cascade="all, delete-orphan")


class ChannelMessage(Base):
    __tablename__ = "channel_messages"
    __table_args__ = (
        # Thread lookup scans (channel_id, contact_phone) newest-first, and the
        # inbox needs it to be a real index rather than a table scan.
        Index("ix_channel_messages_thread", "channel_id", "contact_phone", "created_at"),
        # Inbox GROUP BY on (contact_phone_hash, channel_id) + ORDER BY
        # max(created_at) — composite index avoids full table scan.
        Index("ix_channel_messages_inbox", "channel_id", "contact_phone_hash", "created_at"),
        # Newest-first scan of a whole channel. The two indexes above put
        # contact_phone(_hash) before created_at, so neither can satisfy
        # `WHERE channel_id = ? ORDER BY created_at DESC LIMIT n` without a
        # sort. Search uses exactly that shape, per channel, on every query.
        Index("ix_channel_messages_channel_created", "channel_id", "created_at"),
        # Replay dedupe: a platform message id may be seen more than once, so
        # it must be unique — but NULL is legitimate (locally created rows and
        # pre-column rows), and multiple NULLs must be allowed. The migration
        # encodes exactly this partial unique index; a column-level
        # index=True would create a full, non-unique index instead.
        Index(
            "ix_channel_messages_platform_message_id",
            "platform_message_id",
            unique=True,
            postgresql_where=text("platform_message_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("channels.id"), index=True
    )
    platform_message_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    direction: Mapped[str] = mapped_column(Enum("inbound", "outbound", name="message_direction"))
    content: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(50), default="text")
    status: Mapped[str] = mapped_column(
        Enum("sent", "delivered", "read", "failed", name="message_status"),
        default="sent",
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Who the message is with, in the platform's own addressing. Inbound rows
    # carry the sender; outbound rows carry the recipient, which is what lets a
    # reply be threaded under the same contact as the question it answers.
    #
    # NULL means "sender unknown" — rows written before this column existed. The
    # inbox groups those into one "Unknown" thread rather than dropping them,
    # because they still contain the real conversation text.
    contact_phone: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Best-known display name. WhatsApp only sends a profile name on some
    # payloads, so this is often NULL and the UI falls back to the phone.
    contact_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Conversation category: complaint, inquiry, feedback, review, other.
    # Auto-assigned on inbound; manually overridable via the inbox API.
    category: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    # Conversation priority: urgent, high, normal, low.
    priority: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    # True when the platform's AI authored this outbound row. Set only by the
    # consumer on rows it writes itself. Drives lead_escalation's counter.
    # Never inferred from message text — that would misclassify a human whose
    # reply happens to read like the AI's.
    is_ai: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    # Who handled this message: human / ai / system / unknown (old rows).
    # Drives the AI-performance split in analytics (deflection framing). Set
    # at write time by the consumer (ai), inbox reply endpoints (human) and
    # the escalation handover line (system); never inferred from text.
    handled_by: Mapped[str] = mapped_column(
        Enum("human", "ai", "system", "unknown", name="message_handled_by"),
        default="unknown",
        server_default="unknown",
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    channel = relationship("Channel", back_populates="messages")

class ChannelThread(Base):
    """Denormalized per-thread summary for the unified inbox.

    One row per (channel, contact). Maintained by SQLAlchemy event
    listeners on ChannelMessage so every insert site updates it
    without touching 15+ call sites. The inbox reads this table in a
    single query instead of GROUP BY + full message load.

    unread_count = inbound messages after the most recent outbound.
    """
    __tablename__ = "channel_threads"
    __table_args__ = (
        # Unique index (not a UniqueConstraint) because the migration creates
        # it with CREATE UNIQUE INDEX; same object, and the inbox upsert's
        # ON CONFLICT (channel_id, contact_phone_hash) needs it.
        Index(
            "uq_channel_threads_channel_contact",
            "channel_id",
            "contact_phone_hash",
            unique=True,
        ),
        Index("ix_channel_threads_channel_last", "channel_id", "last_message_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # Both columns are covered by the unique index above (channel_id is its
    # leftmost column), so separate single-column indexes would only add
    # write cost.
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("channels.id", ondelete="CASCADE")
    )
    contact_phone: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_direction: Mapped[str | None] = mapped_column(String(10), nullable=True)
    last_message_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    unread_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    priority: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    # Soft-archive: NULL = active inbox thread. Set to a timestamp to hide
    # the thread from the default inbox view; the row (and its messages) are
    # preserved and reappear when unarchived. Distinct from deletion, which
    # removes everything.
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None, index=True
    )
    # Soft-pin: NULL = not pinned. Pinned threads sort to the top of the
    # inbox list (client already does this; server-persisting lets the pin
    # follow the tenant across devices/browsers).
    pinned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None, index=True
    )
    # Who answers this conversation: "ai" (default) or "human". The single
    # source of truth for the AI mute — priority=important is only the
    # automatic path that sets it. Indexed because the reply consumer and the
    # resume sweep both look it up per inbound.
    conversation_mode: Mapped[str] = mapped_column(
        Enum("ai", "human", name="conversation_mode"),
        default="ai",
        server_default="ai",
        nullable=False,
        index=True,
    )
    # Why the mode last changed, and who did it. "system" means the automatic
    # escalation path, which the resume sweep may reverse; any other value
    # (a user id, "human_reply", "resolve") means a human decision that the
    # sweep must not steal back.
    mode_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    mode_changed_by: Mapped[str | None] = mapped_column(
        String(64), nullable=True, default=None
    )
    channel = relationship("Channel", back_populates="threads")


class ConversationContext(Base):
    """A stored, human-readable summary of one conversation.

    The AI rebuilds its prompt from the last N raw messages every turn, which
    loses everything older than the window and gives a human opening the
    thread no orientation. This table holds point-in-time summaries written on
    mode changes, on resolve, and periodically while a thread runs.

    ``summary`` is encrypted: it paraphrases what the customer said, which is
    the same PII as the messages it came from. History is kept rather than
    overwritten so a bad generation can be replaced without losing the last
    good one — readers always take the newest row.
    """

    __tablename__ = "conversation_contexts"
    __table_args__ = (
        # Latest-context lookup is always "newest row for this thread".
        Index(
            "ix_conversation_contexts_thread",
            "channel_id",
            "contact_phone_hash",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("channels.id", ondelete="CASCADE")
    )
    contact_phone: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str] = mapped_column(Text)
    # How many messages the summary covers, so a reader can tell a 2-message
    # summary from a 200-message one.
    message_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    # mode_change | resolve | escalation | periodic | manual
    reason: Mapped[str] = mapped_column(String(32), default="manual")
    # Which model wrote it. NULL when generation failed and the row records
    # only that an attempt happened.
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )



class ChannelComment(Base):
    """A comment on the tenant's OWN media (Instagram today, FB Pages later).

    The comment section as an inbox: webhook events land here so the tenant
    sees and replies to them from Sayvors with full history. Rows are keyed
    by the platform comment id for replay dedupe; an existing id with new
    text is Meta's "edited" redelivery and updates the row.

    platform_timestamp is when the comment was written on Instagram —
    created_at is only when we stored it. Meta sends no delete webhook, so
    deleted-on-Instagram is discovered lazily (a probe 404s) and recorded
    in deleted_at; a delete via Sayvors sets it immediately.
    """

    __tablename__ = "channel_comments"
    __table_args__ = (
        # Dedupe lookups by platform id, thread lookups (replies of a
        # comment) and per-media feeds all scan — give each a real index.
        Index("ix_channel_comments_platform_id", "platform_comment_id"),
        # The migration enforces replay dedupe with a PARTIAL unique index
        # (NULL platform ids are unsent drafts and may repeat). A column-level
        # unique=True would create a full constraint with a different name.
        Index(
            "uq_channel_comments_platform_id",
            "platform_comment_id",
            unique=True,
            postgresql_where=text("platform_comment_id IS NOT NULL"),
        ),
        Index("ix_channel_comments_parent", "parent_platform_comment_id"),
        Index("ix_channel_comments_media", "channel_id", "media_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("channels.id"), index=True
    )
    platform_comment_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    parent_platform_comment_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    media_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    direction: Mapped[str] = mapped_column(Enum("inbound", "outbound", name="comment_direction"))
    content: Mapped[str] = mapped_column(Text)
    # Who wrote it, in the platform's own addressing (IGSID + username).
    # Outbound rows carry the tenant as author — the fields stay NULL there
    # and the UI renders the account instead.
    author_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    author_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(
        Enum("received", "sent", "failed", name="comment_status"),
        default="received",
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    platform_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ContactProfile(Base):
    """Cached profile for one customer on one platform.

    WhatsApp ships the profile name free on every webhook; Instagram and
    Messenger expose name/username/avatar through a Graph read on the
    conversation participant (IGSID/PSID). Avatar URLs are temporary CDN
    links — `profile_fetched_at` drives a weekly refresh on inbound
    traffic so the inbox keeps showing a current picture.
    """

    __tablename__ = "contact_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    platform: Mapped[str] = mapped_column(String(20), index=True)
    # Phone number (whatsapp), IGSID (instagram) or PSID (facebook)
    contact_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    username: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Temporary CDN URL — never guaranteed long-lived; refresh when stale
    avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    profile_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "platform", "contact_id",
            name="uq_contact_profiles_identity",
        ),
    )


class Lead(Base):
    """A customer the messaging loop is converting.

    One row per (channel, contact): the conversation identity is the key —
    a lead never requires a name or phone number to exist. Capture rides
    the reply LLM call (a trailing ``LEAD: {json}`` line, parsed for free)
    plus cheap deterministic parsing; the merge never overwrites a known
    field with an empty or lower-confidence value, and every captured
    field keeps its provenance in field_provenance.

    stage is the deterministic pipeline state — new -> qualified ->
    follow_up -> converted/lost. The engine moves it; the tenant can
    override to won/lost at any point. opt_out suppresses every scheduled
    action regardless of stage. thread_key is the unified-inbox thread
    identifier, so the UI can walk from the lead into the conversation.
    """

    __tablename__ = "leads"
    __table_args__ = (
        # Dashboard list scans (tenant, newest first) and the capture
        # step's open-lead lookup (channel, contact) — one index each.
        Index("ix_leads_tenant_created", "tenant_id", "created_at"),
        Index("ix_leads_channel_contact", "channel_id", "contact_id"),
        # Board sort: WHERE tenant_id=? ORDER BY priority DESC, updated_at DESC.
        # Stored (not derived in SQL) so this stays an index scan rather than
        # a full sort of the lead table. See lead_escalation.py.
        Index("ix_leads_tenant_priority", "tenant_id", "priority", "updated_at"),
        # ix_leads_pending_reminder is a partial index (WHERE
        # priority='important') and cannot be expressed in __table_args__.
        # It is registered as a PostgreSQL-only after_create hook below so a
        # models-only rebuild still gets it; SQLite skips it.
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("channels.id"), index=True
    )
    # Denormalized from the channel so the list can filter without a join.
    platform: Mapped[str] = mapped_column(String(20))
    # The platform's own contact addressing (IGSID / phone / PSID) — the
    # tenant-scoped conversation identity, never a global customer id.
    contact_id: Mapped[str] = mapped_column(String(64))
    contact_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    contact_username: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # What the customer writes in — templates and localization key off it.
    language: Mapped[str] = mapped_column(String(16), default="en")
    # Buying intent, one of "buying" | "booking" | "quote" | "info".
    intent: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # What they need, in the customer's own words.
    request: Mapped[str | None] = mapped_column(Text, nullable=True)
    # One-line UI summary (falls back to request in the API when unset).
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    stage: Mapped[str] = mapped_column(
        Enum("new", "qualified", "follow_up", "converted", "lost", name="lead_stage"),
        default="new",
    )
    # A phone number the customer TYPED (never the Meta sender identity,
    # which lives in contact_id). "stated" = validated shape only;
    # "verified" requires a real verification flow (nobody sets it yet).
    phone_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    phone_status: Mapped[str] = mapped_column(
        Enum("stated", "verified", name="lead_phone_status"),
        default="stated",
    )
    # Deterministic opt-out (customer said stop / توقف). Kills every
    # pending and future scheduled action for this lead.
    opt_out: Mapped[bool] = mapped_column(Boolean, default=False)
    opt_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # {field: {value, confidence, source_message_id, at}} — provenance for
    # every extracted field, so a merge can refuse to downgrade.
    field_provenance: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Platform message id that first created the lead (provenance anchor).
    source_message_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Staleness guard for scheduled actions: the last inbound we had seen
    # when the action was armed. A different id at send time means the
    # customer replied since — the action is stale.
    last_inbound_message_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Mirror of the next scheduled follow-up's due_at (cheap UI badge).
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # ── Escalation state ──────────────────────────────────────────────
    # Consecutive "AI replied, customer wrote again" cycles. This is the sole
    # input that ever moves `priority` — see lead_escalation.py, which is the
    # only writer of both, so the two cannot drift.
    ai_miss_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    # "normal" | "important". Stored and indexed so the board can sort and
    # filter, and so the reminder sweep can query across tenants.
    priority: Mapped[str] = mapped_column(
        Enum("normal", "important", name="lead_priority"),
        default="normal", server_default="normal", nullable=False,
    )
    priority_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # NULL is terminal — "already reminded, or never armed" — NOT "not yet".
    escalation_reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The holding line ("let me get my colleague help") has been delivered, so
    # a re-trigger never repeats it.
    handover_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Unified-inbox thread key, for the lead -> conversation deep link.
    thread_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class LeadAction(Base):
    """One durable, scheduled follow-up for a lead.

    The database is the scheduler — no in-memory timers. A worker claims
    rows with a short lease and never holds a transaction across the Meta
    API call. guard_message_id (the inbound we were answering) is the
    staleness guard: if the thread's newest inbound differs at send time,
    the customer answered and the action cancels itself. Idempotency is
    structural: unique (lead, guard message, attempt) can only exist once,
    however many workers race to arm it.
    """

    __tablename__ = "lead_actions"
    __table_args__ = (
        UniqueConstraint(
            "lead_id", "guard_message_id", "attempt",
            name="uq_lead_actions_step",
        ),
        # The dispatcher's only scan: claimable rows, due first.
        Index("ix_lead_actions_due", "status", "due_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    lead_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("leads.id"), index=True
    )
    channel_id: Mapped[str] = mapped_column(String(36))
    contact_id: Mapped[str] = mapped_column(String(64))
    platform: Mapped[str] = mapped_column(String(20))
    action_type: Mapped[str] = mapped_column(
        Enum("follow_up", name="lead_action_type"), default="follow_up"
    )
    status: Mapped[str] = mapped_column(
        Enum(
            "pending", "claimed", "sent", "cancelled", "failed",
            "ineligible", "ambiguous",
            name="lead_action_status",
        ),
        default="pending",
    )
    # 1-based: 1 = first nudge (minutes), 2 = second (~24h), 3 = final (~72h).
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    # The open question being chased + context for the template.
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(String(16), default="en")
    guard_message_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Claim lease: a worker owns this row only until claimed_until.
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Why a send never happened: "opt_out", "window_closed", "stage_closed",
    # "answered", "attempt_cap", "guard_stale", ...
    ineligible_reason: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # "transient" (backoff + retry) vs "permanent" (stop, actionable).
    error_category: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Bounded transient retries per action — no unbounded background work.
    send_retries: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class LeadDigestSend(Base):
    """One pending-leads digest, per tenant, per local calendar day.

    Exists so "email this tenant once a day" is enforced by the database rather
    than by a check-then-insert. Several workers can run the sweep and one can
    restart mid-send; with UNIQUE (tenant_id, digest_date) a second send is not
    a race to be guarded but an insert that cannot happen.

    digest_date is the tenant's LOCAL date. A tenant in Riyadh gets theirs on
    their morning, and "already sent today" stays one indexed lookup.
    """

    __tablename__ = "lead_digest_sends"
    __table_args__ = (
        UniqueConstraint("tenant_id", "digest_date", name="uq_lead_digest_sends_tenant_date"),
        Index("ix_lead_digest_sends_tenant_date", "tenant_id", "digest_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    digest_date: Mapped[date] = mapped_column(Date, nullable=False)
    # How many leads the email listed. Retained so a 0-lead send is visibly
    # wrong rather than a silent no-op.
    lead_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class AutoReplyConfig(Base):
    """Per-channel auto-reply settings (Phase 1: Google Reviews)."""

    __tablename__ = "auto_reply_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("channels.id", ondelete="CASCADE"), unique=True, index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Tone preset: friendly, professional, apologetic, playful, ...
    tone: Mapped[str] = mapped_column(String(50), default="friendly")
    # Optional Databank linked for grounding replies in merchant knowledge
    databank_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # Reviews with rating below this are queued for human approval, not auto-posted
    min_rating_auto: Mapped[int] = mapped_column(Integer, default=4)
    # "auto" = post above min_rating_auto, queue below.
    # "approval" = every reply waits for human approval.
    approval_mode: Mapped[str] = mapped_column(
        Enum("auto", "approval", name="reply_approval_mode"), default="approval"
    )
    # When a reviewer edits a review we already answered, the follow-up
    # reply waits for human approval by default. True = the follow-up may
    # auto-post, through the same gates as a fresh reply (approval_mode
    # "auto" + rating at/above min_rating_auto).
    edited_review_autopost: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    # Free-text brand voice / house rules injected into every reply prompt
    custom_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    # LLM model id (provider catalog id, e.g. "groq:openai/gpt-oss-120b").
    # NULL = tenant default, resolved from the admin-managed enabled
    # models at generation time. Never a hardcoded provider default.
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Arabic dialect code (review_engine.dialects catalog) or "auto".
    dialect: Mapped[str] = mapped_column(String(30), default="auto")
    # Reply language policy: match the review, or force en/ar.
    reply_language: Mapped[str] = mapped_column(String(10), default="match")
    # Promotional toggles — all default OFF (historical no-promo behavior).
    promo_product_mentions: Mapped[bool] = mapped_column(Boolean, default=False)
    promo_links: Mapped[bool] = mapped_column(Boolean, default=False)
    promo_only_relevant: Mapped[bool] = mapped_column(Boolean, default=True)
    promo_max_ctas: Mapped[int] = mapped_column(Integer, default=1)
    # Offer needs-attention reviewers a wa.me deep link (prefilled with the
    # issue's handoff code) in the public reply, so the WhatsApp assistant
    # greets them with the ticket already known. The link publishes the
    # tenant's WhatsApp number on the listing, so this is opt-out — default ON
    # because the recovery loop is the point, OFF for tenants who must not
    # publish the line.
    handoff_link_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    # Lifetime of a handoff code (days). The wa.me link carries the code as
    # its `text` payload, so expiring the code also expires the link: a stale
    # review reply stops attaching a customer to a ticket months later.
    # Clamped to [1, 30] in review_engine.handoff; default 1 day.
    handoff_code_ttl_days: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1"
    )
    # Polling lease (atomic claim across worker instances)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    polling_locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class VerificationRecord(Base):
    """Sayvors-side verification request state for a Google channel."""

    __tablename__ = "channel_verifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("channels.id", ondelete="CASCADE"), unique=True, index=True
    )
    status: Mapped[str] = mapped_column(String(30), default="unstarted")
    method: Mapped[str | None] = mapped_column(String(30), nullable=True)
    contact_target: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )


class BusinessService(Base):
    """Merchant services managed for one connected Google channel."""

    __tablename__ = "channel_services"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("channels.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(120), default="Custom")
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_offered: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String(30), default="custom")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )


class ReviewReply(Base):
    """A (candidate or posted) reply to a Google review."""

    __tablename__ = "review_replies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("channels.id", ondelete="CASCADE"), index=True
    )
    # Google review resource name: accounts/{a}/locations/{l}/reviews/{r}
    review_id: Mapped[str] = mapped_column(String(500), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    review_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reply_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        # "approved" = merchant approved a Localith draft; it is NOT on
        # Google yet — they post it from their Localith/GBP dashboard.
        Enum("posted", "pending_approval", "failed", "rejected", "approved",
             name="review_reply_status"),
        default="pending_approval",
    )
    # How many times a draft has been generated for this review
    # (1 = first draft; regenerate/retry/resume increments it).
    generation_attempt: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Set when the row is adopted from a reply Google already shows (the
    # Localith sync pulls the live reply text on every poll). Identifies the
    # provider-side reply so a later poll can tell "same reply" from "the
    # business edited it directly in the Google Business Profile".
    reply_external_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    # When that live reply was published, per the provider. Distinct from
    # created_at, which is when Sayvors first learned about the row.
    replied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

class ReviewIssue(Base):
    """A classified Google review — issue, subcategory, intent, sentiment,
    priority, status. One row per review that we have parsed.

    This is the atom we later hang the WhatsApp handoff off of. It also lets
    the phone-friendly 'Status: Review' state exist at all — the dashboard can
    show the state of every customer-facing issue without reopening review
    threads.

    primary_category is one of the 12 fixed choices defined in
    review_engine/issues.py. subcategory is tenant-defined (per industry list)
    with 'other' as fallback. subcategory_detail is free text when a tenant
    wants a richer record.
    """

    __tablename__ = "review_issues"
    __table_args__ = (
        # The public wa.me prefill carries no tenant id, so a handoff code
        # must be globally unique. ensure_handoff_code() relies on this index
        # to catch the rare random collision and retry; without it a duplicate
        # can be written and resolve_inbound() would raise MultipleResultsFound.
        Index("ix_review_issues_handoff_code", "handoff_code", unique=True),
        # Ticket numbers are sequential per tenant. The advisory lock is the
        # primary guard; this unique index is the database backstop.
        Index(
            "ix_review_issues_tenant_ticket",
            "tenant_id",
            "ticket_number",
            unique=True,
        ),
        # Ticket queue scans: tenant + status / priority / review.
        Index("ix_review_issues_tenant_status", "tenant_id", "status"),
        Index("ix_review_issues_tenant_priority", "tenant_id", "priority"),
        Index("ix_review_issues_tenant_review_id", "tenant_id", "review_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    channel_id: Mapped[str] = mapped_column(String(36), ForeignKey("channels.id", ondelete="CASCADE"), index=True, nullable=False)
    review_reply_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("review_replies.id", ondelete="CASCADE"), nullable=True, index=True)
    review_id: Mapped[str] = mapped_column(String(500), index=True, nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    primary_category: Mapped[str] = mapped_column(String(60), nullable=False, default="other", server_default="other")
    subcategory: Mapped[str] = mapped_column(String(100), nullable=False, default="other", server_default="other")
    subcategory_detail: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Defaults must be members of review_engine.classification.INTENTS /
    # SENTIMENTS — "question"/"neutral" are not, and a row holding either would
    # fail ReviewClassification.validate().
    intent: Mapped[str] = mapped_column(String(40), nullable=False, default="ask_question", server_default="ask_question")
    sentiment: Mapped[str] = mapped_column(String(20), nullable=False, default="mixed", server_default="mixed")
    priority: Mapped[str] = mapped_column(String(10), nullable=False, default="normal", server_default="normal")
    needs_attention: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False, index=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new", server_default="new")
    reviewer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    review_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extractor_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Sequential per tenant, assigned by review_engine.tickets.persist_issue
    # only to issues that need attention. NULL for praise / neutral chatter, so
    # a ticket number always means "a human owes this customer something".
    # Unique per (tenant_id, ticket_number) -- NULLs do not collide in Postgres
    # or SQLite unique indexes, so unnumbered issues stack freely.
    ticket_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Six characters from CODE_ALPHABET. Globally unique (ix_review_issues_
    # handoff_code) because the public wa.me prefill carries no tenant id.
    handoff_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # When the code (and therefore the wa.me link that prefills it) stops
    # resolving. NULL = legacy row minted before TTLs existed: never expires.
    handoff_code_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def summary_line(self) -> str:
        """One-line ticket summary for a returning customer's short-circuit reply."""
        tag = self.primary_category.replace("_", " ").title()
        return tag if not self.summary else f"{tag} -- {self.summary}"





class WhatsAppThreadState(Base):
    """Per-conversation stats for one WhatsApp customer.

    A thread is (channel, contact_phone) — the same key the inbox groups on.
    The consumer refreshes `language` and `confused` from a small classifier
    call on every inbound message; `awaiting_since`/`followup_sent` drive the
    ONE gentle follow-up when the AI asked the customer something and they
    went quiet. `followup_sent=True` guarantees a second nudge is never sent
    until the user replies (which resets both fields).
    """

    __tablename__ = "whatsapp_thread_states"
    __table_args__ = (
        UniqueConstraint("channel_id", "contact_phone", name="uq_wa_thread_channel_phone"),
        # Explicit names so a models-only rebuild matches the migrated
        # database (its indexes were created as ix_wa_thread_states_*).
        Index("ix_wa_thread_states_channel_id", "channel_id"),
        Index("ix_wa_thread_states_contact_phone", "contact_phone"),
        Index("ix_wa_thread_states_contact_phone_hash", "contact_phone_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    channel_id: Mapped[str] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE")
    )
    # get_or_create_thread_state() returns None before constructing a row when
    # the phone is missing, so every persisted row has one. The migrated
    # column is NOT NULL; the model must say the same.
    contact_phone: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_phone_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Customer's language as detected from their own words ("en", "ar",
    # "ur", "ps", "hi", "bn", ...). Drives the voice-note language.
    language: Mapped[str] = mapped_column(String(16), default="en")
    confused: Mapped[bool] = mapped_column(Boolean, default=False)
    confused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set when the AI's reply asked the customer something; cleared the
    # moment any inbound message from the contact arrives.
    awaiting_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    followup_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


# The escalation sweep is the only cross-tenant query in the feature; without
# this partial index it scans every lead row. Registered here (not in
# __table_args__) because SQLite cannot express a partial index.
register_postgres_index_ddl(
    Lead.__table__,
    [
        "CREATE INDEX IF NOT EXISTS ix_leads_pending_reminder "
        "ON leads (escalation_reminder_at) WHERE priority = 'important'"
    ],
    names=["ix_leads_pending_reminder"],
)

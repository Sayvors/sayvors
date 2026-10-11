"""Leads + durable lead_actions scheduler + tenant lead settings.

Revision ID: b7d6e5f4a3c2
Revises: f8a9b0c1d2e3
Create Date: 2026-10-11

The messaging loop captures interested customers while it chats (a
trailing LEAD extraction line on the reply call, plus deterministic
parsing) and schedules follow-ups as database rows instead of LLM calls.

- `leads` — one row per (channel, contact): stage, intent, request,
  language, stated phone (+ provenance), opt-out, staleness guard.
- `lead_actions` — the durable scheduler: unique (lead, guard message,
  attempt) makes idempotency structural; (status, due_at) is the
  dispatcher's only scan; lease columns survive worker crashes.
- `users.lead_settings` — tenant knobs (clamped by the engine, NULL =
  safe defaults). JSON so new knobs never need a migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7d6e5f4a3c2"
down_revision: Union[str, None] = "f8a9b0c1d2e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "leads",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column(
            "channel_id", sa.String(36), sa.ForeignKey("channels.id"), nullable=False
        ),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("contact_id", sa.String(64), nullable=False),
        sa.Column("contact_name", sa.String(120), nullable=True),
        sa.Column("contact_username", sa.String(120), nullable=True),
        sa.Column("language", sa.String(16), nullable=False, server_default="en"),
        sa.Column("intent", sa.String(30), nullable=True),
        sa.Column("request", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "stage",
            sa.Enum("new", "qualified", "follow_up", "converted", "lost", name="lead_stage"),
            nullable=False,
            server_default="new",
        ),
        sa.Column("phone_number", sa.String(32), nullable=True),
        sa.Column(
            "phone_status",
            sa.Enum("stated", "verified", name="lead_phone_status"),
            nullable=False,
            server_default="stated",
        ),
        sa.Column("opt_out", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("opt_out_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("field_provenance", sa.JSON(), nullable=True),
        sa.Column("source_message_id", sa.String(200), nullable=True),
        sa.Column("last_inbound_message_id", sa.String(200), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_action_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("thread_key", sa.String(200), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Index("ix_leads_tenant_id", "tenant_id"),
        sa.Index("ix_leads_channel_id", "channel_id"),
        sa.Index("ix_leads_tenant_created", "tenant_id", "created_at"),
        sa.Index("ix_leads_channel_contact", "channel_id", "contact_id"),
    )
    op.create_table(
        "lead_actions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column(
            "lead_id", sa.String(36), sa.ForeignKey("leads.id"), nullable=False
        ),
        sa.Column("channel_id", sa.String(36), nullable=False),
        sa.Column("contact_id", sa.String(64), nullable=False),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column(
            "action_type",
            sa.Enum("follow_up", name="lead_action_type"),
            nullable=False,
            server_default="follow_up",
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "claimed", "sent", "cancelled", "failed",
                "ineligible", "ambiguous",
                name="lead_action_status",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("language", sa.String(16), nullable=False, server_default="en"),
        sa.Column("guard_message_id", sa.String(200), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_by", sa.String(64), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_message_id", sa.String(200), nullable=True),
        sa.Column("ineligible_reason", sa.String(60), nullable=True),
        sa.Column("error_category", sa.String(30), nullable=True),
        sa.Column("send_retries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "lead_id", "guard_message_id", "attempt", name="uq_lead_actions_step"
        ),
        sa.Index("ix_lead_actions_tenant_id", "tenant_id"),
        sa.Index("ix_lead_actions_lead_id", "lead_id"),
        sa.Index("ix_lead_actions_due", "status", "due_at"),
    )
    op.add_column(
        "users",
        sa.Column("lead_settings", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "lead_settings")
    op.drop_table("lead_actions")
    sa.Enum(name="lead_action_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="lead_action_type").drop(op.get_bind(), checkfirst=True)
    op.drop_table("leads")
    sa.Enum(name="lead_phone_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="lead_stage").drop(op.get_bind(), checkfirst=True)

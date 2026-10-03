"""WhatsApp thread stats + tenant voice replies + admin voice models.

Revision ID: e0f1a2b3c4d5
Revises: d9e0f1a2b3c4
Create Date: 2026-10-03

- users.voice_replies: tenant tier ("off" | "simple" | "advanced"). "off"
  never sends voice notes; the engine behind each tier is admin-managed.
- whatsapp_thread_states: per-(channel, contact) conversation stats —
  detected language, confusion signal, and the one-shot follow-up flags.
- voice_model_configs: admin-managed TTS engines (provider, tier, language
  coverage). Seeded with the two free Edge engines so voice works out of
  the box; admins can add ElevenLabs/OpenAI later without a migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e0f1a2b3c4d5"
down_revision: Union[str, None] = "d9e0f1a2b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "voice_replies",
            sa.String(length=16),
            nullable=False,
            server_default="off",
        ),
    )
    op.create_table(
        "whatsapp_thread_states",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "channel_id",
            sa.String(length=36),
            sa.ForeignKey("channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("contact_phone", sa.String(length=32), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False, server_default="en"),
        sa.Column("confused", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("confused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("awaiting_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("followup_sent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("channel_id", "contact_phone", name="uq_wa_thread_channel_phone"),
    )
    op.create_index("ix_wa_thread_states_channel_id", "whatsapp_thread_states", ["channel_id"])
    op.create_index("ix_wa_thread_states_contact_phone", "whatsapp_thread_states", ["contact_phone"])
    op.create_table(
        "voice_model_configs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="edge"),
        sa.Column("api_url", sa.String(length=500), nullable=True),
        sa.Column("api_model", sa.String(length=200), nullable=True),
        # Voice identity pin (Fish reference_id). Without it Fish picks an
        # arbitrary persona per request; pinned, every note sounds the same.
        sa.Column("reference_id", sa.String(length=200), nullable=True),
        # Provider API key, Fernet-encrypted at rest (same scheme as OAuth
        # tokens). Set/rotated through the admin API — never in code.
        sa.Column("key_encrypted", sa.Text(), nullable=True),
        sa.Column("tier", sa.String(length=16), nullable=False, server_default="simple"),
        sa.Column("languages", sa.String(length=500), nullable=False, server_default="*"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # Out-of-the-box engines: "advanced" = Fish Audio (free developer tier,
    # key added via the admin API — never seeded in code); "simple" = the
    # free Edge neural voices, which work with no key at all. The Fish row
    # pins "Sarah", a top-scored public voice, so the persona is stable
    # across conversations (admins can swap it for any fish.audio voice id).
    op.bulk_insert(
        sa.table(
            "voice_model_configs",
            sa.column("id", sa.String),
            sa.column("label", sa.String),
            sa.column("provider", sa.String),
            sa.column("api_url", sa.String),
            sa.column("api_model", sa.String),
            sa.column("reference_id", sa.String),
            sa.column("tier", sa.String),
            sa.column("languages", sa.String),
            sa.column("enabled", sa.Boolean),
        ),
        [
            {
                "id": "voice-edge-simple-0001",
                "label": "Natural voices (simple)",
                "provider": "edge",
                "api_url": None,
                "api_model": None,
                "reference_id": None,
                "tier": "simple",
                "languages": "*",
                "enabled": True,
            },
            {
                "id": "voice-fish-advanced-001",
                "label": "Fish Audio (advanced)",
                "provider": "fish",
                "api_url": "https://api.fish.audio/v1/tts",
                "api_model": "s2.1-pro-free",
                "reference_id": "933563129e564b19a115bedd57b7406a",
                "tier": "advanced",
                "languages": "*",
                "enabled": True,
            },
        ],
    )


def downgrade() -> None:
    op.drop_table("voice_model_configs")
    op.drop_index("ix_wa_thread_states_contact_phone", table_name="whatsapp_thread_states")
    op.drop_index("ix_wa_thread_states_channel_id", table_name="whatsapp_thread_states")
    op.drop_table("whatsapp_thread_states")
    op.drop_column("users", "voice_replies")

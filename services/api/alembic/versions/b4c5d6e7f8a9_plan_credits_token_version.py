"""Plan + AI credit balance + token version on users; billing_events ledger.

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-09-22

P0 security/billing batch:
- users.plan / users.ai_credit_cents — Pro plan grants a USD-cent AI
  budget; every LLM call spends from it (D1 enforcement).
- users.token_version — bumped on password change / logout-all so
  previously issued access tokens are rejected (G1 revocation).
- billing_events — admin-visible audit ledger for plan/credit changes
  (one row per grant/topup, never per AI call).
"""
import sqlalchemy as sa

from alembic import op

revision = "b4c5d6e7f8a9"
down_revision = "a3b4c5d6e7f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("plan", sa.String(16), nullable=False, server_default="free"),
    )
    op.add_column(
        "users",
        sa.Column("ai_credit_cents", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "billing_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("balance_after_cents", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("billing_events")
    op.drop_column("users", "token_version")
    op.drop_column("users", "ai_credit_cents")
    op.drop_column("users", "plan")

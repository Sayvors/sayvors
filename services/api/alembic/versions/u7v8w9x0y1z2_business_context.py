"""Merge heads + tenant business-context columns on users.

Revision ID: u7v8w9x0y1z2
Revises: g8a9b0c1d2e3, t6u7v8w9x0y1 (merges the two heads)
Create Date: 2026-09-21

business_sells / business_doesnt_sell / business_description ground the AI
(review replies + post drafts) in what the company actually is — e.g. a
shawarma place can answer "do you sell shawarma?" from facts and decline
"is Dettol shampoo available?" instead of hallucinating.
"""
import sqlalchemy as sa

from alembic import op

revision = "u7v8w9x0y1z2"
down_revision = ("g8a9b0c1d2e3", "t6u7v8w9x0y1")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("business_sells", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("business_doesnt_sell", sa.Text(), nullable=True))
    op.add_column(
        "users", sa.Column("business_description", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "business_description")
    op.drop_column("users", "business_doesnt_sell")
    op.drop_column("users", "business_sells")

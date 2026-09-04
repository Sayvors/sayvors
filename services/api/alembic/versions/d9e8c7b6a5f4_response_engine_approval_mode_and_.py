"""response engine: approval mode + custom instructions

Revision ID: d9e8c7b6a5f4
Revises: c8d2f4a6b9e1
Create Date: 2026-09-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd9e8c7b6a5f4'
down_revision: Union[str, None] = 'c8d2f4a6b9e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APPROVAL_ENUM = 'reply_approval_mode'
STATUS_ENUM = 'review_reply_status'


def upgrade() -> None:
    # New enum values cannot be created/added inside a transaction block.
    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE TYPE {APPROVAL_ENUM} AS ENUM ('auto', 'approval')"
        )
        op.execute(
            f"ALTER TABLE auto_reply_configs ADD COLUMN approval_mode {APPROVAL_ENUM} "
            f"NOT NULL DEFAULT 'auto'"
        )
        op.execute(f"ALTER TYPE {STATUS_ENUM} ADD VALUE IF NOT EXISTS 'rejected'")

    op.add_column(
        'auto_reply_configs',
        sa.Column('custom_instructions', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('auto_reply_configs', 'custom_instructions')
    op.drop_column('auto_reply_configs', 'approval_mode')
    sa.Enum(name=APPROVAL_ENUM).drop(op.get_bind(), checkfirst=True)

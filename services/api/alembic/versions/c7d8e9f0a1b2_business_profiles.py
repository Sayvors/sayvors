"""business profiles — LLM-distilled business card per tenant

ONE row per user (unique user_id). Distilled from the tenant's databank
uploads after a successful ingest (or via the manual Regenerate button),
shown on the Databank screen, and injected into every AI prompt so the
assistant can answer "what can you do for me?" without searching the
databank. source = 'auto' | 'edited'; user edits always win over
regeneration.

Revision ID: c7d8e9f0a1b2
Revises: b4e7d1a9c350
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c7d8e9f0a1b2'
down_revision: Union[str, None] = 'b4e7d1a9c350'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'business_profiles',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('domain', sa.String(length=200), nullable=True),
        sa.Column('products_services', sa.Text(), nullable=True),
        sa.Column('not_offered_and_policies', sa.Text(), nullable=True),
        sa.Column('audience_languages', sa.String(length=500), nullable=True),
        sa.Column('source', sa.String(length=16), nullable=False, server_default='auto'),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    # One card per tenant — the unique index is the "get or create" guard.
    op.create_index(
        op.f('ix_business_profiles_user_id'),
        'business_profiles',
        ['user_id'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_business_profiles_user_id'), table_name='business_profiles')
    op.drop_table('business_profiles')

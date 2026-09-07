"""databank live database sources + database document origin

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-09-07 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f5a6b7c8d9e0'
down_revision: Union[str, None] = 'e4f5a6b7c8d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # New enum values / types cannot be created inside a transaction block,
    # and DO blocks make re-runs safe after a partial upgrade.
    with op.get_context().autocommit_block():
        op.execute("""
            DO $$ BEGIN
                ALTER TYPE document_source_type ADD VALUE 'database';
            EXCEPTION WHEN duplicate_object THEN NULL; END $$;
        """)
        op.execute("""
            DO $$ BEGIN
                ALTER TYPE ingest_job_type ADD VALUE 'database';
            EXCEPTION WHEN duplicate_object THEN NULL; END $$;
        """)
        op.execute("""
            DO $$ BEGIN
                CREATE TYPE datasource_db_type AS ENUM ('postgres', 'mysql');
            EXCEPTION WHEN duplicate_object THEN NULL; END $$;
        """)

    op.create_table(
        'databank_sources',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('databank_id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('db_type', postgresql.ENUM('postgres', 'mysql', name='datasource_db_type', create_type=False), nullable=False),
        sa.Column('host', sa.String(length=255), nullable=False, server_default='localhost'),
        sa.Column('port', sa.Integer(), nullable=False, server_default='5432'),
        sa.Column('database', sa.String(length=255), nullable=False),
        sa.Column('username', sa.String(length=255), nullable=False),
        sa.Column('password_encrypted', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['databank_id'], ['databanks.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_databank_sources_databank_id', 'databank_sources', ['databank_id'])
    op.create_index('ix_databank_sources_user_id', 'databank_sources', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_databank_sources_user_id', table_name='databank_sources')
    op.drop_index('ix_databank_sources_databank_id', table_name='databank_sources')
    op.drop_table('databank_sources')
    with op.get_context().autocommit_block():
        op.execute("DROP TYPE IF EXISTS datasource_db_type")
    # NOTE: postgres cannot remove enum values; 'database' stays valid.

"""meta connections, assets, oauth transactions, webhook events

Revision ID: t5u6v7w8x9y0
Revises: s4t5u6v7w8x9
Create Date: 2026-09-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 't5u6v7w8x9y0'
down_revision: Union[str, None] = 's4t5u6v7w8x9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'meta_connections',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('tenant_id', sa.String(length=36), nullable=False, index=True),
        sa.Column('provider', sa.Enum('whatsapp', 'facebook', 'instagram',
                                      name='meta_provider'),
                  nullable=False, index=True),
        sa.Column('connection_type', sa.String(length=50), nullable=False,
                  server_default='oauth'),
        sa.Column('meta_business_id', sa.String(length=100), nullable=True),
        sa.Column('access_token_encrypted', sa.Text(), nullable=True),
        sa.Column('token_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('scopes', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('status', sa.Enum('active', 'needs_reauth', 'expired', 'revoked',
                                    'error', name='meta_connection_status'),
                  nullable=False, server_default='active', index=True),
        sa.Column('metadata', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('last_validated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_successful_api_call_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_webhook_received_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('tenant_id', 'provider',
                            name='uq_meta_connections_tenant_provider'),
    )
    op.create_index('ix_meta_connections_tenant', 'meta_connections', ['tenant_id'])

    op.create_table(
        'meta_assets',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('tenant_id', sa.String(length=36), nullable=False, index=True),
        sa.Column('connection_id', sa.String(length=36),
                  sa.ForeignKey('meta_connections.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('provider', sa.Enum('whatsapp', 'facebook', 'instagram',
                                      name='meta_provider'),
                  nullable=False, index=True),
        sa.Column('asset_type', sa.Enum('waba', 'phone_number', 'page', 'ig_account',
                                        name='meta_asset_type'),
                  nullable=False, index=True),
        sa.Column('external_asset_id', sa.String(length=100), nullable=False, index=True),
        sa.Column('parent_asset_id', sa.String(length=36),
                  sa.ForeignKey('meta_assets.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('username', sa.String(length=255), nullable=True),
        sa.Column('phone', sa.String(length=50), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('status', sa.String(length=50), nullable=False,
                  server_default='connected'),
        sa.Column('metadata', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('provider', 'external_asset_id',
                            name='uq_meta_assets_provider_external'),
    )
    op.create_index('ix_meta_assets_tenant', 'meta_assets', ['tenant_id'])
    op.create_index('ix_meta_assets_connection', 'meta_assets', ['connection_id'])

    op.create_table(
        'meta_oauth_transactions',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('tenant_id', sa.String(length=36), nullable=False, index=True),
        sa.Column('provider', sa.Enum('whatsapp', 'facebook', 'instagram',
                                      name='meta_provider'),
                  nullable=False, index=True),
        sa.Column('state_hash', sa.String(length=64), nullable=False,
                  unique=True, index=True),
        sa.Column('status', sa.Enum('pending', 'completed', 'failed', 'expired',
                                    name='meta_oauth_status'),
                  nullable=False, server_default='pending', index=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_meta_oauth_tenant', 'meta_oauth_transactions', ['tenant_id'])

    op.create_table(
        'meta_webhook_events',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('provider', sa.Enum('whatsapp', 'facebook', 'instagram', 'unknown',
                                      name='meta_webhook_provider'),
                  nullable=False, index=True),
        sa.Column('external_event_id', sa.String(length=255), nullable=False, index=True),
        sa.Column('event_type', sa.String(length=100), nullable=False, index=True),
        sa.Column('tenant_id', sa.String(length=36), nullable=True, index=True),
        sa.Column('connection_id', sa.String(length=36), nullable=True, index=True),
        sa.Column('raw_payload', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('status', sa.Enum('received', 'processed', 'duplicate', 'rejected',
                                    'unresolved', name='meta_webhook_status'),
                  nullable=False, server_default='received', index=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('provider', 'external_event_id', 'event_type',
                            name='uq_meta_webhook_events_dedupe'),
    )
    op.create_index('ix_meta_webhook_tenant', 'meta_webhook_events', ['tenant_id'])


def downgrade() -> None:
    op.drop_index('ix_meta_webhook_tenant', table_name='meta_webhook_events')
    op.drop_table('meta_webhook_events')
    op.execute('DROP TYPE IF EXISTS meta_webhook_status')
    op.execute('DROP TYPE IF EXISTS meta_webhook_provider')
    op.drop_index('ix_meta_oauth_tenant', table_name='meta_oauth_transactions')
    op.drop_table('meta_oauth_transactions')
    op.execute('DROP TYPE IF EXISTS meta_oauth_status')
    op.drop_index('ix_meta_assets_tenant', table_name='meta_assets')
    op.drop_index('ix_meta_assets_connection', table_name='meta_assets')
    op.drop_table('meta_assets')
    op.execute('DROP TYPE IF EXISTS meta_asset_type')
    op.drop_index('ix_meta_connections_tenant', table_name='meta_connections')
    op.drop_table('meta_connections')
    op.execute('DROP TYPE IF EXISTS meta_connection_status')
    op.execute('DROP TYPE IF EXISTS meta_provider')

"""Team RBAC: roles, members, per-channel access, users.tenant_id.

Revision ID: b9c8d7e6f5a4
Revises: c8a1b2c3d4e5
Create Date: 2026-10-06

Phase 1 team management. The workspace owner is implicit (tenant_id ==
owner's users.id, the existing convention) and never stored as a member.
`team_members.user_id` is UNIQUE — phase 1 gives each user exactly one
workspace; multi-workspace membership is a later, additive change.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b9c8d7e6f5a4"
down_revision: Union[str, None] = "c8a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "team_roles",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("permissions", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uq_team_roles_tenant_name"),
    )
    op.create_index("ix_team_roles_tenant_id", "team_roles", ["tenant_id"])

    op.create_table(
        "team_members",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("role_id", sa.String(length=36), nullable=False),
        sa.Column(
            "status",
            sa.Enum("invited", "active", "suspended", name="team_member_status"),
            nullable=False,
            server_default="invited",
        ),
        sa.Column("invited_by", sa.String(length=36), nullable=True),
        sa.Column("invite_token_hash", sa.String(length=128), nullable=True),
        sa.Column("invite_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invited_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["team_roles.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("tenant_id", "email", name="uq_team_members_tenant_email"),
    )
    op.create_index("ix_team_members_tenant_id", "team_members", ["tenant_id"])
    op.create_index("ix_team_members_user_id", "team_members", ["user_id"])
    op.create_index("ix_team_members_email", "team_members", ["email"])
    op.create_index("ix_team_members_role_id", "team_members", ["role_id"])
    op.create_index("ix_team_members_invite_token_hash", "team_members", ["invite_token_hash"], unique=True)

    op.create_table(
        "team_member_channels",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("member_id", sa.String(length=36), nullable=False),
        sa.Column("channel_id", sa.String(length=36), nullable=False),
        sa.Column(
            "level",
            sa.Enum("none", "view", "edit", name="team_channel_level"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["member_id"], ["team_members.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("member_id", "channel_id", name="uq_team_member_channels_member_channel"),
    )
    op.create_index("ix_team_member_channels_member_id", "team_member_channels", ["member_id"])
    op.create_index("ix_team_member_channels_channel_id", "team_member_channels", ["channel_id"])

    # Phase 1 workspace attachment: NULL / own id = owner, someone else's
    # id = employee working in that workspace.
    op.add_column("users", sa.Column("tenant_id", sa.String(length=36), nullable=True))
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_users_tenant_id", table_name="users")
    op.drop_column("users", "tenant_id")
    op.drop_table("team_member_channels")
    op.drop_table("team_members")
    op.drop_index("ix_team_roles_tenant_id", table_name="team_roles")
    op.drop_table("team_roles")
    sa.Enum(name="team_member_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="team_channel_level").drop(op.get_bind(), checkfirst=True)

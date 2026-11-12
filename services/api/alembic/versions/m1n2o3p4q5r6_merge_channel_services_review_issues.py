"""Merge the channel-services and review-issue migration branches.

Revision ID: m1n2o3p4q5r6
Revises: r8s9t0u1v2w3, z6a7b8c9d0e1
Create Date: 2026-11-12

The channel-services line (q7w8e9r0t1y2 -> r8s9t0u1v2w3) and the review-issue
unique-index line (z5a6b7c8d9e0 -> z6a7b8c9d0e1) were authored in parallel
and both left the chain with two heads. ``alembic upgrade head`` refuses to
run while more than one head exists, so a deploy would crash-loop. This merge
revision joins them into a single head. It is a structural no-op: both
branches are already applied independently in every environment that ran
them.
"""

from __future__ import annotations

from alembic import op

revision: str = "m1n2o3p4q5r6"
down_revision: tuple[str, ...] | None = ("r8s9t0u1v2w3", "z6a7b8c9d0e1")
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Structural merge only; both branches carry their own DDL.
    pass


def downgrade() -> None:
    pass
"""add pricing to apologize/reassure strategy conditions

Revision ID: r3s4t5u6v7w8
Revises: q2b3c4d5e6f7
Create Date: 2026-09-12
"""
import json

from alembic import op
from sqlalchemy import text

revision = "r3s4t5u6v7w8"
down_revision = "q2b3c4d5e6f7"
branch_labels = None
depends_on = None

TARGETS = ("apologize_for_issue", "reassure_customer")


def upgrade() -> None:
    conn = op.get_bind()
    for sid in TARGETS:
        row = conn.execute(
            text("SELECT conditions FROM response_strategies WHERE id = :sid"),
            {"sid": sid},
        ).fetchone()
        if not row or not row[0]:
            continue
        conds = row[0] if isinstance(row[0], dict) else json.loads(row[0])
        issue_types = conds.get("issue_types") or []
        if "pricing" not in issue_types:
            issue_types.append("pricing")
            conds["issue_types"] = issue_types
            conn.execute(
                text("UPDATE response_strategies SET conditions = :conds WHERE id = :sid"),
                {"conds": json.dumps(conds), "sid": sid},
            )


def downgrade() -> None:
    conn = op.get_bind()
    for sid in TARGETS:
        row = conn.execute(
            text("SELECT conditions FROM response_strategies WHERE id = :sid"),
            {"sid": sid},
        ).fetchone()
        if not row or not row[0]:
            continue
        conds = row[0] if isinstance(row[0], dict) else json.loads(row[0])
        issue_types = [t for t in (conds.get("issue_types") or []) if t != "pricing"]
        conds["issue_types"] = issue_types
        conn.execute(
            text("UPDATE response_strategies SET conditions = :conds WHERE id = :sid"),
            {"conds": json.dumps(conds), "sid": sid},
        )

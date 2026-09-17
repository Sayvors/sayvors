"""dialects table + seed of the 23 Arabic dialects.

The catalog lives in the DB from here on (admin-managed via
POST/DELETE /api/v1/admin/dialects) — nothing reads hardcoded lists.

Revision ID: z1a2b3c4d5e6
Revises: y0z1a2b3c4d5
Create Date: 2026-09-17 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "z1a2b3c4d5e6"
down_revision: Union[str, None] = "y0z1a2b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SEED: list[tuple[str, str, str, list[str]]] = [
    ("egyptian", "Egyptian Arabic", "اللهجة المصرية", ["أهلاً", "إزيك؟"]),
    ("syrian", "Syrian Arabic", "اللهجة الشامية السورية", ["أهلاً", "شلونك؟"]),
    ("lebanese", "Lebanese Arabic", "اللهجة اللبنانية", ["أهلا", "كيفك؟"]),
    ("palestinian", "Palestinian Arabic", "اللهجة الفلسطينية", ["أهلاً", "كيفك؟"]),
    ("jordanian", "Jordanian Arabic", "اللهجة الأردنية", ["أهلاً وسهلاً", "كيفك؟"]),
    ("iraqi-baghdadi", "Baghdadi Iraqi Arabic", "اللهجة العراقية البغدادية", ["هلا", "شلونك؟"]),
    ("iraqi-southern", "Southern Iraqi Arabic", "اللهجة العراقية الجنوبية", ["هلا بيك", "شلونك؟"]),
    ("najdi", "Najdi Arabic", "اللهجة النجدية", ["هلا", "وشلونك؟"]),
    ("hejazi", "Hejazi Arabic", "اللهجة الحجازية", ["أهلاً", "كيفك؟"]),
    ("eastern-saudi", "Eastern Saudi Arabic", "اللهجة السعودية الشرقية", ["هلا", "شلونك؟"]),
    ("kuwaiti", "Kuwaiti Arabic", "اللهجة الكويتية", ["هلا", "شلونك؟"]),
    ("bahraini", "Bahraini Arabic", "اللهجة البحرينية", ["هلا", "شلونك؟"]),
    ("qatari", "Qatari Arabic", "اللهجة القطرية", ["هلا", "شلونك؟"]),
    ("emirati", "Emirati Arabic", "اللهجة الإماراتية", ["مرحبا", "شخبارك؟"]),
    ("omani", "Omani Arabic", "اللهجة العُمانية", ["هلا", "كيف حالك؟"]),
    ("yemeni-sanaani", "Sanaani Yemeni Arabic", "اللهجة اليمنية الصنعانية", ["هلا", "كيف حالك؟"]),
    ("yemeni-hadhrami", "Hadhrami Arabic", "اللهجة الحضرمية", ["مرحبا", "كيف حالك؟"]),
    ("sudanese", "Sudanese Arabic", "اللهجة السودانية", ["سلام", "كيفنك؟"]),
    ("libyan", "Libyan Arabic", "اللهجة الليبية", ["هلا", "شن حالك؟"]),
    ("tunisian", "Tunisian Arabic", "اللهجة التونسية", ["عسلامة", "شنوّة أحوالك؟"]),
    ("algerian", "Algerian Arabic", "اللهجة الجزائرية", ["سلام", "واش راك؟"]),
    ("moroccan", "Moroccan Arabic (Darija)", "اللهجة المغربية", ["سلام", "كيداير؟"]),
    ("hassaniya", "Hassaniya Arabic", "اللهجة الموريتانية الحسانية", ["السلام عليكم", "كيف حالك؟"]),
]


def upgrade() -> None:
    op.create_table(
        "dialects",
        sa.Column("code", sa.String(30), primary_key=True),
        sa.Column("dialect_en", sa.String(120), nullable=False),
        sa.Column("dialect_ar", sa.String(120), nullable=False),
        sa.Column("examples", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    dialects_table = sa.table(
        "dialects",
        sa.column("code", sa.String),
        sa.column("dialect_en", sa.String),
        sa.column("dialect_ar", sa.String),
        sa.column("examples", sa.JSON),
    )
    existing = {row[0] for row in op.get_bind().execute(sa.text("SELECT code FROM dialects"))}
    op.bulk_insert(
        dialects_table,
        [
            {"code": code, "dialect_en": en, "dialect_ar": ar, "examples": examples}
            for code, en, ar, examples in SEED
            if code not in existing
        ],
    )


def downgrade() -> None:
    op.drop_table("dialects")

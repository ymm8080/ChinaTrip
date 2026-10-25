"""双语 P1.6 补漏：restaurants.opening_hours_en（0014 漏加致 ORM 查询炸列）.

根因（2026-10-25 实测探针）：models.py 已声明 Restaurant.opening_hours_en，
但 0014 只给 pois 加列；DB 缺列导致夜作业 poi_en_nightly 跑完 pois 段后
restaurants 段 UndefinedColumn 中断（task1.docx 待查项）。

Revision ID: w12_0016
Revises: w12_0015
Create Date: 2026-10-25

"""

from collections.abc import Sequence

from alembic import op

revision: str = "w12_0016"
down_revision: str | None = "w12_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE restaurants ADD COLUMN opening_hours_en VARCHAR(500)")


def downgrade() -> None:
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS opening_hours_en")

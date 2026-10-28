"""双语 P1.6：pois.opening_hours_en（审计最后缺口：1841/1899 中文时长表述）.

卡片直接展示营业时间（"周一闭馆"类中文表述），EN 站混语言最后一处。
district 经查前端不展示，不加列；city 走前端字典（v1.4 决策）。

Revision ID: w12_0014
Revises: w12_0013
Create Date: 2026-10-25

"""

from collections.abc import Sequence

from alembic import op

revision: str = "w12_0014"
down_revision: str | None = "w12_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE pois ADD COLUMN opening_hours_en VARCHAR(500)")


def downgrade() -> None:
    op.execute("ALTER TABLE pois DROP COLUMN IF EXISTS opening_hours_en")

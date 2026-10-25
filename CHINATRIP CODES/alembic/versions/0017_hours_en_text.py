"""双语 P1.6 补漏2：opening_hours_en VARCHAR(500) → TEXT.

zh 源最长 ~400 字装得下 VARCHAR(500)，但英文翻译膨胀 2-3 倍——
网师园分季分时段表述译后 >500 字符触发 StringDataRightTruncation，
DataError 未捕获掀翻整个回填批次（task1.docx 待查项，2026-10-25 复现实锤）。
两表同步升 TEXT；zh 源列不动。

Revision ID: w12_0017
Revises: w12_0016
Create Date: 2026-10-25

"""

from collections.abc import Sequence

from alembic import op

revision: str = "w12_0017"
down_revision: str | None = "w12_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE pois ALTER COLUMN opening_hours_en TYPE TEXT")
    op.execute(
        "ALTER TABLE restaurants ALTER COLUMN opening_hours_en TYPE TEXT"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE restaurants ALTER COLUMN opening_hours_en TYPE VARCHAR(500)"
    )
    op.execute(
        "ALTER TABLE pois ALTER COLUMN opening_hours_en TYPE VARCHAR(500)"
    )

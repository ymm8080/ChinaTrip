"""v2.5 参考数据域: weather_reports 放开 kind 支持 14 天预报.

新增 Open-Meteo 源（kind=forecast14，14 天逐日预报；高德只给 3 天），
复用同表 latest-wins：每 (source, adcode, kind) 一行。保留行由抓取作业
按 fetched_at 清理（>7 天删除，用户口径：旧记录一周前删）。

Revision ID: w12_0008
Revises: w12_0007
Create Date: 2026-10-24

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "w12_0008"
down_revision: str | None = "w12_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE weather_reports DROP CONSTRAINT ck_weather_reports_kind")
    op.execute(
        """
        ALTER TABLE weather_reports ADD CONSTRAINT ck_weather_reports_kind
        CHECK (kind IN ('live','forecast','forecast14'))
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM weather_reports WHERE kind = 'forecast14'")
    op.execute("ALTER TABLE weather_reports DROP CONSTRAINT ck_weather_reports_kind")
    op.execute(
        """
        ALTER TABLE weather_reports ADD CONSTRAINT ck_weather_reports_kind
        CHECK (kind IN ('live','forecast'))
        """
    )

"""v2.5 参考数据域: weather_reports 城市天气快照表.

数据源高德天气 API（上游中国气象局），latest-wins——每
(source, adcode, kind) 仅存最新一行；report_time 为高德侧数据时间。
见 DESIGN/database_design.md §4.1 / §6.2 矩阵行。

Revision ID: w12_0007
Revises: w12_0006
Create Date: 2026-10-23

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "w12_0007"
down_revision: str | None = "w12_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE weather_reports (
            id UUID NOT NULL,
            source VARCHAR(20) NOT NULL,
            adcode VARCHAR(10) NOT NULL,
            city VARCHAR(50) NOT NULL,
            kind VARCHAR(10) NOT NULL,
            report_time TIMESTAMP,
            payload JSONB,
            fetched_at TIMESTAMP DEFAULT NOW(),
            CONSTRAINT pk_weather_reports PRIMARY KEY (id),
            CONSTRAINT uq_weather_reports_key UNIQUE (source, adcode, kind),
            CONSTRAINT ck_weather_reports_kind CHECK (kind IN ('live','forecast'))
        )
        """
    )
    op.execute("CREATE INDEX idx_weather_reports_city ON weather_reports (city)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_weather_reports_city")
    op.execute("DROP TABLE weather_reports")

"""班次表加英文字段（2026-11-16 用户「BETTER IN ENGLISH」）。

卡片与报表要能全英文呈现：景点英文名、线路英文名、上车点英文名。中文仍是
主键字段（与 pois.name_zh 对齐），英文只做展示与导出。

Revision ID: w12_0041
Revises: w12_0040
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "w12_0041"
down_revision: str | None = "w12_0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "poi_access_services", sa.Column("poi_name_en", sa.String(160), nullable=True)
    )
    op.add_column(
        "poi_access_services",
        sa.Column("service_name_en", sa.String(200), nullable=True),
    )
    op.add_column(
        "poi_access_services",
        sa.Column("boarding_stop_en", sa.String(160), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("poi_access_services", "boarding_stop_en")
    op.drop_column("poi_access_services", "service_name_en")
    op.drop_column("poi_access_services", "poi_name_en")

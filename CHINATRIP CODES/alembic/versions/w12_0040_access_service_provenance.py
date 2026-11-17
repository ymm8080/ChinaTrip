"""班次表按「事实」拆来源（2026-11-16 用户要求「ALL INFORMATION FROM OFFICIAL SITE」）。

现实：中文景区官网普遍只写「怎么来 + 票价」，不公布班次时刻（慕田峪那份官方 PDF
是少数例外）。混一列 `source` 会把「官方说的是线路」和「地图商给的是时刻」搅成
一锅。本迁移把来源拆开：

* ``official_url`` / ``official_status``：官方页地址与核实状态
  （``verified`` / ``pending`` / ``no_official_page``）；
* ``window_source``：首末班时刻来自哪里（``official`` / ``amap`` / ``baidu``）；
* ``fare_source``：票价来自哪里（同上）。

排期只信 ``window_source`` 有值的窗；``pending`` 的点在报表里单独列，等人工补。

Revision ID: w12_0040
Revises: w12_0039
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "w12_0040"
down_revision: str | None = "w12_0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "poi_access_services", sa.Column("official_url", sa.String(400), nullable=True)
    )
    op.add_column(
        "poi_access_services",
        sa.Column("official_status", sa.String(24), nullable=True),
    )
    op.add_column(
        "poi_access_services", sa.Column("window_source", sa.String(24), nullable=True)
    )
    op.add_column(
        "poi_access_services", sa.Column("fare_source", sa.String(24), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("poi_access_services", "fare_source")
    op.drop_column("poi_access_services", "window_source")
    op.drop_column("poi_access_services", "official_status")
    op.drop_column("poi_access_services", "official_url")

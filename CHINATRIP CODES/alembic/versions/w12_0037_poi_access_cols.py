"""POI 到达方式列（2026-11-15 用户拍板「远郊景点要有交通方式」）。

背景：规划器市内腿一律按打车模型（rules.taxi_leg_min 70km/h + 15 分钟叫车），
慕田峪 59km 被算成 81 分钟；实际公交是「景区直达车前门线 2 小时出头、末班
12:00」。候选池里 >25km 的观光件北京 61/199、成都 60/142、杭州 87/200，
不是个别点的手工补丁，需要一层可回填、可展示的到达方式数据。

口径（为什么是摘要列而不是单列自由文本）：
* 一个点有多种方案（地铁/公交/景区专线/铁路），单列装不下，引擎也读不了；
* 有班次的方案（景区直达车、市郊铁路）首末班直接决定当天能不能去；
* 数据可算——高德/百度 transit 链已在本仓（api/navigation.transit），
  以城心为起点回填最快方案，落成本组摘要列，手工只兜底例外点。

列：
* access_mode            出行方式（metro/bus/train/shuttle/ferry/walk）
* access_minutes         城心 → POI 门到门参考分钟（含步行与换乘）
* access_gateway         最后一段车的下车站（火车/专线不落在景区门口）
* access_gateway_minutes 下车后步行分钟
* access_note / _en      一句人话（含首末班）
* access_source          落地图商（baidu/amap）+ 通道（-transit/manual）
* access_updated_at      回填时间（只填空闸的判据；NULL = 未回填）

Revision ID: w12_0037
Revises: w12_0036
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "w12_0037"
down_revision: str | None = "w12_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("pois", sa.Column("access_mode", sa.String(16), nullable=True))
    op.add_column("pois", sa.Column("access_minutes", sa.Integer(), nullable=True))
    op.add_column("pois", sa.Column("access_gateway", sa.String(100), nullable=True))
    op.add_column(
        "pois", sa.Column("access_gateway_minutes", sa.Integer(), nullable=True)
    )
    op.add_column("pois", sa.Column("access_note", sa.String(300), nullable=True))
    op.add_column("pois", sa.Column("access_note_en", sa.String(300), nullable=True))
    op.add_column("pois", sa.Column("access_source", sa.String(20), nullable=True))
    op.add_column("pois", sa.Column("access_updated_at", sa.TIMESTAMP(), nullable=True))


def downgrade() -> None:
    for column in (
        "access_updated_at",
        "access_source",
        "access_note_en",
        "access_note",
        "access_gateway_minutes",
        "access_gateway",
        "access_minutes",
        "access_mode",
    ):
        op.drop_column("pois", column)

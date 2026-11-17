"""远郊景区专线班次表（2026-11-16 用户拍板）。

「远郊景区专线，无论火车还是直达巴士，需要先搜网络或者高德地图数据拿到接驳的
出发地点和时刻表、路途时间、到达时间、回程出发时间、回城到达时间、票价、购票
渠道，然后存入远郊景点交通 DATABASE。每次运行 PLANNING 时候只需要加上 HOTEL
到接驳出发点的 TAXI 腿。」

设计取舍：

* ``pois.access_*``（w12_0037/0038）是「一句话摘要 + 一段接驳链均值」，够卡片
  展示和粗略排期，但没有**时刻表**，也不知道末班几点——引擎会把慕田峪排到
  14:54（末班 12:00 早收车）。
* 本表按「一条线路一行」存班次：去程/回程各自的发车时刻（显式列表，缺则用
  首末班 + 流水间隔）、车上分钟、到达时刻、票价、购票渠道与来源。
* 排期时只需要记住一件事：**酒店 → 上车点**这段打车，其余（候车/车上/落客）
  由时刻表决定。所以表的重点是 ``boarding_*`` + ``depart_*`` + ``ride_minutes``。

Revision ID: w12_0039
Revises: w12_0038
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "w12_0039"
down_revision: str | None = "w12_0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "poi_access_services",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("city", sa.String(40), nullable=False, index=True),
        sa.Column("poi_name", sa.String(120), nullable=False, index=True),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("service_name", sa.String(160), nullable=False),
        sa.Column("operator", sa.String(120), nullable=True),
        sa.Column("boarding_stop", sa.String(120), nullable=True),
        sa.Column("boarding_lon", sa.Numeric(9, 6), nullable=True),
        sa.Column("boarding_lat", sa.Numeric(9, 6), nullable=True),
        sa.Column("alight_stop", sa.String(120), nullable=True),
        sa.Column("alight_lon", sa.Numeric(9, 6), nullable=True),
        sa.Column("alight_lat", sa.Numeric(9, 6), nullable=True),
        sa.Column("outbound_times", postgresql.JSONB(), nullable=True),
        sa.Column("outbound_first", sa.String(5), nullable=True),
        sa.Column("outbound_last", sa.String(5), nullable=True),
        sa.Column("outbound_frequency_minutes", sa.Integer(), nullable=True),
        sa.Column("ride_minutes", sa.Integer(), nullable=True),
        sa.Column("return_times", postgresql.JSONB(), nullable=True),
        sa.Column("return_first", sa.String(5), nullable=True),
        sa.Column("return_last", sa.String(5), nullable=True),
        sa.Column("return_frequency_minutes", sa.Integer(), nullable=True),
        sa.Column("return_ride_minutes", sa.Integer(), nullable=True),
        sa.Column("return_arrive_last", sa.String(5), nullable=True),
        sa.Column("fare_cny", sa.Numeric(8, 2), nullable=True),
        sa.Column("fare_kind", sa.String(24), nullable=True),
        sa.Column("fare_note", sa.String(200), nullable=True),
        sa.Column("ticket_channel", sa.String(120), nullable=True),
        sa.Column("ticket_url", sa.String(400), nullable=True),
        sa.Column("last_mile_minutes", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(400), nullable=True),
        sa.Column("note_en", sa.String(400), nullable=True),
        sa.Column("source", sa.String(40), nullable=True),
        sa.Column("source_url", sa.String(400), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=True),
        sa.Column(
            "active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "city", "poi_name", "service_name", name="uq_access_service_line"
        ),
    )


def downgrade() -> None:
    op.drop_table("poi_access_services")

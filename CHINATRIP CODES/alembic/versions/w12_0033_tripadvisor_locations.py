r"""TripAdvisor (Terra) 地点详情原始镜像表（2026-11-14 定调）。

背景：1000 次免费配额 = 1000 次 GET /locations/{id}（默认 locale 全英文）。
与 w12_0032 的 pois.ta_* 提取列并存——本表是原始镜像：

* payload：整条 API 响应 JSONB 留档（与 trip_items.payload 同惯例），
  含未提列字段（names/descriptions/addresses 全数组、urls 全部子链接、
  opening_hours.periods 结构化、traveler_ratings.breakdowns 分档、
  language_counts 评论语言分布等）；
* 提取列：常用字段的查询友好投影；
* location_id（TA 地点 ID）自然主键，poi_id 反向引用 pois（可空）。

纯镜像表——规划侧只读 pois.ta_*，本表不回填任何主列。

Revision ID: w12_0033
Revises: w12_0032
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "w12_0033"
down_revision: str | None = "w12_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tripadvisor_locations",
        # TA 地点 ID（公开 URL d(\d+)，如故宫 319086）——自然主键
        sa.Column("location_id", sa.BigInteger(), primary_key=True),
        # 反向映射：已归属的 POI（未映射为 NULL）
        sa.Column("poi_id", UUID(as_uuid=True), sa.ForeignKey("pois.id"), nullable=True),
        # 整条 API 响应留档
        sa.Column("payload", JSONB(), nullable=False),
        # --- 提取列（payload 的查询友好投影） ---------------------------
        sa.Column("geo_id", sa.BigInteger(), nullable=True),
        sa.Column("geo", sa.String(100), nullable=True),
        sa.Column("status", sa.String(20), nullable=True),
        sa.Column("name_en", sa.String(200), nullable=True),
        sa.Column("intro_en", sa.Text(), nullable=True),
        sa.Column("address_en", sa.Text(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("website_official", sa.String(300), nullable=True),
        sa.Column("rating", sa.Numeric(3, 1), nullable=True),
        sa.Column("rating_count", sa.Integer(), nullable=True),
        sa.Column("photos_total_count", sa.Integer(), nullable=True),
        sa.Column("opening_hours_formatted", sa.String(500), nullable=True),
        # TA 原始值（单位：小时）；换算分钟在读取侧做
        sa.Column("recommended_visit_length", sa.Integer(), nullable=True),
        sa.Column("fetched_at", sa.TIMESTAMP(), nullable=True),
        sa.Column(
            "updated_at", sa.TIMESTAMP(), server_default=sa.text("NOW()")
        ),
    )
    op.create_index("idx_ta_locations_poi", "tripadvisor_locations", ["poi_id"])
    op.create_index("idx_ta_locations_geo", "tripadvisor_locations", ["geo_id"])


def downgrade() -> None:
    op.drop_index("idx_ta_locations_geo", table_name="tripadvisor_locations")
    op.drop_index("idx_ta_locations_poi", table_name="tripadvisor_locations")
    op.drop_table("tripadvisor_locations")

r"""TripAdvisor (Terra) 富化列（2026-11-14 定调）。

背景：1000 次免费配额 = 1000 次 GET /locations/{id} 详情调用，一次拿全
一个地点的 TA 反馈（地址/坐标/营业时间/评分/英文简介/建议时长）。
名称 → ta_location_id 的映射走免费通道（搜索引擎解析公开 URL 的 d(\d+)，
已用故宫 d319086 验证），配额全部留给详情拉取。

只填空铁律不变：ta_* 列是外部源镜像，时间敏感字段（hours/price/duration）
真相仍归高德/携程回源链——ta_opening_hours / ta_suggested_duration_min 只做
校验/补空/展示参考，绝不回写主列（opening_hours / suggested_duration_min）。
ta_rating 与主 rating 分列（rating_source 继续标高德），避免互踩。
ta_intro_en 为 TA 英文简介镜像（默认 locale，2026-11-14 定调 TA 数据
全取英文——默认调用一次拿全套，中文不取），intro_en 按只填空约定
可从它补空（intro_source='tripadvisor'），intro 中文真相不碰。

Revision ID: w12_0032
Revises: w12_0031
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "w12_0032"
down_revision: str | None = "w12_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- TripAdvisor (Terra) 外部源镜像列（全部只填空） ------------------
    # 映射：ID；ta_fetched_at 是配额记账键
    op.add_column("pois", sa.Column("ta_location_id", sa.String(20), nullable=True))
    op.add_column("pois", sa.Column("ta_geo_id", sa.String(20), nullable=True))
    op.add_column("pois", sa.Column("ta_fetched_at", sa.TIMESTAMP(), nullable=True))

    # 详情反馈镜像：TA 侧自己的评分/时长分列存放，不碰高德真相主列
    op.add_column("pois", sa.Column("ta_status", sa.String(20), nullable=True))
    op.add_column("pois", sa.Column("ta_url", sa.String(500), nullable=True))
    op.add_column(
        "pois", sa.Column("ta_rating", sa.Numeric(3, 1), nullable=True)
    )  # TA 总评（0.0–5.0）
    op.add_column("pois", sa.Column("ta_opening_hours", sa.String(500), nullable=True))
    op.add_column(
        "pois", sa.Column("ta_suggested_duration_min", sa.Integer(), nullable=True)
    )
    # TA 英文简介（descriptions[].value，默认 locale）——intro_en 补空源
    op.add_column("pois", sa.Column("ta_intro_en", sa.Text(), nullable=True))

    # 按 TA ID 反查 POI（补数据/核对时用）；非唯一——映射期允许暂时撞行
    op.create_index("idx_pois_ta_location_id", "pois", ["ta_location_id"])


def downgrade() -> None:
    op.drop_index("idx_pois_ta_location_id", table_name="pois")
    for column in (
        "ta_intro_en",
        "ta_suggested_duration_min",
        "ta_opening_hours",
        "ta_rating",
        "ta_url",
        "ta_status",
        "ta_fetched_at",
        "ta_geo_id",
        "ta_location_id",
    ):
        op.drop_column("pois", column)

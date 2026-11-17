r"""restaurants 表 TripAdvisor (Terra) 富化列（2026-11-14，w12_0034）。

与 w12_0032 的 pois.ta_* 完全同款（9 列，只填空）：餐厅独立底库
（v2.5 用户拍板）与 pois 同批走猫途鹰免费映射（阶段 A）+ 详情拉取
（阶段 B）。ta_* 列语义见 w12_0032 docstring；时间敏感字段真相仍归
高德/携程回源链，ta_rating / ta_opening_hours 只做校验/补空。

Revision ID: w12_0034
Revises: w12_0033
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "w12_0034"
down_revision: str | None = "w12_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "restaurants", sa.Column("ta_location_id", sa.String(20), nullable=True)
    )
    op.add_column("restaurants", sa.Column("ta_geo_id", sa.String(20), nullable=True))
    op.add_column("restaurants", sa.Column("ta_status", sa.String(20), nullable=True))
    op.add_column("restaurants", sa.Column("ta_url", sa.String(500), nullable=True))
    op.add_column(
        "restaurants", sa.Column("ta_rating", sa.Numeric(3, 1), nullable=True)
    )
    op.add_column("restaurants", sa.Column("ta_intro_en", sa.Text(), nullable=True))
    op.add_column(
        "restaurants", sa.Column("ta_opening_hours", sa.String(500), nullable=True)
    )
    op.add_column(
        "restaurants",
        sa.Column("ta_suggested_duration_min", sa.Integer(), nullable=True),
    )
    op.add_column(
        "restaurants", sa.Column("ta_fetched_at", sa.TIMESTAMP(), nullable=True)
    )
    op.create_index(
        "idx_restaurants_ta_location_id", "restaurants", ["ta_location_id"]
    )


def downgrade() -> None:
    op.drop_index("idx_restaurants_ta_location_id", table_name="restaurants")
    for column in (
        "ta_fetched_at",
        "ta_suggested_duration_min",
        "ta_opening_hours",
        "ta_intro_en",
        "ta_rating",
        "ta_url",
        "ta_status",
        "ta_geo_id",
        "ta_location_id",
    ):
        op.drop_column("restaurants", column)

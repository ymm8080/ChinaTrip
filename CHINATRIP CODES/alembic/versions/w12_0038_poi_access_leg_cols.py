"""POI 接驳腿列（2026-11-15 用户拍板「一般是 TAXI + 引擎接驳腿」）。

w12_0037 只存了摘要（方式/总时长/落客站/一句话），够卡片展示但引擎算不出
接驳链。用户口径：市内腿默认仍按打车模型，命中「有班次的接驳」（景区专线 /
市郊铁路 / 轮渡）时改走接驳链 = 打车到乘车点 → 候车 → 班次 → 落客接驳。

需要的量（本迁移补列）：
* access_boarding / _lon / _lat —— 首段乘车点（打车终点）
* access_service_minutes —— 车上分钟（各段乘车时长和）
* access_wait_minutes —— 候车/换乘分钟（总时长 − 车上 − 步行）
* access_last_mile_minutes —— 落客点到景区门口（可步行=步行，否则打车估算）

Revision ID: w12_0038
Revises: w12_0037
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "w12_0038"
down_revision: str | None = "w12_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("pois", sa.Column("access_boarding", sa.String(100), nullable=True))
    op.add_column("pois", sa.Column("access_boarding_lon", sa.Numeric(9, 6), nullable=True))
    op.add_column("pois", sa.Column("access_boarding_lat", sa.Numeric(9, 6), nullable=True))
    op.add_column(
        "pois", sa.Column("access_service_minutes", sa.Integer(), nullable=True)
    )
    op.add_column("pois", sa.Column("access_wait_minutes", sa.Integer(), nullable=True))
    op.add_column(
        "pois", sa.Column("access_last_mile_minutes", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    for column in (
        "access_last_mile_minutes",
        "access_wait_minutes",
        "access_service_minutes",
        "access_boarding_lat",
        "access_boarding_lon",
        "access_boarding",
    ):
        op.drop_column("pois", column)

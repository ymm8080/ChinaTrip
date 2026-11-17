"""用户可选二级标签 P2：pois 加 user_family / user_groups 推导列。

DESIGN user_tag_two_level_2026-11-10 §一：7 一级（family）× 25 二级
（group）受控词表，供用户选择器勾选查询。映射唯一来源
app/services/poi_tag_selector.classify_poi（规则级联 + review 粗词碰撞
消解）；两列由 app/jobs/backfill_poi_user_tags.py 只填空回填；
hotel/food/transport/category=None 服务类行恒空。原始 category/tags/
review_tags 列不动，查询层只用 family/groups。

Revision ID: w12_0022
Revises: w12_0021
Create Date: 2026-11-12

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "w12_0022"
down_revision: str | None = "w12_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pois", sa.Column("user_family", sa.String(50), nullable=True)
    )
    op.add_column(
        "pois",
        sa.Column("user_groups", JSONB(none_as_null=True), nullable=True),
    )
    op.create_index("idx_pois_user_family", "pois", ["user_family"])


def downgrade() -> None:
    op.drop_index("idx_pois_user_family", table_name="pois")
    op.drop_column("pois", "user_groups")
    op.drop_column("pois", "user_family")

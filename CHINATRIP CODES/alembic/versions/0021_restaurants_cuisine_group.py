"""用户可选二级标签 P1：restaurants 加 cuisine_family / cuisine_group 推导列。

DESIGN user_tag_two_level_2026-11-10 §二：库内 cuisine 575 个原值
（中英混杂）→ 6 组（family）× 21 组（group）受控词表，供用户选择器
勾选查询。原值列不动（回源链还会写英文）；两列由
app/services/cuisine_taxonomy.classify_cuisine 推导回填
（app/jobs/backfill_cuisine_group.py），查询层只用 group/family。

Revision ID: w12_0021
Revises: w12_0020
Create Date: 2026-11-11

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "w12_0021"
down_revision: str | None = "w12_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "restaurants",
        sa.Column("cuisine_family", sa.String(50), nullable=True),
    )
    op.add_column(
        "restaurants",
        sa.Column("cuisine_group", sa.String(50), nullable=True),
    )
    op.create_index(
        "idx_restaurants_cuisine_group", "restaurants", ["cuisine_group"]
    )


def downgrade() -> None:
    op.drop_index("idx_restaurants_cuisine_group", table_name="restaurants")
    op.drop_column("restaurants", "cuisine_group")
    op.drop_column("restaurants", "cuisine_family")

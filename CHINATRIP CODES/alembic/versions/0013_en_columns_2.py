"""双语 P1.5：补齐 EN 展示列（review_summary/cuisine/招牌菜/餐厅标签）.

用户指出英文存储缺口后补齐（2026-10-25）：
  pois +1：review_summary_en（口碑摘要，中文版已 423 条）
  restaurants +3：review_tags_en（与 pois 对称）/ cuisine_en（菜系）/
    signature_dishes_en（招牌菜 JSONB 数组）
city 名不加列——小集合走前端 i18n 字典（language_dual_system §6）。

Revision ID: w12_0013
Revises: w12_0012
Create Date: 2026-10-25

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "w12_0013"
down_revision: str | None = "w12_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE pois ADD COLUMN review_summary_en TEXT")
    op.execute("ALTER TABLE restaurants ADD COLUMN review_tags_en JSONB")
    op.execute("ALTER TABLE restaurants ADD COLUMN cuisine_en VARCHAR(50)")
    op.execute("ALTER TABLE restaurants ADD COLUMN signature_dishes_en JSONB")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE restaurants DROP COLUMN IF EXISTS signature_dishes_en"
    )
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS cuisine_en")
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS review_tags_en")
    op.execute("ALTER TABLE pois DROP COLUMN IF EXISTS review_summary_en")

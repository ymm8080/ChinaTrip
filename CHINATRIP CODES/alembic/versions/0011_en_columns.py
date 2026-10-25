"""双语 P1：pois/restaurants 加 _en 列（DESIGN language_dual_system v1.0 §5.2）.

pois +3：intro_en / address_en / review_tags_en；
restaurants +2：intro_en / address_en。
（pois.name_en / restaurants.name_en 既有，不加。）
语义约定：*_en 只填空不覆盖（翻译 backfill 作业铁律）；NULL 时
前端回退中文，翻译未跑完功能完整可用。review_tags_en 与 review_tags
同型 JSONB（英文标签数组）。

Revision ID: w12_0011
Revises: w12_0010
Create Date: 2026-10-25

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "w12_0011"
down_revision: str | None = "w12_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE pois ADD COLUMN intro_en TEXT")
    op.execute("ALTER TABLE pois ADD COLUMN address_en VARCHAR(200)")
    op.execute("ALTER TABLE pois ADD COLUMN review_tags_en JSONB")
    op.execute("ALTER TABLE restaurants ADD COLUMN intro_en TEXT")
    op.execute("ALTER TABLE restaurants ADD COLUMN address_en VARCHAR(200)")


def downgrade() -> None:
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS address_en")
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS intro_en")
    op.execute("ALTER TABLE pois DROP COLUMN IF EXISTS review_tags_en")
    op.execute("ALTER TABLE pois DROP COLUMN IF EXISTS address_en")
    op.execute("ALTER TABLE pois DROP COLUMN IF EXISTS intro_en")

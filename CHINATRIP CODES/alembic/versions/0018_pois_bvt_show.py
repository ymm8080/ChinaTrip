"""演出预订 P0：pois.best_visit_time 枚举扩入 'show'（S5 晚间场演档）。

show_booking_design_2026-10-26 S5：场演（category=entertainment）走专属
晚间档（20:10–20:45 开演，可越过 21:00 日终）——若沿用 'evening' 会被
_BEST_VISIT_WINDOWS 的日终钳制算成不可行。库上 ck_pois_best_visit_time
枚举只认 sunrise/morning/afternoon/evening/sunset/any，import_shows 写
'show' 触发 CheckViolation（2026-10-27 实测），故扩枚举。

Revision ID: w12_0018
Revises: w12_0017
Create Date: 2026-10-27

"""

from collections.abc import Sequence

from alembic import op

revision: str = "w12_0018"
down_revision: str | None = "w12_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENUM_WITH_SHOW = (
    "ARRAY['sunrise','morning','afternoon','evening','sunset','any','show']"
)
_ENUM_WITHOUT_SHOW = "ARRAY['sunrise','morning','afternoon','evening','sunset','any']"


def upgrade() -> None:
    op.execute("ALTER TABLE pois DROP CONSTRAINT ck_pois_best_visit_time")
    op.execute(
        "ALTER TABLE pois ADD CONSTRAINT ck_pois_best_visit_time "
        f"CHECK (best_visit_time::text = ANY ({_ENUM_WITH_SHOW}::text[]))"
    )


def downgrade() -> None:
    # 库内已有 'show' 行时此步会报错——先清档再降级，属预期保护。
    op.execute("ALTER TABLE pois DROP CONSTRAINT ck_pois_best_visit_time")
    op.execute(
        "ALTER TABLE pois ADD CONSTRAINT ck_pois_best_visit_time "
        f"CHECK (best_visit_time::text = ANY ({_ENUM_WITHOUT_SHOW}::text[]))"
    )

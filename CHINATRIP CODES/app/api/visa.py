"""240h 过境免签行程校验端点（DESIGN §14.3-G2）。

GET /api/v1/visa/240h?cities=上海,杭州&entry_date=2026-11-01&exit_date=2026-11-08
确定性纯函数（visa_check.py），零 LLM 零外呼——行程页绿/红横幅数据源。
"""

from fastapi import APIRouter

from app.services.itinerary.visa_check import check_240h_transit

router = APIRouter(prefix="/api/v1/visa", tags=["visa"])


@router.get("/240h")
async def check_240h(
    cities: str,
    entry_date: str | None = None,
    exit_date: str | None = None,
    entry_port: str | None = None,
    exit_port: str | None = None,
) -> dict:
    city_list = [c.strip() for c in (cities or "").split(",") if c.strip()]
    result = check_240h_transit(
        city_list,
        entry_date=entry_date,
        exit_date=exit_date,
        entry_port=entry_port,
        exit_port=exit_port,
    )
    return result.model_dump()

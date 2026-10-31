# -*- coding: utf-8 -*-
"""图商链执行器（2026-10-30 导航页接链）。

run_vendor_chain 依次尝试链上客户端：任一家成功即返回其结果；配额死
（AmapQuotaExhaustedError）写入按日 latch（vendor -> ISO 日期），当日不再
重试、次日键变更自动过期重探；超时/网络/业务错记录后跳下一家；全灭返回
最后一个异常（空链返回 None），调用方按异常类型映射 504/502。

导航 walking/transit 与 amap poi/search、regeo 端点共用本执行器——语义与
规划器 PlanningAgent._search_poi 的逐家 latch 一致。
"""

import logging
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

from app.services.amap_client import (
    AmapError,
    AmapQuotaExhaustedError,
    AmapTimeoutError,
)

logger = logging.getLogger(__name__)


def _today() -> str:
    return date.today().isoformat()


async def run_vendor_chain(
    chain: list[Any],
    run: Callable[[Any], Awaitable[Any]],
    *,
    latch: dict[str, str],
    function: str,
) -> Any:
    """逐家尝试：成功即返；配额死按日 latch；其余异常跳过；全灭回最后异常。"""
    last: Exception | None = None
    for client in chain:
        vendor = getattr(client, "vendor", "amap")
        if latch.get(vendor) == _today():
            continue
        try:
            return await run(client)
        except AmapQuotaExhaustedError as exc:
            latch[vendor] = _today()
            last = exc
            logger.warning(
                "vendor_chain: %s %s quota exhausted, latched for today",
                function,
                vendor,
            )
        except AmapTimeoutError as exc:
            last = exc
            logger.warning(
                "vendor_chain: %s %s timed out, trying next", function, vendor
            )
        except AmapError as exc:
            last = exc
            logger.warning("vendor_chain: %s %s failed: %s", function, vendor, exc)
        except Exception as exc:  # 防御：单家崩溃不拖垮整链
            last = exc
            logger.warning(
                "vendor_chain: %s %s unexpected failure",
                function,
                vendor,
                exc_info=True,
            )
    return last

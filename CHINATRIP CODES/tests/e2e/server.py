"""E2E 专用服务进程：真实 app + 真实静态页 + 真实 DB/求解器，只有 LLM 是确定性桩。

为什么单独起进程而不是 TestClient：E2E 要验的正是「浏览器里跑起来的产品」——
真实 uvicorn（真实中间件、真实 /h5 静态资源、真实 Service Worker）、真实 sqlite
状态库、真实行程求解器。TestClient 在进程内绕过了这些。

唯一被替换的是 LLM：它是要付钱、会 429、回复不定的外部依赖，E2E 里换成固定
JSON（单测一直这么做）。要跑「真模型」版本见 README 的 E2E_LLM=live。

启动：python tests/e2e/server.py   （端口读 E2E_PORT，默认 8010）
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# —— 必须在 import app.* 之前落环境：Settings 是 pydantic-settings，env 覆盖 .env ——
os.environ.setdefault("E2E_PORT", "8010")
# 独立状态库：E2E 别写坏真实 h5_state.db
os.environ.setdefault("STATE_DB_URL", "sqlite:///data/e2e_state.db")
# 关掉图商：真实 AMAP key 会让 E2E 半秒变半分钟，并在配额耗尽时随机失败。
# 空 key ⇒ map_ready()=False ⇒ 走 DB POI，路线仍能出（生产降级路径同样覆盖）。
os.environ["AMAP_API_KEY"] = ""
os.environ["TENCENT_MAP_KEY"] = ""
os.environ["BAIDU_AK"] = ""
# 求解器与线上一致
os.environ.setdefault("TRIP_SOLVER", "cpsat")
# 限流关掉：E2E 一轮会连打几十个请求，别自己把自己 429
os.environ["RATE_LIMIT_PER_MINUTE"] = "10000"
os.environ["RATE_LIMIT_PER_HOUR"] = "100000"

from app.services.llm.base import (  # noqa: E402
    ChatMessage,
    ChatResult,
    ExtractResult,
    POICandidate,
)

# 一个回复同时满足规划（items）、编辑轮（reply/diffs）、澄清（need_clarification）
# 三种解析契约——各解析器只取自己认识的键，多余键无副作用。
_DETERMINISTIC_REPLY = json.dumps(
    {
        "items": [
            {
                "name": "西湖",
                "city": "杭州",
                "category": "sight",
                "day": 1,
                "duration_minutes": 75,
            },
            {
                "name": "雷峰塔",
                "city": "杭州",
                "category": "sight",
                "day": 2,
                "duration_minutes": 60,
            },
        ],
        "reply": "已按你的要求更新行程",
        "diffs": [],
        "need_clarification": [],
        "assumptions": [],
    },
    ensure_ascii=False,
)


class DeterministicLLM:
    """零网络、恒定回复；记录调用次数供用例断言（可选）。"""

    name = "e2e-deterministic"

    def __init__(self) -> None:
        self.calls = 0

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> ChatResult:
        self.calls += 1
        return ChatResult(content=_DETERMINISTIC_REPLY, model=self.name)

    async def extract(self, text: str, *, lang: str = "zh") -> ExtractResult:
        self.calls += 1
        return ExtractResult(
            candidates=[POICandidate(name="西湖", city="杭州", confidence=0.9)],
            assumptions=[],
            model=self.name,
        )


_llm = DeterministicLLM()

# E2E_LLM=live → 不替换，用 .env 里配的真模型（慢、要配额，只在需要验
# 「真模型下也走得通」时用）。默认 stub：E2E 不该因为 429 变红。
_USE_LIVE_LLM = os.environ.get("E2E_LLM", "stub").lower() == "live"

if not _USE_LIVE_LLM:
    # plan.py 在 import 时把工厂函数取进了自己的命名空间，所以要按模块属性替换。
    import app.api.plan as plan_api  # noqa: E402

    plan_api.get_llm_adapter = lambda _settings: _llm
    plan_api.get_flash_adapter = lambda _settings: _llm

    # 其它模块若直接 import 工厂，也一并替换
    import app.services.llm as llm_pkg  # noqa: E402

    llm_pkg.get_llm_adapter = lambda _settings: _llm
    llm_pkg.get_flash_adapter = lambda _settings: _llm

from app.main import app  # noqa: E402  （module-level 单例，含全部路由与 /h5 挂载）


def main() -> None:
    import uvicorn

    port = int(os.environ.get("E2E_PORT", "8010"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()

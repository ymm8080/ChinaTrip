"""候选池坐标闸回归（2026-10-30 修复「两个 SITE 间距离/步行不显示」）。

无坐标骨架行（5A/amap/show 骨架；西安、三亚等非十城池整库无坐标）此前
按 tier 排序顶进候选并选进行程：annotate_legs 对 loc=None 条目整对跳过 →
卡片「距下一站 X km · 步行约 Y 分钟」消失，导航外链也没坐标。规划库候选
必须带坐标；滤空的城市落既有 <10 高德补量/占位降级。
"""

import asyncio

from app.services.agent.plan import PlanningAgent
from app.services.poi_details import PoiDetailStore


def run(coro):
    return asyncio.run(coro)


class NoLLM:
    """候选闸不需要 LLM；任何调用都是测试哨兵。"""

    name = "no-llm"

    async def chat(self, messages, *, temperature: float = 0.3, max_tokens=None):
        raise AssertionError("candidate gate must not call the LLM")


class RemoteAmap:
    """图商检索桩（带坐标，baidu/amap 出参同构）。"""

    def __init__(self, pois_by_city):
        self.pois_by_city = pois_by_city
        self.calls = []

    async def search_poi(self, keywords, *, city=None, page=1):
        self.calls.append(city)
        return self.pois_by_city.get(city, [])


def _mixed_store() -> PoiDetailStore:
    store = PoiDetailStore()
    # 骨架行：有名字无坐标（5A/show 导入常态）
    store.upsert("S1", city="西安", name="秦始皇兵马俑博物馆", category="attraction")
    store.upsert("S2", city="西安", name="大雁塔", category="attraction")
    # 有坐标行：必须保留
    store.upsert(
        "R1",
        city="西安",
        name="回民街",
        category="attraction",
        location=(108.94, 34.26),
    )
    return store


def test_library_candidates_without_location_are_dropped():
    agent = PlanningAgent(NoLLM(), amap_client=None, poi_details=_mixed_store())
    candidates, _ = run(agent._collect_candidates(["西安"]))
    names = {c["name"] for c in candidates}
    assert "回民街" in names
    assert "秦始皇兵马俑博物馆" not in names
    assert "大雁塔" not in names
    assert all(c["location"] for c in candidates)


def test_skeleton_only_city_falls_through_to_map_candidates():
    store = PoiDetailStore()
    store.upsert("S1", city="三亚", name="南山文化旅游区", category="attraction")
    remote = RemoteAmap(
        {
            "三亚": [
                {
                    "name": "亚龙湾",
                    "location": {"lon": 109.65, "lat": 18.26},
                    "city": "三亚",
                },
                {
                    "name": "天涯海角",
                    "location": {"lon": 109.11, "lat": 18.29},
                    "city": "三亚",
                },
            ]
        }
    )
    agent = PlanningAgent(NoLLM(), amap_client=remote, poi_details=store)
    candidates, _ = run(agent._collect_candidates(["三亚"]))
    assert remote.calls == ["三亚"]  # 库候选滤空 → 触发既有 <10 补量
    names = {c["name"] for c in candidates}
    assert {"亚龙湾", "天涯海角"} <= names
    assert all(c["location"] for c in candidates)


def test_search_chain_quota_latch_at_candidate_fill():
    """检索链：首家配额死 latch 到下一家；死家不再被撞（2026-10-30）。"""
    from app.services.amap_client import AmapQuotaExhaustedError

    class QuotaVendor:
        vendor = "first"

        def __init__(self):
            self.calls = 0

        async def search_poi(self, keywords, *, city=None, page=1):
            self.calls += 1
            raise AmapQuotaExhaustedError("quota", "121")

    ok = RemoteAmap(
        {
            "北京": [
                {
                    "name": "故宫",
                    "location": {"lon": 116.39, "lat": 39.91},
                    "city": "北京",
                }
            ]
        }
    )
    ok.vendor = "second"
    agent = PlanningAgent(
        NoLLM(),
        amap_client=None,
        poi_details=PoiDetailStore(),
        search_chain=[QuotaVendor(), ok],
    )
    candidates, _ = run(agent._collect_candidates(["北京"]))
    names = {c["name"] for c in candidates}
    assert "故宫" in names
    assert all(c["location"] for c in candidates)
    assert agent._search_chain[0].calls == 1  # 只撞一次，后续行不再试死家


def test_amap_remote_results_without_location_are_dropped_too():
    """图商补量偶发无坐标（配额熔断壳/异常壳）同样不得入池。"""
    store = PoiDetailStore()
    remote = RemoteAmap(
        {
            "北京": [
                {"name": "坏行", "location": None, "city": "北京"},
                {
                    "name": "好行",
                    "location": {"lon": 116.40, "lat": 39.90},
                    "city": "北京",
                },
            ]
        }
    )
    agent = PlanningAgent(NoLLM(), amap_client=remote, poi_details=store)
    candidates, _ = run(agent._collect_candidates(["北京"]))
    names = {c["name"] for c in candidates}
    assert "好行" in names
    assert "坏行" not in names

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


# --- 2026-10-30 day4 单点事故：坐标闸先于 30 行窗口截断 --------------------


class _DeepStore:
    """库桩：tier 序把 40 行无坐标骨架顶到前排，有坐标行排在 30 名外。"""

    def __init__(self):
        self.calls: list[tuple[str, int]] = []

    def top_pois_in_city(self, city, limit, *, exclude_food=True):
        self.calls.append((city, limit))
        rows = [
            {
                "name": f"骨架{i:02d}",
                "city": city,
                "category": "attraction",
                "location": None,
            }
            for i in range(40)
        ]
        rows += [
            {
                "name": f"真点{i}",
                "city": city,
                "category": "attraction",
                "location": (104.0 + i * 0.01, 30.6),
            }
            for i in range(5)
        ]
        return rows[:limit]


def test_library_window_cuts_after_location_gate():
    """深取后先滤坐标再截窗：30 名外的有坐标行仍能入池（重庆 top30 滤后
    只剩 3 个可用候选、每天 1 点的根因）。"""
    store = _DeepStore()
    agent = PlanningAgent(NoLLM(), amap_client=None, poi_details=store)
    candidates, _ = run(agent._collect_candidates(["成都"]))
    names = {c["name"] for c in candidates}
    assert names == {f"真点{i}" for i in range(5)}
    assert store.calls and store.calls[0][1] > 30  # 深取，不是直取 30


def test_origin_closure_city_collects_no_candidates():
    """往返闭合（上海..上海）尾部重复城不收候选：必被 _assemble_plan 出发
    城闸丢弃，收了白付一次全城扫描。"""

    class RecStore(_DeepStore):
        def __init__(self):
            super().__init__()
            self.cities: list[str] = []

        def top_pois_in_city(self, city, limit, *, exclude_food=True):
            self.cities.append(city)
            return [
                {
                    "name": f"{city}点",
                    "city": city,
                    "category": "attraction",
                    "location": (104.0, 30.6),
                }
            ][:limit]

    store = RecStore()
    agent = PlanningAgent(NoLLM(), amap_client=None, poi_details=store)
    run(agent._collect_candidates(["上海", "成都", "重庆", "上海"]))
    assert store.cities == ["成都", "重庆"]

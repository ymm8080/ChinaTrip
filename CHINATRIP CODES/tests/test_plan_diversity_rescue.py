"""内容类型多样保位回归（2026-11-07 拍板「商业中心/CITYWALK 要能与 5A 竞争」）。

名录档硬分层把无档商业综合体(other)/城走(citywalk/street)压出 top-30 窗口
与选点池（成都实录：环球中心 4.6 分全城 ~77 位、窗口 30 永不出线）。
窗口满员时同城窗外每类保底 2 行（数据闸/回退闸全口径，不享演出豁免）；
选点池再按 span 定深插位追回——尾接在满池时排在认领梯子末尾永远轮不到。
"""

import asyncio

from app.services.agent.plan import PlanningAgent


def run(coro):
    return asyncio.run(coro)


class NoLLM:
    """候选闸不需要 LLM；任何调用都是测试哨兵。"""

    name = "no-llm"

    async def chat(self, messages, *, temperature: float = 0.3, max_tokens=None):
        raise AssertionError("candidate gate must not call the LLM")


def _filler_rows(city: str, n: int = 32, tags=None, rating: float = 4.2) -> list[dict]:
    """窗口填充行：有坐标有评分的名录/普通景点。"""
    return [
        {
            "name": f"填充景点{i:02d}",
            "city": city,
            "category": "attraction",
            "location": (104.0 + i * 0.01, 30.6),
            "rating": rating,
            "tags": list(tags or []),
        }
        for i in range(n)
    ]


def _diversity_rows(city: str) -> list[dict]:
    """窗外多样内容：商业综合体（other）+ 城走街区（citywalk）。"""
    return [
        {
            "name": "环球中心",
            "city": city,
            "category": "other",
            "location": (104.06, 30.57),
            "rating": 4.6,
            "address": "天府大道北段1700号",
            "tags": [],
        },
        {
            "name": "望平坊街区",
            "city": city,
            "category": "citywalk",
            "location": (104.09, 30.67),
            "rating": 4.4,
            "address": "成华区望平滨河路",
            "tags": [],
        },
    ]


def test_window_rescue_carries_diversity_rows_into_candidates():
    """窗口满员（32 有档行 > 30）时，窗外商业/城走行按每类保底 2 进候选。"""

    class _Store:
        def top_pois_in_city(self, city, limit, *, exclude_food=True):
            rows = _filler_rows(city) + _diversity_rows(city)
            return rows[:limit]

    agent = PlanningAgent(NoLLM(), amap_client=None, poi_details=_Store())
    candidates, _ = run(agent._collect_candidates(["成都"]))
    names = {c["name"] for c in candidates}
    assert "环球中心" in names
    assert "望平坊街区" in names
    assert all(c["location"] for c in candidates)


def test_diversity_rescue_respects_data_gate():
    """三空行（无地址/评分/时段）不享多样保位——白鹿原口径，演出才豁免。"""

    class _Store:
        def top_pois_in_city(self, city, limit, *, exclude_food=True):
            rows = _filler_rows(city)
            rows.append(
                {
                    "name": "三空商业体",
                    "city": city,
                    "category": "other",
                    "location": (104.05, 30.58),
                    "rating": None,
                    "tags": [],
                }
            )
            return rows[:limit]

    agent = PlanningAgent(NoLLM(), amap_client=None, poi_details=_Store())
    candidates, _ = run(agent._collect_candidates(["成都"]))
    names = {c["name"] for c in candidates}
    assert "三空商业体" not in names


def test_selection_places_diversity_rows_ahead_of_untiered_filler():
    """池内插位追回：名录档把多样行压出池（span*4 池上限）时，插在池中段
    的多样行在认领梯子上先于同带无档填充行落位——商业/城走能与 5A 竞争。"""

    class _Store:
        def top_pois_in_city(self, city, limit, *, exclude_food=True):
            ace = _filler_rows(city, n=5, tags=["unesco"], rating=4.9)
            rows = [{**r, "name": f"王牌{i:02d}"} for i, r in enumerate(ace)]
            rows += [
                {**r, "name": f"名录{i:02d}"}
                for i, r in enumerate(_filler_rows(city, n=30, tags=["4a"], rating=4.3))
            ]
            rows += _diversity_rows(city)
            return rows[:limit]

    agent = PlanningAgent(NoLLM(), amap_client=None, poi_details=_Store())
    candidates, _ = run(agent._collect_candidates(["成都"]))
    picked = PlanningAgent._deterministic_selection(candidates, 2, {"成都": (1, 2)})
    names = [p["name"] for p in picked]
    assert "环球中心" in names
    assert "望平坊街区" in names
    # 池位证明：多样行插段挤掉了同带靠后的名录填充行
    assert "名录29" not in names
    assert len(names) <= 8

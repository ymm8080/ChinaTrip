"""R28 餐卡名字/地址根修回归(2026-11-23 用户令 "day4 lunch is proposed by
虹鳟鱼, but name and address are not shown up properly")。

事故链(生产取证):POI 库唯一虹鳟鱼行的 name_zh 已被餐槽标注污染为
「虹鳟鱼一条街农家菜(午餐)」——展示名被 `_enrich_hours`/`_hours_db_pass`
原样当真名 upsert 固化进库,此后图商检索(WAF/配额白烧)、TA 目录链
(无过阈候选)、换点候选全用污名;且引擎命名餐卡(meals._meal_card)从不写
address,候选行的地址在 CandidateItem 转换处被丢,卡面 📍 行判空整行不画。

类级修复:数据入口统一清洗(poi_names.clean_meal_slot_suffix:读库查询词、
图商检索关键词、写库 upsert、引擎/legacy 候选名)+ 地址随候选
(CandidateItem.address → meals._meal_card 命名卡落卡;不进 snapshot_hash)。
"""

from app.services.poi_names import clean_meal_slot_suffix
from app.services.restaurants import candidate_from_poi_dict
from app.services.trip_solver.assembly.meals import _meal_card
from app.services.trip_solver.snapshot import snapshot_hash
from app.services.trip_solver.types import (
    CandidateItem,
    FactSnapshot,
    TripRequest,
)

# —— 止污:清洗函数本体 ——————————————————————————


def test_stain_case_is_stripped():
    assert clean_meal_slot_suffix("虹鳟鱼一条街农家菜(午餐)") == "虹鳟鱼一条街农家菜"
    assert clean_meal_slot_suffix("虹鳟鱼一条街农家菜(午餐)") == "虹鳟鱼一条街农家菜"


def test_english_slot_suffixes_stripped():
    assert clean_meal_slot_suffix("Some Shop (Dinner)") == "Some Shop"
    assert clean_meal_slot_suffix("Some Shop (Afternoon Tea)") == "Some Shop"


def test_real_names_are_not_touched():
    # 「(故宫店)」是分店后缀不是槽位标注——必须原样保留
    assert clean_meal_slot_suffix("四季民福烤鸭店(故宫店)") == "四季民福烤鸭店(故宫店)"
    assert clean_meal_slot_suffix("御仙都·皇家菜博物馆") == "御仙都·皇家菜博物馆"
    assert clean_meal_slot_suffix("") == ""
    assert clean_meal_slot_suffix(None) == ""


def test_stacked_suffixes_peel_clean():
    assert clean_meal_slot_suffix("某店(午餐)(晚餐)") == "某店"


# —— 候选入口清洗(引擎+legacy 同口径)————————————————


def test_engine_candidate_name_is_cleaned():
    from app.services.trip_solver.live import _row_to_candidate

    cand = _row_to_candidate(
        "c1",
        {
            "name": "虹鳟鱼一条街农家菜(午餐)",
            "address": "北京市怀柔区红螺寺外",
            "category": "food",
            "meal_slot": "lunch",
        },
    )
    assert cand.name == "虹鳟鱼一条街农家菜"
    # 地址随候选(此前转换处丢弃,卡面无 📍 的根因)
    assert cand.address == "北京市怀柔区红螺寺外"


def test_legacy_candidate_name_is_cleaned():
    cand = candidate_from_poi_dict(
        {
            "name": "虹鳟鱼一条街农家菜(午餐)",
            "category": "food",
            "location": {"lon": 116.6, "lat": 40.3},
        }
    )
    assert cand is not None
    assert cand.name == "虹鳟鱼一条街农家菜"


# —— 物化:命名餐卡带地址;占位卡维持无地址 ————————————————


def test_named_meal_card_carries_address_and_clean_name():
    host = CandidateItem(
        cid="c9",
        name="虹鳟鱼一条街农家菜(午餐)",  # 库行污名
        category="food",
        meal_slot="lunch",
        address="北京市怀柔区渤海镇",
        address_en="Bohai Town, Huairou",
    )
    card = _meal_card("lunch", 4, 12 * 60, 13 * 60, host, "北京", "meal-lunch-4")
    assert card.name == "虹鳟鱼一条街农家菜"  # 卡面不再外露污名尾巴
    assert card.address == "北京市怀柔区渤海镇"
    assert card.address_en == "Bohai Town, Huairou"


def test_placeholder_meal_card_stays_addressless():
    card = _meal_card("lunch", 4, 12 * 60, 13 * 60, None, "北京", "meal-lunch-4")
    assert card.name == "午餐"
    assert card.address is None
    assert card.address_en is None


# —— snapshot_hash 零漂移:address 是显示糖,不进哈希 ————————


def test_address_field_does_not_move_snapshot_hash():
    def snap(cand: CandidateItem) -> str:
        return snapshot_hash(
            FactSnapshot(
                schema_version=1,
                request=TripRequest(days=2, cities=("北京",)),
                candidates=(cand,),
            )
        )

    base = CandidateItem(cid="c1", name="店", category="food")
    with_addr = CandidateItem(
        cid="c1", name="店", category="food", address="某地址", address_en="addr"
    )
    assert base != with_addr  # 字段本身不同
    assert snap(base) == snap(with_addr)  # 哈希不看 address（零漂移）


def test_snapshot_roundtrip_tolerates_missing_address():
    # 旧语料 dict 无 address 键 → None,不炸(零漂移兼容)
    from app.services.trip_solver.snapshot import _cand

    raw = {"cid": "c1", "name": "店", "kind": "fill"}
    item = _cand(raw)
    assert item.address is None
    assert item.address_en is None


# —— _search_poi 检索关键词清洗(验证链能用干净名命中)——————


def test_search_poi_strips_slot_suffix_from_keywords():
    from app.services.agent.plan import PlanningAgent

    agent = PlanningAgent.__new__(PlanningAgent)
    captured: dict = {}

    class _StubClient:
        vendor = "amap"

        async def search_poi(self, keywords, city=None):
            captured["keywords"] = keywords
            return [{"name": "hit", "category": "food"}]

    agent._search_chain_override = [_StubClient()]
    agent._search_quota_dead = set()

    import asyncio

    hits = asyncio.run(agent._search_poi("虹鳟鱼一条街农家菜(午餐)", city="北京"))
    assert hits, "stub 应命中"
    assert captured["keywords"] == "虹鳟鱼一条街农家菜"

"""银行网点闸（2026-11-13 用户拍板「ALL BANKS SHOULD BE SET AS INACTIVE，
而不是只停中国银行」）。

底库偶有平台/图商灌进来的网点行（上海实况：「中国银行」category=other、
tags=intl/layla、别名外滩23号/中国银行大楼，60 分钟默认时长，把外滩挤出
了 day2）。数据侧该行已置 inactive；本闸是读侧对称防线——网点名不进自动
排期池，场馆/大楼/景区类保留。
"""

from __future__ import annotations

from app.services.agent.plan import _cand_is_bank_branch, _pool_worthy


def _cand(name: str, **kw) -> dict:
    c = {
        "name": name,
        "city": "上海",
        "address": "上海市黄浦区中山东一路",
        "location": {"lon": 121.49, "lat": 31.24},
    }
    c.update(kw)
    return c


def test_bank_branch_names_detected():
    assert _cand_is_bank_branch(_cand("中国银行")) is True
    assert _cand_is_bank_branch(_cand("中国工商银行")) is True
    assert _cand_is_bank_branch(_cand("招商银行(南京东路支行)")) is True
    assert _cand_is_bank_branch(_cand("建设银行上海分行")) is True
    assert _cand_is_bank_branch(_cand("农商银行自助银行")) is True


def test_landmark_and_venue_names_not_misjudged():
    # 场馆/大楼/景区/乐园类：名字里带银行但不是网点
    assert _cand_is_bank_branch(_cand("上海市银行博物馆")) is False
    assert _cand_is_bank_branch(_cand("上海外滩12号大楼")) is False
    assert _cand_is_bank_branch(_cand("交通银行耀雪冰雪世界")) is False
    assert _cand_is_bank_branch(_cand("浦发银行东方体育中心")) is False
    assert _cand_is_bank_branch(_cand("外滩")) is False
    assert _cand_is_bank_branch(_cand("金茂大厦")) is False


def test_bank_branch_never_enters_pool():
    # 有地址有评分也不得进池（数据闸之外的对称闸）
    bank = _cand("中国银行", rating=4.8, opening_hours="09:00-17:00")
    assert _pool_worthy(bank) is False
    landmark = _cand("外滩", rating=4.8, opening_hours="全天")
    assert _pool_worthy(landmark) is True

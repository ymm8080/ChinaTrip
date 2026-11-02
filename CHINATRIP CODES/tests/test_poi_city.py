"""市名解析器 app.services.poi_city（backlog P2：07/06/03 无 city 列）.

断言口径：canonical = CITY_ADCODES/KNOWN_CITIES 注册短名；注册表外地级市
用同一套「短名」规则。索引由 ops/build_city_index.py 生成（若缺文件只测
注册表退路，不测县上卷）.
"""

from __future__ import annotations

import pytest

from app.services.poi_city import (
    _index,
    canonical_city,
    known_cities,
    resolve_city,
)


def _index_ready() -> bool:
    return bool(_index())


requires_index = pytest.mark.skipif(not _index_ready(), reason="city_index.json 缺失")


# ---------------- canonical 城市名归一 ----------------


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("西安", "西安"),
        ("西安市", "西安"),
        ("澳门特别行政区", "澳门"),
        ("阿坝藏族羌族自治州", "阿坝"),
        ("阿坝州", "阿坝"),
        ("红河哈尼族彝族自治州", "红河"),
        ("红河州", "红河"),
        ("西双版纳傣族自治州", "西双版纳"),
        ("西双版纳州", "西双版纳"),
        ("黔东南苗族侗族自治州", "黔东南"),
        ("海西蒙古族藏族自治州", "海西"),
        ("锡林郭勒盟", "锡林郭勒"),
        ("阿克苏地区", "阿克苏"),
        ("喀什地区", "喀什"),
        ("巴州", "巴音郭楞"),
        ("伊犁州", "伊犁"),
        ("湘西州", "湘西"),
        ("二连浩特", "锡林郭勒"),
        ("神农架", "神农架林区"),
        ("格尔木", "海西"),
        ("汝州", "平顶山"),
        ("巩义", "郑州"),
        ("长白山", "长白山"),  # 非注册非地级：原样保留
        ("", ""),
    ],
)
def test_canonical_city(raw: str, want: str) -> None:
    assert canonical_city(raw) == want


# ---------------- resolve_city：地级前缀 / 县上卷 / 变体兜底 ----------------


@requires_index
@pytest.mark.parametrize(
    ("province", "text", "want"),
    [
        # 07 国保 address 样式（province 取自 address 本身）
        (None, "北京市平谷区", "北京"),
        (None, "河北省黄骅市", "沧州"),  # 县级市上卷
        (None, "河北省张家口市崇礼区", "张家口"),
        (None, "山西省朔州市朔城区", "朔州"),
        (None, "内蒙古自治区包头市昆都仑区", "包头"),
        (None, "新疆维吾尔自治区阿克苏地区库车市", "阿克苏"),
        (None, "陕西省凤翔县", "宝鸡"),  # 2021 撤县改区旧写法
        (None, "河南省偃师市", "洛阳"),  # 县级市改区旧写法
        (None, "福建省沙县", "三明"),  # 单字 stem 专表
        # 06 名村 locality 样式（province 是列）
        ("北京", "门头沟区斋堂镇", "北京"),
        ("河北", "怀来县鸡鸣驿乡", "张家口"),
        ("河北", "邢台县路罗镇", "邢台"),  # 2020 撤县后索引已无线
        ("四川", "涪陵区青羊镇", "重庆"),  # 跨省划管
        ("贵州", "务川县大坪街道", "遵义"),
        ("云南", "巍山县永建镇", "大理"),
        ("云南", "沧源县勐角傣族彝族拉祜族乡", "临沧"),
        ("广东", "东莞市茶山镇", "东莞"),
        # 注册名直接命中
        ("江西", "景德镇市", "景德镇"),
        # 旧书写（高新区/管委会/直辖县级市短写）
        (None, "石家庄高新区", "石家庄"),
        (None, "长白山管委会池北区", "延边"),
        (None, "长白山管委会池南区", "白山"),
        (None, "济源示范区", "济源"),
        # 扩表批次 3 后「白山」进注册表——特定别名仍须优先于注册表子串
        (None, "白山", "白山"),
        # 识别不了
        ("河北", "北戴河", None),  # 无地级/县可证——保守不猜
    ],
)
def test_resolve_city(province: str | None, text: str, want: str | None) -> None:
    assert resolve_city(province, text) == want


# ---------------- 与已知注册表/数据完整性交叉 ----------------


def test_known_cities_superset_of_registry() -> None:
    from app.services.agent.plan import KNOWN_CITIES

    kc = known_cities()
    outside = {c for c in KNOWN_CITIES if c not in kc}
    assert outside == set(), f"注册名不在 canonical 集: {sorted(outside)}"


def test_municipality_counties_roll_up() -> None:
    entry = _index().get("北京")
    assert entry, "索引缺失"
    assert entry["counties"]["门头沟区"] == "北京"

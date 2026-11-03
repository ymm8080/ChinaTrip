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
    city_from_name,
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
        ("河北", "太行山", None),  # 非行划名，无可证——保守不猜
        # 区名 stem 精确匹配（北戴河区→秦皇岛）；只对整串生效，不做子串
        ("河北", "北戴河", "秦皇岛"),
        # 同串多城名：取出现位置最靠前的（「朝阳」也是注册名——朝阳市）
        ("吉林", "长春市朝阳区红旗街旅游休闲街区", "长春"),
        (None, "长春市朝阳区红旗街旅游休闲街区", "长春"),
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


# ---------------- city 列遗留值：县级单位整串上卷 ----------------


@requires_index
@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("太仓", "苏州"),  # 县级市裸名
        ("邛崃", "成都"),
        ("永康", "金华"),
        ("孟连县", "普洱"),  # 带县后缀
        ("石柱县", "重庆"),  # 自治县上卷
        ("大通县", "西宁"),
    ],
)
def test_resolve_exact_county_value(text: str, want: str) -> None:
    assert resolve_city(None, text) == want


# ---------------- 名称前缀 → 城市（显式行划后缀才认） ----------------


@requires_index
@pytest.mark.parametrize(
    ("name", "want"),
    [
        ("宁波市天一阁博物院（宁波市保国寺古建筑博物馆）", "宁波"),
        ("重庆市江北区观音桥商圈旅游休闲街区", "重庆"),
        ("滕州市汉画像石馆", "枣庄"),  # 县级市全名 → 属地级
        # 「X省 + 后续地名」体例：省名不是归属，剥掉再解析
        ("吉林省长春市朝阳区红旗街旅游休闲街区", "长春"),
        ("吉林省四平市铁西区仁兴里沉浸式文旅街区", "四平"),
    ],
)
def test_city_from_name_admin_suffix(name: str, want: str) -> None:
    assert city_from_name(name) == want


@requires_index
@pytest.mark.parametrize(
    "name",
    [
        "中山舰博物馆",  # 武汉景点，非中山
        "北海公园",  # 北京景点，非北海
        "东方明珠",  # 上海景点，非东方
        "沙溪镇",  # 太仓/中山同名镇
        "四川大学博物馆",  # 省名+机构，非地级
        "广西壮族自治区博物馆",
    ],
)
def test_city_from_name_rejects_unsafe(name: str) -> None:
    assert city_from_name(name) is None


@requires_index
@pytest.mark.parametrize(
    ("name", "province", "want"),
    [
        # 省域已证 + 城市名紧邻通名 → 认（805 行「省名当 city」主场）
        ("桂林博物馆", "广西", "桂林"),
        ("西安碑林博物馆", "陕西", "西安"),
        ("南京中国科举博物馆", "江苏", "南京"),
        ("临夏回族自治州博物馆", "甘肃", "临夏"),
        # 跨省同名：名称虽以城市开头，但该城不属本省 → 拒绝
        ("北海公园", "北京", None),
        ("中山舰博物馆", "湖北", None),
        ("桂林博物馆", "山东", None),
        # 校名相邻不作属地证据（中山大学在广州）
        ("中山大学博物馆（校史馆）", "广东", None),
        ("武汉大学万林艺术博物馆", "湖北", None),
        # 省名未知（区县/园区）时不启用该规则
        ("大九街旅游休闲街区", "江北区", None),
    ],
)
def test_city_from_name_province_gated(
    name: str, province: str, want: str | None
) -> None:
    assert city_from_name(name, province) == want

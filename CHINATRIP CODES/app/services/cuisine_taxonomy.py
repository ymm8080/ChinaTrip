"""cuisine 粗化映射（DESIGN user_tag_two_level_2026-11-10 §二）。

用户可选二级标签（颗粒度粗）：库内 `restaurants.cuisine` 575 个原值
（中英混杂、粒度不一）→ 6 大组（cuisine_family）× 21 组（cuisine_group）
的受控词表。原值列不动（回源链还会写英文），本模块只产出两个推导列。

规则级联：按序首中即停——特异词（火锅/韩式烤肉/日式拉面）排在泛词
（中餐/面/小吃）前面，避免「日式拉面」落进「西北面食」这类错桶。
英文值统一 lower + 去空格后匹配。未命中返回 (None, None)，回填任务
留空不猜（只填空语义）。

用法（回填）：app/jobs/backfill_cuisine_group.py
用法（干跑）：PYTHONPATH=. python -m app.services.cuisine_taxonomy
"""

from __future__ import annotations

import re

# (family, group) 词表——用户选择器的两级标签。顺序即级联优先级。
_RULES: list[tuple[tuple[str, ...], str, str]] = [
    # ---- 异国风味（最前：韩式烤肉/泰式火锅/西餐快餐 归异国不归中餐桶）----
    (
        ("日料", "日本", "日式", "寿司", "刺身", "居酒屋", "拉面", "咖喱", "japanese"),
        "异国风味",
        "日韩料理",
    ),
    (("韩", "朝鲜", "korean"), "异国风味", "日韩料理"),
    (
        (
            "泰",
            "越南",
            "新加坡",
            "印尼",
            "马来",
            "南亚",
            "东南亚",
            "印度",
            "巴基斯坦",
            "土耳其",
            "thai",
            "malaysian",
            "indonesian",
            "south east asian",
        ),
        "异国风味",
        "东南亚菜",
    ),
    (
        (
            "西餐",
            "西式",
            "意",
            "italy",
            "italian",
            "法",
            "french",
            "欧",
            "european",
            "德",
            "俄",
            "墨西哥",
            "西班牙",
            "地中海",
            "牛排",
            "steakhouse",
            "披萨",
            "铁板烧",
            "拉丁",
            "德国",
            "西点",
            "western",
        ),
        "异国风味",
        "西餐",
    ),
    # ---- 火锅烧烤（先于地域：老北京涮肉/椰子鸡火锅 都进锅桶）----
    (
        (
            "火锅",
            "串串",
            "涮",
            "打边炉",
            "汤锅",
            "锅物料理",
            "焖锅",
            "hotpot",
            "hot pot",
            "鸡煲",
            "柴火鸡",
            "煲类",
            "肥肠煲",
            "牛杂煲",
            "肉蟹煲",
            "蟹煲",
            "煲",
            "干锅",
            "猪肚鸡",
            "椰子鸡",
        ),
        "火锅烧烤",
        "火锅串串",
    ),
    (
        (
            "烧烤",
            "烤肉",
            "烤鱼",
            "烤串",
            "炙子",
            "烧肉",
            "烤禽",
            "烤鸡",
            "小龙虾",
            "bbq",
        ),
        "火锅烧烤",
        "烧烤烤鱼",
    ),
    # ---- 轻食茶饮（先于中餐泛词：茶馆不是正餐）----
    (
        (
            "咖啡",
            "烘焙",
            "甜品",
            "糕点",
            "茶饮",
            "奶茶",
            "冰淇淋",
            "巧克力",
            "糖水",
            "凉茶",
            "刨冰",
            "冷饮",
            "coffee",
            "下午茶",
        ),
        "轻食茶饮",
        "咖啡烘焙",
    ),
    (
        ("茶馆", "茶楼", "茶室", "茶艺", "茶宴", "茶点", "茶楼点心"),
        "轻食茶饮",
        "茶馆茶楼",
    ),
    (("素食", "素菜", "蔬食", "素斋", "vegan", "vegetarian"), "轻食茶饮", "素食轻食"),
    # ---- 夜宵酒吧（先于中餐：音乐餐吧/精酿是场景不是菜系）----
    (
        (
            "酒吧",
            "酒馆",
            "酒廊",
            "酒庄",
            "精酿",
            "啤酒",
            "餐吧",
            "餐酒",
            "大堂吧",
            "夜场",
            "酒",
        ),
        "夜宵酒吧",
        "酒吧夜店",
    ),
    (("夜宵", "夜市", "大排档", "排档"), "夜宵酒吧", "夜宵排档"),
    # ---- 自助 ----
    (("自助", "宴会厅", "美食广场"), "便捷小吃", "自助餐"),
    # ---- 中餐经典：特异地域词在前 ----
    (
        (
            "川",
            "湘",
            "渝",
            "麻辣",
            "江湖菜",
            "香辣",
            "重庆菜",
            "重庆小面",
            "酸菜鱼",
            "美蛙",
            "烧鸡公",
            "肥肠鸡",
            "sichuan",
            "hunan",
        ),
        "中餐经典",
        "川湘辣味",
    ),
    (
        (
            "粤",
            "cantonese",
            "港式",
            "潮汕",
            "潮州",
            "chao",
            "teochew",
            "顺德",
            "烧腊",
            "烧鹅",
            "茶餐厅",
            "dim sum",
            "点心",
            "肠粉",
            "早茶",
            "牛杂",
            "海南鸡饭",
            "车仔面",
            "云吞",
        ),
        "中餐经典",
        "粤式茶点",
    ),
    (
        (
            "本帮",
            "上海",
            "shanghai",
            "杭",
            "hangzhou",
            "苏",
            "suzhou",
            "jiangsu",
            "浙",
            "zhejiang",
            "淮扬",
            "huaiyang",
            "金陵",
            "南京",
            "宁波",
            "ningbo",
            "绍兴",
            "无锡",
            "江南",
            "江浙",
            "jiangzhe",
            "台州",
            "taizhou",
            "蟹",
            "hairycrab",
            "海派",
            "崇明",
            "淳安",
            "桐庐",
            "shuntak",
        ),
        "中餐经典",
        "江浙本帮",
    ),
    (
        (
            "京",
            "beijing",
            "鲁",
            "山东",
            "shandong",
            "东北",
            "dongbei",
            "辽菜",
            "晋菜",
            "宫廷",
            "官府",
            "烤鸭",
            "卤煮",
            "驴肉",
            "新京",
            "炙子烤肉",
            "北方",
            "officialcuisine",
            "牛肉羊肉",
            "牛羊肉",
        ),
        "中餐经典",
        "北方风味",
    ),
    (
        (
            "新疆",
            "西域",
            "清真",
            "兰州",
            "西北",
            "陕西",
            "xibei",
            "羊肉馆",
            "驴肉",
            "面馆",
            "noodles",
            "饺子",
            "包子",
            "面食",
            "面点",
            "米粉",
            "米线",
            "牛肉面",
            "螺蛳粉",
            "油茶",
            "dumpling",
        ),
        "中餐经典",
        "西北面食",
    ),
    (
        (
            "云南",
            "yunnan",
            "贵州",
            "云贵",
            "湖北",
            "hubei",
            "鄂",
            "楚",
            "海南",
            "台湾",
            "客家",
            "hakka",
            "hakkanese",
            "福建",
            "闽",
            "fujian",
            "hokkien",
            "土家",
            "藏餐",
            "徽",
            "anhui",
            "huicuisine",
            "希腊",
            "江西",
        ),
        "中餐经典",
        "其他地方菜",
    ),
    (
        (
            "海鲜",
            "鱼鲜",
            "虾蟹",
            "虾",
            "蟹",
            "河鲜",
            "鱼头",
            "鱼馆",
            "鱼",
            "fish",
            "seafood",
            "lobster",
            "龙虾",
        ),
        "中餐经典",
        "粤式茶点",
    ),
    # ---- 中餐兜底泛词 ----
    (
        (
            "中餐",
            "中式",
            "中华",
            "家常",
            "私房",
            "私厨",
            "农家",
            "创意",
            "融合",
            "innovative",
            "乡土",
            "民间",
            "地方",
            "特色",
            "综合",
            "主题",
            "民国",
            "养生",
            "蒸菜",
            "砂锅",
            "炖",
            "汤",
            "粥",
            "congee",
            "卤味",
            "熟食",
            "简餐",
            "正餐",
            "餐厅",
            "餐饮",
            "料理",
            "chinese",
            "家庭",
            "其他",
            "亚洲",
            "精品",
            "宴请",
            "newpassiondish",
            "specialdishes",
        ),
        "中餐经典",
        "其他地方菜",
    ),
    # ---- 便捷小吃 ----
    (
        (
            "小吃",
            "快餐",
            "简餐",
            "早餐",
            "炸鸡",
            "零食",
            "美食街",
            "街区",
            "smalleats",
            "老字号",
        ),
        "便捷小吃",
        "小吃快餐",
    ),
    (("面", "粉"), "便捷小吃", "小吃快餐"),
    (("轻食", "茶饮", "饮品"), "轻食茶饮", "咖啡烘焙"),
]


def classify_cuisine(raw: object) -> tuple[str | None, str | None]:
    """原值 → (cuisine_family, cuisine_group)；未命中 (None, None)。

    level1/level2 是用户选择器的两级标签（DESIGN §二）；原值列永不
    改写。匹配前两边都归一：lower + 去所有空白（「Dim Sum」/「South
    East Asian」这类带空格英文词才能命中）。
    """
    s = _norm(str(raw or ""))
    if not s:
        return None, None
    for keywords, family, group in _RULES:
        for kw in keywords:
            if _norm(kw) in s:
                return family, group
    return None, None


def _norm(s: str) -> str:
    return "".join(s.split()).lower()


def _dry_run() -> None:  # pragma: no cover — ops 工具入口
    """打印全库映射结果与未命中清单（只读，不写库）。"""
    from pathlib import Path

    from sqlalchemy import create_engine, text

    env = Path(__file__).resolve().parents[2] / ".env"
    m = re.search(r"DATABASE_URL\s*=\s*(.+)", env.read_text(encoding="utf-8"))
    eng = create_engine(m.group(1).strip() if m else "")
    with eng.connect() as c:
        rows = c.execute(
            text("SELECT cuisine, count(*) FROM restaurants GROUP BY 1 ORDER BY 2 DESC")
        ).all()
    unmapped: list[tuple[str, int]] = []
    for cuisine, n in rows:
        fam, grp = classify_cuisine(cuisine)
        if fam is None:
            unmapped.append((cuisine, n))
    print(
        f"distinct={len(rows)} unmapped={len(unmapped)} "
        f"rows_unmapped={sum(n for _, n in unmapped)}"
    )
    for cuisine, n in unmapped:
        print("  MISS", cuisine, n)


if __name__ == "__main__":
    _dry_run()

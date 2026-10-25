"""240 小时过境免签行程可行性校验（DESIGN §14.3-G2，2026-10-25）。

确定性规则引擎，零 LLM：入境游客（主要客户）最常吐槽「官方答案互相
矛盾」且无一家规划器有权威校验——本模块把政策快照落成可热更数据 +
纯函数判定，行程页据此亮绿/红横幅，恒挂「以边检为准」免责。

政策口径（快照 VISA_POLICY.effective_date）：
- 停留 ≤240h（自入境次日 00:00 起算的口径差异由 messages 提示）
- 行程城市须全部落在允许省域内
- 须持第三国联程客票（提醒项，无法程序化验证）
- 入境/出境口岸须在名单内（调用方给端口则校验；缺省仅提醒）

名单 v0 为编写时最优已知口径、**待官方源逐项校订**——结构即产品：
换名单 = 换快照 dict，不动引擎。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

# 政策快照（可热更：改这里不动引擎；生效日期随公告刷新）
VISA_POLICY: dict = {
    # 官方源校订 2026-10-25（第二轮，口岸全表）：240h 政策 2024-12-17
    # 起施行（国家移民管理局公告）；现行口径 57 国 / 65 口岸 / 24 省。
    # 24 省名单勘误（vs v0）：贵州属允许省域（v0 漏）、吉林省不在范围
    # （v0 误入）；山西/江西/广西/四川/云南五省区为市级活动范围（非全省），
    # 见 city_scope。口岸全表 65 = 航空 47 + 水运 14 + 铁路 2 + 公路 2。
    "effective_date": "2024-12-17",
    "max_stay_hours": 240,
    "source": (
        "国家移民管理局公告及后续修订（57国/65口岸/24省，"
        "市级范围：晋太原大同/赣南昌景德镇/桂12市/川11市/滇9市州；"
        "全表校订 2026-10-25）"
    ),
    # 允许省域（24 省 = 原19省 + 2024-12-17 新增晋/皖/赣/琼/黔；无吉林）
    "provinces_allowed": {
        "北京",
        "天津",
        "河北",
        "山西",
        "辽宁",
        "黑龙江",
        "上海",
        "江苏",
        "浙江",
        "安徽",
        "福建",
        "江西",
        "山东",
        "河南",
        "湖北",
        "湖南",
        "广东",
        "广西",
        "海南",
        "重庆",
        "四川",
        "贵州",
        "云南",
        "陕西",
    },
    # 市级活动范围（公告原文限定；未列出的省 = 全省可活动）
    "city_scope": {
        "山西": {"太原", "大同"},
        "江西": {"南昌", "景德镇"},
        "广西": {
            "南宁",
            "柳州",
            "桂林",
            "梧州",
            "北海",
            "防城港",
            "钦州",
            "贵港",
            "玉林",
            "贺州",
            "河池",
            "来宾",
        },
        "四川": {
            "成都",
            "自贡",
            "泸州",
            "德阳",
            "遂宁",
            "内江",
            "乐山",
            "宜宾",
            "雅安",
            "眉山",
            "资阳",
        },
        # 云南 9 市州（深圳市政府在线政策问答口径，2026-10-25 三轮补）
        "云南": {
            "昆明",
            "丽江",
            "玉溪",
            "普洱",
            "楚雄",
            "大理",
            "西双版纳",
            "红河",
            "文山",
        },
    },
    # 口岸全表 65（航空47 + 水运14 + 铁路2 + 公路2；校订 2026-10-25）
    "entry_ports": {
        # 航空 47
        "北京首都",
        "北京大兴",
        "天津滨海",
        "石家庄正定",
        "太原武宿",
        "沈阳桃仙",
        "大连周水子",
        "哈尔滨太平",
        "上海浦东",
        "上海虹桥",
        "南京禄口",
        "苏南硕放",
        "扬州泰州",
        "杭州萧山",
        "宁波栎社",
        "温州龙湾",
        "义乌",
        "合肥新桥",
        "黄山屯溪",
        "福州长乐",
        "厦门高崎",
        "泉州晋江",
        "武夷山",
        "南昌昌北",
        "青岛胶东",
        "济南遥墙",
        "烟台蓬莱",
        "威海大水泊",
        "郑州新郑",
        "武汉天河",
        "长沙黄花",
        "张家界荷花",
        "广州白云",
        "深圳宝安",
        "揭阳潮汕",
        "南宁吴圩",
        "桂林两江",
        "北海福成",
        "海口美兰",
        "三亚凤凰",
        "重庆江北",
        "成都双流",
        "成都天府",
        "贵阳龙洞堡",
        "昆明长水",
        "丽江三义",
        "西安咸阳",
        # 水运 14
        "上海港",
        "天津港",
        "大连港",
        "秦皇岛港",
        "青岛港",
        "连云港港",
        "温州港",
        "宁波舟山港",
        "厦门港",
        "广州南沙港",
        "深圳蛇口邮轮中心",
        "中山港",
        "广州琶洲港",
        "北海港",
        # 铁路 2
        "磨憨铁路口岸",
        "香港西九龙",
        # 公路 2
        "横琴口岸",
        "港珠澳大桥珠海口岸",
    },
}

# 城市→省域映射（覆盖 CITY_ALIASES 常用城；非大陆城市单独口径）
CITY_PROVINCE: dict[str, str] = {
    "北京": "北京",
    "上海": "上海",
    "天津": "天津",
    "重庆": "重庆",
    "杭州": "浙江",
    "宁波": "浙江",
    "温州": "浙江",
    "绍兴": "浙江",
    "苏州": "江苏",
    "南京": "江苏",
    "无锡": "江苏",
    "扬州": "江苏",
    "广州": "广东",
    "深圳": "广东",
    "珠海": "广东",
    "汕头": "广东",
    "佛山": "广东",
    "东莞": "广东",
    "中山": "广东",
    "惠州": "广东",
    "成都": "四川",
    "乐山": "四川",
    "宜宾": "四川",
    "阿坝": "四川",
    "西安": "陕西",
    "汉中": "陕西",
    "延安": "陕西",
    "武汉": "湖北",
    "宜昌": "湖北",
    "襄阳": "湖北",
    "长沙": "湖南",
    "张家界": "湖南",
    "湘西": "湖南",
    "岳阳": "湖南",
    "厦门": "福建",
    "福州": "福建",
    "泉州": "福建",
    "武夷山": "福建",
    "昆明": "云南",
    "大理": "云南",
    "丽江": "云南",
    "西双版纳": "云南",
    "贵阳": "贵州",
    "桂林": "广西",
    "南宁": "广西",
    "北海": "广西",
    "三亚": "海南",
    "海口": "海南",
    "青岛": "山东",
    "济南": "山东",
    "威海": "山东",
    "烟台": "山东",
    "郑州": "河南",
    "洛阳": "河南",
    "开封": "河南",
    "合肥": "安徽",
    "黄山": "安徽",
    "南昌": "江西",
    "九江": "江西",
    "哈尔滨": "黑龙江",
    "长春": "吉林",
    "沈阳": "辽宁",
    "大连": "辽宁",
    "石家庄": "河北",
    "太原": "山西",
    "呼和浩特": "内蒙古",
    # 政策省域外的西部城市（映射齐全才能判 fail，否则只 warning）
    "兰州": "甘肃",
    "敦煌": "甘肃",
    "嘉峪关": "甘肃",
    "乌鲁木齐": "新疆",
    "伊犁": "新疆",
    "喀什": "新疆",
    "拉萨": "西藏",
    "林芝": "西藏",
    "西宁": "青海",
    "银川": "宁夏",
}

#: 非大陆城市：240h 过境政策不覆盖，需港澳台各自签注/入台证口径
NON_MAINLAND = {"香港", "澳门", "台北", "台中", "高雄"}


class VisaCheckResult(BaseModel):
    """行程页横幅数据源：ok=绿 / warning=黄（信息不全）/ fail=红。"""

    status: Literal["ok", "warning", "fail"]
    stay_hours: int | None = None
    messages: list[str] = []


def _norm(city: str) -> str:
    return (city or "").strip().removesuffix("市")


def check_240h_transit(
    cities: list[str],
    *,
    entry_date: str | None = None,
    exit_date: str | None = None,
    entry_port: str | None = None,
    exit_port: str | None = None,
    policy: dict | None = None,
) -> VisaCheckResult:
    """校验行程是否满足 240h 过境免签口径（纯函数，可离线）。

    entry/exit_date 为 ISO "YYYY-MM-DD"；缺日期 → warning（时钟无法
    计算）；口岸缺省 → 提醒不硬卡；所有结论恒附「以边检为准」。
    """
    p = policy or VISA_POLICY
    messages: list[str] = [f"政策口径 {p['effective_date']}（{p['source']}）"]
    problems: list[str] = []
    warns: list[str] = []

    # ① 省域校验（含市级活动范围：山西/江西/广西/四川/云南非全省）
    bad_cities: list[str] = []
    unknown: list[str] = []
    non_mainland: list[str] = []
    city_scope: dict = p.get("city_scope", {})
    for raw in cities:
        city = _norm(raw)
        if not city:
            continue
        if city in NON_MAINLAND or any(city.startswith(k) for k in NON_MAINLAND):
            non_mainland.append(city)
            continue
        prov = CITY_PROVINCE.get(city)
        if prov is None:
            unknown.append(city)
        elif prov not in p["provinces_allowed"]:
            bad_cities.append(f"{city}（{prov}）")
        elif prov in city_scope and city not in city_scope[prov]:
            scope = "、".join(sorted(city_scope[prov])[:6])
            bad_cities.append(f"{city}不在 {prov} 允许活动范围（限 {scope} 等）")
    if bad_cities:
        problems.append("以下城市不在 240h 免签允许省域：" + "、".join(bad_cities))
    if unknown:
        warns.append("城市省份未收录，请自查：" + "、".join(unknown))
    if non_mainland:
        warns.append(
            "行程含港澳台城市（" + "、".join(non_mainland) + "），"
            "240h 过境政策不覆盖，需各自签注/证件口径"
        )

    # ② 停留时钟
    stay_hours: int | None = None
    if entry_date and exit_date:
        try:
            entry = datetime.strptime(entry_date, "%Y-%m-%d")
            exit_ = datetime.strptime(exit_date, "%Y-%m-%d")
        except ValueError:
            warns.append("出入境日期格式应为 YYYY-MM-DD，停留时长未校验")
        else:
            stay_hours = int((exit_ - entry).total_seconds() // 3600)
            limit: int = p["max_stay_hours"]
            if stay_hours > limit:
                problems.append(
                    f"停留 {stay_hours}h 超过 {limit}h 上限"
                    "（注意入境次日 00:00 起算的官方口径差异）"
                )
    else:
        warns.append("未填出入境日期，240h 停留时钟未校验")

    # ③ 口岸（全表 65 已校订 2026-10-25；命名差异以边检现场为准）
    if entry_port:
        if entry_port not in p["entry_ports"]:
            problems.append(
                f"入境口岸「{entry_port}」不在名单"
                "（名录为 2026-10 校订快照，请以官方为准）"
            )
    else:
        warns.append("未指定入境口岸（须为名单口岸，如上海浦东/北京首都）")
    if exit_port and exit_port not in p["entry_ports"]:
        # 出境口岸与入境可不同口岸；共用同一名单
        problems.append(
            f"出境口岸「{exit_port}」不在名单（名录为 2026-10 校订快照，请以官方为准）"
        )

    # ④ 联程票提醒 + 免责（恒挂）
    messages.append("须持 240h 内离境前往第三国的联程客票（登机牌/行程单备查）")
    messages.extend(problems)
    messages.extend(warns)
    messages.append("最终以边检现场认定为准")

    status: Literal["ok", "warning", "fail"] = (
        "fail" if problems else ("warning" if warns else "ok")
    )
    return VisaCheckResult(status=status, stay_hours=stay_hours, messages=messages)

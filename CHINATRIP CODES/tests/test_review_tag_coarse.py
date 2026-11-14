"""review_tag_coarse 粗化映射单测（DESIGN user_tag_two_level_2026-11-10 §五）。"""

from app.services.review_tag_coarse import _COARSE_MAP, coarse_tags


def test_all_surveyed_words_mapped():
    """2026-11-10 库实测 36 个携程词必须全部有粗桶（无透传漏网）。"""
    surveyed = [
        "赏花胜地", "遛娃宝藏地", "亲子同乐", "夜游观景", "历史建筑",
        "乘船游览", "自然山水", "登高爬山", "漂流", "古镇古村", "城市漫步",
        "地标观景", "清凉漂流", "海滨玩水", "园林花园", "亲近动物", "科技馆",
        "度假村", "徒步", "草原采风", "影视基地", "沙漠戈壁", "文化体验",
        "泡温泉", "儿童乐园", "冰雪乐园", "滑雪", "室内滑雪", "潜水", "缆车索道",
        "亲水乐园", "冲浪", "巴士观光", "户外滑雪", "游艇帆船", "跳伞", "飞行体验",
    ]
    unmapped = [t for t in surveyed if t not in _COARSE_MAP]
    # 城市漫步有独立粗桶（二级标签「街区漫步」语义），设计 §五 未收进 12 桶，
    # 唯一允许的透传词；其余词必须显式在词表（含 亲近动物/文化体验 恒等映射）。
    assert unmapped == ["城市漫步"]


def test_coarse_twelve_buckets():
    assert coarse_tags(["亲子同乐", "遛娃宝藏地", "儿童乐园"]) == ["适合带娃"]
    assert coarse_tags(["漂流", "清凉漂流"]) == ["水上项目"]
    assert coarse_tags(["跳伞", "飞行体验"]) == ["刺激冒险"]
    assert coarse_tags(["滑雪", "室内滑雪", "户外滑雪", "冰雪乐园", "泡温泉"]) == [
        "温泉滑雪"
    ]


def test_dedup_and_order_and_passthrough():
    # 保序 + 去重：同一粗桶多细词只出一次
    assert coarse_tags(["泡温泉", "滑雪", "泡温泉"]) == ["温泉滑雪"]
    # 未知词透传（不猜桶）
    assert coarse_tags(["未知标签"]) == ["未知标签"]
    assert coarse_tags(["历史建筑", "未知标签"]) == ["怀旧历史", "未知标签"]
    assert coarse_tags(None) == []
    assert coarse_tags([]) == []
    # 非字符串跳过
    assert coarse_tags([1, "跳伞", None]) == ["刺激冒险"]


def test_idempotent():
    """幂等：粗词再过一遍映射不变（存量重刷任务可安全重跑）。"""
    once = coarse_tags(["赏花胜地", "跳伞", "未知标签"])
    assert coarse_tags(once) == once

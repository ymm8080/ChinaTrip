"""cuisine_taxonomy 粗化映射单测（DESIGN user_tag_two_level_2026-11-10 §二）。"""

from app.services.cuisine_taxonomy import classify_cuisine


def test_bilingual_synonyms_converge():
    """同义中英多写法收敛到同一（family, group）。"""
    for raw in ("粤菜", "Cantonese", "Cantonese Cuisine", "潮汕菜", "茶餐厅"):
        assert classify_cuisine(raw) == ("中餐经典", "粤式茶点"), raw
    for raw in ("川菜", "Sichuan", "Sichuan Cuisine", "湘菜"):
        assert classify_cuisine(raw) == ("中餐经典", "川湘辣味"), raw
    for raw in ("本帮菜", "Shanghainese", "上海菜"):
        assert classify_cuisine(raw) == ("中餐经典", "江浙本帮"), raw


def test_specific_beats_generic():
    """特异词优先：韩式烤肉≠中餐烧烤、老北京涮肉=火锅、日式拉面≠面食。"""
    assert classify_cuisine("韩式烤肉") == ("异国风味", "日韩料理")
    assert classify_cuisine("老北京涮肉") == ("火锅烧烤", "火锅串串")
    assert classify_cuisine("日式拉面") == ("异国风味", "日韩料理")
    assert classify_cuisine("泰式火锅") == ("异国风味", "东南亚菜")
    assert classify_cuisine("西餐快餐") == ("异国风味", "西餐")


def test_coarse_group_slots():
    assert classify_cuisine("火锅") == ("火锅烧烤", "火锅串串")
    assert classify_cuisine("小龙虾") == ("火锅烧烤", "烧烤烤鱼")
    assert classify_cuisine("面馆") == ("中餐经典", "西北面食")
    assert classify_cuisine("苏式面馆") == ("中餐经典", "江浙本帮")
    assert classify_cuisine("海鲜") == ("中餐经典", "粤式茶点")
    assert classify_cuisine("茶馆") == ("轻食茶饮", "茶馆茶楼")
    assert classify_cuisine("咖啡烘焙") == ("轻食茶饮", "咖啡烘焙")
    assert classify_cuisine("素食") == ("轻食茶饮", "素食轻食")
    assert classify_cuisine("酒吧") == ("夜宵酒吧", "酒吧夜店")
    assert classify_cuisine("自助餐") == ("便捷小吃", "自助餐")
    assert classify_cuisine("小吃") == ("便捷小吃", "小吃快餐")
    assert classify_cuisine("烤鸭") == ("中餐经典", "北方风味")
    assert classify_cuisine("中餐") == ("中餐经典", "其他地方菜")


def test_empty_and_unknown():
    assert classify_cuisine(None) == (None, None)
    assert classify_cuisine("") == (None, None)


def test_space_insensitive():
    """「South East Asian」「Dim Sum」等带空格英文词可命中。"""
    assert classify_cuisine("South East Asian") == ("异国风味", "东南亚菜")
    assert classify_cuisine("Dim Sum") == ("中餐经典", "粤式茶点")

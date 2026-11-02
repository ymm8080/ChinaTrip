"""§4 产品过滤共享闸测试（词表正典性 + 接线行为，2026-11-03）。"""

from app.services.product_filter import (
    apply_product_filter,
    red_exclusion_reason,
    write_excluded_csv,
)


def test_red_tokens_hit_with_reason():
    cases = {
        "平津战役纪念馆": "§4关键词:战役",
        "中共满洲省委旧址": "§4关键词:中共",
        "八路军太行纪念馆": "§4关键词:八路军",
        "湘江战役红色纪念园": "§4关键词:红色",
        "周恩来故居": "§4人名:周恩来",
        "宋庆龄儿童科学技术馆": "§4人名:宋庆龄",
    }
    for name, want in cases.items():
        assert red_exclusion_reason(name) == want, name


def test_keep_samples_not_matched():
    """§4 保留类（古代人物/事件类）不得误伤。"""
    for name in (
        "杜甫草堂",
        "武侯祠",
        "三苏祠",
        "八大山人纪念馆",
        "蒲松龄故居",
        "李白纪念馆",
        "林则徐纪念馆",
        "大足石刻",
        "良渚博物院",
        "汶川特大地震纪念馆",
        "上海犹太难民纪念馆",
        "北海公园",
        "西湖风景名胜区",
    ):
        assert red_exclusion_reason(name) is None, name


def test_apply_product_filter_split():
    rows = [
        {"source": "museum1", "city": "重庆", "name_zh": "重庆红岩革命纪念馆"},
        {"source": "museum1", "city": "北京", "name_zh": "故宫博物院"},
    ]
    kept, excluded = apply_product_filter(rows)
    assert [r["name_zh"] for r in kept] == ["故宫博物院"]
    assert len(excluded) == 1
    assert excluded[0]["exclusion_reason"] == "§4关键词:革命"


def test_write_excluded_csv_roundtrip(tmp_path):
    rows = [
        {
            "source": "museum1",
            "city": "天津",
            "name_zh": "平津战役纪念馆",
            "batch": "一",
        },
    ]
    _, excluded = apply_product_filter(rows)
    p = tmp_path / "x_excluded.csv"
    write_excluded_csv(
        str(p), excluded, fields=("source", "city", "name_zh", "exclusion_reason")
    )
    import csv as _csv

    with open(p, encoding="utf-8-sig", newline="") as f:
        out = list(_csv.DictReader(f))
    assert len(out) == 1
    assert out[0]["name_zh"] == "平津战役纪念馆"
    assert out[0]["exclusion_reason"] == "§4关键词:战役"


def test_museum_grades_import_filters_red_rows(tmp_path):
    """接线测试：红色名单行在导入前被剔除并落 excluded CSV。"""
    import csv as _csv

    import app.jobs.import_museum_grades as job

    csv_path = tmp_path / "museum_grades.csv"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = _csv.DictWriter(
            f, fieldnames=["name_zh", "province", "city", "grade", "batch", "alias_zh"]
        )
        w.writeheader()
        w.writerow(
            {
                "name_zh": "某红军战役纪念馆",
                "province": "江西",
                "city": "瑞金",
                "grade": "国家一级博物馆",
                "batch": "一",
                "alias_zh": "",
            }
        )
        w.writerow(
            {
                "name_zh": "故宫博物院",
                "province": "北京",
                "city": "北京",
                "grade": "国家一级博物馆",
                "batch": "一",
                "alias_zh": "",
            }
        )
    rows, invalid = job.load_rows(str(csv_path))
    assert invalid == 0
    kept, excluded = job.apply_product_filter(rows)
    assert [r["name_zh"] for r in kept] == ["故宫博物院"]
    assert excluded[0]["name_zh"] == "某红军战役纪念馆"
    assert excluded[0]["exclusion_reason"] == "§4关键词:红军"


def test_shows_source_csv_red_rows_excluded():
    """接线测试（真实数据）：04 演出 CSV 的红色题材行（红秀/西安事变）
    被过滤器剔除——2026-11-03 用户拍板后的回流防线。"""
    import app.jobs.import_shows as job
    from app.services.product_filter import apply_product_filter as _apf

    rows = job.load_rows("../DESIGN/POIS DATASOURCE/04_演艺演出_主要旅游城市.csv")
    kept, excluded = _apf(rows)
    excluded_names = {r["name_zh"] for r in excluded}
    assert any("延安" in n for n in excluded_names), excluded_names
    assert any("西安事变" in n for n in excluded_names), excluded_names
    kept_names = {r["name_zh"] for r in kept}
    assert not any("延安" in n or "西安事变" in n for n in kept_names)

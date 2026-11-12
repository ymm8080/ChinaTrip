"""Tests for 2026-11-12 免费新源：Wikipedia media-list / Commons 搜索 /
官网 og:image（poi_photos 扩链）——纯解析器单测 + 链序验证，无真网络。"""

import asyncio
from types import SimpleNamespace

import app.services.poi_photos as pp

# --- 解析器 -------------------------------------------------------------------


def test_parse_media_items_original_thumb_and_mime_filter():
    data = {
        "items": [
            {
                "title": "File:A.jpg",
                "mime": "image/jpeg",
                "original": {"source": "https://upload.wikimedia.org/a.jpg"},
            },
            # 协议相对补 https:
            {
                "title": "File:B.jpg",
                "mime": "image/png",
                "thumb": {"url": "//upload.wikimedia.org/b800.jpg"},
            },
            # 非 image mime 剔除
            {
                "title": "V",
                "mime": "video/mp4",
                "original": {"source": "https://x/v.mp4"},
            },
            {"title": "N", "mime": "image/jpeg"},  # 无 url 剔除
        ]
    }
    out = pp._parse_media_items(data)
    assert [o["url"] for o in out] == [
        "https://upload.wikimedia.org/a.jpg",
        "https://upload.wikimedia.org/b800.jpg",
    ]


def test_parse_commons_pages_name_guard_and_thumb_pref():
    data = {
        "query": {
            "pages": {
                "1": {
                    "title": "File:西湖全景.jpg",
                    "imageinfo": [
                        {"mime": "image/jpeg", "thumburl": "https://c/w800.jpg"}
                    ],
                },
                "2": {  # 文件名不含「西湖」→ 防张冠李戴剔除
                    "title": "File:Unrelated.jpg",
                    "imageinfo": [{"mime": "image/png", "url": "https://c/u.png"}],
                },
                "3": {  # 无 imageinfo 剔除
                    "title": "File:西湖-空.png",
                },
            }
        }
    }
    out = pp._parse_commons_pages(data, "西湖")
    assert [o["url"] for o in out] == ["https://c/w800.jpg"]


def test_official_og_sync_requires_absolute_url(monkeypatch):
    # 非法 website 直接 None，不发请求
    assert pp._official_og_sync("not-a-url") is None
    assert pp._official_og_sync("") is None


# --- 链序：media-list → commons → official og → P18 ---------------------------


def _run_chain(monkeypatch, results, website=None):
    order = []

    def make_fake(fnname):
        async def fake(name):
            order.append(fnname)
            return results.get(fnname)

        return fake

    for fname in (
        "_commons_search",
        "_wikimedia",
    ):
        monkeypatch.setattr(pp, fname, make_fake(fname))
    monkeypatch.setattr(pp, "_official_og", make_fake("_official_og"))

    row = SimpleNamespace(
        name_zh="西湖",
        city="杭州",
        source="unesco",
        source_poi_id=None,
        location=None,
        website=website,
    )
    photos, source = asyncio.run(pp.fetch_photo_chain(row, amap=None))
    return order, photos, source


def test_chain_media_list_wins(monkeypatch):
    order, photos, source = _run_chain(
        monkeypatch,
        {"_commons_search": [{"title": "", "url": "https://u/1.jpg"}]},
    )
    assert order == ["_commons_search"]
    assert source == "wikimedia"


def test_chain_falls_through_to_official_og(monkeypatch):
    og = [{"title": "", "url": "https://official/x.jpg"}]
    order, photos, source = _run_chain(
        monkeypatch,
        {"_official_og": og},
        website="https://www.xihu.example.cn",
    )
    assert order == ["_commons_search", "_official_og"]
    assert source == "official"


def test_chain_all_empty_returns_none(monkeypatch):
    order, photos, source = _run_chain(monkeypatch, {})
    assert order == ["_commons_search", "_wikimedia"]
    assert photos is None
    assert source is None

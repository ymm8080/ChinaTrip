"""app.jobs.backfill_intro 测试：MockTransport 喂假 Wikidata/Wikipedia 响应 +
假 session factory（预置 Poi 行），不触网、不落库。"""

import uuid
from urllib.parse import unquote, urlsplit

import httpx

from app.jobs import backfill_intro as job
from app.jobs.backfill_intro import backfill_intro, select_targets
from app.models import Poi

LONG_EXTRACT = (
    "洪崖洞位于重庆市渝中区嘉陵江滨江路，是集巴渝民俗文化、"
    "餐饮与夜景于一体的吊脚楼建筑群，夜景尤为出名。"
)
SHORT_EXTRACT = "洪崖洞，重庆景点。"
P18_FILE = "Hongya_Cave.jpg"


# --- 假 session factory（预置 Poi 行，query/filter 只做取数） ----------------


class FakeQuery:
    def __init__(self, rows: list[Poi]) -> None:
        self._rows = list(rows)
        self._limit: int | None = None

    def filter(self, *criteria: object) -> "FakeQuery":
        return self

    def limit(self, n: int) -> "FakeQuery":
        self._limit = n
        return self

    def all(self) -> list[Poi]:
        if self._limit is not None:
            return self._rows[: self._limit]
        return list(self._rows)


class FakeSession:
    def __init__(self, rows: list[Poi]) -> None:
        self.rows = list(rows)
        self.commits = 0

    def query(self, model: object) -> FakeQuery:
        return FakeQuery(self.rows)

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:
        pass

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def fake_factory(rows: list[Poi]):
    return lambda: FakeSession(rows)


def make_poi(
    *,
    name_zh: str = "洪崖洞",
    city: str | None = "重庆市",
    intro: str | None = None,
    intro_source: str | None = None,
    photos: list | None = None,
    photos_source: str | None = None,
) -> Poi:
    return Poi(
        id=uuid.uuid4(),
        source="amap",
        source_poi_id=f"B{uuid.uuid4().hex[:10]}",
        city=city,
        name_zh=name_zh,
        status="active",
        intro=intro,
        intro_source=intro_source,
        photos=photos,
        photos_source=photos_source,
    )


# --- 假 Wikimedia / Wikipedia 响应 -------------------------------------------


def p18_claims(filename: str) -> dict:
    return {
        "P18": [
            {
                "mainsnak": {
                    "snaktype": "value",
                    "datavalue": {"value": filename, "type": "string"},
                }
            }
        ]
    }


def make_handler(
    *,
    qid: str | None = "Q123",
    claims: dict | None = None,
    zhwiki_title: str | None = "洪崖洞",
    wikitext: str | None = LONG_EXTRACT,
    calls: list | None = None,
):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        url = request.url
        if url.host == "www.wikidata.org" and url.path == "/w/api.php":
            assert request.headers["user-agent"].startswith("ChinaTrip-POI-library/")
            assert url.params.get("action") == "wbsearchentities"
            assert url.params.get("language") == "zh"
            body = {"search": [{"id": qid, "label": "洪崖洞"}] if qid else []}
            return httpx.Response(200, json=body)
        if url.host == "www.wikidata.org" and unquote(url.path) == (
            f"/wiki/Special:EntityData/{qid}.json"
        ):
            entity = {
                "claims": claims if claims is not None else {},
                "sitelinks": (
                    {"zhwiki": {"site": "zhwiki", "title": zhwiki_title}}
                    if zhwiki_title
                    else {}
                ),
            }
            return httpx.Response(200, json={"entities": {qid: entity}})
        if url.host == "api.wikimedia.org" and url.path.startswith(
            "/core/v1/wikipedia/zh/page/"
        ):
            return httpx.Response(200, json={"source": wikitext})
        return httpx.Response(404, json={"error": f"unexpected {url}"})

    return handler


def make_client(handler) -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(handler),
        headers={"User-Agent": job.USER_AGENT},
        timeout=5.0,
    )


# --- 用例 --------------------------------------------------------------------


def test_full_hit_fills_intro_and_photos():
    row = make_poi()
    calls: list[str] = []
    client = make_client(make_handler(claims=p18_claims(P18_FILE), calls=calls))
    stats = backfill_intro(fake_factory([row]), client, sleep_seconds=0.0)

    assert stats == {
        "targets": 1,
        "intro_filled": 1,
        "photos_filled": 1,
        "no_entity": 0,
        "no_sitelink": 0,
        "no_extract": 0,
        "no_p18": 0,
        "errors": 0,
    }
    assert row.intro == LONG_EXTRACT
    # intro 取自 api.wikimedia.org 页面 wikitext 抽取（标题来自 sitelink）
    assert row.intro_source == "wikimedia_api"
    assert row.photos_source == "wikimedia"
    assert row.photos == [
        {
            "url": (
                "https://commons.wikimedia.org/wiki/Special:FilePath/"
                f"{P18_FILE}?width=800"
            ),
            "source": "wikimedia",
            "license": "CC",
        }
    ]
    for entry in row.photos:
        assert set(entry) == {"url", "source", "license"}
    # 请求顺序：搜索 → 实体 → zh 页面，且都打到预期主机
    assert "action=wbsearchentities" in calls[0]
    assert "Special:EntityData/Q123.json" in calls[1]
    assert urlsplit(calls[2]).hostname == "api.wikimedia.org"


def test_existing_intro_not_overwritten():
    row = make_poi(intro="已有官方简介", intro_source="manual")
    calls: list[str] = []
    client = make_client(make_handler(claims=p18_claims(P18_FILE), calls=calls))
    stats = backfill_intro(fake_factory([row]), client, sleep_seconds=0.0)

    assert row.intro == "已有官方简介"
    assert row.intro_source == "manual"
    assert stats["intro_filled"] == 0
    assert stats["no_extract"] == 0
    # intro 已有 → 不发 summary 请求；photos 仍回填
    assert not any("zh.wikipedia.org" in c for c in calls)
    assert stats["photos_filled"] == 1
    assert row.photos_source == "wikimedia"


def test_existing_photos_not_overwritten():
    existing = [{"url": "https://example.com/a.jpg", "source": "amap", "license": ""}]
    row = make_poi(photos=existing, photos_source="amap")
    client = make_client(make_handler(claims=p18_claims(P18_FILE)))
    stats = backfill_intro(fake_factory([row]), client, sleep_seconds=0.0)

    assert row.photos == existing
    assert row.photos_source == "amap"
    assert stats["photos_filled"] == 0
    assert stats["no_p18"] == 0
    assert stats["intro_filled"] == 1


def test_no_entity():
    row = make_poi(name_zh="不存在的景点名")
    client = make_client(make_handler(qid=None))
    stats = backfill_intro(fake_factory([row]), client, sleep_seconds=0.0)

    assert stats["no_entity"] == 1
    assert stats["intro_filled"] == 0
    assert stats["photos_filled"] == 0
    assert stats["errors"] == 0
    assert row.intro is None
    assert row.photos is None


def test_short_extract_not_used():
    row = make_poi()
    client = make_client(
        make_handler(claims=p18_claims(P18_FILE), wikitext=SHORT_EXTRACT)
    )
    stats = backfill_intro(fake_factory([row]), client, sleep_seconds=0.0)

    assert stats["no_extract"] == 1
    assert row.intro is None
    assert row.intro_source is None
    # extract 不合格不影响 photos 回填
    assert stats["photos_filled"] == 1


def test_no_p18():
    row = make_poi()
    client = make_client(make_handler(claims={}))
    stats = backfill_intro(fake_factory([row]), client, sleep_seconds=0.0)

    assert stats["no_p18"] == 1
    assert row.photos is None
    assert row.photos_source is None
    assert stats["intro_filled"] == 1
    assert row.intro == LONG_EXTRACT


def test_limit_only_processes_n_rows():
    rows = [make_poi(), make_poi(), make_poi()]
    client = make_client(make_handler(claims=p18_claims(P18_FILE)))
    stats = backfill_intro(fake_factory(rows), client, limit=2, sleep_seconds=0.0)

    assert stats["targets"] == 2
    assert rows[0].intro == LONG_EXTRACT
    assert rows[1].intro == LONG_EXTRACT
    assert rows[2].intro is None
    assert rows[2].photos is None


def test_city_filter_strips_shi_suffix():
    cq = make_poi(city="重庆")
    cqs = make_poi(city="重庆市")
    bj = make_poi(city="北京")
    noname_city = make_poi(city=None)
    factory = fake_factory([cq, cqs, bj, noname_city])
    client = make_client(make_handler(claims=p18_claims(P18_FILE)))

    matched = select_targets(factory, limit=100, city="重庆")
    assert {id(r) for r in matched} == {id(cq), id(cqs)}

    stats = backfill_intro(factory, client, limit=100, city="重庆", sleep_seconds=0.0)
    assert stats["targets"] == 2
    assert bj.intro is None
    assert noname_city.intro is None


def test_empty_intro_string_is_a_target():
    row = make_poi(intro="")  # 空串视同 NULL
    client = make_client(make_handler(claims=p18_claims(P18_FILE)))
    stats = backfill_intro(fake_factory([row]), client, sleep_seconds=0.0)

    assert stats["targets"] == 1
    assert stats["intro_filled"] == 1
    assert row.intro == LONG_EXTRACT


def test_user_agent_constant_has_contact():
    # Wikimedia UA 政策要求带联系方式
    assert "ChinaTrip-POI-library" in job.USER_AGENT
    assert "mailto:" in job.USER_AGENT

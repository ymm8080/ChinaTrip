"""app.jobs.backfill_intro_llm 测试：MockTransport 喂假智谱响应 + 假
session factory（预置 Poi 行），不触网、不落库、不调真实 LLM。"""

import asyncio
import json
import uuid

import httpx
import pytest

from app.jobs.backfill_intro_llm import (
    _validate_intro,
    backfill_intro_llm,
    dry_run,
    select_targets,
)
from app.models import Poi
from app.services.llm.base import ChatResult
from app.services.llm.zhipu import ZhipuGLMAdapter

INTRO = (
    "洪崖洞位于重庆渝中区嘉陵江畔，是依山而建的吊脚楼建筑群，"
    "夜景灯火璀璨，是重庆最知名的地标之一。"
)


# --- 假 session factory（预置 Poi 行，query/filter 只做取数） ----------------


class FakeQuery:
    def __init__(self, rows: list[Poi]) -> None:
        self._rows = list(rows)
        self._limit: int | None = None

    def filter(self, *criteria: object) -> "FakeQuery":
        return self

    def order_by(self, *criteria: object) -> "FakeQuery":
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

    def get(self, model: object, pk: object) -> Poi | None:
        for row in self.rows:
            if row.id == pk:
                return row
        return None

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
    category: str | None = "attraction",
    intro: str | None = None,
    intro_source: str | None = None,
) -> Poi:
    return Poi(
        id=uuid.uuid4(),
        source="amap",
        source_poi_id=f"B{uuid.uuid4().hex[:10]}",
        city=city,
        name_zh=name_zh,
        category=category,
        status="active",
        intro=intro,
        intro_source=intro_source,
    )


# --- 假智谱适配器（MockTransport 注入） ---------------------------------------


def make_adapter(handler) -> ZhipuGLMAdapter:
    return ZhipuGLMAdapter(
        api_key="secret-key",
        base_url="https://glm.test/api/paas/v4",
        model="glm-5.3-flash",
        timeout_seconds=5.0,
        transport=httpx.MockTransport(handler),
    )


def glm_ok(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        },
    )


def prompt_text(request: httpx.Request) -> str:
    return json.loads(request.content)["messages"][1]["content"]


# --- 用例 --------------------------------------------------------------------


def test_normal_generation_fills_row():
    row = make_poi()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer secret-key"
        body = json.loads(request.content)
        # 探针硬规格：思考模型必须 max_tokens=1024，否则正文被吃光
        assert body["max_tokens"] == 1024
        assert body["model"] == "glm-5.3-flash"
        assert body["messages"][0]["role"] == "system"
        sent = prompt_text(request)
        assert "洪崖洞" in sent
        assert "重庆市" in sent
        assert "attraction" in sent
        return glm_ok(INTRO)

    stats = asyncio.run(backfill_intro_llm(fake_factory([row]), make_adapter(handler)))

    assert stats == {
        "targets": 1,
        "filled": 1,
        "skipped": 0,
        "rejected": 0,
        "rejected_by_reason": {},
        "errors": 0,
        "tokens_in": 100,
        "tokens_out": 50,
    }
    assert row.intro == INTRO
    assert row.intro_source == "llm"


def test_skip_prefix_leaves_row_untouched():
    # 探针：模型对辨认不出的行回 "SKIP\n\n(Note: ...)"——前缀判定即 skip
    row = make_poi()
    content = "skip\n\n(Note: this place could not be identified)"
    stats = asyncio.run(
        backfill_intro_llm(
            fake_factory([row]), make_adapter(lambda req: glm_ok(content))
        )
    )

    assert stats["skipped"] == 1
    assert stats["filled"] == 0
    assert stats["rejected"] == 0
    assert row.intro is None
    assert row.intro_source is None


def test_llm_error_counts_and_continues():
    bad = make_poi(name_zh="哑炮景点")
    good = make_poi(name_zh="故宫")

    def handler(request: httpx.Request) -> httpx.Response:
        if "哑炮景点" in prompt_text(request):
            raise httpx.ConnectError("boom")
        return glm_ok(INTRO)

    stats = asyncio.run(
        backfill_intro_llm(fake_factory([bad, good]), make_adapter(handler))
    )

    assert stats["errors"] == 1
    assert stats["filled"] == 1
    assert stats["targets"] == 2
    assert bad.intro is None
    assert good.intro == INTRO
    assert stats["tokens_in"] == 100  # 只累计成功那条


def test_rows_with_intro_not_selected():
    filled = make_poi(intro="已有官方简介", intro_source="manual")
    null_intro = make_poi()
    empty_intro = make_poi(intro="")

    targets = select_targets(fake_factory([filled, null_intro, empty_intro]))
    assert {id(r) for r in targets} == {id(null_intro), id(empty_intro)}


def test_dry_run_prints_without_api_or_write(capsys):
    rows = [make_poi(name_zh="景点一"), make_poi(name_zh="景点二")]
    # dry_run 没有 adapter 参数——物理上不可能调 API；只验证打印与不写库
    dry_run(fake_factory(rows), limit=10)

    out = capsys.readouterr().out.splitlines()
    payload = json.loads(out[0])
    assert payload == {"dry_run": True, "targets": 2}
    sample = json.loads(out[1])
    assert sample["name"] == "景点一"
    assert sample["source"] == "amap"
    assert len(out) == 3  # 行数一行 + 前 2 个样例
    for row in rows:
        assert row.intro is None


# --- 校验层（_validate_intro 纯函数 + 端到端 rejected 计数） -------------------


def test_validate_intro_passes_normal_text():
    assert _validate_intro(INTRO, name_zh="洪崖洞") is None


def test_validate_intro_echo_and_too_long():
    long_name = "秦始皇兵马俑博物馆位于陕西省西安市临潼区的景区"
    assert _validate_intro(long_name, name_zh=long_name) == "echo"
    assert _validate_intro("长" * 301) == "too_long"


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        ("洪崖洞。", "too_short"),
        ("The Bund is a famous waterfront landmark in Shanghai.", "no_cjk"),
        ("很抱歉，我无法确定这个景点的具体历史与位置信息。", "hedge"),
        ("以下是关于洪崖洞的一段简短中文介绍，希望对你有帮助。", "meta_text"),
    ],
)
def test_rejected_contents_counted_with_reason(content, reason):
    row = make_poi()
    stats = asyncio.run(
        backfill_intro_llm(
            fake_factory([row]), make_adapter(lambda req: glm_ok(content))
        )
    )

    assert stats["rejected"] == 1
    assert stats["rejected_by_reason"] == {reason: 1}
    assert stats["filled"] == 0
    assert row.intro is None


# --- 并发 --------------------------------------------------------------------


def test_concurrency_fills_all_rows():
    rows = [make_poi(name_zh=f"景点{i}") for i in range(4)]

    class SlowAdapter:
        name = "slow"

        def __init__(self) -> None:
            self.inflight = 0
            self.peak = 0

        async def chat(self, messages, *, temperature=0.3, max_tokens=None):
            self.inflight += 1
            self.peak = max(self.peak, self.inflight)
            await asyncio.sleep(0.01)
            self.inflight -= 1
            return ChatResult(content=INTRO, model="t", tokens_in=1, tokens_out=1)

    slow = SlowAdapter()
    stats = asyncio.run(backfill_intro_llm(fake_factory(rows), slow, concurrency=4))

    assert stats["targets"] == 4
    assert stats["filled"] == 4
    assert stats["errors"] == 0
    assert slow.peak >= 2  # 并发确实发生了
    assert stats["tokens_in"] == 4
    for row in rows:
        assert row.intro == INTRO
        assert row.intro_source == "llm"

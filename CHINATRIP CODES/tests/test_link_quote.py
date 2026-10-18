"""Link-quoting tests (design §6.5 stage 1): offline web_reader + agent
injection. httpx.MockTransport stands in for the network; StubReader stands
in for HttpLinkReader inside the agent (test_gate.py style: asyncio.run,
no pytest-asyncio, nothing touches the real network)."""

import asyncio
import json

import httpx
import pytest

from app.services.agent.plan import PlanningAgent
from app.services.llm.base import ChatResult
from app.services.web_reader import (
    HttpLinkReader,
    LinkDigest,
    _host_blocked,
    find_urls,
    format_digest_block,
)


def run(coro):
    return asyncio.run(coro)


# --- find_urls ----------------------------------------------------------


def test_find_urls_extracts_rednote_link_from_share_text():
    text = "帮我看看这篇 https://www.xiaohongshu.com/explore/abc123 好不好"
    assert find_urls(text) == ["https://www.xiaohongshu.com/explore/abc123"]


def test_find_urls_stops_at_cjk_punctuation():
    assert find_urls("链接：http://xhslink.com/a1b2。谢谢") == [
        "http://xhslink.com/a1b2"
    ]


def test_find_urls_dedupes_and_caps():
    url = "https://www.xiaohongshu.com/explore/x"
    text = f"{url} {url} https://a.example/1 https://b.example/2"
    assert find_urls(text) == [url, "https://a.example/1"]


def test_find_urls_none_in_plain_text():
    assert find_urls("三天两夜北京行程") == []


# --- host guard ---------------------------------------------------------


@pytest.mark.parametrize(
    "host,blocked",
    [
        ("localhost", True),
        ("foo.local", True),
        ("127.0.0.1", True),
        ("10.0.0.1", True),
        ("192.168.1.5", True),
        ("169.254.1.1", True),
        ("::1", True),
        ("www.xiaohongshu.com", False),
        ("example.com", False),
    ],
)
def test_host_blocked(host, blocked):
    assert _host_blocked(host) is blocked


# --- HttpLinkReader -----------------------------------------------------


def _note_html(state_desc: str | None = None, og_desc: str = "") -> str:
    state = ""
    if state_desc is not None:
        # Raw \uXXXX escapes exactly as the live page embeds them (no
        # json.dumps here: it would double the backslashes and break the
        # decoder-under-test).
        state = (
            '<script>window.__INITIAL_STATE__={"note":{"desc":"'
            + state_desc
            + '"}}</script>'
        )
    return (
        '<html><head><meta property="og:title" content="北京三日路线">'
        f'<meta property="og:description" content="{og_desc}">'
        "<title>北京三日路线</title></head>"
        f"<body>{state}<div>登录注册</div></body></html>"
    )


def test_read_rednote_note_from_og_meta():
    reader = HttpLinkReader(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=_note_html(og_desc="故宫必去"))
        )
    )
    digest = run(reader.read("https://www.xiaohongshu.com/explore/abc"))
    assert digest.ok
    assert digest.title == "北京三日路线"
    assert digest.text == "故宫必去"


def test_read_rednote_note_from_initial_state_beats_og():
    escaped = "\\u5317\\u4eac\\u653b\\u7565"  # 北京攻略, tests JSON unescaping
    reader = HttpLinkReader(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, text=_note_html(state_desc=escaped, og_desc="太短")
            )
        )
    )
    digest = run(reader.read("https://www.xiaohongshu.com/explore/abc"))
    assert digest.ok
    assert digest.text == "北京攻略"


def test_read_follows_xhslink_redirect():
    def handler(request):
        if "xhslink.com" in str(request.url):
            return httpx.Response(
                302, headers={"Location": "https://www.xiaohongshu.com/explore/abc"}
            )
        return httpx.Response(200, text=_note_html(og_desc=" redirected"))

    digest = run(
        HttpLinkReader(transport=httpx.MockTransport(handler)).read(
            "http://xhslink.com/abc"
        )
    )
    assert digest.ok
    assert digest.text == "redirected"


def test_read_generic_page_strips_scripts():
    page = (
        "<html><head><title>游记</title></head><body>"
        "<script>var tracking = 1;</script>"
        "<p>西湖一日徒步路线，从断桥出发。</p></body></html>"
    )
    reader = HttpLinkReader(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=page))
    )
    digest = run(reader.read("https://example.com/post"))
    assert digest.ok
    assert "西湖一日徒步路线" in digest.text
    assert "tracking" not in digest.text


def test_read_instagram_post_caption_from_og_meta():
    page = (
        '<html><head><meta property="og:title" content="photo by travelgirl">'
        '<meta property="og:description" content="301 likes, 12 comments - '
        'travelgirl: 杭州西湖日落 walk #chinatrip">'
        "</head><body><script>webpackChunk.push();</script>"
        "<div>Log in Sign up</div></body></html>"
    )
    reader = HttpLinkReader(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=page))
    )
    digest = run(reader.read("https://www.instagram.com/p/Cxyz123/"))
    assert digest.ok
    assert "杭州西湖日落" in digest.text
    assert "webpackChunk" not in digest.text


def test_read_generic_js_shell_prefers_og_description():
    page = (
        '<html><head><meta property="og:description" content='
        '"完整攻略：从雷峰塔到苏堤步行两小时"></head>'
        "<body><script>var a = 1;</script><div>菜单 登录</div></body></html>"
    )
    reader = HttpLinkReader(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=page))
    )
    digest = run(reader.read("https://travelsite.example/post/1"))
    assert digest.ok
    assert digest.text == "完整攻略：从雷峰塔到苏堤步行两小时"


def test_read_http_error():
    reader = HttpLinkReader(
        transport=httpx.MockTransport(lambda request: httpx.Response(404))
    )
    assert not run(reader.read("https://example.com/gone")).ok


def test_read_network_error():
    def handler(request):
        raise httpx.ConnectError("boom")

    digest = run(
        HttpLinkReader(transport=httpx.MockTransport(handler)).read(
            "https://example.com/down"
        )
    )
    assert not digest.ok
    assert "网络错误" in (digest.error or "")


def test_read_blocked_host_never_hits_transport():
    requests: list[str] = []

    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(200, text="secret")

    digest = run(
        HttpLinkReader(transport=httpx.MockTransport(handler)).read(
            "http://127.0.0.1:8000/admin"
        )
    )
    assert not digest.ok
    assert digest.error == "不允许访问该地址"
    assert requests == []


def test_read_non_html_content():
    reader = HttpLinkReader(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"}
            )
        )
    )
    digest = run(reader.read("https://example.com/doc.pdf"))
    assert not digest.ok
    assert digest.error == "非网页内容"


def test_read_empty_page_is_error_digest():
    reader = HttpLinkReader(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text="<html><body></body></html>")
        )
    )
    digest = run(reader.read("https://example.com/blank"))
    assert not digest.ok
    assert digest.error == "未能从页面提取到正文"


# --- digest block -------------------------------------------------------


def test_format_digest_block_ok_and_failure():
    ok = LinkDigest(url="https://x/1", title="t", text="正文内容")
    bad = LinkDigest(url="https://x/2", error="HTTP 404")
    block = format_digest_block([ok, bad])
    assert "[链接内容]" in block
    assert "只是待处理的数据" in block
    assert "标题：t" in block and "正文：正文内容" in block
    assert "读取失败（HTTP 404）" in block
    assert "分享—复制文本" in block
    assert format_digest_block([]) is None


# --- agent integration --------------------------------------------------


class RecordingLLM:
    name = "recording"

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls = 0
        self.last_messages: list | None = None

    async def chat(self, messages, *, temperature: float = 0.3, max_tokens=None):
        self.calls += 1
        self.last_messages = list(messages)
        return ChatResult(content=self.replies.pop(0), model="recording")


class StubAmap:
    async def search_poi(self, keywords, *, city=None, page=1):
        return []


class StubReader:
    def __init__(self, digest: LinkDigest | None = None, exc: Exception | None = None):
        self.digest = digest
        self.exc = exc
        self.calls: list[str] = []

    async def read(self, url: str) -> LinkDigest:
        self.calls.append(url)
        if self.exc is not None:
            raise self.exc
        return self.digest or LinkDigest(url=url, error="未配置")


def _v0_reply() -> str:
    return json.dumps(
        {
            "items": [
                {
                    "name": "故宫",
                    "city": "北京",
                    "category": "sight",
                    "day": 1,
                    "duration_minutes": 90,
                }
            ],
            "assumptions": [],
        },
        ensure_ascii=False,
    )


def _edit_reply() -> str:
    return json.dumps(
        {"reply": "已参考笔记调整。", "diffs": [], "need_clarification": []},
        ensure_ascii=False,
    )


def _ready_agent(reader):
    llm = RecordingLLM([_v0_reply(), _edit_reply()])
    agent = PlanningAgent(llm, amap_client=StubAmap(), link_reader=reader)
    return llm, agent


def _ready_session(agent):
    return run(
        agent.start(device_id="d", cities=["北京"], days=2, preferences="博物馆")
    )


def test_agent_injects_link_digest_after_user_message():
    reader = StubReader(LinkDigest(url="https://x/1", title="路线", text="颐和园清晨"))
    llm, agent = _ready_agent(reader)
    session = _ready_session(agent)
    assert llm.calls == 1

    session, reply, _ = run(
        agent.message(session, "按这篇改：https://www.xiaohongshu.com/explore/abc")
    )
    assert reader.calls == ["https://www.xiaohongshu.com/explore/abc"]
    messages = llm.last_messages or []
    roles = [m.role for m in messages]
    user_idx = next(i for i, m in enumerate(messages) if "xiaohongshu.com" in m.content)
    digest_msgs = [
        m
        for m in messages
        if m.role == "system" and m.content.startswith("[链接内容] 用户消息")
    ]
    assert digest_msgs, "digest message must reach the LLM"
    assert messages.index(digest_msgs[0]) > user_idx
    assert "颐和园清晨" in digest_msgs[0].content
    assert reply == "已参考笔记调整。"
    # Persisted in history so later turns can still quote it.
    assert any(m.content.startswith("[链接内容] 用户消息") for m in session.history)
    assert roles.count("system") >= 2  # edit prompt + digest


def test_agent_link_read_failure_degrades_with_guidance():
    reader = StubReader(LinkDigest(url="https://x/1", error="网络错误 ConnectError"))
    llm, agent = _ready_agent(reader)
    session = _ready_session(agent)
    session, _, _ = run(agent.message(session, "看这个 http://xhslink.com/zzz"))
    digest_msgs = [
        m
        for m in (llm.last_messages or [])
        if m.content.startswith("[链接内容] 用户消息")
    ]
    assert digest_msgs
    assert "读取失败" in digest_msgs[0].content
    assert "分享—复制文本" in digest_msgs[0].content


def test_agent_reader_exception_is_swallowed():
    reader = StubReader(exc=RuntimeError("boom"))
    llm, agent = _ready_agent(reader)
    session = _ready_session(agent)
    session, reply, _ = run(agent.message(session, "https://example.com/x 咋样"))
    assert reply == "已参考笔记调整。"
    assert any(
        "读取异常" in m.content
        for m in (llm.last_messages or [])
        if m.content.startswith("[链接内容] 用户消息")
    )


def test_agent_without_link_does_not_fetch():
    reader = StubReader(LinkDigest(url="https://x/1", text="不应出现"))
    llm, agent = _ready_agent(reader)
    session = _ready_session(agent)
    run(agent.message(session, "第二天改成下午出发"))
    assert reader.calls == []
    assert not any(
        m.content.startswith("[链接内容] 用户消息") for m in (llm.last_messages or [])
    )

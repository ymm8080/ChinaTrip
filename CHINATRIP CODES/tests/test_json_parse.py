"""parse_json_content must survive glm flash narrating before the JSON.

Production shape (uvicorn_h5_1018e.log 2026-10-19, session 2efc8ed9…):
the edit-round reply leads with a friendly Chinese sentence, then the
required JSON object — plain json.loads fails at char 0 and the user sees
「刚才模型回复没能解析，已自动重试仍未成功，请再发一次」even though
the JSON payload itself is valid.
"""

import asyncio

import httpx
import pytest

from app.services.llm.base import parse_json_content
from app.services.llm.zhipu import ZhipuGLMAdapter

EDIT_REPLY = (
    "已把你笔记里的三家江湖菜加入第1天：14:30 老甘家、16:30 憨邓、"
    "18:30 秋姐三样菜。\n\n"
    '{"reply":"已加入","diffs":[{"op":"add","item":{"name":"老甘家",'
    '"city":"重庆","category":"美食","day":1,"duration_minutes":90}}],'
    '"need_clarification":[]}'
)
JSON_PART = EDIT_REPLY.split("\n\n", 1)[1]


def test_prose_then_json_object():
    assert parse_json_content(EDIT_REPLY)["reply"] == "已加入"


def test_prose_then_fenced_json():
    content = f"说明文字在前。\n```json\n{JSON_PART}\n```"
    assert parse_json_content(EDIT_REPLY)["diffs"][0]["op"] == "add"
    assert parse_json_content(content)["diffs"][0]["op"] == "add"


def test_json_then_trailing_prose():
    assert parse_json_content('{"reply":"好"}\n以上。') == {"reply": "好"}


def test_broken_brace_in_prose_is_skipped():
    content = '统计 {未闭合 括号 {"reply":"ok"}'
    assert parse_json_content(content) == {"reply": "ok"}


def test_plain_and_leading_fence_still_parse():
    assert parse_json_content('{"a":1}') == {"a": 1}
    assert parse_json_content('```json\n{"a":2}\n```') == {"a": 2}


def test_prose_without_json_raises():
    with pytest.raises(ValueError):
        parse_json_content("今天天气不错，没有结构化内容。")


def test_array_is_not_an_object():
    with pytest.raises(ValueError):
        parse_json_content("[1, 2, 3]")


def _prose_then_extract_json(request: httpx.Request) -> httpx.Response:
    content = (
        "先说两句：外滩值得一去。\n"
        '{"candidates":[{"name":"外滩","city":"上海","confidence":0.9}],'
        '"assum":[]}'
    )
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {},
        },
    )


def test_zhipu_extract_tolerates_prose_prefix():
    adapter = ZhipuGLMAdapter(
        api_key="k",
        base_url="https://example.invalid",
        model="m",
        timeout_seconds=5,
        transport=httpx.MockTransport(_prose_then_extract_json),
    )
    result = asyncio.run(adapter.extract("外滩"))
    assert [c.name for c in result.candidates] == ["外滩"]

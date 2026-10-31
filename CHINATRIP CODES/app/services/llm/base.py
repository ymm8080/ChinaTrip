"""LLM adapter contract (design v2.0 §2.1 / §6.12).

MVP = zhipu cloud GLM (v1.9.9 canonical path); mock adapter for offline dev.
Beyond /extract, adapters expose a generic `chat` used by the classification
gate (Flash tier), translation fast lane, and the planning agent.
"""

import json
from typing import Protocol

from pydantic import BaseModel, Field


class POICandidate(BaseModel):
    name: str
    city: str | None = None
    category: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    poi_id: str | None = None


class ExtractResult(BaseModel):
    candidates: list[POICandidate] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    quarantined: bool = False
    model: str = "mock"
    tokens_in: int = 0
    tokens_out: int = 0


class ChatMessage(BaseModel):
    role: str  # "system" | "user" | "assistant"
    content: str


class ChatResult(BaseModel):
    content: str
    model: str = "mock"
    tokens_in: int = 0
    tokens_out: int = 0


def strip_code_fences(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        newline = text.find("\n")
        text = text[newline + 1 :] if newline != -1 else ""
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


def parse_json_content(content: str) -> dict:
    """Parse a JSON object out of an LLM reply.

    Tolerates code fences and prose around the object: glm flash narrates
    a friendly sentence before emitting the required JSON (production
    2026-10-19), which made plain json.loads fail at char 0.

    Raises ValueError when the reply contains no JSON object.
    """
    text = strip_code_fences(content)
    try:
        raw = json.loads(text)
    except ValueError:
        raw = _first_json_object(text)
    if not isinstance(raw, dict):
        raise ValueError("not a json object")
    return raw


def _first_json_object(text: str) -> object:
    decoder = json.JSONDecoder()
    for idx, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text, idx)
        except ValueError:
            continue
        return obj
    raise ValueError("no json object in reply")


class LLMAdapter(Protocol):
    name: str

    async def extract(self, text: str, *, lang: str = "zh") -> ExtractResult: ...

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> ChatResult: ...

    async def chat_vision(
        self,
        images: list[tuple[bytes, str]],
        prompt: str,
    ) -> str:
        """图片理解（行程导入 OCR 等）：images 为 (字节, mime) 列表，返回
        纯文本。视觉模型不可用/全部 429 时抛 LLMError（zhipu 实现）。"""
        ...

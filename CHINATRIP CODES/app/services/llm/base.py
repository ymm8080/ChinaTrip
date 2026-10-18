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
    """Parse a JSON object out of an LLM reply (tolerates code fences).

    Raises ValueError when the reply is not a JSON object.
    """
    raw = json.loads(strip_code_fences(content))
    if not isinstance(raw, dict):
        raise ValueError("not a json object")
    return raw


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

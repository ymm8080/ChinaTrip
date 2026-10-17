"""LLM adapter contract (design v1.6 section 2.1).

W1-2 ships only the mock adapter. W7-8 adds the LiteLLM adapter that routes
to the in-region self-hosted vLLM endpoint. Both must satisfy this protocol.
"""

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


class LLMAdapter(Protocol):
    name: str

    async def extract(self, text: str, *, lang: str = "zh") -> ExtractResult: ...

"""Deterministic mock LLM adapter: line-rule parsing, zero network."""

from app.services.llm.base import (
    ChatMessage,
    ChatResult,
    ExtractResult,
    POICandidate,
)


class MockLLMAdapter:
    name = "mock"

    async def extract(self, text: str, *, lang: str = "zh") -> ExtractResult:
        # Deferred import: app.services.extraction imports this package.
        from app.services.extraction import scan_injection

        candidates: list[POICandidate] = []
        assumptions: list[str] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if line.startswith("- "):
                candidates.append(POICandidate(name=line[2:].strip(), confidence=0.9))
            elif line.startswith("? "):
                candidates.append(POICandidate(name=line[2:].strip(), confidence=0.5))
            elif line.startswith("# "):
                assumptions.append(line[2:].strip())
        return ExtractResult(
            candidates=candidates,
            assumptions=assumptions,
            quarantined=scan_injection(text),
            model="mock",
            tokens_in=len(text) // 4,
            tokens_out=50,
        )

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> ChatResult:
        # Deterministic echo: unit tests steer behavior with their own stub
        # adapters; this keeps app-level smoke tests zero-network.
        last_user = next(
            (m.content for m in reversed(messages) if m.role == "user"), ""
        )
        return ChatResult(
            content=f"mock-chat:{last_user[-64:]}",
            model="mock",
            tokens_in=sum(len(m.content) for m in messages) // 4,
            tokens_out=32,
        )

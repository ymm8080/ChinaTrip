"""Extraction service: adapter call + shared prompt-injection scan.

Iron rule 15: untrusted user content is DATA, never instructions — flagged
text is quarantined, never executed as instructions.
"""

import re

from app.services.llm.base import ExtractResult, LLMAdapter

INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore\s+(?:all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"disregard.{0,20}instructions", re.IGNORECASE),
    re.compile(r"system\s+prompt", re.IGNORECASE),
    re.compile(r"jailbreak", re.IGNORECASE),
    re.compile(r"developer\s+mode", re.IGNORECASE),
    re.compile(r"<\|im_start\|>", re.IGNORECASE),
    re.compile(r"忽略(?:之前|以上|前面)(?:的)?(?:指令|提示)"),
    re.compile(r"你现在是"),
    re.compile(r"请扮演"),
    re.compile(r"无视(?:以上|之前)"),
)


def scan_injection(text: str) -> bool:
    return any(p.search(text) for p in INJECTION_PATTERNS)


class ExtractionService:
    def __init__(self, adapter: LLMAdapter) -> None:
        self.adapter = adapter

    async def run(self, text: str, lang: str) -> ExtractResult:
        result = await self.adapter.extract(text, lang=lang)
        if scan_injection(text):
            result.quarantined = True
        return result

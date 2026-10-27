"""快车道处理器（design §6.12 ②）：闸门判 fast 的高频意图用确定性代码
直接出答案——不进 agent loop、不触达主力模型；答不出来（宁缺毋错，
对齐「宁可慢不可错」）返回 None 交回主车道。

v1 覆盖：
- poi_hours  行程/心愿单里出现过的 POI 名 × POI 底库营业时间
- wishlist   trip_items 心愿单列表（铁律 0 同源）
- translate  指令剥壳后走 Flash 翻译（zh<->en；非 zh/en 内容 v1 不虚构）
- restaurant 底库 search_keyword 确定性命中；命不中回退主车道
  （restaurants 独立表还没有 service 读端点，不编答案）

答案缓存：短 TTL 插入序字典（同款哲学：gate 意图缓存 / translate
短语缓存——高频问句重复出现在秒级窗口内）。
"""

from __future__ import annotations

import re
import time

from pydantic import BaseModel

from app.services.gate import _contains_foreign_script
from app.services.itinerary import VisitItem
from app.services.lang_ctx import L
from app.services.translate import TranslationService, UnsupportedLanguageError

_TRANSLATE_INSTRUCTION_PHRASES = (
    "帮我翻译一下",
    "帮我翻译",
    "麻烦翻译一下",
    "麻烦翻译",
    "请翻译",
    "翻译一下",
    "翻译",
    "用英语怎么说",
    "英语怎么说",
    "怎么用英语说",
    "怎么说",
    "用中文怎么说",
    "中文怎么说",
)
_STRIP_CHARS = " \t\r\n，。！？!?.,、：:;；「」『』\"'()（）"

_RESTAURANT_TOKENS = ("餐厅", "美食", "小吃")


class FastLaneAnswer(BaseModel):
    intent: str
    text: str
    cached: bool = False
    data: dict | None = None


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _strip_translate_instructions(text: str) -> str:
    content = text
    for phrase in _TRANSLATE_INSTRUCTION_PHRASES:
        content = content.replace(phrase, "")
    content = re.sub(r"(?i)translate", "", content)
    return content.strip(_STRIP_CHARS)


def _translation_direction(content: str) -> tuple[str, str] | None:
    """zh<->en 之外的语向 v1 不接（底座是 TranslationService 支持对）。"""
    has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in content)
    if has_cjk and not _contains_foreign_script(content):
        return ("zh", "en")
    if not has_cjk and content.isascii() and any(ch.isalpha() for ch in content):
        return ("en", "zh")
    return None


class FastLane:
    """answer(session, text, intent)：确定性出答案或 None（回主车道）。"""

    def __init__(
        self,
        *,
        poi_details,
        trip_items,
        translate: TranslationService,
        answer_ttl_seconds: float = 60.0,
        answer_max_entries: int = 4_096,
    ) -> None:
        self._poi_details = poi_details
        self._trip_items = trip_items
        self._translate = translate
        self._ttl = answer_ttl_seconds
        self._max_entries = answer_max_entries
        self._cache: dict[tuple, tuple[float, FastLaneAnswer]] = {}

    async def answer(self, session, text: str, intent: str) -> FastLaneAnswer | None:
        key = (intent, _norm(text), tuple(session.cities))
        hit = self._cache.get(key)
        if hit is not None:
            if time.monotonic() - hit[0] < self._ttl:
                return hit[1].model_copy(update={"cached": True})
            del self._cache[key]
        result = await self._dispatch(session, text, intent)
        if result is not None:
            self._store(key, result)
        return result

    async def _dispatch(self, session, text: str, intent: str) -> FastLaneAnswer | None:
        if intent == "poi_hours":
            return self._poi_hours(session, text)
        if intent == "wishlist":
            return self._wishlist(session)
        if intent == "translate":
            return await self._translate_answer(text)
        if intent == "restaurant":
            return self._restaurant(session)
        return None

    def _store(self, key: tuple, answer: FastLaneAnswer) -> None:
        if self._max_entries <= 0:
            return
        if len(self._cache) >= self._max_entries and self._cache:
            self._cache.pop(next(iter(self._cache)))  # 插入序 FIFO
        self._cache[key] = (time.monotonic(), answer)

    # --- handlers -----------------------------------------------------------

    def _known_names(self, session) -> list[str]:
        """本会话「语境专名池」：行程景点 + 心愿单（不认识的名字不瞎答）。"""
        names: list[str] = []
        if session.plan is not None:
            for day in session.plan.days:
                for item in day.items:
                    if isinstance(item, VisitItem):
                        names.append(item.name)
        itinerary_id = session.plan.itinerary_id if session.plan is not None else None
        for entry in self._trip_items.list_groups(itinerary_id).get("wishlist", []):
            name = entry.get("name")
            if name:
                names.append(name)
        return names

    def _poi_hours(self, session, text: str) -> FastLaneAnswer | None:
        matched = max(
            (n for n in self._known_names(session) if n and n in text),
            key=len,
            default=None,
        )
        if matched is None:
            return None
        detail = self._poi_details.get_by_name(None, matched)
        if not detail:
            return None
        hours = detail.get("opening_hours")
        if not hours:
            return None
        source = detail.get("hours_source") or "poi"
        return FastLaneAnswer(
            intent="poi_hours",
            text=L(
                f"{matched} 营业时间：{hours}（来源 {source}，节假日以现场为准）",
                f"{matched} opening hours: {hours} (source {source};"
                " holidays may differ)",
            ),
            data={"name": matched, "opening_hours": hours},
        )

    def _wishlist(self, session) -> FastLaneAnswer | None:
        itinerary_id = session.plan.itinerary_id if session.plan is not None else None
        groups = self._trip_items.list_groups(itinerary_id)
        names = [i.get("name") for i in groups.get("wishlist", []) if i.get("name")]
        if not names:
            return None
        return FastLaneAnswer(
            intent="wishlist",
            text=L(
                "你的心愿单：" + "、".join(names),
                "Your wishlist: " + ", ".join(names),
            ),
            data={"names": names},
        )

    async def _translate_answer(self, text: str) -> FastLaneAnswer | None:
        content = _strip_translate_instructions(text)
        if not content:
            return None
        pair = _translation_direction(content)
        if pair is None:
            return None
        try:
            result = await self._translate.translate(
                content, source_lang=pair[0], target_lang=pair[1]
            )
        except (UnsupportedLanguageError, ValueError):
            return None
        return FastLaneAnswer(
            intent="translate",
            text=result.translated,
            data={"pair": f"{pair[0]}-{pair[1]}", "translation_cached": result.cached},
        )

    def _restaurant(self, session) -> FastLaneAnswer | None:
        city = session.cities[0] if session.cities else None
        if not city:
            return None
        hits = self._poi_details.search_keyword(city, list(_RESTAURANT_TOKENS), limit=6)
        picks: list[dict] = []
        seen: set[str] = set()
        for hit in hits:
            name = hit.get("name")
            if not name or name in seen:
                continue
            seen.add(name)
            picks.append(hit)
            if len(picks) == 3:
                break
        if not picks:
            return None
        segs = []
        for hit in picks:
            rating = hit.get("rating")
            addr = (hit.get("address") or "").strip()
            seg = hit["name"] + (f"（{rating} 分）" if rating else "")
            if addr:
                seg += f" · {addr}"
            segs.append(seg)
        return FastLaneAnswer(
            intent="restaurant",
            text=L(
                "附近餐饮候选：" + "；".join(segs),
                "Food picks nearby: " + ", ".join(h["name"] for h in picks),
            ),
            data={"names": [h["name"] for h in picks]},
        )

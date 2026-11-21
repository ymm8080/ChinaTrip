"""开局 NLU mixin（切片 3）——start/换局判定/重开/brief 轮/LLM 事实解读从
legacy 迁入，行为零变化；PlanningAgent 继承承载。

legacy ``app/services/agent/plan.py`` 的 ``PlanningAgent`` 顶部 import 本模块
并追加 ``StartNluMixin`` 基类：五方法经继承原位可用，旧引用路径
（``PlanningAgent.start`` / 子类覆盖 / ``super()`` 链）不变。

import 面：顶层只 import 非 agent 层模块（lang_ctx / llm.base /
trip_orchestrator.nlu / trip_orchestrator.session / web_reader / 标准库，
与 conversation 前置片同向，不反向依赖 legacy）。仍被 legacy 其它代码或下游
共用的名字（``_PREF_ROUND_ENABLED`` / ``_pref_question`` / ``clarify_questions`` /
``_trip_brief`` / ``_parse_days`` / ``_parse_cities`` / ``_normalize_city`` /
``_resolve_brief_cities`` / ``_is_new_trip_request`` / ``_same_site`` /
``_norm_city`` / ``_parse_text_start_date`` / ``_count_text_dates`` /
``_MIN_FACTS_LLM_TEXT`` / ``logger``）在方法体内 lazy import——调用时
agent.plan 已加载完成，取到的是同一个对象，行为零变化。
"""

from __future__ import annotations

import asyncio
import uuid

from app.services.lang_ctx import SUPPORTED, L
from app.services.llm.base import ChatMessage
from app.services.trip_orchestrator.nlu import _parse_text_day_start
from app.services.trip_orchestrator.session import PlanSession
from app.services.web_reader import find_urls


class StartNluMixin:
    # --- public API -------------------------------------------------------

    async def start(
        self,
        *,
        device_id: str,
        cities: list[str],
        days: int,
        preferences: str = "",
        city_days: dict[str, int] | None = None,
        start_date: str | None = None,
        intercity_mode: str = "auto",
        lang: str | None = None,
        brief: str | None = None,
        arrival_no: str | None = None,
        arrival_time: str | None = None,
        departure_no: str | None = None,
        departure_time: str | None = None,
        arrival_date: str | None = None,
        departure_date: str | None = None,
        intake: bool = False,
        days_override: int | None = None,
        arrival_no_override: str | None = None,
        departure_no_override: str | None = None,
        images: list[tuple[bytes, str]] | None = None,
    ) -> PlanSession:
        # legacy 共享名：顶层反向 import agent.plan 会循环——运行时取同一对象
        from app.services.agent.plan import (
            _PREF_ROUND_ENABLED,
            _normalize_city,
            _parse_cities,
            _parse_days,
            _pref_question,
            _resolve_brief_cities,
            _trip_brief,
            clarify_questions,
            logger,
        )

        # 2026-11-13（陕历博跨城串行程案）：心愿绑定缓存按会话隔离——
        # agent 是单例、跨行程复用，上一趟的 _wish_bindings 会让新行程的
        # 心愿行按名字命中，被换绑到不含该城的行程（西安心愿挂进成都
        # 重庆行程）。新会话从零绑定，绑定结果由本趟重新建立。
        self._wish_bindings.clear()
        self._wish_bind_misses.clear()
        session = PlanSession(
            session_id=uuid.uuid4().hex,
            device_id=device_id,
            cities=[_normalize_city(c) for c in cities if c and c.strip()],
            days=days if days and days > 0 else 0,
            preferences=preferences or "",
            start_date=start_date or None,
            city_days={
                _normalize_city(k): v
                for k, v in (city_days or {}).items()
                if isinstance(v, int) and v >= 1
            },
            intercity_mode=(
                intercity_mode if intercity_mode in ("train", "flight") else "auto"
            ),
            # 多语言（design nlang §2.1）：lang 白名单走 SUPPORTED 注册表，
            # 注册表加语言这里自动放行（未知码归 None=zh 行为）
            lang=lang if lang in SUPPORTED else None,
            arrival_no=(arrival_no or "").strip().upper() or None,
            arrival_time=(arrival_time or "").strip() or None,
            departure_no=(departure_no or "").strip().upper() or None,
            departure_time=(departure_time or "").strip() or None,
            arrival_date=(arrival_date or "").strip() or None,
            departure_date=(departure_date or "").strip() or None,
            intake_done=bool(intake),
        )
        # 自由输入框里的「新行程简报」（2026-11-13）：表单可能是上一次行程
        # 的回填（重新规划/自动打开后），而用户刚打的这句才是新设置——它写出
        # 的路线与表单不同时以简报为准，旧路线不参与本趟生成。
        # 自由输入原句存进会话（2026-11-14 起步页长描述被整段丢弃案）：
        # 生成前按它读「点名景点 → 必去」；澄清补答天数后再生成也能读。
        session.brief_text = (brief or "").strip()
        parsed = _trip_brief(brief) if brief else None
        brief_cities: list[str] = []
        brief_days: int | None = None
        if parsed is not None and parsed[0]:
            brief_cities = [_normalize_city(c) for c in parsed[0]]
            brief_days = parsed[1]
        elif brief and brief.strip():
            # 2026-11-14：起步页那句话本身就是路线声明——句子点名了表单
            # 里没有的城市（或写了天数）时以它为准。旧逻辑单城必须带
            # 天数才算简报，英文「Beijing…」读不出天数就整句作废，
            # 表单默认值永远压过文本（用户实报「引擎根本不读输入」）。
            typed_cities = [_normalize_city(c) for c in _parse_cities(brief)]
            typed_days = _parse_days(brief)
            form_norm = {_normalize_city(c) for c in session.cities}
            if typed_cities and (
                typed_days or any(c not in form_norm for c in typed_cities)
            ):
                brief_cities = typed_cities
                brief_days = typed_days
        if brief_cities:
            form_cities = list(session.cities)
            resolved = _resolve_brief_cities(brief_cities, form_cities)
            if {_normalize_city(c) for c in resolved} != {
                _normalize_city(c) for c in form_cities
            }:
                session.cities = resolved
                session.city_days = {}
                if brief_days:
                    session.days = brief_days
            elif brief_days and not session.city_days:
                # 同城但只给了整趟天数（表单没填分城天数）：文本为准
                session.days = brief_days
        # 差异确认选边覆写（2026-11-14 用户拍板）：天数/班次号以用户在确认卡上
        # 选定的为准——在简报解析之后应用，盖过一切自动解析。
        if days_override:
            session.days = max(1, int(days_override))
            session.city_days = {}
        if arrival_no_override:
            session.arrival_no = str(arrival_no_override).strip().upper() or None
        if departure_no_override:
            session.departure_no = str(departure_no_override).strip().upper() or None
        # 票务预热（2026-10-28 用户拍板）：开始日期落定且城市齐（起止+中间）
        # 就开跑火车查询，不等行程生成——CachedTrainService 命中后组装零等待。
        if session.start_date and len(session.cities) > 1:
            self._transfer_prefetch_task = asyncio.create_task(
                self.prefetch_transfer_schedules(
                    session.cities, session.days or 1, session.start_date
                )
            )
        if not session.cities:
            # H5 composer text ("Shanghai 5 days, museums") carries the
            # cities when the plan starts from free text instead of the
            # pickers; without this the English name never matches and no
            # city is ever recognized (2026-11-12: no silent default city
            # anymore — clarify-exhausted flow asks for the destination).
            session.cities = _parse_cities(session.preferences)
        if not session.cities:
            # 2026-11-17（ZHUJIAZUI 案）：城市没写，但句子里点名的地点全库
            # 唯一落在一座城 → 直接定城，不再问「从哪个城市出发」。假设区
            # 披露推断依据；跨城命中=拿不准，照旧问。
            _inferred = await self._infer_city_from_site_text(
                session.brief_text or session.preferences
            )
            if _inferred:
                _city, _rows = _inferred
                session.cities = [_city]
                _named = "、".join(
                    str(r.get("name") or "") for r in _rows[:3] if r.get("name")
                )
                session.brief_notes = [
                    *session.brief_notes,
                    L(
                        f"目的地城市按你点名的「{_named}」推断为{_city}。",
                        f"Destination city set to {_city} from the places you "
                        f"named ({_named}).",
                    ),
                ]
                logger.info(
                    "plan: city inferred from brief sites: %s (%s)", _city, _named
                )
        wanted = "、".join(session.cities) if session.cities else "（城市未定）"
        session.history.append(
            ChatMessage(
                role="user",
                content=(
                    f"帮我规划行程：{session.days or '?'} 天，城市：{wanted}；"
                    f"偏好：{session.preferences or '无'}"
                ),
            )
        )
        if find_urls(session.preferences):
            # First message carried a link (H5 folds typed text into
            # preferences when no session exists yet): read it here, or
            # it would sit unread in the preference string forever.
            handled = await self._ingest_links(session, session.preferences)
            if session.state == "site_confirm" or handled:
                # Either the mandatory/optional question, or a single-site
                # link that already rode the pipeline as a must-visit.
                return session
        # R9-1（2026-11-19 拍板「复杂开局也走 CP-SAT」）：表单齐全时
        # _understand 不跑，但 brief 里的「LEAVE HOTEL ON 11AM」首日出
        # 发语义只有原句里有——正则轻读（零 LLM），读出即
        # comment_day_start（引擎 C-04 地板 + compact 地板同源消费）。
        _brief_src = (session.brief_text or session.preferences or "").strip()
        if _brief_src and not session.comment_day_start:
            _hm = _parse_text_day_start(_brief_src)
            if _hm:
                session.comment_day_start = _hm
        # LLM/底库先读懂那句话（2026-11-17 用户拍板「LLM UNDERSTAND USER
        # COMMENTS FIRST」+「城市按点名景点反推」）：表单没给城市/天数时先
        # 从自由输入原句补齐——日期/天数/出发时刻/城市（点名景点的所在城，
        # 同名分布多城=歧义不猜）。都读不出才照旧弹追问窗。
        # 触发：城市/天数缺（会弹窗才读）——只为补日期不值得烧 LLM。
        if not session.cities or session.days <= 0:
            await self._understand_trip_comment(session)
        if not session.cities or session.days <= 0:
            session.state = "clarify"
            session.clarify_count = 1
            session.history.append(
                ChatMessage(
                    role="assistant",
                    content=" ".join(clarify_questions(session)),
                )
            )
            return session
        # 2026-11-08 屏蔽期：偏好轮下线——完整请求按无特别要求直接出 v0
        if not session.preferences and _PREF_ROUND_ENABLED:
            # Complete request but no sightseeing preference yet: one
            # preference round before v0 (product ask), still §6.1 envelope.
            session.state = "clarify"
            session.clarify_count = 1
            session.pref_asked = True
            session.history.append(
                ChatMessage(role="assistant", content=_pref_question())
            )
            return session
        if images:
            # 开局带图（2026-11-14「图片上有的也抽出来」）：先把文字+图片
            # 读成地点开确认轮，用户点选后才生成行程——与链接轮同一口径。
            notes = await self._brief_site_round(session, images=images)
            if session.state == "site_confirm":
                return session
            if notes:
                session.brief_notes = [*session.brief_notes, *notes]
        session = await self._generate_v0(session)
        # R11（intake 双重应用守卫，2026-11-19）：引擎服务的会话不再跑
        # legacy 落位——引擎快照已含到达/离开时刻与日序，
        # _apply_intake_times 再钉腿/撤腿会二次改写引擎计划。
        # _generate_v0 钩子成功路径打上 _ts_engine_served_sid，据此跳过
        # （restart_with_brief → start 同一守卫自动生效）。
        try:
            if session.plan is not None and (
                getattr(self, "_ts_engine_served_sid", "") != session.session_id
            ):
                await self._apply_intake_times(session)
        finally:
            self._ts_engine_served_sid = ""
        return session

    def new_trip_brief(
        self, session: PlanSession, text: str
    ) -> tuple[list[str], int | None] | None:
        """当前会话收到「另一趟行程」的整句时返回 (cities, days)，否则 None。

        只在两件事同时成立时换局：句子本身像一趟完整行程
        （_is_new_trip_request），并且目的地真的换了（解析出的城市不全是当前
        城市）；或者会话本来就是载入的已存行程（✏️ 修改）——那种会话里用户
        报新的完整路线，一律按新行程开，绝不改旧行程。
        """
        # legacy 共享名：顶层反向 import agent.plan 会循环——运行时取同一对象
        from app.services.agent.plan import (
            _is_new_trip_request,
            _normalize_city,
            _trip_brief,
        )

        if not _is_new_trip_request(text):
            return None
        brief = _trip_brief(text)
        if brief is None:  # pragma: no cover - _is_new_trip_request 已保证
            return None
        cities, days = brief
        current = {_normalize_city(c) for c in (session.cities or [])}
        fresh = {_normalize_city(c) for c in cities}
        changed = not current or not fresh.issubset(current)
        if not changed and session.source_itinerary_id is None:
            return None
        return cities, days

    async def restart_with_brief(
        self,
        session: PlanSession,
        text: str,
        brief: tuple[list[str], int | None],
    ) -> tuple[PlanSession, str]:
        """按「新行程简报」重开一局（旧会话/旧行程原样留着，不写不绑）。"""
        cities, days = brief
        fresh = await self.start(
            device_id=session.device_id,
            cities=cities,
            days=days or session.days,
            preferences=text,
            start_date=session.start_date,
            intercity_mode=session.intercity_mode,
            lang=session.lang,
        )
        note = L(
            "已按你刚说的新行程重开一局："
            f"{'→'.join(fresh.cities) or '（城市待定）'}，{fresh.days or '?'} 天"
            "（上一趟行程没有被改动）。",
            "Started a new trip from your latest message: "
            f"{' → '.join(fresh.cities) or '(city TBC)'}, {fresh.days or '?'} days "
            "(the previous itinerary was left untouched).",
        )
        return fresh, note

    async def _brief_site_round(
        self, session: PlanSession, images: list[tuple[bytes, str]] | None = None
    ) -> list[str]:
        """文字/视频描述（+可选的图片）读出的地点先问用户一轮，确认后落库。

        产品线（用户拍板 2026-11-14）：从用户的视频、文字或图片里取景点 →
        用户确认 → 成为行程中心心愿单的备排项。链接路径早就有这一轮
        （_ingest_links），起步页那段文字此前直接把读出的名字钉成必去、
        跳过了确认——这里补齐：读出的名字只进 pending_sites 等点选，未点选
        的不入库（与链接轮同口径），点选的由 confirm_sites /
        _answer_site_confirm 落库并排期。

        返回要随 v0 披露的读点备注（对不上具体地点、已按「避开」剔除等）；
        开轮时备注并进追问，随对话给用户看。每会话只开一轮。
        """
        # legacy 共享名：顶层反向 import agent.plan 会循环——运行时取同一对象
        from app.services.agent.plan import _same_site, logger

        if session.plan is not None or session.brief_mined:
            return []
        added, notes = await self._mine_brief_sites(session, commit=False)
        source = "brief"
        if images:
            pool = list(
                session.cities[1:] if len(session.cities) > 1 else session.cities
            )
            pool = [c for c in pool if c]
            rows, image_notes = await self._image_sites(images, pool or session.cities)
            notes = [*notes, *image_notes]
            for name, kind, city in rows:
                if any(_same_site(name, other) for other in added):
                    continue
                added.append(name)
                session.site_kinds.setdefault(name, kind)
                if city:
                    session.site_cities.setdefault(name, city)
            if rows:
                source = "image"
        if not added:
            return notes
        session.pending_sites = list(added)
        session.pending_sites_source = source
        session.state = "site_confirm"
        question = self._site_confirm_question(session, source=source)
        if notes:
            question += L("（", " (") + "；".join(notes) + L("）", ")")
        session.history.append(ChatMessage(role="assistant", content=question))
        logger.info("plan: brief site round opened (%s): %s", source, added)
        return []

    async def _understand_trip_comment(self, session: PlanSession) -> None:
        """LLM/底库先读懂用户那句话（2026-11-17 用户拍板「LLM UNDERSTAND
        USER COMMENTS FIRST」）：表单没给的路线事实从自由输入原句里补——
        出发日期（英文 Dec.02 也认）、天数（只写一个日期=一日游）、第一
        天出发时刻（LEAVE HOTEL ON 11AM）、目的城（按点名景点反推）。纯
        补空：表单/行前卡已有的字段一律不覆盖；读不出留给追问轮。"""
        # legacy 共享名：顶层反向 import agent.plan 会循环——运行时取同一对象
        from app.services.agent.plan import (
            _MIN_FACTS_LLM_TEXT,
            _count_text_dates,
            _norm_city,
            _parse_days,
            _parse_text_start_date,
            logger,
        )

        text = (session.brief_text or session.preferences or "").strip()
        if not text or find_urls(text):
            return
        # LLM facts（拍板「LLM UNDERSTAND USER COMMENTS FIRST」）：先让 LLM
        # 读懂日期/天数/出发时刻/城市，正则只在 LLM 读不出的字段上兜底。
        facts: dict = {}
        if len(text) >= _MIN_FACTS_LLM_TEXT:
            facts = await self.trip_facts_from_llm(text) or {}
        if not session.start_date:
            session.start_date = facts.get("start_date") or _parse_text_start_date(text)
        if session.days <= 0:
            days = facts.get("days") or _parse_days(text)
            if days is None and session.start_date and _count_text_dates(text) <= 1:
                days = 1
            if days:
                session.days = days
        if not session.comment_day_start:
            hm = facts.get("day1_start") or _parse_text_day_start(text)
            if hm:
                session.comment_day_start = hm
        if not session.cities:
            # 城市：LLM 给的城（白名单）优先；没给再按点名景点反推（拍板
            # 「FILTER CITY ACCORDING TO SITES NAME」，同名多城不猜）。
            city = _norm_city(str(facts.get("city") or ""))
            if not city:
                city = await self._city_from_text_sites(text)
            if city:
                session.cities = [city]
                logger.info("plan: city inferred from comment: %s", city)

"""对话路由 mixin（切片 2）——message/_ingest_links/_apply_conversation 从
legacy 迁入，行为零变化；PlanningAgent 继承承载。

legacy ``app/services/agent/plan.py`` 的 ``PlanningAgent`` 顶部 import 本模块
并声明 ``ConversationMixin`` 基类：三方法经继承原位可用，旧引用路径
（``PlanningAgent.message`` / 子类覆盖 / ``super()`` 链）不变。

import 面：顶层只 import 非 agent 层模块（itinerary / lang_ctx / llm /
llm.base / trip_orchestrator.nlu / trip_orchestrator.session / web_reader，
与 session 前置片同向，不反向依赖 legacy）。仍被 legacy 其它代码共用的名字
（``HISTORY_WINDOW`` / ``LLM_ATTEMPTS`` / ``MAX_LINK_SITES`` / ``logger`` /
``_same_site`` / ``_requested_day_count`` / ``_expansion_move_diffs`` /
``try_fast_wish``）在方法体内 lazy import——调用时 agent.plan 已加载完成，
取到的是同一个对象，行为零变化。
"""

from __future__ import annotations

from app.services.itinerary import ChangeSummary, DiffOp, annotate_legs
from app.services.lang_ctx import L
from app.services.llm import LLMError, LLMQuotaError
from app.services.llm.base import ChatMessage, parse_json_content
from app.services.trip_orchestrator.nlu import _bare_preference_statement
from app.services.trip_orchestrator.session import PlanSession
from app.services.web_reader import LinkDigest, find_urls, format_digest_block


class ConversationMixin:
    async def message(
        self, session: PlanSession, text: str
    ) -> tuple[PlanSession, str, ChangeSummary | None]:
        # Deep-copy: the caller's stored session must never see partial
        # mutations (v0 flips state to "planning" before a plan exists —
        # an exception there used to poison the session for good).
        session = session.model_copy(deep=True)
        session.history.append(ChatMessage(role="user", content=text))
        handled = await self._ingest_links(session, text)
        if session.state == "site_confirm" and not handled:
            return await self._answer_site_confirm(session, text)
        if session.state == "resto_confirm" and not handled:
            return await self._answer_resto_confirm(session, text)
        if handled:
            # Link processing ended the turn: either the mandatory/optional
            # question was born from this very message, or a single-site
            # link already rode the pipeline as a must-visit.
            return session, session.history[-1].content, None
        if session.pending_wish_cities:
            answered = await self._answer_wish_city(session, text)
            if answered is not None:
                return answered
        if session.state == "clarify":
            return await self._answer_clarification(session, text)
        return await self._apply_conversation(session, text)

    async def _ingest_links(self, session: PlanSession, text: str) -> bool:
        """§6.5 stage 1: fetch pasted links and park the quarantined digest
        in history, so the model can quote it on this and later turns.
        Returns True when this turn asked the site mandatory/optional round."""
        # legacy 共享名：顶层反向 import agent.plan 会循环——运行时取同一对象
        from app.services.agent.plan import MAX_LINK_SITES, _same_site, logger

        if self._link_reader is None:
            return False
        urls = find_urls(text)
        if not urls:
            return False
        digests: list[LinkDigest] = []
        for url in urls:
            try:
                digests.append(await self._link_reader.read(url))
            except Exception:
                logger.warning("plan: link read failed for %s", url, exc_info=True)
                digests.append(LinkDigest(url=url, error="读取异常"))
        block = format_digest_block(digests)
        if not block:
            return False
        session.history.append(ChatMessage(role="system", content=block))
        if session.state in ("site_confirm", "resto_confirm"):
            return False
        sites: list[tuple[str, str, str]] = []
        for digest in digests:
            if digest.ok:
                sites.extend(await self._extract_sites(digest, session.lang))
        deduped: list[tuple[str, str, str]] = []
        for name, kind, city in sites:
            if not any(_same_site(name, kept[0]) for kept in deduped):
                deduped.append((name, kind, city))
        sites = deduped[:MAX_LINK_SITES]
        if not sites and any(d.ok for d in digests):
            logger.info(
                "plan: link digests ok but 0 sites extracted for %s",
                [d.url for d in digests if d.ok],
            )
        url = next((d.url for d in digests if d.ok), "")
        if len(sites) == 1:
            # The whole link is about exactly one place: that IS the
            # must-have (product rule 2026-10-19) — no round needed.
            self._absorb_days_cities(session, text)
            name, kind, city = sites[0]
            await self._finish_link_sites(
                session, [name], [], url, kinds={name: kind}, cities={name: city}
            )
            return True
        if len(sites) < 2:
            return False
        session.pending_sites = [name for name, _, _ in sites]
        session.site_kinds.update({name: kind for name, kind, _ in sites})
        session.site_cities.update({name: city for name, _, city in sites if city})
        session.pending_link_url = url
        session.pending_sites_source = "link"
        session.state = "site_confirm"
        question = self._site_confirm_question(session)
        session.history.append(ChatMessage(role="assistant", content=question))
        return True

    async def _apply_conversation(
        self, session: PlanSession, text: str
    ) -> tuple[PlanSession, str, ChangeSummary | None]:
        # legacy 共享名：顶层反向 import agent.plan 会循环——运行时取同一对象
        from app.services.agent.plan import (
            HISTORY_WINDOW,
            LLM_ATTEMPTS,
            _expansion_move_diffs,
            _requested_day_count,
            logger,
        )
        from app.services.agent.wish_fast import try_fast_wish

        # 一句话加心愿（2026-11-13 用户拍板）：单点专名心愿走确定性落位
        # （查库→归簇择日→插位→按优先级/距离让位），不再 LLM + CP 全量重解。
        fast = await try_fast_wish(self, session, text)
        if fast is not None:
            return fast
        assert session.plan is not None
        if self._type_ask_hit(session, text):
            # 同档同类让位问答（2026-11-03 拍板「三个5A博物馆可以问用户」
            # +「喜欢某个类型则可以有很多」）：偏好答复并入 preferences 并
            # 自动重排——偏好优先于默认封顶，两通道（选点/回填）同步豁免
            prev = (session.preferences or "").strip()
            session.preferences = f"{prev} {text.strip()}".strip()
            session.pending_type_ask = []
            session = await self._generate_v0(
                session,
                extra_assumptions=[
                    L(
                        "已按偏好解除同类默认封顶重排：" + text.strip(),
                        "Re-planned with your preference (same-type default "
                        "cap lifted): " + text.strip(),
                    )
                ],
            )
            reply = (
                session.history[-1].content
                if session.history
                else L("已按偏好重排。", "Re-planned with your preference.")
            )
            return session, reply, None
        if session.plan is not None and _bare_preference_statement(text):
            # R8b（2026-11-18 用户拍板「裸偏好也触发全量引擎重排」）：纯
            # 品类偏好语句并入 preferences（留存——此前 diff 道会蒸发）
            # 并全量重排——_generate_v0 的 R8 钩子自动换模型引擎，用户
            # 钉卡按 C-04 全保位（日+时刻钉死，NEVER_RELAX）；点名/心愿/
            # 结构变更语句照旧原道。
            prev = (session.preferences or "").strip()
            session.preferences = f"{prev} {text.strip()}".strip()
            session = await self._generate_v0(
                session,
                extra_assumptions=[
                    L(
                        "已按你的偏好重排：" + text.strip() + "（同类可多个景点）",
                        "Re-planned with your preference: "
                        + text.strip()
                        + " (several same-type sights possible)",
                    )
                ],
            )
            reply = (
                session.history[-1].content
                if session.history
                else L("已按偏好重排。", "Re-planned with your preference.")
            )
            return session, reply, None
        messages = [
            ChatMessage(role="system", content=self._edit_system_prompt(session)),
            *session.history[-HISTORY_WINDOW:],
        ]
        result = None
        data = None
        reply = ""
        diffs: list[DiffOp] = []
        last_llm_error: LLMError | None = None
        for _ in range(LLM_ATTEMPTS):
            try:
                result = await self._llm.chat(messages, temperature=0.2)
            except LLMError as exc:
                last_llm_error = exc
                logger.warning(
                    "plan: edit llm call failed (%s: %s), retrying",
                    type(exc).__name__,
                    exc,
                )
                continue
            try:
                data = parse_json_content(result.content)
                # 2026-11-17 用户二拍：信息不全时 LLM 直接在 reply 里问用户
                # （先查底库、猜测需确认——约束在系统提示词里，不在这里硬剥）。
                reply = str(data.get("reply") or "")
                diffs = self._coerce_diffs(data.get("diffs"), plan=session.plan)
                wishes = self._coerce_wishes(data.get("wishes"))
                if diffs or reply or wishes:
                    reply = reply or L("已处理你的消息。", "Your message is handled.")
                    break
                # Degenerate draw (empty reply AND no diffs): glm flash
                # sometimes answers a clear add request this way — accept
                # it and the turn becomes a silent no-op. Resample like
                # any other bad output.
                logger.warning("plan: edit degenerate draw, resampling")
                continue
            except (ValueError, TypeError) as exc:
                # Same loop shape as v0: an unparseable draw is resampled,
                # not punted back to the user on the first bad output.
                logger.warning(
                    "plan: edit structured output failed (%s: %s), retrying",
                    type(exc).__name__,
                    exc,
                )
                continue
        if data is None:
            if result is None:
                if isinstance(last_llm_error, LLMQuotaError):
                    # 配额死 ≠ 暂时无响应：窗口内重试无效，照实说恢复时间
                    # （2026-11-11 事故：泛化「请再发一次」把用户卡到死循环）。
                    recover = last_llm_error.recover_at
                    if recover:
                        reply = L(
                            f"模型额度已用尽（服务商预计 {recover} 恢复），"
                            "这轮没有改动行程，恢复后再发一次即可。",
                            "The model quota is exhausted (the provider says it"
                            f" recovers at {recover}); the itinerary is unchanged"
                            " — send your request again after that time.",
                        )
                    else:
                        reply = L(
                            "模型额度已用尽，这轮没有改动行程，请稍后再试。",
                            "The model quota is exhausted; the itinerary is"
                            " unchanged — please try again later.",
                        )
                else:
                    # All attempts stalled (glm flash ReadTimeout in prod logs):
                    # keep the conversation alive in-band instead of a 502 dead end.
                    reply = L(
                        "模型暂时无响应，这轮没有改动行程，请再发一次。",
                        "The model isn't responding right now; the itinerary is "
                        "unchanged — please send again.",
                    )
            else:
                reply = L(
                    "刚才模型回复没能解析，已自动重试仍未成功，请再发一次。",
                    "The model's last reply couldn't be parsed and the retry "
                    "failed too — please send again.",
                )
            session.history.append(ChatMessage(role="assistant", content=reply))
            return session, reply, None
        if not diffs:
            # 改总天数（2026-11-17「I WANT TWO DAYS TRIP」案）：纯天数诉求
            # 也走 apply 通道——LLM 没给 diff 时由 fallback split 兜底重分，
            # 不再走「只回话不动行程」的早退分支。
            current_days = len(session.plan.days)
            day_target = _requested_day_count(text, current_days)
            if day_target == current_days:
                day_target = None  # 明确说了与当前相同的天数：无变化
            if day_target is not None and day_target > current_days:
                diffs = _expansion_move_diffs(session.plan, day_target)
        else:
            # LLM 给了 diff：检查它是否真的把卡挪到了新天——只扩天数不挪卡
            # 会交付一个空天。没有指向新天的 move/add 时补 fallback split。
            current_days = len(session.plan.days)
            day_target = _requested_day_count(text, current_days)
            if day_target == current_days:
                day_target = None
            if (
                day_target is not None
                and day_target > current_days
                and not any(
                    (op.op == "move" and (op.new_day or 0) > current_days)
                    or (
                        op.op == "add"
                        and op.item is not None
                        and op.item.day > current_days
                    )
                    for op in diffs
                )
            ):
                diffs = [*diffs, *_expansion_move_diffs(session.plan, day_target)]
        if not diffs and day_target is None:
            reply = reply or L("已处理你的消息。", "Your message is handled.")
            sync_notes, unresolved = await self.sync_wishes_to_trip_items(
                session,
                wishes,
                user_texts=self._user_corpus(session),
            )
            extras = list(sync_notes)
            note = await self._ensure_wishlist_coverage(session)
            if note:
                extras.append(note)
            pending_note = self._finalize_wish_cities(session, unresolved)
            if pending_note:
                extras.append(pending_note)
            if extras:
                reply = L(
                    f"{reply}（{'；'.join(extras)}）",
                    f"{reply} ({'; '.join(extras)})",
                )
            if session.plan is not None:
                # re-annotate/re-measure so stale leg values never linger
                annotate_legs(session.plan)
                await self._enrich_parallel(session.plan)
            session.history.append(ChatMessage(role="assistant", content=reply))
            return session, reply, None

        new_plan, summary, notes = await self._apply_with_repair(
            session, diffs, text, target_days=day_target
        )
        session.plan = new_plan
        session.state = "ready"
        if day_target is not None:
            # 行程天数落定后回写会话（后续补排/重解都按新天数窗口走）
            session.days = len(new_plan.days)
        sync_notes, unresolved = await self.sync_wishes_to_trip_items(
            session, wishes, user_texts=self._user_corpus(session)
        )
        notes.extend(sync_notes)
        coverage_note = await self._ensure_wishlist_coverage(session)
        if coverage_note:
            notes.append(coverage_note)
        pending_note = self._finalize_wish_cities(session, unresolved)
        if pending_note:
            notes.append(pending_note)
        if notes:
            reply = L(
                f"{reply}（{'；'.join(notes)}）",
                f"{reply} ({'; '.join(notes)})",
            )
        session.history.append(ChatMessage(role="assistant", content=reply))
        return session, reply, summary

"""会话模型（前置片）——从 legacy agent/plan.py 迁入，行为零变化。

``PendingResto`` / ``PlanSession`` / ``PlanSessionStore`` 三个会话模型与其依赖的
自愈函数 ``heal_item_ids``（``PlanSessionStore.get`` 读入自愈口）原样迁入；legacy
``app/services/agent/plan.py`` 原位同名 re-import，旧引用路径（agent.plan /
agent 包 / app/api / state_persist / tests）照旧可用。后续三个 mixin 切片从本
模块取会话模型，不反向 import legacy（避免循环依赖）。
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

from app.services.itinerary import ItineraryPlan
from app.services.itinerary.item_ids import ensure_unique_item_ids
from app.services.llm.base import ChatMessage

logger = logging.getLogger(__name__)


class PendingResto(BaseModel):
    """A link-derived restaurant held out for the >RESTO_ASK_KM ask round."""

    name: str
    item_id: str | None = None  # set when it already rides the plan (v0 path)
    day: int | None = None
    nearest_km: float | None = None


class PlanSession(BaseModel):
    """One planning conversation (Redis in W7-8; in-process dict for MVP)."""

    session_id: str
    device_id: str
    cities: list[str] = Field(default_factory=list)
    days: int = 0
    # 城市名 → 停留天数（仅目的地）
    city_days: dict[str, int] = Field(default_factory=dict)
    # 起始城市游玩天数（2026-11-22 用户拍板「起始城市也要能够选游玩日期数」）：
    # ≥1 时出发城是真实首站（Day1..k 在出发城活动，k+1 早上转场去第一目的
    # 地）；0=旧口径「出发日只排交通」。闭合行程出发城可同时是尾城——
    # 起始天数走本字段、结束天数走 city_days[尾城]，两值独立。
    origin_days: int = 0
    # 出发日期（ISO，可空）——落到 ItineraryPlan.start_date 随快照持久化
    start_date: str | None = None
    # 行前信息（2026-11-14 用户拍板「每次规划需求都先核对出发日期、行程日期是否
    # 覆盖到达日与离开日，覆盖就要航班/车次或当地到达时间」）：H5 行前确认卡/补答
    # 落在会话里，v0 出来后按真实时刻落位去程/返程腿（班次号优先查班次库）。
    arrival_no: str | None = None
    arrival_time: str | None = None  # 当地到达时刻「HH:MM」
    departure_no: str | None = None
    departure_time: str | None = None  # 当地离开（起飞/发车）时刻「HH:MM」
    arrival_date: str | None = None  # 到达日 ISO（缺省=首日）
    departure_date: str | None = None  # 离开日 ISO（缺省=末日）
    # 文字里读出的「第一天出发时刻」（2026-11-17「LEAVE HOTEL ON 11AM」
    # 案）：v0 生成后把第 1 天第一张景点卡 retime 到该时刻（酒店晨卡跟
    # 随），不建交通腿；落位一次即清，不跨回合重放。
    comment_day_start: str | None = None
    # 行前卡 opting-in（2026-11-14）：H5 弹过行前卡才置真——「班次/时刻都没填
    # → 对应天按全天规划（撤腿重排）」只对见过卡的请求生效；聊天换局/API 直调
    # 不带此标志，保持引擎默认时刻腿的既有契约。
    intake_done: bool = False
    state: Literal["clarify", "planning", "ready", "site_confirm", "resto_confirm"] = (
        "clarify"
    )
    clarify_count: int = 0
    # 链接读不到时的专属追问（2026-11-23 用户拍板「IF ENGINE CAN NOT READ
    # LINK, SHOULD REPLY AND ASK USER TO PASTE THE CONTENTS」）：非空时
    # clarify_questions 原样返回它，不再问城市/天数；用户答复后由
    # _answer_clarification 清空。
    clarify_override: list[str] = Field(default_factory=list)
    pref_asked: bool = False
    plan: ItineraryPlan | None = None
    history: list[ChatMessage] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    preferences: str = ""
    pending_sites: list[str] = Field(default_factory=list)
    # 待确认地点的来源（2026-11-14 用户拍板「从视频或文字里取景点，
    # 用户确认后才成为行程中心心愿单的备排项」）："link"=贴进来的
    # 链接读出；"brief"=起步页那段自由输入（或视频转写）读出——两种
    # 轮次的问法、默认勾选与落库备注不同。
    pending_sites_source: str = "link"
    # 读点披露（对不上具体地点等）暂存位（2026-11-14）：开局带图/带字时
    # 确认轮先跑、v0 后跑，备注要跨这一步带进 assumptions。
    brief_notes: list[str] = Field(default_factory=list)
    pending_link_url: str = ""
    must_visits: list[str] = Field(default_factory=list)
    # 手建卡通道（2026-11-08 拍板「CREATED 低于心愿、高于其它TAG」）：行程
    # 中心 source=manual 的心愿行不进 must_visits 强钉——入池置顶+让位档
    # 0，物理不可排时仍可出局（有心愿绝对安全在上）。
    created_sites: list[str] = Field(default_factory=list)
    site_kinds: dict[str, str] = Field(default_factory=dict)  # name -> sight|food
    site_cities: dict[str, str] = Field(default_factory=dict)  # name -> city
    pending_restos: list[PendingResto] = Field(default_factory=list)
    resto_asked: list[str] = Field(default_factory=list)  # anti re-ask loop
    # 心愿城市追问队列（2026-10-24）：解析落空的专名心愿，等用户下一条消息
    pending_wish_cities: list[str] = Field(default_factory=list)
    # 同档同类让位待问（2026-11-03 拍板「三个5A博物馆可以问用户」）：品类
    # 封顶裁掉的世界遗产/5A 同类行，问答式让用户裁定要不要多排——偏好
    # 命中的答复并入 preferences 并自动重排（偏好优先于默认封顶）
    pending_type_ask: list[dict] = Field(default_factory=list)
    # 心愿行挂过的行程 id（2026-10-30 深夜）：重组换 id 后允许重挂到当前
    linked_itins: list[str] = Field(default_factory=list)
    # 心愿→真实 POI 绑定（2026-10-30 深夜）：跨回合持久（agent 按请求新
    # 建，会话才是载体）——防重复添加、供 merge 钉选与心愿行收口
    wish_bindings: dict[str, dict] = Field(default_factory=dict)
    # 双语 P2（DESIGN language_dual_system §6）：会话级回复语言；
    # None=中文（CN 站默认），"en"=LLM 面向用户的输出全英文
    lang: str | None = None
    # 城际交通方式（2026-11-07 拍板）：auto=距离闸（>600km 航班、≤600km 火车），
    # train/flight=用户在 H5 起始页指定，作用于全程城际段（去程/途经/返程）；
    # 规划后单段仍可 /transfers/{item_id}/mode 改乘细调
    intercity_mode: Literal["auto", "train", "flight"] = "auto"
    # 载入来源行程（2026-11-13「重新规划却回到上次行程」修复）：✏️ 修改/
    # 页首自动打开出来的会话记下来源行程号——用户在这个会话里说出**另一趟
    # 完整行程**时后端重开会话生成新行程，旧行程一个字段都不动。
    source_itinerary_id: str | None = None
    # 2026-11-14（用户拍板「没保存行程，心愿单就不该保存」）：本会话是否已
    # 点过「💾 保存行程」——未保存前建的心愿行是草稿（draft_session_id），
    # 看板/心愿单不显示；保存时转正。from-itinerary 会话天然已保存。
    wish_committed: bool = False
    # USER ID（2026-11-14 用户拍板「心愿单/已排期按 USER ID 出内容」）：
    # 会话记住登录账号（owner_account_id 同源），建心愿行时随行落库。
    account_id: str | None = None
    # 自由输入原句（2026-11-14「引擎不读输入」）：起步页那句话存下来，
    # 生成前按它读「点名景点 → 必去」；brief_mined 每会话只读一次——
    # 澄清补答天数后再生成不重复烧 LLM，也不重复读同一句。
    brief_text: str = ""
    brief_mined: bool = False
    # 文本日程（2026-11-14「按输入的日程顺序排」）：自由输入写明「第 N 天/
    # On day N」时，点名的地点落到那一天，不再由地理择日改天。
    site_days: dict[str, int] = Field(default_factory=dict)
    # R25 顺序选边（2026-11-23 用户令「文本已按天写好 → 问保持顺序还是按
    # 天气/地理重排」）：keep=site_days 天钉喂引擎（C-25）与 legacy（forced_days）；
    # replan=两边都不吃 site_days；None=旧口径（legacy 吃、引擎不吃）。
    sequence_choice: str | None = None
    # 自由输入点名的排除项（2026-11-14 北京小众案）：「尽量避开故宫、长城」
    # 里的地点不是必去，是排除项——不进 must_visits，选点池同名候选直接出局。
    avoid_sites: list[str] = Field(default_factory=list)
    # 心愿来源留档（2026-11-15 用户拍板「心愿单只在保存/删除时进数据库」）：
    # 规划期间建的心愿不再落库——名字 → {source, note, city, dropped}，
    # 保存行程时 materialize_wish_rows 按它物化成正式行。
    wish_sources: dict[str, dict] = Field(default_factory=dict)
    # 会话修订号（2026-11-23 R20③ 异步重排基线竞态）：每次 PlanSessionStore.save
    # 单调 +1。慢车道重排入队时把它作 baseline_rev 记进 payload，执行时/落盘前
    # 重读会话比对——用户在此期间的手排操作会让 rev 前进，据此丢弃过期重排，
    # 杜绝后台盘面盖掉用户最新手排状态（R13q「回复 07:23 vs 实际 06:30」漂移）。
    rev: int = 0


def heal_item_ids(session: PlanSession) -> list[str]:
    """会话条目 id 重号自愈（2026-11-13 「Day6 磁器口 换点 422 no_match」）：
    agent 的 ``_item_seq`` 是进程级计数，重启归零后新条目会撞上会话里载入的
    旧 id（v1…v30）。同一计划两条同 id 时，换点/删除/钉/移动按 id 首命中别
    天那条，再拿错城去 POI 库精确匹配就 422 no_match。会话读入与响应出站都
    过这一口；幂等，无重号时零改动。"""
    if getattr(session, "plan", None) is None:
        return []
    try:
        notes = ensure_unique_item_ids(session.plan)
    except Exception:  # noqa: BLE001 - 自愈失败绝不能挡住主流程
        logger.warning("plan: item_id heal failed", exc_info=True)
        return []
    if notes:
        logger.warning(
            "plan: session %s 条目 id 重号已改配：%s",
            session.session_id,
            "、".join(notes),
        )
    return notes


class PlanSessionStore:
    """In-process session dict; lookups are device-scoped."""

    def __init__(self) -> None:
        self._sessions: dict[str, PlanSession] = {}

    def save(self, session: PlanSession) -> None:
        # R20③：每次落盘单调推进修订号。所有写库点（主车道消息、拖卡、
        # 点选、confirm、异步重排）都经本口，故 rev 是会话盘面的权威基线。
        session.rev += 1
        self._sessions[session.session_id] = session

    def get(self, session_id: str, *, device_id: str) -> PlanSession | None:
        session = self._sessions.get(session_id)
        if session is None or session.device_id != device_id:
            return None
        heal_item_ids(session)
        return session

    def live_itinerary_ids(self, device_id: str) -> set[str]:
        """本设备在册会话的当前工作行程 id 集（2026-11-12 行程中心死行
        程闸判活）：重排会换新 itinerary_id 且未入库（2026-10-20 拍板
        「只在保存时写入行程库」），但会话仍持有该计划——读侧不得把它
        当死行程把 scheduled 行打回心愿单（排上了还在心愿单振荡根因）。"""
        return {
            s.plan.itinerary_id
            for s in self._sessions.values()
            if s.device_id == device_id and s.plan is not None and s.plan.itinerary_id
        }

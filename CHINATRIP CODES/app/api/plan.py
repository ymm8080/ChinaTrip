"""Plan-agent API (design v2.0 §6.1-§6.3): progressive multi-city planning.

POST /api/v1/plan/start          — <=2 clarifications or an immediate v0
POST /api/v1/plan/{id}/message   — conversational diff iterations
POST /api/v1/plan/{id}/sites/confirm — H5 点选必去确认直插心愿单
POST /api/v1/plan/{id}/save      — explicit save: upsert the working
                                   copy into the itinerary store and
                                   freeze a snapshot (2026-10-20:
                                   planning NEVER auto-persists)

X-Device-ID is required on all routes. Transient LLM failures degrade
in-conversation (one retry, then a friendly reply — the session and plan
survive); the v0 path degrades to a placeholder plan instead of failing
(§6.1 time-to-first-itinerary contract). 502 stays as the safety net for
anything the agent still raises.
"""

import asyncio
import base64
import logging
import re
import uuid
from datetime import date, datetime, time, timezone
from functools import partial
from time import monotonic
from typing import Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    UploadFile,
)
from pydantic import BaseModel, Field

from app.api.amap import get_search_chain
from app.api.hotels import search_hotel_candidates
from app.api.itineraries import (
    _account_from_auth,
    _owned_record,
    get_entitlement_service,
    get_itinerary_service,
    get_store,
)
from app.api.translate import get_translation_service
from app.api.trip_items import get_trip_item_service
from app.config import Settings, get_settings
from app.db import get_session_factory
from app.services.agent.hotel_stays import (
    attach_hotel_mornings,
    attach_hotel_nights,
    hotel_morning_label,
    is_hotel_morning,
    is_hotel_night,
    paired_hotel_card,
    reanchor_hotel_cards,
    sync_hotel_stay,
)
from app.services.agent.plan import (
    PlanningAgent,
    PlanSession,
    PlanSessionStore,
    PoiStoreUnavailableError,
    _count_text_dates,
    _enforce_city_coherence,
    _extract_transport_numbers,
    _find_transfer_item,
    _leg_date_iso,
    _normalize_city,
    _open_meal_leg_gaps,
    _parse_days,
    _parse_text_start_date,
    _resolve_brief_cities,
    _trip_brief,
    clarify_questions,
    current_violations,
    dedupe_plan_visits,
    drop_dangling_visits,
    enforce_entry_gate,
    heal_arrival_light,
    heal_item_ids,
    heal_leg_gaps,
    heal_meal_cards,
)
from app.services.agent.wish_fast import consume_fast_turn
from app.services.ctrip_hours import get_ctrip_hours
from app.services.entitlement import EntitlementService
from app.services.fast_lane import FastLane
from app.services.flights_variflight import build_flight_service
from app.services.gate import Lane, RequestGate
from app.services.itinerary import DiffOp, GeoPoint, VisitItem, mutate
from app.services.itinerary.hotfix_1117 import (
    evict_fillers_when_must_unseated,
    evict_pre_remote_fillers,
    fold_restaurant_visit_cards,
    rescue_entry_gated_musts,
    restore_evicted_fillers,
    retime_remote_day_from_access,
)
from app.services.itinerary.legs import annotate_legs, attach_return_cards
from app.services.itinerary.models import UnplacedCandidate
from app.services.itinerary.request_coverage import (
    dedupe_unplaced_against_scheduled,
    demote_untimed_musts,
    ensure_must_disclosure,
    unarranged_must_visits,
)
from app.services.itinerary_store import (
    ItineraryRecord,
    ItineraryService,
    QuotaExceededError,
)
from app.services.lane_metrics import get_lane_metrics
from app.services.lang_ctx import L, get_lang
from app.services.llm import get_flash_adapter, get_llm_adapter
from app.services.llm.base import ChatMessage
from app.services.llm.zhipu import LLMError
from app.services.map_provider import (
    build_client_chain,
    build_map_client,
    map_ready,
)
from app.services.offer_cards import flight_offer_cards, train_offer_cards
from app.services.poi_alternatives import attach_plan_alternatives
from app.services.poi_details import get_poi_detail_store
from app.services.state_persist import (
    PersistentPlanSessionStore,
    db_path_from_url,
    get_state_backend,
)
from app.services.task_queue import TaskStore, get_task_store
from app.services.trains import get_train_service
from app.services.translate import TranslationService
from app.services.trip_orchestrator.nlu import (
    _restart_named_musts,
    _restart_route_only,
)
from app.services.weather import daily_weather_text
from app.services.web_reader import find_urls

router = APIRouter(prefix="/api/v1", tags=["plan"])
logger = logging.getLogger(__name__)


_MAX_START_IMAGES = 4
_MAX_IMAGE_BYTES = 6 * 1024 * 1024
_ALLOWED_IMAGE_MIME = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/bmp",
}


def _decode_image_payloads(items: list[str] | None) -> list[tuple[bytes, str]]:
    """data URL 图片 → [(bytes, mime)]；非法/超重的整条丢弃，不阻塞开局。"""
    out: list[tuple[bytes, str]] = []
    for raw in (items or [])[:_MAX_START_IMAGES]:
        text = (raw or "").strip()
        if not text.startswith("data:image/"):
            continue
        try:
            head, b64 = text.split(",", 1)
            mime = head[5:].split(";", 1)[0] or "image/jpeg"
            data = base64.b64decode(b64, validate=False)
        except Exception:
            logger.warning("plan/start: bad image payload skipped")
            continue
        if not data or len(data) > _MAX_IMAGE_BYTES:
            logger.warning("plan/start: image payload dropped (size=%d)", len(data))
            continue
        out.append((data, mime))
    return out


class PlanStartRequest(BaseModel):
    cities: list[str] | None = None
    days: int | None = None
    preferences: str = ""
    city_days: dict[str, int] | None = None  # 目的地 → 停留天数（H5 每城天数）
    start_date: str | None = None  # 出发日期 ISO（可空）——随快照持久化
    # 城际交通方式（2026-11-07 拍板）：auto=距离闸（>600km 航班、≤600km 火车），
    # train/flight=H5 起始页用户指定；全程城际段统一口径
    intercity_mode: Literal["auto", "train", "flight"] = "auto"
    lang: str | None = None  # 双语 P2：会话回复语言 "en"/"zh"（缺省 zh）
    # 自由输入框里那一整句（2026-11-13「重新规划却回到上次行程」）：它写出
    # 的路线优先于表单回填值——用户刚打的这句才是新设置。
    brief: str | None = None
    # 开局带图（2026-11-14「图片上有的也抽出来」）：data URL 列表，最多 4 张；
    # 后端读成地点先开确认轮，用户点选后才生成行程。
    images: list[str] | None = None
    # 行前信息（2026-11-14 用户拍板）：去程/返程班次号或当地到达·离开时刻——
    # H5 行前确认卡收集，全部可空；后端 v0 后按真实时刻落位对应城际腿。
    arrival_no: str | None = None
    arrival_time: str | None = None  # 当地到达「HH:MM」
    departure_no: str | None = None
    departure_time: str | None = None  # 当地离开「HH:MM」
    arrival_date: str | None = None  # 到达日 ISO（缺省=首日）
    departure_date: str | None = None  # 离开日 ISO（缺省=末日）
    # 行前卡标志：H5 弹过行前确认卡才置真（放宽语义 opting-in，见 PlanSession）
    intake: bool = False
    # 路线冲突确认（2026-11-14 用户拍板）：文字简报与表单参数不一致时先让用户
    # 裁决——confirm_route 确认卡回传 "brief"=按文字 / "form"=按表单。
    route_source: Literal["brief", "form"] | None = None
    # 确认卡逐条选边的落点（2026-11-14 用户三条口径）：天数/班次号由用户选定
    days_override: int | None = None
    arrival_no_override: str | None = None
    departure_no_override: str | None = None


class PlanMessageRequest(BaseModel):
    text: str = Field(min_length=1)


class PlanSitesConfirmRequest(BaseModel):
    mandatory: list[str] = Field(default_factory=list)  # 点选的必去地点名


class PlanPinRequest(BaseModel):
    pinned: bool


_agent_singleton: PlanningAgent | None = None
_sessions_singleton: PersistentPlanSessionStore | None = None


def get_planning_agent() -> PlanningAgent:
    """Process-wide lazy singleton (translate.py pattern). No amap key
    means placeholder candidates, not a 503 — planning must still deliver.

    settings 函数体内直取、不走 Depends 默认值——慢车道后台重排在 DI
    上下文外直接调本工厂（task_queue._replan_handler），裸 Depends 哨兵
    会被当实参炸出 'Depends' object has no attribute 'map_provider'
    （2026-11-07 事故门禁；写法对齐 get_plan_sessions）。"""
    global _agent_singleton
    if _agent_singleton is None:
        settings = get_settings()
        amap = build_map_client(settings) if map_ready(settings) else None
        _agent_singleton = PlanningAgent(
            get_llm_adapter(settings),
            amap_client=amap,
            # 检索链（2026-10-30 vendor_policy）：amap>tencent>baidu，缺 key 自动跳过
            search_chain=build_client_chain(settings, "search"),
            train_service=get_train_service(settings),
            # 航班与火车同构（2026-10-28）：flight_api_key 空 → Mock 占位，
            # 配置 key → VariFlight 适配器（管线零改动）。
            flight_service=build_flight_service(settings),
            time_budget_seconds=settings.solver_time_budget_seconds,
            trip_items=get_trip_item_service(),
            poi_details=get_poi_detail_store(),
            ctrip_hours=get_ctrip_hours(),
            # 雨天感知（2026-10-30）：纯 DB 读 weather_reports（每日
            # 08:10 管线全量 40 城），请求路径零外呼；读失败在
            # _rain_map 内降级为无雨，规划不受影响
            weather_lookup=partial(daily_weather_text, get_session_factory()),
        )
    return _agent_singleton


def get_plan_sessions() -> PlanSessionStore:
    """Process-wide persistent store: sessions survive uvicorn restarts."""
    global _sessions_singleton
    if _sessions_singleton is None:
        settings = get_settings()
        _sessions_singleton = PersistentPlanSessionStore(
            get_state_backend(db_path_from_url(settings.state_db_url))
        )
    return _sessions_singleton


_gate_singleton: RequestGate | None = None
_fast_lane_singleton: FastLane | None = None


def get_request_gate(settings: Settings = Depends(get_settings)) -> RequestGate:
    """§6.12 分类闸门进程级单例（translate.py 单例模式）。"""
    global _gate_singleton
    if _gate_singleton is None:
        _gate_singleton = RequestGate(
            get_flash_adapter(settings),
            intent_cache_ttl_seconds=settings.intent_cache_ttl_seconds,
            intent_cache_max_entries=settings.intent_cache_max_entries,
        )
    return _gate_singleton


def get_fast_lane(
    settings: Settings = Depends(get_settings),
    translate: TranslationService = Depends(get_translation_service),
) -> FastLane:
    """§6.12 快车道处理器单例（答案缓存 TTL/容量走 settings）。
    translate 必须走 Depends 注入——直接调 get_translation_service()
    会把裸 Depends 默认值当实参（2026-10-27 事故门禁）。"""
    global _fast_lane_singleton
    if _fast_lane_singleton is None:
        _fast_lane_singleton = FastLane(
            poi_details=get_poi_detail_store(),
            trip_items=get_trip_item_service(),
            translate=translate,
            answer_ttl_seconds=settings.fast_lane_answer_ttl_seconds,
            answer_max_entries=settings.fast_lane_answer_max_entries,
        )
    return _fast_lane_singleton


_BG_PREFETCH_TASKS: set[asyncio.Task] = set()  # 防后台任务被 GC


class PlanSaveRequest(BaseModel):
    name: str | None = None
    note: str | None = None
    # 2026-10-25 旧行程自愈：itinEdit 对没存过出发日期的行程缺省「今天」，
    # 随保存落库（None = 不改 plan 里已有的值）
    start_date: str | None = None


@router.post("/plan/{session_id}/save", status_code=201)
async def save_plan(
    session_id: str,
    request: PlanSaveRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: PlanSessionStore = Depends(get_plan_sessions),
    itinerary_store=Depends(get_store),
    service: ItineraryService = Depends(get_itinerary_service),
    entitlement: EntitlementService = Depends(get_entitlement_service),
    account: str | None = Depends(_account_from_auth),
    agent: PlanningAgent = Depends(get_planning_agent),
) -> dict:
    """Explicit save (2026-10-20 product rule: 行程只在用户点「💾 保存行程」
    时写入行程库). Upserts the session's working plan into the itinerary
    store (owner = device; a Bearer account claims it) and freezes one
    immutable snapshot — quota denial answers 402 with the paywall
    trigger, while the working copy stays persisted."""
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    session = store.get(session_id, device_id=x_device_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    if session.plan is None:
        raise HTTPException(status_code=400, detail="nothing_to_save")
    plan = session.plan
    # 旗时最高优先级（2026-11-14 UAT 五修）：保存即按数据库旗时纠正
    # 天安门开始时刻（含 fixed 在册被行编辑/默认值改回的），不随旧值入库。
    from app.services.agent.plan import _apply_flag_schedule

    _apply_flag_schedule(plan)
    if request.start_date and request.start_date != plan.start_date:
        plan = plan.model_copy(update={"start_date": request.start_date})
        session.plan = plan
        store.save(session)
        # 出发日期变更即预热票务（2026-10-28）：城市在计划里已齐，火车查询
        # 立刻开跑，下一次组装/重排直接吃缓存。
        _warm = asyncio.create_task(
            agent.prefetch_transfer_schedules(
                plan.cities, len(plan.days), request.start_date
            )
        )
        _BG_PREFETCH_TASKS.add(_warm)
        _warm.add_done_callback(_BG_PREFETCH_TASKS.discard)
    # 入库终闸（2026-10-28 变脸 x4 事故）：冻结快照前强制同站合并——
    # 任何来源（旧代码进程编辑/历史脏会话）的重复站点从此进不了行程库；
    # 合并发生时把工作副本一并存回会话。
    if dedupe_plan_visits(plan):
        session.plan = plan
        store.save(session)
    # 腿间隔终闸（2026-11-03）：零车程背靠背时刻进不了行程库——带腿
    # 重排后再冻结；钉/餐不动。
    heal_notes = heal_leg_gaps(plan)
    if heal_notes:
        for note in heal_notes:
            logger.warning("plan/save %s leg-gap heal: %s", session_id, note)
        session.plan = plan
        store.save(session)
    # 无时刻卡终闸（2026-11-03 Day4 太平森林公园案）：混合日垫底的
    # None-None 参访卡进不了行程库——非钉移除留痕，钉/餐不动；整日
    # 全未排的降级日不动（读路径不重议交付层拍板）。
    drop_notes = drop_dangling_visits(plan)
    if drop_notes:
        for note in drop_notes:
            logger.warning("plan/save %s untimed-drop: %s", session_id, note)
        plan.assumptions.extend(drop_notes)
        session.plan = plan
        store.save(session)
    # 雨日调换终闸（2026-11-11 拍板「打开行程自动更新天气，同时根据雨
    # 天走调换逻辑」）：冻结前现查天气库——雨日不耐雨组合与干日耐雨组
    # 合对调，钉/场次/餐酒店不动，披露进 assumptions。
    rain_notes = agent.rain_rebalance_days(session)
    if rain_notes:
        for note in rain_notes:
            logger.warning("plan/save %s rain-swap: %s", session_id, note)
        session.plan = plan
        store.save(session)
    record = itinerary_store.get(plan.itinerary_id)
    # 2026-11-13（用户拍板「CHANGE LOG … AFTER CLICK SAVE BUTTON」）：
    # 覆盖前先留一份旧计划，保存后写逐条 diff。
    prev_plan = record.plan.model_copy(deep=True) if record is not None else None
    if record is None:
        record = ItineraryRecord(
            itinerary_id=plan.itinerary_id,
            owner_device_id=x_device_id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            plan=plan,
        )
    else:
        record.plan = plan
        record.working_sync_version += 1
        record.updated_at = datetime.now(timezone.utc)
    if account is not None and not record.owner_account_id:
        record.owner_account_id = account
    itinerary_store.put(record)
    # 2026-11-14（用户拍板「WHEN I DO NOT SAVE TRIP, 心愿单 should not be
    # saved」的对偶）：点保存 = 本会话建的心愿草稿转正（清 draft_session_id）
    # ——从这一刻起行程中心的愿望单/已排期才看得到这些行；之后再聊出来的
    # 心愿行直接是正式行（行程已在库）。
    agent.commit_wish_drafts(session, account)
    store.save(session)
    try:
        snapshot = service.create_snapshot(
            record,
            name=request.name,
            note=request.note,
            entitlement=entitlement,
            subject_id=x_device_id,
        )
    except QuotaExceededError as exc:
        raise HTTPException(
            status_code=402,
            detail={
                "denied_reason": exc.denied_reason or "quota_exhausted",
                "paywall_trigger": exc.paywall_trigger,
            },
        ) from exc
    # 2026-11-13（陕历博仍躺心愿单案）：保存即对账看板（保存是行程入库的
    # 唯一时刻，看板必须跟着落排走）。
    agent.sync_trip_rows(session)
    # 2026-11-13（用户拍板 trip 头/明细/变更日志进库）：一次保存写三份——
    # 头（改名/最后变更/创建人）、明细（天·时段·点位·备选）、变更日志
    # （USER / USER NAME / CHANGES）。
    try:
        from app.db import get_session_factory as _sf
        from app.services.trip_changes import record_trip_change

        record_trip_change(
            _sf(),
            record,
            old_plan=prev_plan,
            new_plan=plan,
            actor_name=(account or x_device_id),
            snapshot_id=snapshot.snapshot_id,
        )
    except Exception:
        logger.warning("plan/save %s change-log failed", session_id, exc_info=True)
    return snapshot.model_dump(exclude={"plan"})


@router.post("/plan/from-itinerary/{itinerary_id}", status_code=201)
async def start_plan_from_itinerary(
    itinerary_id: str,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    agent: PlanningAgent = Depends(get_planning_agent),
    store: PlanSessionStore = Depends(get_plan_sessions),
    itinerary_store=Depends(get_store),
    account: str | None = Depends(_account_from_auth),
) -> dict:
    """继续修改已有行程（2026-10-20：「行程」页 ✏️ 修改）——deep-copy 该
    行程的工作副本开一个新规划会话（state=ready），对话改动照走铁律
    管线；「💾 保存行程」按原 itinerary_id 覆盖并冻结新快照。Unknown /
    foreign-owner ids answer 404（itineraries 同款防枚举）。"""
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    record = _owned_record(itinerary_store, itinerary_id, x_device_id, account)
    plan = record.plan.model_copy(deep=True)
    # 2026-11-14：✏️ 修改已存行程的会话也记住 USER ID（心愿行即时落账号）
    # 同站合并开档闸（2026-10-28）：旧行程带出的重复站点（如变脸 x4）
    # 开档即合并；行程库本体由 save 终闸兜住。
    dedupe_plan_visits(plan)
    # 2026-11-13：功能上线前保存的老行程快照没有酒店卡——开档补齐
    # 「回酒店·夜间休息」与「🏨 从酒店出发」，否则继续修改时每天没有
    # 起点（用户报「看不到酒店作为出发点」）。只补「一张酒店卡都没有」
    # 的行程，已有卡（含用户删剩一张）不复活、不重复。
    if not any(
        is_hotel_night(i) or is_hotel_morning(i) for d in plan.days for i in d.items
    ):
        plan.assumptions.extend(attach_hotel_nights(plan.days))
        plan.assumptions.extend(attach_hotel_mornings(plan.days))
    session = PlanSession(
        session_id=uuid.uuid4().hex,
        device_id=x_device_id,
        # 2026-11-14（用户拍板「心愿单按 USER ID 出内容」）：编辑会话带账号
        account_id=account,
        # 双语 P2 补漏（2026-10-30）：会话语言随 X-Lang 请求头
        # （LangMiddleware 写入的 contextvar，与端内 L() 同源）。
        # 漏传时英文界面下「✏️ 修改」会话的编辑回合恒中文——
        # _with_lang 的英文输出指令只认 session.lang。
        lang=get_lang(),
        # 2026-11-13：记下来源行程——✏️ 修改会话里用户说出另一趟完整行程时，
        # 后端重开新会话，旧行程不被顺手改掉（「重新规划却回到上次行程」）。
        source_itinerary_id=itinerary_id,
        cities=list(plan.cities),
        days=len(plan.days),
        state="ready",
        plan=plan,
        assumptions=list(plan.assumptions),
        history=[
            ChatMessage(
                role="assistant",
                content=(
                    L(
                        f"已载入行程 {itinerary_id}（{':'.join(plan.cities)}，"
                        f"{len(plan.days)} 天）。直接说要怎么改（例如：把第二天的"
                        "景点挪到第三天、加一天）；改完点「💾 保存行程」覆盖保存。",
                        f"Itinerary {itinerary_id} loaded ({':'.join(plan.cities)}, "
                        f"{len(plan.days)} days). Just say what to change (e.g. move "
                        "day-2 sights to day 3, or add a day); tap '💾 Save Itinerary' "
                        "to overwrite when done.",
                    )
                ),
            )
        ],
    )
    # 2026-11-14（故宫灰卡案）：开档即自愈必去覆盖——钉住/必去观光件
    # 无时刻的旧行程先让位清算+跨日救生（能排即排、低优先件让位），
    # 再实测腿（救生重排过的相邻对才有真腿）。
    await agent.heal_must_coverage(session)
    # 空档补点（2026-11-16 上海案）：旧行程开档也补一次——幂等（已有补点
    # 披露即跳过），反复打开不会叠加。
    await agent.fill_leftover_gaps(session)
    await agent.refresh_legs(session)
    # 旗时最高优先级（2026-11-14 UAT：载入旧行程天安门仍是 8:30）：
    # 开档即按数据库旗时纠正（含 fixed 已在册被行编辑改回的时刻）。
    from app.services.agent.plan import _apply_flag_schedule

    _apply_flag_schedule(plan)
    store.save(session)
    # 2026-11-13（陕历博仍躺心愿单案）：开档即对账看板——心愿单里已落排的
    # 翻已排期，已排期里本行程没有的回心愿单。
    agent.sync_trip_rows(session)
    body: dict = {"session_id": session.session_id, "state": session.state}
    body["plan"] = _plan_for_response(session.plan)
    body["assumptions"] = session.assumptions
    body["violations"] = current_violations(session)
    return body


@router.get("/plan/{session_id}")
async def get_plan_session(
    session_id: str,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    agent: PlanningAgent = Depends(get_planning_agent),
    store: PlanSessionStore = Depends(get_plan_sessions),
) -> dict:
    """规划会话读取（2026-10-28）：H5 刷新/重开页面恢复行程卡用。返回前跑
    一遍实测腿刷新（annotate → 缺坐标回填 → 缓存回放 → 新对高德/百度实测），
    旧行程打开即有距离与步行信息，无需先做一次编辑。"""
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    session = store.get(session_id, device_id=x_device_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    if session.plan is None:
        raise HTTPException(status_code=400, detail="no_plan")
    # 同站合并读闸（2026-10-28 变脸 x4 事故）：历史脏数据打开即自愈，
    # 与下方实测腿刷新同模式（读路径修复 + store.save 持久化）。
    dedupe_plan_visits(session.plan)
    # 腿间隔读闸（2026-11-03 Day2 大明宫→城墙 15:00 零车程事故）：
    # 11-02 前旧兜底产物带腿重排自愈，钉/餐不动，装不下留空披露。
    for note in heal_leg_gaps(session.plan):
        logger.warning("plan/session %s leg-gap heal: %s", session_id, note)
    # 无时刻卡读闸（2026-11-03 Day4 太平森林公园案）：旧会话混合日的
    # None-None 参访卡（垫在 19:30 演出之后、腿标注画巨腿）打开即清
    # ——非钉移除留痕；钉（build 期必打钉）铁律 19 不动；整日全未排
    # 的降级日不清（骨架会话不能被读闸读穿成空壳）。
    drop_notes = drop_dangling_visits(session.plan)
    if drop_notes:
        for note in drop_notes:
            logger.warning("plan/session %s untimed-drop: %s", session_id, note)
        session.plan.assumptions.extend(drop_notes)
    # 雨日调换读闸（2026-11-11 拍板「天气真值每日漂移，打开行程自动更
    # 新天气，同时根据雨天走调换逻辑」）：现查天气库——雨日不耐雨组合
    # 与干日耐雨组合对调，钉/场次/餐酒店不动；双语披露进 assumptions。
    for note in agent.rain_rebalance_days(session):
        logger.warning("plan/session %s rain-swap: %s", session_id, note)
    # 空档补点读闸（2026-11-16 上海案）：开页只治「上午空着」——晨卡先回
    # 08:30 日始，上午空出来的天按类型多样性补点；无空上午的行程零成本空转，
    # 绝不在刷新时往行程里加新卡。
    await agent.fill_leftover_gaps(session, morning_only=True)
    await agent.refresh_legs(session)
    # 覆盖审计要在 save 之前跑（2026-11-17）：所有端点都是先落库再组响应，
    # 只在响应层审计会让披露/清脏不落库——GET 是持久化主路径，幂等可重入。
    # 白天入场闸读闸（2026-11-17 二拍）同位落库：越闸非钉普通观光卡退回
    # 无时刻+披露（幂等；豁免面与 solver.generic_entry_cap 同源）。
    session.plan.assumptions.extend(enforce_entry_gate(session.plan))
    _audit_must_coverage(session)
    store.save(session)
    return _plan_turn_body(session, None, None)


@router.post("/plan/start")
async def start_plan(
    request: PlanStartRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    agent: PlanningAgent = Depends(get_planning_agent),
    store: PlanSessionStore = Depends(get_plan_sessions),
    account: str | None = Depends(_account_from_auth),
) -> dict:
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    # 行前卡只在「文字输入且信息不足」时弹出（2026-11-15 用户拍板）：文字里
    # 读得出出发日期=信息足够，直接生成；读不出且行前卡信息也没给 → 先弹卡
    # （state=intake，不开会话）。
    brief_text = (request.brief or "").strip()
    # H5 开局把自由输入折进 preferences（2026-11-17 ZHUJIAZUI 案）：表单
    # 没填城市/天数时，日期天数从 preferences 原句里读——文字里说了就不
    # 再弹行前卡。表单齐全时仍只看 brief，不打扰表单用户。
    pref_text = (
        (request.preferences or "").strip()
        if not request.cities and not request.days
        else ""
    )
    fact_text = brief_text or pref_text
    if find_urls(fact_text):  # 链接流不走行前卡（链接自己进读点管线）
        fact_text = ""
    text_date = _parse_text_start_date(fact_text) if fact_text else None
    parsed_brief = _trip_brief(brief_text) if brief_text else None
    text_days = parsed_brief[1] if parsed_brief else None
    if text_days is None and fact_text:
        text_days = _parse_days(fact_text)
    # 文字明说的天数（拍板③「行前卡信息和文字不同要摆差异」的文字侧）：
    # 正则口径（brief 天数 → 原句天数兜底）。下面「单日期⇒一日游」只是行前
    # 卡闸门的推断，不算文字陈述——用户在卡上挑了别的跨度不算和文字打架，
    # 不进差异（2026-11-17「文字 2 天、弹窗 1 天没确认」案）。
    stated_days = text_days
    # 只写了一个日期 ⇒ 一日游（2026-11-17 用户拍板「IT MEANS ONLY ONE DAY
    # TRIP」）；写了起止两个日期仍按缺天数处理，行前卡照弹。
    if (
        text_date is not None
        and text_days is None
        and not request.days
        and _count_text_dates(fact_text) <= 1
    ):
        text_days = 1
    # 信息不足=缺「任何必填项」（2026-11-15 用户拍板二拍「不止是出发日期」）：
    # 文字读不出出发日期、或读得出日期却读不出天数/结束日 → 都弹行前卡
    # （响应带 start_date_hint，卡上的开始日期用文字日期预填）。
    insufficient = text_date is None or text_days is None
    if (
        request.route_source is None
        and fact_text
        and not request.arrival_date
        and not request.departure_date
        and insufficient
    ):
        # LLM 先读懂日期/天数（2026-11-17 拍板「LLM UNDERSTAND DATE, TIME
        # DURATION ETC」）：正则读不出的（next Friday / around New Year /
        # 三晚）交给 LLM；LLM 也读不出才弹行前卡。
        facts = await agent.trip_facts_from_llm(fact_text) or {}
        if text_date is None and facts.get("start_date"):
            text_date = str(facts["start_date"])
        if text_days is None and facts.get("days"):
            text_days = int(facts["days"])
        elif (
            text_date is not None
            and text_days is None
            and not request.days
            and _count_text_dates(fact_text) <= 1
        ):
            text_days = 1
        insufficient = text_date is None or text_days is None
        if insufficient:
            return {"state": "intake", "start_date_hint": text_date}
        if facts.get("city") and not request.cities:
            # LLM 读出的城市一并预填——agent.start 不再二次读句（一次 LLM
            # 读出全部事实，直接灌引擎）。
            request = request.model_copy(update={"cities": [str(facts["city"])]})
    if text_date and not request.start_date:
        request = request.model_copy(update={"start_date": text_date})
    # 行前卡提交后的天数推导（2026-11-15 用户实报「填了开始/结束日期还问玩
    # 几天」）：request.days 缺省且卡给了到达/离开日期 → 天数=跨度，不再追问。
    if not request.days and request.arrival_date and request.departure_date:
        try:
            span = (
                date.fromisoformat(str(request.departure_date)[:10])
                - date.fromisoformat(str(request.arrival_date)[:10])
            ).days + 1
            if span >= 1:
                request = request.model_copy(update={"days": span})
        except ValueError:
            pass
    # 差异确认（2026-11-14 用户拍板三条）：①表单没填+有文字 → 默认按文字；
    # ②表单和文字都填了 → 摆出差异让用户确认；③行前卡信息和文字不同 → 同样
    # 摆出差异。统一收集 diffs，任何一条且用户还没选边 → confirm_route。
    parsed = (
        _trip_brief(request.brief)
        if (request.brief and request.brief.strip())
        else None
    )
    diffs: list[dict] = []
    resolved: list[str] | None = None
    if parsed is not None and request.cities and request.route_source is None:
        resolved = _resolve_brief_cities(
            [_normalize_city(c) for c in parsed[0]], request.cities
        )
        if {_normalize_city(c) for c in resolved} != {
            _normalize_city(c) for c in request.cities
        } or (parsed[1] is not None and request.days and parsed[1] != request.days):
            diffs.append(
                {
                    "what": "route",
                    "text": {"cities": resolved, "days": parsed[1]},
                    "intake": {"cities": request.cities, "days": request.days},
                }
            )
    card_span = None
    if request.arrival_date and request.departure_date:
        try:
            card_span = (
                date.fromisoformat(str(request.departure_date)[:10])
                - date.fromisoformat(str(request.arrival_date)[:10])
            ).days + 1
        except ValueError:
            card_span = None
    if (
        stated_days
        and card_span
        and stated_days != card_span
        and request.days_override is None
    ):
        # 文字天数 vs 行前卡日期跨度（用户拍板③：行前卡信息和文字不同也要摆）。
        # 文字侧用 stated_days：brief 只认正则明说的天数，客户端丢简报把它折
        # 进 preferences 时照样比得上（2026-11-17「文字 2 天、弹窗 1 天没确
        # 认」案）；days_override=确认卡已选边，不再二次弹卡。
        diffs.append({"what": "days", "text": stated_days, "intake": card_span})
    text_nos = _extract_transport_numbers(request.brief)
    card_nos = [
        n
        for n in (
            (request.arrival_no or "").strip().upper(),
            (request.departure_no or "").strip().upper(),
        )
        if n
    ]
    if (
        text_nos
        and {n.upper() for n in text_nos} != set(card_nos)
        and request.arrival_no_override is None
        and request.departure_no_override is None
    ):
        # 班次差异；覆写=确认卡已选边（选文字班次的落点），不再二次弹卡
        diffs.append({"what": "numbers", "text": text_nos, "intake": card_nos})
    if (
        card_span
        and request.days
        and card_span != request.days
        and request.days_override is None
    ):
        # 行前卡日期跨度 vs 表单天数（用户改过行前卡结束日期时如实呈现）；
        # days_override=确认卡已选边，不再二次弹卡
        diffs.append({"what": "card_days", "intake": card_span, "form": request.days})
    if diffs and request.route_source is None:
        return {
            "state": "confirm_route",
            "diffs": diffs,
            "text_route": {
                "cities": resolved or [],
                "days": stated_days,
            },
            "form_route": {"cities": request.cities, "days": request.days},
        }
    # 用户在确认卡上选了边：brief=按文字路线（表单参数作废，路线全从文字解析）；
    # form=按表单参数（文字只当偏好文本，不再当简报改写路线）。
    if request.route_source == "brief":
        # 按文字路线：表单参数作废，但出发城上下文仍传给 start——简报只报
        # 目的地时出发城沿用表单（2026-11-13「成都 3 天」口径）；分城天数
        # 作废（city_days=None），文字天数才能生效。
        start_cities = request.cities
        start_days = request.days or 0
        start_brief = request.brief
        start_city_days = None
    elif request.route_source == "form":
        start_cities = request.cities
        start_days = request.days or 0
        start_brief = None
        start_city_days = request.city_days
    else:
        start_cities = request.cities or []
        start_days = request.days or 0
        start_brief = request.brief
        start_city_days = request.city_days
    # R8（2026-11-18 拍板「全量切引擎」）：确认卡 override=用户已选边，
    # 折算后透传给引擎——与 legacy agent.start 的 session 落位同口径
    # （days_override 同时作废分城天数）。
    ts_days = (
        max(1, int(request.days_override)) if request.days_override else start_days
    )
    ts_city_days = {} if request.days_override else start_city_days
    ts_arrival_no = (
        str(request.arrival_no_override).strip().upper()
        if request.arrival_no_override
        else request.arrival_no
    )
    ts_departure_no = (
        str(request.departure_no_override).strip().upper()
        if request.departure_no_override
        else request.departure_no
    )
    # P3 seam (F-35/F-42, default legacy = zero behavior change): when
    # TRIP_SOLVER=cpsat and the serving stack is ready, generate through
    # the model engine in a worker thread; any failure falls back to the
    # legacy cascade with a disclosure (M8 rollback shape).
    trip_session = None
    trip_outcome = None
    # 2026-11-21 成都环球中心案（心愿单被引擎缝吞掉）：R8 全量切引擎后，
    # 纯开局走 generate_session_via_trip_solver(musts=[]) 硬编码空必去，
    # 绕开 legacy 的 _generate_v0 → _absorb_wishlist——行程中心心愿单里属于
    # 本次城市的心愿（如「成都环球中心」city=成都）静默不进规划、也无披露。
    # 走缝前复用同一权威吸收逻辑（城市闸/排除/meta/跨城披露），把结果并进
    # musts 交给引擎；跨城跳过披露随会话带出。legacy 路径不受影响（它自己
    # 在 _generate_v0 里吸收），这里只在引擎缝分支生效。
    seam_wish_musts: list[str] = []
    seam_wish_notes: list[str] = []
    try:
        from app.services.trip_solver.entry import (
            ENGINE_CPSAT,
            engine_flag,
            seam_plain_shape,
            serving_ready,
            set_seam_attempted,
        )
        from app.services.trip_solver.live import (
            _intake_day_no,
            generate_session_via_trip_solver,
        )

        if (
            engine_flag() == ENGINE_CPSAT
            and serving_ready()[0]
            # R8 形状闸收窄（2026-11-18「全量切引擎」）：映射类字段
            # （城际方式/班次 override/行前卡标志）透传直连；仍留 legacy
            # 的唯 brief/带图（读点确认轮）、分城天数（建模挂账）、
            # 非默认端点行前日期（中途转移日）。
            and seam_plain_shape(
                brief=start_brief,
                images=request.images,
                arrival_date=request.arrival_date,
                departure_date=request.departure_date,
                start_date=request.start_date,
                days=ts_days,
                cities=start_cities,
            )
        ):
            # 二期：本请求已由 api 缝尝试引擎——_generate_v0 重解钩子
            # 不再重试（防双跑/双披露）；失败回落由缝自带披露
            set_seam_attempted()

            # 复用 agent 的心愿吸收（与 legacy _generate_v0 同一函数）：构造
            # 轻会话只带设备/城市，读心愿单得到本行程城市心愿名 + 跨城披露。
            # 取返回值即可，不污染引擎缝随后自建的真正规划会话。
            try:
                wish_probe = PlanSession(
                    session_id="wish-absorb-probe",
                    device_id=x_device_id,
                    cities=list(start_cities or []),
                    account_id=account,
                )
                seam_wish_musts, seam_wish_notes = await agent._absorb_wishlist(
                    wish_probe
                )
            except Exception:
                logger.warning("plan/start seam wishlist absorb failed", exc_info=True)
                seam_wish_musts, seam_wish_notes = [], []

            def _ts_generate():
                return generate_session_via_trip_solver(
                    device_id=x_device_id,
                    cities=list(start_cities or []),
                    days=ts_days or 0,
                    start_date=request.start_date,
                    musts=list(seam_wish_musts),
                    store=get_poi_detail_store(),
                    # R13j：live 引擎雨天约束接线（此前两缝均不传
                    # weather_lookup——legacy 有天气/corpus 有 baked 天气、
                    # 唯独 live 引擎瞎排雨天）。同 legacy 注入口径
                    # （agent._weather_lookup=api:255 同款 partial）。
                    weather_lookup=partial(daily_weather_text, get_session_factory()),
                    preferences=request.preferences or "",
                    arrival_time=request.arrival_time,
                    departure_time=request.departure_time,
                    arrival_no=ts_arrival_no,
                    departure_no=ts_departure_no,
                    intercity_mode=request.intercity_mode,
                    city_days=dict(ts_city_days) if ts_city_days else None,
                    lang=request.lang,
                    # R13p（2026-11-22 审计修复）：原始行前日期也随缝落地——
                    # 重排 _session_snapshot 从会话 arrival_date/departure_date
                    # 用 _intake_day_no 重算中途转移日，只传 arrival_day 不够。
                    arrival_date=request.arrival_date,
                    departure_date=request.departure_date,
                    # R9-2：中途转移日——行前日期折天序入快照（C-05 地板/
                    # 顶盖挪到该日；端点日=None 保持旧形状）
                    arrival_day=_intake_day_no(
                        request.arrival_date,
                        request.start_date,
                        ts_days or 0,
                        1,
                    ),
                    departure_day=_intake_day_no(
                        request.departure_date,
                        request.start_date,
                        ts_days or 0,
                        ts_days or 1,
                    ),
                )

            trip_session, trip_outcome = await asyncio.to_thread(_ts_generate)
    except Exception:
        logger.exception("plan/start trip_solver seam failed; legacy serves")
    if trip_session is not None:
        session = trip_session
    else:
        # R12 质量营救（2026-11-19 用户拍板）：引擎失败 → agent.start
        # （legacy）服务 + 缝披露随附（下方 append）——绝不静默。
        try:
            session = await agent.start(
                device_id=x_device_id,
                cities=start_cities,
                days=start_days,
                preferences=request.preferences or "",
                city_days=start_city_days,
                start_date=request.start_date,
                intercity_mode=request.intercity_mode,
                lang=request.lang,
                brief=start_brief,
                arrival_no=request.arrival_no,
                arrival_time=request.arrival_time,
                departure_no=request.departure_no,
                departure_time=request.departure_time,
                arrival_date=request.arrival_date,
                departure_date=request.departure_date,
                intake=request.intake,
                days_override=request.days_override,
                arrival_no_override=request.arrival_no_override,
                departure_no_override=request.departure_no_override,
                images=_decode_image_payloads(request.images),
                # 换设备登录心愿归属：会话创建即带账号，legacy
                # _generate_v0 → _absorb_wishlist 能按 owner_account_id 读行
                account_id=account,
            )
        except PoiStoreUnavailableError:
            # 库降级（DB 锁存+空内存）不出占位假行程——干净 503 让前端
            # 提示稍后重试（2026-10-25 占位事故门禁）。
            logger.warning("plan/start poi_store_unavailable")
            raise HTTPException(status_code=503, detail="poi_store_unavailable")
        except LLMError as exc:
            # LLMError messages are sanitized (never contain the API key).
            logger.exception("plan/start llm_error: %s", exc)
            raise HTTPException(status_code=502, detail="llm_error") from exc
        if (
            trip_outcome is not None
            and getattr(trip_outcome, "fallback", False)
            and trip_outcome.disclosures
        ):
            # R12：legacy 营救的披露随附（绝不静默换引擎）
            session.assumptions.append(trip_outcome.disclosures[0].get("zh", ""))
    # 2026-11-14（用户拍板「心愿单/已排期按 USER ID 出内容」）：会话记住
    # 登录账号——会话里建的心愿行落 owner_account_id
    session.account_id = account or session.account_id
    # 2026-11-21 心愿吸收披露：引擎缝成功时把 absorbed/skip 带出（legacy
    # 路径已在 _generate_v0 自报，不重复）。must_visits 也补记，供后续
    # message/replan 的 _session_snapshot 继续认这些心愿为必去。
    if trip_session is not None and (seam_wish_musts or seam_wish_notes):
        session.must_visits = list(
            dict.fromkeys([*(session.must_visits or []), *seam_wish_musts])
        )
        if seam_wish_musts:
            session.assumptions.append(
                L(
                    "已从行程中心心愿单带入必去：" + "、".join(seam_wish_musts),
                    "Must-visits brought in from the trip-center wishlist: "
                    + "、".join(seam_wish_musts),
                )
            )
        if seam_wish_notes:
            session.assumptions.extend(seam_wish_notes)
    # R13o③（R13n 审计）：升旗锚接 start 缝尾——旗时最高优先（2026-11-14
    # UAT 拍板）此前只接在 save/from-itinerary 开档缝，全新引擎会话首屏
    # 不跑升旗链（北京新单天安门排 12:00 中午场）。幂等（R12-G 重叠推平
    # 已内建）。
    if session.plan is not None:
        from app.services.agent.plan import _apply_flag_schedule

        _apply_flag_schedule(session.plan)
    # 同款：save 前审计，生成首屏的披露/清脏直接落库（下方响应层的
    # _audit_must_coverage 保留为兜底，幂等无副作用）。
    # 白天入场闸读闸同位：生成首屏的越闸卡先清时刻再落库。
    if session.plan is not None:
        session.plan.assumptions.extend(enforce_entry_gate(session.plan))
        # 城市日一致性出站闸（2026-11-22 上海→西安→北京案）：生成首屏
        # 不许把北京景点排进西安天、上海外滩排进北京天——落库前最后收口。
        for _note in _enforce_city_coherence(session.plan):
            if _note not in session.plan.assumptions:
                session.plan.assumptions.append(_note)
            if _note not in session.assumptions:
                session.assumptions.append(_note)
    _audit_must_coverage(session)
    store.save(session)
    body: dict = {"session_id": session.session_id, "state": session.state}
    if session.plan is not None:
        # 餐卡与紧邻景点的通勤腿（2026-11-15）：/plan/start 自己组响应、
        # 不走 _plan_turn_body，出站闸在这里也跑一次（幂等）。
        session.plan.assumptions.extend(_open_meal_leg_gaps(session.plan))
        # 白天入场闸读闸同款出站闸：生成首屏同样不允许越闸开场。
        session.plan.assumptions.extend(enforce_entry_gate(session.plan))
        # 必去覆盖审计同款出站闸：生成响应首屏也不允许必去无声消失。
        _audit_must_coverage(session)
    if session.state == "clarify":
        body["clarify"] = clarify_questions(session)
        return body
    if session.state == "site_confirm":
        body["sites"] = session.pending_sites
        body["sites_source"] = session.pending_sites_source
        if session.history and session.history[-1].role == "assistant":
            body["reply"] = session.history[-1].content
        body["clarify"] = clarify_questions(session)
        return body
    if session.state == "resto_confirm":
        body["restos"] = [r.model_dump() for r in session.pending_restos]
        if session.history and session.history[-1].role == "assistant":
            body["reply"] = session.history[-1].content
    body["plan"] = _plan_for_response(session.plan)
    body["assumptions"] = session.assumptions
    body["violations"] = current_violations(session)
    return body


@router.post("/plan/{session_id}/message")
async def message_plan(
    session_id: str,
    request: PlanMessageRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    agent: PlanningAgent = Depends(get_planning_agent),
    store: PlanSessionStore = Depends(get_plan_sessions),
    gate: RequestGate = Depends(get_request_gate),
    fast_lane: FastLane = Depends(get_fast_lane),
    tasks: TaskStore = Depends(get_task_store),
    account: str | None = Depends(_account_from_auth),
) -> dict:
    """§6.12 双车道分流的消息回合：闸门分类 → 快车道直答 / 慢车道入队
    「已受理」/ 主车道走完整 agent 管线。每回合记 lane + 耗时指标。"""
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    session = store.get(session_id, device_id=x_device_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    # 2026-11-14（用户拍板「心愿单按 USER ID 出内容」）：会话记住登录账号
    session.account_id = account or session.account_id
    # 换局闸（2026-11-13「重新规划却回到上次行程」）：这句话本身是另一趟完整
    # 行程（换城市/换天数）时重开会话出新车，旧行程一个字段都不动；必须先于
    # 车道分类——否则慢车道会把「重新规划」当后台重排塞回旧行程。
    brief = agent.new_trip_brief(session, request.text)
    if brief is not None:
        restart_cities, restart_days = brief
        # 二期（消息轮换引擎，2026-11-18）：换局语句重开的新行程走模型
        # 引擎——纯路线声明或点名长句 + auto 城际（会话班次/语言随缝透
        # 传）。点名长句由 _restart_named_musts 离线读「必去」类短语进
        # musts，绑定走快照绑定链（精确名→文本匹配→骨架兜底，缝不吞
        # 点、B-01）；短语读不出/引擎失败仍落 legacy（读点确认轮管线）。
        restart_named_musts: list[str] = []
        try:
            restart_named_musts = _restart_named_musts(
                request.text,
                store=get_poi_detail_store(),
                cities=list(restart_cities or []),
            )
        except Exception:
            logger.exception("plan/message restart named-must parse failed")
        trip_session = None
        trip_outcome = None
        restart_wish_musts: list[str] = []
        restart_wish_notes: list[str] = []
        try:
            from app.services.trip_solver.entry import (
                ENGINE_CPSAT,
                engine_flag,
                serving_ready,
                set_seam_attempted,
            )
            from app.services.trip_solver.live import (
                generate_session_via_trip_solver,
            )

            if (
                engine_flag() == ENGINE_CPSAT
                and serving_ready()[0]
                and (
                    _restart_route_only(request.text, restart_cities)
                    or restart_named_musts
                )
                and (session.intercity_mode or "auto") == "auto"
            ):
                # 二期：换局缝已尝试引擎——回落 restart_with_brief 内的
                # _generate_v0 钩子不再重试
                set_seam_attempted()

                # 2026-11-22（换局缝吞心愿案）：与 start 缝同口径——换局
                # 重开同样吸收行程中心心愿单。此前 musts 只带点名短语，
                # 引擎成功时心愿静默不进规划、失败回落 legacy 反而吸收
                # （restart_with_brief → _generate_v0），行为分叉。复用
                # 同一权威吸收函数（城市闸/exclusion/跨城披露）。
                try:
                    wish_probe = PlanSession(
                        session_id="wish-absorb-probe-restart",
                        device_id=session.device_id,
                        cities=list(restart_cities or []),
                        account_id=account or session.account_id,
                    )
                    (
                        restart_wish_musts,
                        restart_wish_notes,
                    ) = await agent._absorb_wishlist(wish_probe)
                except Exception:
                    logger.warning(
                        "plan/message restart seam wishlist absorb failed",
                        exc_info=True,
                    )
                    restart_wish_musts, restart_wish_notes = [], []

                def _ts_restart():
                    # R13k：镜像 legacy restart_with_brief 的 fresh-start
                    # 语义——旧行程的行前信息（班次/时刻）不带入新局
                    # （此前引擎缝多传 session.arrival_*/departure_*：
                    # 换城市重启带着旧航班号=与 legacy 分歧；且传了
                    # no/time 却不传 arrival_day（_intake_day_no 只在
                    # start 缝算）——参数集自相矛盾）。
                    return generate_session_via_trip_solver(
                        device_id=session.device_id,
                        cities=list(restart_cities or []),
                        days=restart_days or session.days or 0,
                        start_date=session.start_date,
                        # 点名短语 + 心愿单（同一权威吸收，去重不双卡）
                        musts=list(
                            dict.fromkeys([*restart_named_musts, *restart_wish_musts])
                        ),
                        store=get_poi_detail_store(),
                        weather_lookup=partial(
                            daily_weather_text, get_session_factory()
                        ),
                        preferences=request.text,
                        lang=session.lang,
                    )

                trip_session, trip_outcome = await asyncio.to_thread(_ts_restart)
        except Exception:
            logger.exception("plan/message restart seam failed; legacy serves")
        if trip_session is not None:
            session = trip_session
            session.account_id = account or session.account_id
            # 换局缝心愿披露（与 start 缝同款）：引擎只带 plan.assumptions，
            # absorbed/skip 需 API 层补上卡；must_visits 已由 live.py 用
            # 合并后的 musts 写好，这里只做去重兜底。
            if restart_wish_musts or restart_wish_notes:
                session.must_visits = list(
                    dict.fromkeys([*(session.must_visits or []), *restart_wish_musts])
                )
                if restart_wish_musts:
                    session.assumptions.append(
                        L(
                            "已从行程中心心愿单带入必去："
                            + "、".join(restart_wish_musts),
                            "Must-visits brought in from the trip-center "
                            "wishlist: " + ", ".join(restart_wish_musts),
                        )
                    )
                if restart_wish_notes:
                    session.assumptions.extend(restart_wish_notes)
            reply = L(
                "已按你刚说的新行程重开一局："
                f"{'→'.join(session.cities) or '（城市待定）'}，"
                f"{session.days or '?'} 天（上一趟行程没有被改动）。",
                "Started a new trip from your latest message: "
                f"{' → '.join(session.cities) or '(city TBC)'}, "
                f"{session.days or '?'} days "
                "(the previous itinerary was left untouched).",
            )
            store.save(session)
            body = _plan_turn_body(session, reply, None)
            body["new_trip"] = True
            body["lane"] = {
                "lane": "main",
                "intent": "new_trip",
                "engine": "cpsat",
            }
            return body
        # R12（换局营救）：引擎失败 → restart_with_brief（legacy）服务
        # + 披露随附（旧会话原样不动的语义不变——重开新会话）。
        try:
            session, reply = await agent.restart_with_brief(
                session, request.text, brief
            )
        except PoiStoreUnavailableError:
            logger.warning("plan/message poi_store_unavailable")
            raise HTTPException(status_code=503, detail="poi_store_unavailable")
        except LLMError as exc:
            logger.exception("plan/message llm_error: %s", exc)
            raise HTTPException(status_code=502, detail="llm_error") from exc
        if (
            trip_outcome is not None
            and getattr(trip_outcome, "fallback", False)
            and trip_outcome.disclosures
        ):
            # R12：legacy 营救的披露随附
            session.assumptions.append(trip_outcome.disclosures[0].get("zh", ""))
        store.save(session)
        body = _plan_turn_body(session, reply, None)
        body["new_trip"] = True
        body["lane"] = {"lane": "main", "intent": "new_trip"}
        return body
    metrics = get_lane_metrics()
    started = monotonic()

    decision = await gate.classify(request.text)

    if decision.lane is Lane.fast:
        answer = await fast_lane.answer(session, request.text, decision.intent)
        if answer is not None:
            session.history.append(ChatMessage(role="user", content=request.text))
            session.history.append(ChatMessage(role="assistant", content=answer.text))
            store.save(session)
            metrics.record(
                "fast",
                ttft_ms=(monotonic() - started) * 1000.0,
                intent=decision.intent,
                source=decision.source,
            )
            body = _plan_turn_body(session, answer.text, None)
            body["lane"] = {"lane": "fast", "intent": decision.intent}
            return body
        # 快车道答不出（宁缺毋错）：落主车道继续，不虚构。
    elif decision.lane is Lane.slow:
        task = tasks.enqueue(
            "replan",
            {
                "session_id": session.session_id,
                "device_id": x_device_id,
                "text": request.text,
            },
            device_id=x_device_id,
        )
        metrics.record(
            "slow",
            ttft_ms=(monotonic() - started) * 1000.0,
            intent=decision.intent,
            source=decision.source,
        )
        body = _plan_turn_body(
            session,
            L(
                "收到，重排已在后台进行，完成后会通知你（任务 "
                f"{task.task_id[:8]}…可稍后刷新查看）",
                "Got it — replanning in the background; you'll be notified"
                f" when done (task {task.task_id[:8]}…).",
            ),
            None,
        )
        body["lane"] = {
            "lane": "slow",
            "intent": decision.intent,
            "task_id": task.task_id,
        }
        return body

    try:
        session, reply, change = await agent.message(session, request.text)
    except PoiStoreUnavailableError:
        logger.warning("plan/message poi_store_unavailable")
        raise HTTPException(status_code=503, detail="poi_store_unavailable")
    except LLMError as exc:
        logger.exception("plan/message llm_error: %s", exc)
        raise HTTPException(status_code=502, detail="llm_error") from exc
    metrics.record(
        "main",
        ttft_ms=(monotonic() - started) * 1000.0,
        intent=decision.intent,
        source=decision.source,
    )
    # 2026-10-30 用户拍板「加入/减少 SITE，距离/步数重新从 API 算」：对话式
    # 增删改与按钮端点（pin/delete/move/retime）同款——变更后实测腿刷新
    # （缓存对零网络回放，新对走图商链，配额死降级估算不阻塞回合）。
    # 2026-11-13 快路径：落位已在 agent 内按直线估算标好腿，本回合不再整趟
    # 实测（图商惩罚/配额死时实测可拖 30s+）；动线实测交给下一次编辑/打开。
    fast_turn = consume_fast_turn(session.session_id)
    if session.plan is not None and not fast_turn:
        await agent.refresh_legs(session)
    store.save(session)
    body = _plan_turn_body(session, reply, change, alternatives=not fast_turn)
    body["lane"] = {"lane": "main", "intent": decision.intent}
    return body


# 无时刻卡下发过滤豁免类别（2026-11-13 拍板「未安排不显示」）：餐/酒店是
# 行程骨架（落地即吃/住），无时刻也随行程交付；交通 TransferItem 不在
# VisitItem 过滤范围内，天然豁免。内部清算层的 created/curated/tier≤3
# 保护名册只保「不删除」，不保「下发显示」——下发层一律滤掉。
_UNTIMED_KEEP_CATEGORIES = frozenset({"food", "hotel"})


def _strip_untimed_items(plan):
    """API 出口过滤（2026-11-13 用户拍板「未安排（无时刻灰卡）不要显示」
    「只有替代项，不应该有未安排项」）：days[].items 中 start_time 为 None
    的非钉 VisitItem 从下发响应剔除，并转入 plan.unplaced——由
    attach_plan_alternatives 按正常备选规则亮成宿主卡「想去」chip
    （day_hint=原天号，选宿主同天优先）；pinned（铁律 19）与餐/酒店骨架
    保留。非变异——浅拷贝 plan/day 壳、条目对象共享，session.plan 本体与
    持久化会话不动（内部重排/清算逻辑不受影响）；assumptions 披露原样
    下发（披露是另一回事）。"""
    if plan is None:
        return plan
    days = []
    stripped: list[VisitItem] = []
    changed = False
    for day in plan.days:
        kept = []
        for item in day.items:
            if (
                isinstance(item, VisitItem)
                and item.start_time is None
                and not item.pinned
                and (item.category or "") not in _UNTIMED_KEEP_CATEGORIES
            ):
                stripped.append(item)
                changed = True
            else:
                kept.append(item)
        if len(kept) != len(day.items):
            day = day.model_copy(update={"items": kept})
        days.append(day)
    if not changed:
        return plan
    unplaced = list(plan.unplaced or ())
    known_poi_ids = {c.poi_id for c in unplaced if c.poi_id}
    known_names = {str(c.name or "").strip().lower() for c in unplaced}
    for item in stripped:
        if (item.poi_id and item.poi_id in known_poi_ids) or (
            str(item.name or "").strip().lower() in known_names
        ):
            continue
        unplaced.append(
            UnplacedCandidate(
                name=item.name,
                name_en=item.name_en,
                poi_id=item.poi_id,
                category=item.category,
                tier=item.tier,
                duration_minutes=item.duration_minutes,
                location=item.location,
                city=item.city,
                day_hint=item.day,
                reason="untimed_demoted",
            )
        )
        if item.poi_id:
            known_poi_ids.add(item.poi_id)
        known_names.add(str(item.name or "").strip().lower())
    return plan.model_copy(update={"days": days, "unplaced": unplaced})


def _with_gap_bridges(plan):
    """R12 响应件：>=45 分钟同日空档挂「前往下一站」交通桥卡（幂等、
    非变异链路下游再挂一次也安全）。展示糖——挂挂失守绝不挂挂挂挂
    坏行程。"""
    from app.services.trip_solver.assembly.bridges import (
        attach_gap_bridges,
    )

    try:
        return attach_gap_bridges(plan)
    except Exception:
        logger.warning("plan gap bridges attach failed", exc_info=True)
        return plan


def _plan_for_response(plan):
    """行程下发出口装配（2026-11-13 拍板「未安排卡不显示」）：先剔无时刻
    非钉参访卡（剔除件转 plan.unplaced，亮成宿主卡「想去」chip——只有
    替代项，没有未安排项），再把晨卡收成「出发时刻点」（2026-11-16 拍板
    「早晨卡只有出发时间，没有 DURATION」），最后挂同级备选 chip。所有
    返回完整行程的端点（start / from-itinerary / _plan_turn_body 一族）
    统一走本入口，禁止旁路。"""
    plan = _plan_with_alternatives(
        _morning_point_cards(_hotel_cards_front_back(_strip_untimed_items(plan)))
    )
    try:
        plan = attach_return_cards(plan)
    except Exception:  # 展示糖：绝不能把行程卡拉挂
        logger.warning("plan return cards attach failed", exc_info=True)
    # R14（2026-11-21 用户令「打车应该在酒店和去程之间」FIX）：引擎远郊日
    # 去程卡里的打车段拆成独立 🚕 卡插在晨卡与去程卡之间——响应副本渲染件
    # （幂等先清后挂；会话本体零打车卡），交通桥卡在最终形状上重挂。
    from app.services.itinerary.legs import attach_outbound_taxi_cards

    try:
        plan = attach_outbound_taxi_cards(plan)
    except Exception:  # 展示糖：绝不能把行程卡拉挂
        logger.warning("plan outbound taxi cards attach failed", exc_info=True)
    # R12（2026-11-19 拍板「天安门后应该在去下一个景点的路上，而不是
    # 空着等到午餐卡」）：>=45 分钟的同日空档挂可见「前往下一站」交通
    # 桥卡——与回城卡同契约（响应副本、幂等先清后挂），session 本体
    # 与持久会话零桥卡。
    from app.services.trip_solver.assembly.bridges import (
        attach_gap_bridges,
    )

    try:
        return attach_gap_bridges(plan)
    except Exception:  # 展示糖：绝不能把行程卡拉挂
        logger.warning("plan gap bridges attach failed", exc_info=True)
        return plan


def _hotel_cards_front_back(plan):
    """R13p（2026-11-21 用户拍板「酒店卡不应该出现在天安门后；酒店卡如果
    出现应该是第一位的」）：出站副本终态归位——晨卡（hotel-morning-）恒排
    当天最前、夜卡（hotel-night-）恒排最后，其余卡按开始时刻稳定重排。
    修两形状：①升旗锚缝尾 realign 只改时刻不动位次（天安门 07:10 曾显示
    在 day 中部、前面还是 09:30 的八达岭）；②旧快照里被误推到锚后的晨卡
    在此钳回首个非酒店卡之前（start = 首卡 start − 30，C-13 打包窗口径）。
    非变异：会话本体与持久快照不动（同 _morning_point_cards 契约）。"""
    if plan is None:
        return plan
    out = plan.model_copy(deep=True)
    for d in out.days:
        if not d.items:
            continue
        mornings = [
            i
            for i in d.items
            if isinstance(i, VisitItem)
            and (i.item_id or "").startswith("hotel-morning")
        ]
        nights = [
            i
            for i in d.items
            if isinstance(i, VisitItem) and (i.item_id or "").startswith("hotel-night")
        ]
        ids_m = {id(i) for i in mornings}
        ids_n = {id(i) for i in nights}
        others = [i for i in d.items if id(i) not in ids_m and id(i) not in ids_n]
        others.sort(key=lambda i: (i.start_time is None, i.start_time or time(0, 0)))
        if mornings:
            first = next((i for i in others if i.start_time is not None), None)
            m = mornings[0]
            if (
                first is not None
                and m.start_time is not None
                and (m.start_time.hour * 60 + m.start_time.minute)
                > (first.start_time.hour * 60 + first.start_time.minute)
            ):
                f_min = first.start_time.hour * 60 + first.start_time.minute
                new_start = max(0, f_min - 30)
                dur = int(m.duration_minutes or 30)
                m.start_time = time(new_start // 60 % 24, new_start % 60)
                m.end_time = time((new_start + dur) // 60 % 24, (new_start + dur) % 60)
        d.items = mornings + others + nights
    return out


def _morning_point_cards(plan):
    """晨卡=出发时刻点（2026-11-16 用户拍板）：出站副本上把 hotel-morning
    卡的结束时间收成开始时间、时长归 0——「只有出发时间，没有 DURATION」。
    非变异：会话本体仍保留 30 分钟打包窗口（排期口径靠 start），只在
    下发副本上收。"""
    if plan is None:
        return plan
    mornings = [
        i
        for d in plan.days
        for i in d.items
        if isinstance(i, VisitItem) and (i.item_id or "").startswith("hotel-morning")
    ]
    if not mornings:
        return plan
    out = plan.model_copy(deep=True)
    for d in out.days:
        for i in d.items:
            if isinstance(i, VisitItem) and (i.item_id or "").startswith(
                "hotel-morning"
            ):
                i.end_time = i.start_time
                i.duration_minutes = 0
    return out


def _plan_with_alternatives(plan):
    """行程卡装配期挂「同级备选」（2026-11-05 拍板，规则见
    services/poi_alternatives）：深拷贝上挂，session.plan 本体与持久化
    会话永不携带展示数据。任何异常静默回落原 plan——备选是展示糖，
    绝不能把行程卡拉挂。"""
    try:
        return attach_plan_alternatives(plan, get_poi_detail_store())
    except Exception:
        logger.warning("plan alternatives attach failed", exc_info=True)
        return plan


def _audit_must_coverage(session: PlanSession) -> None:
    """必去覆盖审计（2026-11-17 豫园/外滩静默丢失案）：出站闸最后一道。

    每个 must_visit 在最终行程里必须 已排 / 落 unplaced / 有披露，三者皆无
    = 静默丢失——ensure_must_disclosure 自动补一条披露行，把「无声消失」
    机械变成「至少有披露」。只补文案不改排期（选点/求解器重构在途，那片
    不碰）；幂等，补过的行本身就是披露。
    """
    if session.plan is None:
        return
    # 2026-11-17 事故热修（会话 24379abd）：必去优先三闸 + 灰卡降级。
    lang = getattr(session, "lang", "zh") or "zh"
    must_names = getattr(session, "must_visits", None) or []
    # R12-E（2026-11-19 用户令「指定的天坛为什么漏了，没指定的景山
    # 插进去了」）：先营救——被入场闸剥掉的必去顶进让出的填充窗口；
    # 营救不了再走必让位清场。
    notes: list[str] = list(
        rescue_entry_gated_musts(session.plan, must_names=must_names, lang=lang)
    )
    # 让位清单（2026-11-22 上海→西安→北京案，用户「兵马俑 PRIORITY 最高，
    # 再怎么删也不会删它」）：让位不是撤完就算——撤不成就得放回，否则 D2
    # 只剩华清宫、下午空 5 小时，兵马俑/秦俑情凭空消失。
    evicted: list[tuple[int, int, object]] = []
    yield_notes = evict_fillers_when_must_unseated(
        session.plan, must_names=must_names, lang=lang, evicted=evicted
    )
    notes += evict_pre_remote_fillers(session.plan, lang=lang)
    notes += retime_remote_day_from_access(session.plan, lang=lang)
    # R12-C（2026-11-19 拍板「餐厅放午餐/晚餐卡上」）：存量/回退计划
    # 里观光卡形态的餐馆折进餐卡——读闸自愈，刷新即正。
    notes += fold_restaurant_visit_cards(session.plan, lang=lang)
    untimed = demote_untimed_musts(session.plan, lang=lang)
    if evicted:
        # 读闸不做重解行程（2026-11-22 复核）：让位腾出的窗口只交给
        # rescue_entry_gated_musts 那条带入场闸/邻卡约束的安全通道（它在
        # 本闸最前面跑）；它没坐上的必去，任何「硬塞」都只会造出闭馆日
        # 的故宫 16:00-20:00、到达日 14:30-19:30 的颐和园这种假排期。
        # 所以这里只认「没坐上就把撤掉的放回」，宁可必去落想去。
        back: list = []
        notes += restore_evicted_fillers(
            session.plan, evicted, lang=lang, restored_out=back
        )
        # 放回的件不再说「已让位移出」——两句互相打架的文案只留真相那句；
        # 被别的口径（远郊日清场）挡住没放回的，移出文案照旧成立。
        back_names = {f"「{getattr(i, 'name', '')}」" for i in back}
        notes += [
            line for line in yield_notes if not any(name in line for name in back_names)
        ]
    if notes or untimed:
        # 热修动了盘面（撤补点/挪卡/降级灰卡）→ 腿字段按新布局重算：
        # annotate 只在生成期跑过，读闸改形后卡面还挂着撤掉的前补点腿、
        # 去程接驳链整段消失（2026-11-17 慕田峪复验实录：天安门卡挂着
        # 已被移出的老舍茶馆打车腿，09:30 专线无卡可挂）。幂等，重算
        # 只覆写展示腿字段。
        annotate_legs(session.plan)
    # 让位→回座→放回是一条会「来回试探」的链：同一个盘面每次过闸都会重算
    # 一遍，文案必须按内容去重（2026-11-22），否则刷新几次假设区就刷出一串
    # 重复的「已让位移出/已放回原时段」。幂等只指盘面，文案这里单独收口。
    seen = set(session.plan.assumptions)
    for line in notes:
        if line in seen:
            continue
        seen.add(line)
        session.plan.assumptions.append(line)
    # 已按「闭馆」单独披露过的必去，不再补一条「当天排不下」（2026-11-22
    # 故宫案：周一闭馆 × 暂未排上时刻 两句互相打架，用户看不出到底为什么）。
    closed_mentioned: set[str] = set()
    for line in session.plan.assumptions:
        if "闭馆" in line:
            match = re.search(r"「(.+?)」", line)
            if match:
                closed_mentioned.add(match.group(1))
    for line in untimed:
        logger.warning(
            "plan/session %s untimed must demoted: %s",
            session.session_id,
            line,
        )
        match = re.search(r"「(.+?)」", line)
        if match and match.group(1) in closed_mentioned:
            continue
        if line not in seen:
            seen.add(line)
            session.plan.assumptions.append(line)
    for line in ensure_must_disclosure(
        session.plan,
        getattr(session, "must_visits", None) or [],
        disclosed=session.assumptions or [],
        lang=lang,
    ):
        logger.warning(
            "plan/session %s must-visit silent drop: %s", session.session_id, line
        )
    # 双在场清脏（2026-11-17 基线排查实锤）：已排卡的必去不得同时挂在
    # unplaced——保守同体判定（poi_id 相同/规范名全等），互含不算
    # （外滩 vs 外滩源是两个景点，误清会丢合法 chip）。无披露必要：
    # 站点已在行程里，chip 本身是脏数据，记日志即可。
    dups = dedupe_unplaced_against_scheduled(session.plan)
    if dups:
        logger.warning(
            "plan/session %s unplaced duplicate chips removed: %s",
            session.session_id,
            [d.name for d in dups],
        )
    # 未排上必去名册（2026-11-17 一日游案）：H5 非折叠横幅的数据面——
    # 假设块折叠着用户不看，「必去未排上」必须一眼可见（想去 chip 只是
    # 次要面，无宿主卡时连 chip 都没有）。每次过闸重算，编辑后自愈。
    session.plan.unarranged_musts = unarranged_must_visits(session.plan, must_names)


def _plan_turn_body(session, reply: str, change, *, alternatives: bool = True) -> dict:
    """Shared response envelope for message + sites/confirm turns."""
    body: dict = {
        "reply": reply,
        "state": session.state,
        # 2026-11-13：换局（新行程）时后端返回的是**另一个**会话，前端要
        # 跟着换指针，否则保存/导出仍挂在上一趟行程上。同会话回合原样。
        "session_id": session.session_id,
    }
    if session.state == "site_confirm":
        body["sites"] = session.pending_sites
        body["sites_source"] = session.pending_sites_source
    if session.state == "resto_confirm":
        body["restos"] = [r.model_dump() for r in session.pending_restos]
    if session.state == "clarify":
        body["clarify"] = clarify_questions(session)
    if session.plan is not None:
        # 出站前条目 id 重号自愈（2026-11-13 磁器口换点 422）：新增条目可能
        # 撞上会话里载入的旧号，前端拿到重号卡片后按 id 换点会命中别天那条。
        heal_item_ids(session)
        # 餐卡=槽位、餐厅=数据：旧会话漂在卡窗外的餐厅在出站前回填
        heal_meal_cards(session)
        # 到达日不再整天没安排（2026-11-13 六拍）：旧行程的空到达日出站前
        # 补一段「城市漫步（自由安排）」+ 缺的餐卡，刷新即修不必重规划。
        heal_arrival_light(session.plan)
        # 餐卡与紧邻景点的通勤腿（2026-11-15）：出站最后一道对账。
        # 餐卡重排（装配/编辑/救急）都可能在收口后抹平间隙，这里在真正
        # 交付的 plan 上补回；幂等——无间隙时不产生备注、不改时刻。
        session.plan.assumptions.extend(_open_meal_leg_gaps(session.plan))
        # R13o③：升旗锚在消息回合出站前同样收口（引擎 replan/edit 的新
        # 计划此前不带旗时）——幂等，先于入场闸跑。
        from app.services.agent.plan import _apply_flag_schedule

        _apply_flag_schedule(session.plan)
        # 白天入场闸读闸（2026-11-17 二拍）：顺延/贴锚/兜底把非钉普通观光
        # 卡推过 16:00/15:30 开场带的，出站前退回无时刻并披露（幂等）。
        session.plan.assumptions.extend(enforce_entry_gate(session.plan))
        # 必去覆盖审计（2026-11-17）：出站闸最后一道——必去无声消失自动补披露。
        _audit_must_coverage(session)
        # 2026-11-13 快路径：备选 chip 装配是整池扫描（18 件 ~4.5s），
        # 加心愿回合先跳过——卡片本体完整，备选在下次普通回合/打开行程补回。
        body["plan"] = (
            _plan_for_response(session.plan)
            if alternatives
            else _with_gap_bridges(_strip_untimed_items(session.plan))
        )
        body["violations"] = current_violations(session)
    if change is not None:
        body["change"] = change
    return body


@router.post("/plan/{session_id}/sites/confirm")
async def confirm_plan_sites(
    session_id: str,
    request: PlanSitesConfirmRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    agent: PlanningAgent = Depends(get_planning_agent),
    store: PlanSessionStore = Depends(get_plan_sessions),
) -> dict:
    """H5 点选「必去」确认（product rule 2026-10-20）：the picked names
    ride straight to the wishlist write + pipeline — no composed text
    to re-parse; unpicked candidates are never recorded."""
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    session = store.get(session_id, device_id=x_device_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    if session.state != "site_confirm" or not session.pending_sites:
        raise HTTPException(status_code=409, detail="not_awaiting_sites")
    try:
        session, reply, change = await agent.confirm_sites(session, request.mandatory)
    except PoiStoreUnavailableError:
        logger.warning("plan/sites_confirm poi_store_unavailable")
        raise HTTPException(status_code=503, detail="poi_store_unavailable")
    except LLMError as exc:
        logger.exception("plan/sites_confirm llm_error: %s", exc)
        raise HTTPException(status_code=502, detail="llm_error") from exc
    store.save(session)
    return _plan_turn_body(session, reply, change)


@router.post("/plan/{session_id}/images")
async def plan_session_images(
    session_id: str,
    files: list[UploadFile] = File(...),
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    agent: PlanningAgent = Depends(get_planning_agent),
    store: PlanSessionStore = Depends(get_plan_sessions),
) -> dict:
    """📷 图片读点（2026-11-14 用户拍板「图片上有的也抽出来」）。

    图片（笔记截图/行程照片/地图）读出的地点与链接、文字同一条确认轮：
    用户点选的才写进行程中心心愿单并排期，未点选的不入库。"""
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    session = store.get(session_id, device_id=x_device_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    images: list[tuple[bytes, str]] = []
    for upload in list(files)[:_MAX_START_IMAGES]:
        mime = (upload.content_type or "").lower()
        if mime and mime not in _ALLOWED_IMAGE_MIME:
            raise HTTPException(status_code=422, detail="unsupported_image_type")
        data = await upload.read()
        if len(data) > _MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="image_too_large")
        if data:
            images.append((data, mime or "image/jpeg"))
    if not images:
        raise HTTPException(status_code=422, detail="empty_image")
    try:
        session, reply = await agent.image_site_round(session, images)
    except LLMError as exc:
        logger.exception("plan/images llm_error: %s", exc)
        raise HTTPException(status_code=502, detail="llm_error") from exc
    store.save(session)
    return _plan_turn_body(session, reply, None)


def _find_visit_item(plan, item_id: str) -> VisitItem | None:
    for day in plan.days:
        for item in day.items:
            if isinstance(item, VisitItem) and item.item_id == item_id:
                return item
    return None


@router.post("/plan/{session_id}/items/{item_id}/pin")
async def pin_plan_item(
    session_id: str,
    item_id: str,
    request: PlanPinRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    agent: PlanningAgent = Depends(get_planning_agent),
    store: PlanSessionStore = Depends(get_plan_sessions),
) -> dict:
    """钉住/取消钉住（iron rule 19）：pinned 的项目引擎不重排时间。"""
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    session = store.get(session_id, device_id=x_device_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    if session.plan is None:
        raise HTTPException(status_code=400, detail="no_plan")
    item = _find_visit_item(session.plan, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item_not_found")
    if request.pinned and item.start_time is None:
        raise HTTPException(status_code=422, detail="pinned_requires_time")
    item.pinned = request.pinned
    # 用户手钉：清软钉（铁律 19）；取消钉住同时释放软钉
    item.soft_pin = False
    await agent.refresh_legs(session)
    store.save(session)
    reply = (
        L(f"已钉住 {item.name}", f"Pinned {item.name}")
        if request.pinned
        else L(f"已取消钉住 {item.name}", f"Unpinned {item.name}")
    )
    return _plan_turn_body(session, reply, None)


@router.post("/plan/{session_id}/items/{item_id}/delete")
async def delete_plan_item(
    session_id: str,
    item_id: str,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    agent: PlanningAgent = Depends(get_planning_agent),
    store: PlanSessionStore = Depends(get_plan_sessions),
) -> dict:
    """删除按钮 = 用户对这一项的明确同意：mutate 不带 old_plan，rule 19
    不拦按钮删除；删除结果回写行程中心（记入「不想去」）。"""
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    session = store.get(session_id, device_id=x_device_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    if session.plan is None:
        raise HTTPException(status_code=400, detail="no_plan")
    item = _find_visit_item(session.plan, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item_not_found")
    plan_before = session.plan
    day_of_item = next(d for d in plan_before.days if item in d.items)
    diffs = [DiffOp(op="remove", item_id=item_id)]
    # 2026-11-13 续（每天出发点是 HOTEL）：删夜卡=这一晚不住店，次日
    # 「🏨 从酒店出发」晨卡一并移除——否则次日仍声称从酒店出发。
    pair = paired_hotel_card(plan_before.days, item) if is_hotel_night(item) else None
    if pair is not None:
        diffs.append(DiffOp(op="remove", item_id=pair.item_id))
    # 删掉这张卡后，当天后面的卡要跟着上移补位（2026-11-15 用户：删
    # 天安门后故宫没做相应调整）——删除位置之后的用户手钉卡会挡住
    # 重排，回复里点名说明，别让用户以为没生效。
    follow_pinned = [
        i.name
        for i in list(day_of_item.items)[list(day_of_item.items).index(item) + 1 :]
        if isinstance(i, VisitItem)
        and i.pinned
        and not i.soft_pin
        and not getattr(i, "must", False)
    ]
    new_plan, _, _ = mutate(
        plan_before,
        diffs,
        poi_hours=[],
        post_apply=lambda p: reanchor_hotel_cards(p.days, keep_ids={item_id}),
    )
    session.plan = new_plan
    affected_days = {item.day}
    if pair is not None:
        affected_days.add(pair.day)
    agent.reflow_after_delete(session, days=affected_days)
    # 2026-11-14：未保存行程里新建的排除行同样是草稿（看板不显示）
    agent.sync_removals_to_trip_items(plan_before, diffs, session=session)
    await agent.refresh_legs(session)
    store.save(session)
    if pair is not None:
        reply = L(
            f"已删除 {item.name}（次日「从酒店出发」晨卡一并移除），已记入不想去",
            f"Deleted {item.name} (next day's 'depart from hotel' card removed "
            "too) — recorded under 'not interested'",
        )
    else:
        reply = L(
            f"已删除 {item.name}，已记入不想去",
            f"Deleted {item.name} — recorded under 'not interested'",
        )
    if follow_pinned:
        pinned_names = "、".join(follow_pinned)
        pinned_names_en = ", ".join(follow_pinned)
        reply += L(
            f"（后面的{pinned_names}是钉住的，保持原时间；要跟着上移可先在卡上解钉）",
            f" ({pinned_names_en} stay pinned at their times; "
            "unpin them to let them shift up)",
        )
    return _plan_turn_body(session, reply, None)


class PlanMoveRequest(BaseModel):
    day: int = Field(ge=1)
    after_item_id: str | None = Field(default=None, max_length=32)


@router.post("/plan/{session_id}/items/{item_id}/move")
async def move_plan_item(
    session_id: str,
    item_id: str,
    request: PlanMoveRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    agent: PlanningAgent = Depends(get_planning_agent),
    store: PlanSessionStore = Depends(get_plan_sessions),
) -> dict:
    """规划页拖拽（2026-10-24）：同天重排 / 跨天移动。用户顺序权威——
    引擎不跑 solver 重优化，清空受影响天非 pinned 景点时间后按新顺序
    重排时链（纯计算）；pinned 项 422 拒绝（前端无把手）。"""
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    session = store.get(session_id, device_id=x_device_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    if session.plan is None:
        raise HTTPException(status_code=400, detail="no_plan")
    try:
        _, _, notes = agent.move_item(
            session, item_id, new_day=request.day, after_item_id=request.after_item_id
        )
    except ValueError as exc:
        code = str(exc)
        if code == "item_not_found":
            raise HTTPException(status_code=404, detail="item_not_found") from None
        raise HTTPException(status_code=422, detail=code) from None
    await agent.refresh_legs(session)
    store.save(session)
    reply = L("已按你的顺序调整", "Reordered to your sequence") + (
        f"（{'；'.join(notes)}）" if notes else ""
    )
    return _plan_turn_body(session, reply, None)


class PlanRetimeRequest(BaseModel):
    start_time: time  # "HH:MM"


@router.post("/plan/{session_id}/items/{item_id}/retime")
async def retime_plan_item(
    session_id: str,
    item_id: str,
    request: PlanRetimeRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    agent: PlanningAgent = Depends(get_planning_agent),
    store: PlanSessionStore = Depends(get_plan_sessions),
) -> dict:
    """规划页点时间戳改时间（2026-10-24）：用户显式设时最高优先（pinned
    也允许改）；改后该景点成固定锚点，当天其余非 pinned 景点围绕它按
    顺序游标重排并按时间排序。"""
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    session = store.get(session_id, device_id=x_device_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    if session.plan is None:
        raise HTTPException(status_code=400, detail="no_plan")
    try:
        _, summary, notes = agent.retime_item(
            session, item_id, start=request.start_time
        )
    except ValueError as exc:
        code = str(exc)
        if code == "item_not_found":
            raise HTTPException(status_code=404, detail="item_not_found") from None
        raise HTTPException(status_code=422, detail=code) from None
    await agent.refresh_legs(session)
    store.save(session)
    base = (
        summary.change_summary[0]
        if summary.change_summary
        else L("已调整时间", "Time updated")
    )
    reply = base + (f"（{'；'.join(notes)}）" if notes else "")
    return _plan_turn_body(session, reply, None)


class PlanDurationRequest(BaseModel):
    # 停留时长（分钟）：15 下限=再短就不值得单开一张卡；720 上限=一整天
    minutes: int = Field(ge=15, le=720)


@router.post("/plan/{session_id}/items/{item_id}/duration")
async def set_plan_item_duration(
    session_id: str,
    item_id: str,
    request: PlanDurationRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    agent: PlanningAgent = Depends(get_planning_agent),
    store: PlanSessionStore = Depends(get_plan_sessions),
) -> dict:
    """行程卡编辑面板改停留时长（2026-11-16 用户拍板「site edit button

    should able to change duration in addition to site name」）：与
    /retime 同款用户权威路径——本卡成固定锚点（开始时刻保留、结束=开始+
    新时长），当天其余非钉住件按序重排并按时间排序。酒店卡/系统餐位是
    系统骨架（时长由规则算）→ 422 duration_locked。
    """
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    session = store.get(session_id, device_id=x_device_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    if session.plan is None:
        raise HTTPException(status_code=400, detail="no_plan")
    try:
        _, summary, notes = agent.set_item_duration(
            session, item_id, minutes=request.minutes
        )
    except ValueError as exc:
        code = str(exc)
        if code == "item_not_found":
            raise HTTPException(status_code=404, detail="item_not_found") from None
        raise HTTPException(status_code=422, detail=code) from None
    await agent.refresh_legs(session)
    store.save(session)
    base = (
        summary.change_summary[0]
        if summary.change_summary
        else L("已改停留时长", "Visit length updated")
    )
    reply = base + (f"（{'；'.join(notes)}）" if notes else "")
    return _plan_turn_body(session, reply, None)


class PlanDepartureRequest(BaseModel):
    item_id: str
    direction: Literal["out", "return"] = "out"
    depart: str  # "HH:MM"


@router.post("/plan/{session_id}/departure")
async def select_plan_departure(
    session_id: str,
    request: PlanDepartureRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    agent: PlanningAgent = Depends(get_planning_agent),
    store: PlanSessionStore = Depends(get_plan_sessions),
) -> dict:
    """接驳卡点选班次重排（2026-11-16 用户拍板「班次可以点击选取重排」）：

    去程点选 → 晨卡按该班次回算离店时刻（离店 = 班次 − 打车含早高峰）；
    返程点选 → 景区卡按该返程班次回推离场时刻；当天其余件按序重排。
    点选值落卡，后续重建不被默认班次覆盖。
    """
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    session = store.get(session_id, device_id=x_device_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    if session.plan is None:
        raise HTTPException(status_code=400, detail="no_plan")
    raw = (request.depart or "").strip()
    try:
        hour, _, minute = raw.partition(":")
        depart_at = time(int(hour), int(minute[:2] or "0"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="bad_depart") from None
    try:
        _, summary, notes = agent.set_access_departure(
            session,
            request.item_id,
            direction=request.direction,
            depart=depart_at,
        )
    except ValueError as exc:
        code = str(exc)
        if code == "item_not_found":
            raise HTTPException(status_code=404, detail="item_not_found") from None
        raise HTTPException(status_code=422, detail=code) from None
    await agent.refresh_legs(session)
    store.save(session)
    base = (
        summary.change_summary[0]
        if summary.change_summary
        else L("已按所选班次重排", "Re-planned on the selected departure")
    )
    reply = base + (f"（{'；'.join(notes)}）" if notes else "")
    return _plan_turn_body(session, reply, None)


class PlanTransferModeRequest(BaseModel):
    mode: Literal["train", "flight"]


@router.post("/plan/{session_id}/transfers/{item_id}/mode")
async def switch_transfer_mode(
    session_id: str,
    item_id: str,
    request: PlanTransferModeRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    agent: PlanningAgent = Depends(get_planning_agent),
    store: PlanSessionStore = Depends(get_plan_sessions),
) -> dict:
    """路途行程改乘（2026-11-04 规划页）：飞机/火车二选一，按真实乘车日
    重查班次回填时刻并重排受影响天。查不到班次 422（no_flight_found /
    no_train_found），旧腿原样保留。"""
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    session = store.get(session_id, device_id=x_device_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    if session.plan is None:
        raise HTTPException(status_code=400, detail="no_plan")
    try:
        _, summary, notes = await agent.switch_transfer_mode(
            session, item_id, mode=request.mode
        )
    except ValueError as exc:
        code = str(exc)
        if code == "item_not_found":
            raise HTTPException(status_code=404, detail="item_not_found") from None
        raise HTTPException(status_code=422, detail=code) from None
    except PoiStoreUnavailableError:
        # 班次重查链路库降级：干净 503 与 plan/start 同口径（PR 评审 rule 3）。
        logger.warning("plan/transfers_mode poi_store_unavailable")
        raise HTTPException(status_code=503, detail="poi_store_unavailable")
    try:
        await agent.refresh_legs(session)
    except PoiStoreUnavailableError:
        # 实测腿刷新是增强步骤：库降级保留直线估算，不挡已生效的改乘。
        logger.warning("plan/transfers_mode refresh poi_store_unavailable")
    store.save(session)
    base = (
        summary.change_summary[0]
        if summary.change_summary
        else L("已改乘", "Transport switched")
    )
    reply = base + (f"（{'；'.join(notes)}）" if notes else "")
    return _plan_turn_body(session, reply, None)


class PlanTransferNumberRequest(BaseModel):
    number: str = Field(min_length=2, max_length=8)  # 航班号/车次号原文


@router.post("/plan/{session_id}/transfers/{item_id}/number")
async def set_transfer_number(
    session_id: str,
    item_id: str,
    request: PlanTransferNumberRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    agent: PlanningAgent = Depends(get_planning_agent),
    store: PlanSessionStore = Depends(get_plan_sessions),
) -> dict:
    """路途行程输入航班号/车次号（2026-11-04 规划页）：格式校验 → 班次库
    查询 → 命中回填真实起降/到发时刻并按班次改写腿别（输入航班号该腿即
    成航班）。查无此班 422 number_not_found；格式不符 422 bad_number_format。"""
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    session = store.get(session_id, device_id=x_device_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    if session.plan is None:
        raise HTTPException(status_code=400, detail="no_plan")
    try:
        _, summary, notes = await agent.set_transfer_number(
            session, item_id, number=request.number
        )
    except ValueError as exc:
        code = str(exc)
        if code == "item_not_found":
            raise HTTPException(status_code=404, detail="item_not_found") from None
        raise HTTPException(status_code=422, detail=code) from None
    except PoiStoreUnavailableError:
        # 班次查询链路库降级：干净 503 与 plan/start 同口径（PR 评审 rule 3）。
        logger.warning("plan/transfers_number poi_store_unavailable")
        raise HTTPException(status_code=503, detail="poi_store_unavailable")
    try:
        await agent.refresh_legs(session)
    except PoiStoreUnavailableError:
        # 实测腿刷新是增强步骤：库降级保留直线估算，不挡已生效的班次回填。
        logger.warning("plan/transfers_number refresh poi_store_unavailable")
    store.save(session)
    base = (
        summary.change_summary[0]
        if summary.change_summary
        else L("班次时刻已更新", "Schedule times updated")
    )
    reply = base + (f"（{'；'.join(notes)}）" if notes else "")
    return _plan_turn_body(session, reply, None)


@router.post("/plan/{session_id}/transfers/{item_id}/booking-links")
async def transfer_booking_links(
    session_id: str,
    item_id: str,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: PlanSessionStore = Depends(get_plan_sessions),
    settings: Settings = Depends(get_settings),
) -> dict:
    """路途行程订票跳转渠道卡（2026-11-04 规划页；铁律 22/23）：服务端
    组装成品深链（机票=携程/去哪儿/飞猪，火车=12306 全国统一价单卡）+
    退改摘要；前端过 bkConfirm 浮层后才 window.open。驾车/公交腿 422
    booking_unavailable（同城段无票可订）。"""
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    session = store.get(session_id, device_id=x_device_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    if session.plan is None:
        raise HTTPException(status_code=400, detail="no_plan")
    transfer = _find_transfer_item(session.plan, item_id)
    if transfer is None:
        raise HTTPException(status_code=404, detail="item_not_found")
    if transfer.mode not in ("train", "flight"):
        raise HTTPException(status_code=422, detail="booking_unavailable")
    date = _leg_date_iso(session.start_date or session.plan.start_date, transfer.day)
    try:
        if transfer.mode == "flight":
            # 无出发日期时 date 传空串：渠道列表页照常打开（无日期预填），
            # 不伪造哨兵日期。
            return flight_offer_cards(
                transfer.from_city,
                transfer.to_city,
                date,
                settings=settings,
            )
        return await train_offer_cards(
            transfer.from_city, transfer.to_city, date, settings=settings
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid_booking") from exc
    except Exception as exc:
        # 渠道上游（12306 班次库等）故障不裸 500：502 + 日志，前端可重试。
        logger.warning("transfer booking links upstream failed: %r", exc)
        raise HTTPException(
            status_code=502, detail="booking_service_unavailable"
        ) from exc


class PlanReplaceRequest(BaseModel):
    # 库内选中项的名字（H5 /api/pois/search 下拉选中后携带；replace 按
    # 条目所在城 + 精确同名落实，防止跨城/模糊误换）
    name: str = Field(min_length=1, max_length=64)


@router.post("/plan/{session_id}/items/{item_id}/replace")
async def replace_plan_item(
    session_id: str,
    item_id: str,
    request: PlanReplaceRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    agent: PlanningAgent = Depends(get_planning_agent),
    store: PlanSessionStore = Depends(get_plan_sessions),
) -> dict:
    """行程卡「换景点」（2026-11-01 拍板：景点名可编辑，拿关键字去库
    里匹配）：条目原位换成库内精确同名 POI，当天按游标链重排。无同名
    422 no_match（H5 端引导留空）；与行程内重复 422 duplicate_in_plan；
    系统餐位（soft_pin 餐件）422 meal_slot_locked。"""
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    session = store.get(session_id, device_id=x_device_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    if session.plan is None:
        raise HTTPException(status_code=400, detail="no_plan")
    try:
        _, summary, notes = await agent.replace_item(
            session, item_id, name=request.name
        )
    except ValueError as exc:
        code = str(exc)
        if code == "item_not_found":
            raise HTTPException(status_code=404, detail="item_not_found") from None
        raise HTTPException(status_code=422, detail=code) from None
    await agent.refresh_legs(session)
    store.save(session)
    base = (
        summary.change_summary[0] if summary.change_summary else L("已替换", "Replaced")
    )
    reply = base + (f"（{'；'.join(notes)}）" if notes else "")
    return _plan_turn_body(session, reply, None)


class PlanAltInsertRequest(BaseModel):
    # 备选 chip 拖入（2026-11-14）：库内候选精确同名 + 落点（第 day 天
    # after_item_id 之后；None=当天第一个参访件之前）
    name: str = Field(min_length=1, max_length=64)
    day: int = Field(ge=1)
    after_item_id: str | None = Field(default=None, max_length=32)


@router.post("/plan/{session_id}/items/{item_id}/insert-alt")
async def insert_plan_alternative(
    session_id: str,
    item_id: str,
    request: PlanAltInsertRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    agent: PlanningAgent = Depends(get_planning_agent),
    store: PlanSessionStore = Depends(get_plan_sessions),
) -> dict:
    """备选 chip 拖进时间轴（2026-11-14 拍板「备选要像其它条目一样可拖，
    拖到两个条目之间就插在那里」）：把条目右侧的备选（或「想去」chip）
    拖到某天两件之间即在那里插入一张新卡——主点保留（不是点击换点）。
    当天排不下时按档号/距离让位，撤下谁写进回复与假设标注；一处都排不
    下 422 no_slot（原行程不动）。跨城落点 422 city_mismatch；行程内已有
    同名/同替代组 422 duplicate_in_plan；库里查不到 422 no_match。
    不走 refresh_legs（实测 12-30s）：腿先按 annotate 直线估价出卡，下一次
    普通回合/打开行程补实测——拖动是高频操作，不能让每次松手等半分钟。
    """
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    session = store.get(session_id, device_id=x_device_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    if session.plan is None:
        raise HTTPException(status_code=400, detail="no_plan")
    try:
        _, summary, notes = await agent.insert_alternative(
            session,
            item_id,
            name=request.name,
            new_day=request.day,
            after_item_id=request.after_item_id,
        )
    except ValueError as exc:
        code = str(exc)
        if code == "item_not_found":
            raise HTTPException(status_code=404, detail="item_not_found") from None
        raise HTTPException(status_code=422, detail=code) from None
    store.save(session)
    base = (
        summary.change_summary[0] if summary.change_summary else L("已插入", "Inserted")
    )
    reply = base + (f"（{'；'.join(notes)}）" if notes else "")
    return _plan_turn_body(session, reply, None)


class PlanSetHotelRequest(BaseModel):
    # 验证下拉选中的候选（H5 /api/v1/hotels/search 选中后携带）。仅 name
    # 必填：客户端带坐标=已在下拉验证过，直接落卡；缺坐标由服务端重走
    # 检索链验证——绝不落未验证裸名（2026-11-07 用户指令「NEED TO VERIFY
    # THE NAME AND SHOW ADDRESS ACCORDINGLY」）。
    name: str = Field(min_length=1, max_length=64)
    source_poi_id: str | None = Field(default=None, max_length=64)
    address: str | None = Field(default=None, max_length=200)
    opening_hours: str | None = Field(default=None, max_length=120)
    lon: float | None = Field(default=None, ge=-180.0, le=180.0)
    lat: float | None = Field(default=None, ge=-90.0, le=90.0)


@router.post("/plan/{session_id}/items/{item_id}/set-hotel")
async def set_plan_hotel(
    session_id: str,
    item_id: str,
    request: PlanSetHotelRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    agent: PlanningAgent = Depends(get_planning_agent),
    store: PlanSessionStore = Depends(get_plan_sessions),
    settings: Settings = Depends(get_settings),
    chain: list = Depends(get_search_chain),
) -> dict:
    """每晚酒店卡 / 次日晨卡 ✏️ 手输酒店名：验证后写回卡面（名称/地址/
    营业时间/坐标/poi_id 一次性写入，卡片 meta 行即亮 📍 地址）。缺坐标
    时服务端检索链验证（酒店类目命中优先，全无命中 422 no_match）；
    非酒店卡 422 not_hotel_slot。2026-11-13「到达后每天出发点是 HOTEL」：
    夜卡 ↔ 次日晨卡双向同步酒店身份（晨卡名=「🏨 从酒店出发（酒店名）」，
    夜卡名=酒店名），并回拨晨卡给足离店到首站的路程。"""
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    session = store.get(session_id, device_id=x_device_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    if session.plan is None:
        raise HTTPException(status_code=400, detail="no_plan")
    item = _find_visit_item(session.plan, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item_not_found")
    if not (is_hotel_night(item) or is_hotel_morning(item)):
        raise HTTPException(status_code=422, detail="not_hotel_slot")
    name = request.name.strip()
    lon, lat = request.lon, request.lat
    address, opening_hours = request.address, request.opening_hours
    poi_id = request.source_poi_id
    if lon is None or lat is None:
        hits = await search_hotel_candidates(chain, settings, name, item.city or None)
        best = next((h for h in hits if h["is_hotel"]), hits[0] if hits else None)
        if best is None or not best.get("name"):
            raise HTTPException(status_code=422, detail="no_match") from None
        name = best["name"]
        poi_id = best.get("source_poi_id") or poi_id
        address = address or best.get("address")
        opening_hours = opening_hours or best.get("opening_hours")
        loc = best.get("location")
        if isinstance(loc, dict):
            lon, lat = loc.get("lon"), loc.get("lat")
    item.name = hotel_morning_label(name) if is_hotel_morning(item) else name
    item.poi_id = poi_id
    item.address = address
    item.opening_hours = opening_hours
    item.location = (
        GeoPoint(lon=lon, lat=lat) if lon is not None and lat is not None else None
    )
    # 2026-11-13 续：一次 ✏️ 铺开整段住宿（夜卡↔晨卡对 + 同城连续夜里
    # 尚未验证的占位卡一起写上同一家酒店），随后全卡按当天首/末件顺延。
    _, filled = sync_hotel_stay(session.plan.days, item, hotel_name=name)
    reanchor_hotel_cards(session.plan.days)
    try:
        await agent.refresh_legs(session)
    except PoiStoreUnavailableError:
        # 实测腿刷新是增强步骤：库降级保留直线估算，不挡已写回的酒店卡。
        logger.warning("plan/set_hotel refresh poi_store_unavailable")
    store.save(session)
    addr_zh = f"（{address}）" if address else ""
    addr_en = f" ({address})" if address else ""
    extra_zh = f"，同段住宿其余 {filled} 张卡已同步" if filled else ""
    extra_en = f", synced {filled} more card(s) of this stay" if filled else ""
    reply = L(
        f"已验证并填入酒店「{name}」" + addr_zh + extra_zh,
        f'Verified hotel "{name}"' + addr_en + extra_en,
    )
    return _plan_turn_body(session, reply, None)

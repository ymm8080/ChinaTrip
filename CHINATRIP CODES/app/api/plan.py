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
import uuid
from datetime import datetime, time, timezone
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
    _find_transfer_item,
    _leg_date_iso,
    clarify_questions,
    current_violations,
    dedupe_plan_visits,
    drop_dangling_visits,
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
from app.services.itinerary.models import UnplacedCandidate
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
from app.services.weather import daily_weather_text

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
    await agent.refresh_legs(session)
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
    await agent.refresh_legs(session)
    store.save(session)
    return _plan_turn_body(session, None, None)


@router.post("/plan/start")
async def start_plan(
    request: PlanStartRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    agent: PlanningAgent = Depends(get_planning_agent),
    store: PlanSessionStore = Depends(get_plan_sessions),
) -> dict:
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    try:
        session = await agent.start(
            device_id=x_device_id,
            cities=request.cities or [],
            days=request.days or 0,
            preferences=request.preferences or "",
            city_days=request.city_days,
            start_date=request.start_date,
            intercity_mode=request.intercity_mode,
            lang=request.lang,
            brief=request.brief,
            images=_decode_image_payloads(request.images),
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
    store.save(session)
    body: dict = {"session_id": session.session_id, "state": session.state}
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
) -> dict:
    """§6.12 双车道分流的消息回合：闸门分类 → 快车道直答 / 慢车道入队
    「已受理」/ 主车道走完整 agent 管线。每回合记 lane + 耗时指标。"""
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    session = store.get(session_id, device_id=x_device_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    # 换局闸（2026-11-13「重新规划却回到上次行程」）：这句话本身是另一趟完整
    # 行程（换城市/换天数）时重开会话出新车，旧行程一个字段都不动；必须先于
    # 车道分类——否则慢车道会把「重新规划」当后台重排塞回旧行程。
    brief = agent.new_trip_brief(session, request.text)
    if brief is not None:
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


def _plan_for_response(plan):
    """行程下发出口装配（2026-11-13 拍板「未安排卡不显示」）：先剔无时刻
    非钉参访卡（剔除件转 plan.unplaced，亮成宿主卡「想去」chip——只有
    替代项，没有未安排项），再挂同级备选 chip。所有返回完整行程的端点
    （start / from-itinerary / _plan_turn_body 一族）统一走本入口，禁止
    旁路。"""
    return _plan_with_alternatives(_strip_untimed_items(plan))


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
        # 2026-11-13 快路径：备选 chip 装配是整池扫描（18 件 ~4.5s），
        # 加心愿回合先跳过——卡片本体完整，备选在下次普通回合/打开行程补回。
        body["plan"] = (
            _plan_for_response(session.plan)
            if alternatives
            else _strip_untimed_items(session.plan)
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
    diffs = [DiffOp(op="remove", item_id=item_id)]
    # 2026-11-13 续（每天出发点是 HOTEL）：删夜卡=这一晚不住店，次日
    # 「🏨 从酒店出发」晨卡一并移除——否则次日仍声称从酒店出发。
    pair = paired_hotel_card(plan_before.days, item) if is_hotel_night(item) else None
    if pair is not None:
        diffs.append(DiffOp(op="remove", item_id=pair.item_id))
    new_plan, _, _ = mutate(
        plan_before,
        diffs,
        poi_hours=[],
        post_apply=lambda p: reanchor_hotel_cards(p.days, keep_ids={item_id}),
    )
    session.plan = new_plan
    agent.sync_removals_to_trip_items(plan_before, diffs)
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
    await agent.refresh_legs(session)
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
    await agent.refresh_legs(session)
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
    await agent.refresh_legs(session)
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

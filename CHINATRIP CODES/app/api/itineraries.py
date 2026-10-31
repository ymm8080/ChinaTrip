"""Itinerary CRUD + snapshot version API (design v2.0 §5.4/§6.8).

Every route requires X-Device-ID. Cross-owner access answers 404 (not
403) so foreign itinerary ids cannot be enumerated. The router is NOT
registered in app/main.py — the orchestrator wires it.
"""

import logging
import uuid as uuid_mod
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field, ValidationError

from app.config import Settings, get_settings
from app.db import get_session_factory
from app.models import ItineraryImport
from app.services import trip_export
from app.services.accounts import AccountService, parse_bearer_token
from app.services.agent.plan import dedupe_plan_visits
from app.services.entitlement import EntitlementService, InMemoryQuotaStore
from app.services.itinerary import DiffOp, PipelineError, PoiHours
from app.services.itinerary.models import ItineraryPlan
from app.services.itinerary_store import (
    InMemoryItineraryStore,
    ItineraryRecord,
    ItineraryService,
    ItineraryStore,
    QuotaExceededError,
)
from app.services.lang_ctx import L
from app.services.llm import get_llm_adapter
from app.services.llm.zhipu import LLMError
from app.services.mailer import get_mailer
from app.services.pg_state import PgItineraryStore, _pg_uuid_loose
from app.services.state_persist import (
    db_path_from_url,
    get_state_backend,
)
from app.services.trip_import import (
    ImportNoText,
    ImportParseError,
    TripImportService,
    UnsupportedImportFormat,
    build_plan,
)
from app.services.trip_items import TripItemService

router = APIRouter(prefix="/api/v1", tags=["itineraries"])
logger = logging.getLogger(__name__)


class CreateItineraryRequest(BaseModel):
    cities: list[str] = Field(min_length=1)
    days: int = Field(ge=1)


class MutateItineraryRequest(BaseModel):
    diffs: list[DiffOp]
    poi_hours: list[PoiHours] = Field(default_factory=list)


class CreateSnapshotRequest(BaseModel):
    name: str | None = None
    note: str | None = None


class ConfirmImportRequest(BaseModel):
    """import/confirm 请求体：preview 原样带回的 file_id/file_name + 草稿
    plan（预览确认流无服务端会话态，草稿由前端带回，confirm 重校验）。"""

    file_id: str = Field(pattern=r"^imp_[0-9a-f]{32}$")
    file_name: str = Field(min_length=1, max_length=255)
    plan: dict


# --- dependency factories (process-level singletons, translate.py pattern) ---

_store_singleton: InMemoryItineraryStore | None = None
_entitlement_singleton: EntitlementService | None = None
_account_service_singleton: AccountService | None = None


def get_store() -> ItineraryStore:
    """Process-wide persistent singleton: itinerary state must survive
    across requests AND across uvicorn restarts（2026-10-25 起写穿 PG——
    行程保存即入库，pg_state.PgItineraryStore；PG 不可达时自动降级纯
    内存，SQLite 状态库停写、文件保留为备份）."""
    global _store_singleton
    if _store_singleton is None:
        _store_singleton = PgItineraryStore(get_session_factory())
    return _store_singleton


def get_entitlement_service() -> EntitlementService:
    """Process-wide singleton: quota counters must be shared across
    requests or the snapshot cap would never trigger. rules=[] = default
    free policy (§6.8 ⑥); offers get configured in the rule table later."""
    global _entitlement_singleton
    if _entitlement_singleton is None:
        _entitlement_singleton = EntitlementService(
            store=InMemoryQuotaStore(), rules=[]
        )
    return _entitlement_singleton


def get_account_service() -> AccountService:
    """Process-wide singleton: account rows live in the same SQLite file
    as the itinerary store, and claiming must mutate the SAME in-memory
    store instance the routes use — hence built on ``get_store()``. The
    factory lives here (not in api/auth.py) so auth.py can import it
    without a circular import."""
    global _account_service_singleton
    if _account_service_singleton is None:
        _account_service_singleton = AccountService(
            get_state_backend(db_path_from_url(get_settings().state_db_url)),
            get_store(),
            mailer=get_mailer(),
        )
    return _account_service_singleton


def get_itinerary_service(
    store: ItineraryStore = Depends(get_store),
) -> ItineraryService:
    # Stateless wrapper; all persistent state lives in the store singleton.
    return ItineraryService(store)


def get_trip_import_service(
    settings: Settings = Depends(get_settings),
) -> TripImportService:
    """行程导入 LLM 结构化服务（api/trip_import 测试用 stub adapter 覆盖）。"""
    return TripImportService(get_llm_adapter(settings))


def _trip_items_service() -> TripItemService:
    """行程删除时释放名下已排期心愿用（2026-10-31）。函数内延迟导入：
    app.api.trip_items 顶部 import 本模块 get_store，模块级互相导入两个
    方向都炸（get_account_service 工厂同款防环考量）。"""
    from app.api.trip_items import get_trip_item_service

    return get_trip_item_service()


# --- helpers -----------------------------------------------------------------


def _require_device(x_device_id: str | None) -> str:
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    return x_device_id


def _account_from_auth(
    authorization: str | None = Header(default=None),
    service: AccountService = Depends(get_account_service),
) -> str | None:
    """Bearer token -> username, or None. Anonymous/invalid tokens stay
    anonymous — the device-scoped behavior is untouched."""
    token = parse_bearer_token(authorization)
    if token is None:
        return None
    return service.verify_token(token)


def _owned_record(
    store: ItineraryStore,
    itinerary_id: str,
    owner_device_id: str,
    account: str | None = None,
) -> ItineraryRecord:
    record = store.get(itinerary_id)
    # 404 for foreign owners too — never confirm someone else's id exists.
    # Logged-in accounts also own itineraries claimed by/created for them,
    # regardless of which device made them.
    if record is None:
        raise HTTPException(status_code=404, detail="itinerary_not_found")
    if record.owner_device_id != owner_device_id and not (
        account is not None and record.owner_account_id == account
    ):
        raise HTTPException(status_code=404, detail="itinerary_not_found")
    return record


def _summary(record: ItineraryRecord) -> dict:
    # 行程生成时间（2026-10-20）：created_at 为 None 的存量旧记录回退到
    # 最早快照的 created_at（记录里唯一真实历史时间戳），都没有则 None。
    created_at = record.created_at
    if created_at is None and record.snapshots:
        created_at = min(s.created_at for s in record.snapshots)
    # 更新时间（2026-10-20）：随保存/变更/恢复刷新；旧记录回退创建时间。
    updated_at = record.updated_at or record.created_at or created_at
    return {
        "itinerary_id": record.itinerary_id,
        "working_sync_version": record.working_sync_version,
        "cities": record.plan.cities,
        "active_snapshot_id": record.active_snapshot_id,
        "snapshot_count": len(record.snapshots),
        "created_at": created_at,
        "updated_at": updated_at,
        "share_enabled": record.share_enabled,
        # 导入溯源（2026-10-31）：常规行程为 None，前端行程列表行据此标注
        # 「📄 文件名（文件ID）」。
        "import_file_id": record.import_file_id,
        "import_file_name": record.import_file_name,
    }


# --- routes ------------------------------------------------------------------


# --- 行程导入（2026-10-31：行程页 📥 上传 → 预览 → 确认生成行程单）-----------
#
# 预览确认流无服务端会话态：preview 解析+LLM 结构化后把草稿 plan 原样返回，
# 前端弹层展示；用户确认后 confirm 把草稿带回，服务端重校验落库。file_id
# （imp_<hex>）在 preview 生成、每次导入全新——同一文件重复导入得新 id 新
# 行程，不做内容去重（用户拍板）。itinerary_id 也在 preview 分配并写进草稿
# plan，confirm 用它建记录，保证预览与落库是同一张行程单。


def _file_ext(file_name: str) -> str:
    return file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""


def _import_log(
    file_id: str,
    *,
    file_name: str,
    ext: str,
    size_bytes: int,
    owner_device_id: str,
    owner_account_id: str | None,
    status: str,
    text_chars: int | None = None,
    text_preview: str | None = None,
    error: str | None = None,
) -> None:
    """导入流水落 PG（audit/排障，app 无读路径）。写失败只告警——日志
    永不阻断导入主流程（pg_state 写穿同款哲学）。"""
    try:
        row = ItineraryImport(
            id=uuid_mod.UUID(hex=file_id[4:]),
            file_name=file_name[:255],
            ext=ext[:20] or None,
            size_bytes=size_bytes,
            text_chars=text_chars,
            text_preview=(text_preview[:2000] if text_preview else None),
            status=status,
            error=(error[:2000] if error else None),
            owner_device_id=owner_device_id,
            owner_account_id=owner_account_id,
            created_at=datetime.now(timezone.utc),
        )
        with get_session_factory()() as session:
            session.add(row)
            session.commit()
    except Exception:
        logger.warning(
            "itinerary_import: 流水落库失败 file_id=%s", file_id, exc_info=True
        )


def _import_mark_confirmed(file_id: str, itinerary_id: str) -> None:
    """confirm 后把流水行置 confirmed 并回填行程号；行不存在（如 PG 熔断
    期 preview 没写进去）静默跳过。"""
    try:
        uid = uuid_mod.UUID(hex=file_id[4:])
        trip_uid = _pg_uuid_loose(itinerary_id, "it_")
    except (ValueError, AttributeError):
        return
    if trip_uid is None:
        return
    try:
        with get_session_factory()() as session:
            updated = (
                session.query(ItineraryImport)
                .filter(ItineraryImport.id == uid)
                .update(
                    {
                        "status": "confirmed",
                        "itinerary_id": trip_uid,
                        "confirmed_at": datetime.now(timezone.utc),
                    }
                )
            )
            session.commit()
            if not updated:
                logger.info(
                    "itinerary_import: confirm 无对应流水行 file_id=%s", file_id
                )
    except Exception:
        logger.warning(
            "itinerary_import: 流水确认更新失败 file_id=%s", file_id, exc_info=True
        )


@router.post("/itineraries/import/preview")
async def import_preview(
    file: UploadFile = File(...),
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    settings: Settings = Depends(get_settings),
    service: TripImportService = Depends(get_trip_import_service),
    store: ItineraryStore = Depends(get_store),
    account: str | None = Depends(_account_from_auth),
) -> dict:
    device = _require_device(x_device_id)
    file_name = file.filename or "unnamed"
    ext = _file_ext(file_name)
    data = await file.read()
    size_bytes = len(data)
    file_id = f"imp_{uuid_mod.uuid4().hex}"
    if size_bytes > settings.import_max_file_bytes:
        _import_log(
            file_id,
            file_name=file_name,
            ext=ext,
            size_bytes=size_bytes,
            owner_device_id=device,
            owner_account_id=account,
            status="failed",
            error="import_file_too_large",
        )
        raise HTTPException(status_code=413, detail="import_file_too_large")
    try:
        text = await service.extract(
            file_name,
            data,
            max_text_chars=settings.import_max_text_chars,
            max_ocr_pages=settings.import_max_ocr_pages,
        )
    except LLMError as exc:
        # 视觉 OCR 故障（含全部视觉模型 429）——与结构化 LLM 同款 502。
        logger.exception("import preview llm_error: %s", exc)
        _import_log(
            file_id,
            file_name=file_name,
            ext=ext,
            size_bytes=size_bytes,
            owner_device_id=device,
            owner_account_id=account,
            status="failed",
            error="llm_error",
        )
        raise HTTPException(status_code=502, detail="llm_error") from exc
    except UnsupportedImportFormat as exc:
        _import_log(
            file_id,
            file_name=file_name,
            ext=ext,
            size_bytes=size_bytes,
            owner_device_id=device,
            owner_account_id=account,
            status="failed",
            error=exc.code,
        )
        raise HTTPException(status_code=422, detail=exc.code) from exc
    except ImportNoText as exc:
        _import_log(
            file_id,
            file_name=file_name,
            ext=ext,
            size_bytes=size_bytes,
            owner_device_id=device,
            owner_account_id=account,
            status="failed",
            error="import_no_text",
        )
        raise HTTPException(status_code=422, detail="import_no_text") from exc
    try:
        draft, quarantined = await service.structure(text)
        # itinerary_id 在 preview 分配：预览与确认落库是同一张行程单。
        itinerary_id = store.new_itinerary_id()
        plan, warnings = build_plan(draft, itinerary_id)
    except ImportParseError as exc:
        _import_log(
            file_id,
            file_name=file_name,
            ext=ext,
            size_bytes=size_bytes,
            owner_device_id=device,
            owner_account_id=account,
            status="failed",
            error=",".join(exc.reasons),
        )
        raise HTTPException(
            status_code=422,
            detail={"message": "import_parse_failed", "reasons": exc.reasons},
        ) from exc
    except LLMError as exc:
        logger.exception("import preview llm_error: %s", exc)
        _import_log(
            file_id,
            file_name=file_name,
            ext=ext,
            size_bytes=size_bytes,
            owner_device_id=device,
            owner_account_id=account,
            status="failed",
            error="llm_error",
        )
        # LLMError messages are sanitized (never contain the API key).
        raise HTTPException(status_code=502, detail="llm_error") from exc
    _import_log(
        file_id,
        file_name=file_name,
        ext=ext,
        size_bytes=size_bytes,
        owner_device_id=device,
        owner_account_id=account,
        status="previewed",
        text_chars=len(text),
        text_preview=text,
    )
    return {
        "file_id": file_id,
        "file_name": file_name,
        "ext": ext,
        "size_bytes": size_bytes,
        "text_chars": len(text),
        "plan": plan.model_dump(mode="json"),
        "warnings": warnings,
        "quarantined": quarantined,
    }


@router.post("/itineraries/import/confirm", status_code=201)
async def import_confirm(
    request: ConfirmImportRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: ItineraryStore = Depends(get_store),
    service: ItineraryService = Depends(get_itinerary_service),
    entitlement: EntitlementService = Depends(get_entitlement_service),
    account: str | None = Depends(_account_from_auth),
) -> dict:
    device = _require_device(x_device_id)
    try:
        plan = ItineraryPlan.model_validate(request.plan)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="import_plan_invalid") from exc
    # 导入文档常在多天重复出现同一景点：落库前过同站合并唯一入口，drop
    # 名单由 dedupe 自己写进假设区。
    dedupe_plan_visits(plan)
    now = datetime.now(timezone.utc)
    record = ItineraryRecord(
        itinerary_id=plan.itinerary_id,
        owner_device_id=device,
        owner_account_id=account,
        created_at=now,
        updated_at=now,
        plan=plan,
        import_file_id=request.file_id,
        import_file_name=request.file_name,
    )
    store.put(record)
    # 快照 v1「导入原版」：改坏了可还原。额度耗尽照存不冻结（镜像保存
    # 行程行为：行程已落库，快照跳过并在响应里说明）。
    snapshot_skipped: str | None = None
    try:
        service.create_snapshot(
            record,
            name=L("导入原版", "Imported original"),
            entitlement=entitlement,
            subject_id=device,
        )
    except QuotaExceededError:
        snapshot_skipped = "quota_exhausted"
    _import_mark_confirmed(request.file_id, record.itinerary_id)
    summary = _summary(record)
    summary["snapshot_skipped"] = snapshot_skipped
    return summary


@router.post("/itineraries", status_code=201)
async def create_itinerary(
    request: CreateItineraryRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: ItineraryStore = Depends(get_store),
    service: ItineraryService = Depends(get_itinerary_service),
    account: str | None = Depends(_account_from_auth),
) -> dict:
    device = _require_device(x_device_id)
    record = service.create(device, request.cities, days_count=request.days)
    if account is not None:
        # Logged-in: the new itinerary belongs to the account immediately,
        # so it shows up on every device of that account.
        record.owner_account_id = account
        store.put(record)
    return _summary(record)


@router.get("/itineraries")
async def list_itineraries(
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: ItineraryStore = Depends(get_store),
    account: str | None = Depends(_account_from_auth),
) -> list[dict]:
    device = _require_device(x_device_id)
    records = (
        store.list_by_account(account)
        if account is not None
        else store.list_by_owner(device)
    )
    # 行程页按时间倒序（新的在前）：store 恢复后是 DB 行序/插入序，不保证
    # 时间序；_summary 已把旧记录回退到创建时间，None（无任何时间戳）垫底。
    summaries = [_summary(r) for r in records]
    summaries.sort(
        key=lambda s: (s["updated_at"] is None, s["updated_at"]), reverse=True
    )
    return summaries


@router.get("/itineraries/{itinerary_id}")
async def get_itinerary(
    itinerary_id: str,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: ItineraryStore = Depends(get_store),
    account: str | None = Depends(_account_from_auth),
) -> ItineraryRecord:
    device = _require_device(x_device_id)
    return _owned_record(store, itinerary_id, device, account)


@router.put("/itineraries/{itinerary_id}")
async def mutate_itinerary(
    itinerary_id: str,
    request: MutateItineraryRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: ItineraryStore = Depends(get_store),
    service: ItineraryService = Depends(get_itinerary_service),
    account: str | None = Depends(_account_from_auth),
) -> dict:
    device = _require_device(x_device_id)
    record = _owned_record(store, itinerary_id, device, account)
    try:
        record, report, summary = service.mutate(
            record, request.diffs, poi_hours=request.poi_hours
        )
    except PipelineError as exc:
        raise HTTPException(status_code=400, detail="invalid_diff") from exc
    if not report.ok:
        # Error-severity violation: version untouched, caller must repair.
        raise HTTPException(status_code=422, detail=report.model_dump())
    return {
        "record": _summary(record),
        "validation": report.model_dump(),
        "change_summary": summary.model_dump(),
    }


@router.post("/itineraries/{itinerary_id}/snapshots", status_code=201)
async def create_snapshot(
    itinerary_id: str,
    request: CreateSnapshotRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: ItineraryStore = Depends(get_store),
    service: ItineraryService = Depends(get_itinerary_service),
    entitlement: EntitlementService = Depends(get_entitlement_service),
    account: str | None = Depends(_account_from_auth),
) -> dict:
    device = _require_device(x_device_id)
    record = _owned_record(store, itinerary_id, device, account)
    try:
        snapshot = service.create_snapshot(
            record,
            name=request.name,
            note=request.note,
            entitlement=entitlement,
            subject_id=device,
        )
    except QuotaExceededError as exc:
        # §6.8: the client PaywallGate reports this trigger and we answer
        # with the same trigger so the gate can match an offer client-side.
        raise HTTPException(
            status_code=402,
            detail={
                "denied_reason": exc.denied_reason or "quota_exhausted",
                "paywall_trigger": exc.paywall_trigger,
            },
        ) from exc
    return snapshot.model_dump(exclude={"plan"})


@router.get("/itineraries/{itinerary_id}/snapshots")
async def list_snapshots(
    itinerary_id: str,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: ItineraryStore = Depends(get_store),
    account: str | None = Depends(_account_from_auth),
) -> list[dict]:
    device = _require_device(x_device_id)
    record = _owned_record(store, itinerary_id, device, account)
    return [s.model_dump(exclude={"plan"}) for s in record.snapshots]


@router.post("/itineraries/{itinerary_id}/snapshots/{snapshot_id}/restore")
async def restore_snapshot(
    itinerary_id: str,
    snapshot_id: str,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: ItineraryStore = Depends(get_store),
    service: ItineraryService = Depends(get_itinerary_service),
    account: str | None = Depends(_account_from_auth),
) -> ItineraryRecord:
    device = _require_device(x_device_id)
    record = _owned_record(store, itinerary_id, device, account)
    try:
        record = service.restore(record, snapshot_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="snapshot_not_found") from exc
    # 恢复闸（2026-10-28 变脸 x4 事故）：旧快照可能冻结着重复站点，恢复
    # 即合并——service.restore 已 put 过一次，合并非空时补一次 put 持久化。
    if dedupe_plan_visits(record.plan):
        store.put(record)
    return record


@router.get("/itineraries/{itinerary_id}/export")
async def export_itinerary(
    itinerary_id: str,
    fmt: str = Query("pdf", alias="format", pattern="^(pdf|docx|xlsx)$"),
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: ItineraryStore = Depends(get_store),
    account: str | None = Depends(_account_from_auth),
) -> Response:
    """行程导出（2026-10-23，gap #2 行程的出口）：pdf = 打印 HTML（前端
    iframe 调浏览器「另存为 PDF」，TREK 零依赖方案）；docx / xlsx = 服务端
    生成二进制。鉴权与其余路由一致：跨 owner 一律 404。"""
    device = _require_device(x_device_id)
    record = _owned_record(store, itinerary_id, device, account)
    filename = quote(trip_export.safe_filename(record.plan))
    if fmt == "pdf":
        return HTMLResponse(
            trip_export.render_html(record.plan),
            headers={
                "Content-Disposition": f"inline; filename*=UTF-8''{filename}.html"
            },
        )
    if fmt == "docx":
        data = trip_export.render_docx(record.plan)
        media = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
    else:
        data = trip_export.render_xlsx(record.plan)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(
        content=data,
        media_type=media,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}.{fmt}"
        },
    )


@router.delete("/itineraries/{itinerary_id}", status_code=204)
async def delete_itinerary(
    itinerary_id: str,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: ItineraryStore = Depends(get_store),
    trip_items: TripItemService = Depends(_trip_items_service),
    account: str | None = Depends(_account_from_auth),
) -> None:
    """Delete an owned itinerary together with its snapshots (2026-10-20:
    「行程」页 per-trip 查看/删除 buttons). Unknown / foreign-owner ids
    answer 404 like every other route (no enumeration). 2026-10-31（用户
    拍板）：删行程前名下 scheduled 行先回心愿单栏（day/position/booking_id
    清空；booked 保留真实订单不动）——先释放后删除，释放失败行程仍在，
    可重试。trip_items 依旧不物理删除：看板自有真相（铁律 0）。"""
    device = _require_device(x_device_id)
    _owned_record(store, itinerary_id, device, account)
    trip_items.release_itinerary(itinerary_id)
    store.delete(itinerary_id)

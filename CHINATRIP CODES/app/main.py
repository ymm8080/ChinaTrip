import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.amap import router as amap_router
from app.api.asr import router as asr_router
from app.api.auth import router as auth_router
from app.api.backfill import router as backfill_router
from app.api.booking_auto import router as booking_auto_router
from app.api.bookings import router as bookings_router
from app.api.call import router as call_router
from app.api.extract import router as extract_router
from app.api.feedback import router as feedback_router
from app.api.health import router as health_router
from app.api.itineraries import router as itineraries_router
from app.api.metrics import router as metrics_router
from app.api.navigation import router as navi_router
from app.api.offers import router as offers_router
from app.api.payments import router as payments_router
from app.api.plan import router as plan_router
from app.api.pois import router as pois_router
from app.api.profile import links_router, profile_router
from app.api.share import router as share_router
from app.api.tasks import router as tasks_router
from app.api.translate import router as translate_router
from app.api.travelers import router as travelers_router
from app.api.trip_items import router as trip_items_router
from app.api.visa import router as visa_router
from app.api.weather import router as weather_router
from app.config import get_settings
from app.middleware.lang import LangMiddleware
from app.middleware.ratelimit import RateLimitMiddleware
from app.middleware.usage import TraceIdMiddleware

logger = logging.getLogger(__name__)

# Dev/live db lives in WSL, which idle-sleeps ~1min without traffic and
# takes PG (and the whole plan pipeline) with it (2026-10-25 placeholder
# incident). A 30s ping keeps the VM awake and clears the store's
# down-latch the moment PG answers again.
_PG_KEEPALIVE_INTERVAL_SECONDS = 30.0


def _pg_keepalive(stop: threading.Event) -> None:
    from app.services.poi_details import get_poi_detail_store

    store = get_poi_detail_store()
    last_ok: bool | None = None
    while True:
        ok = store.ping()
        if ok != last_ok:
            if ok:
                logger.info("pg keepalive: db up (latch cleared)")
            else:
                logger.warning("pg keepalive: db unreachable")
            last_ok = ok
        if stop.wait(_PG_KEEPALIVE_INTERVAL_SECONDS):
            return


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # 2026-10-30 事故：.env 被改成 LLM_BACKEND=mock 后重启，会话编辑轮
    # （mock chat 永远回 mock-chat:原文，无 JSON）100% 解析失败，用户端
    # 表现为「刚才模型回复没能解析」。boot 时大声示警，别再静默降级。
    if get_settings().llm_backend == "mock":
        logger.warning(
            "main: LLM_BACKEND=mock —— 对话/抽取走 Mock 适配器，"
            "会话编辑轮必然解析失败（生产环境应配 zhipu）"
        )
    stop = threading.Event()
    threading.Thread(
        target=_pg_keepalive, args=(stop,), daemon=True, name="pg-keepalive"
    ).start()
    # §6.12 慢车道 worker：进程内 asyncio 任务，逐条消化队列（空转 sleep）。
    from app.services.task_queue import get_task_worker

    worker_task = asyncio.create_task(get_task_worker().run_forever())
    try:
        yield
    finally:
        stop.set()
        worker_task.cancel()


def create_app() -> FastAPI:
    settings = get_settings()
    # settings.log_level existed but was never applied — the root
    # logger stayed at WARNING, so app INFO diagnostics (plan stage
    # timings, degrade warnings) never reached the console.
    # 2026-10-20: wire it once at app creation.
    logging.basicConfig(level=settings.log_level.upper(), force=True)
    app = FastAPI(
        title="自助景点规划助手 API",
        summary="ChinaTrip backend (设计文档 v2.0, 国内区先行 · MVP 最小成本)",
        version=__version__,
        lifespan=_lifespan,
    )

    # Starlette: last add_middleware = outermost. TraceIdMiddleware added last
    # so it measures everything, including 429s from the rate limiter.
    app.add_middleware(
        RateLimitMiddleware,
        per_minute=settings.rate_limit_per_minute,
        per_hour=settings.rate_limit_per_hour,
        exempt_paths=("/health", "/docs", "/redoc", "/openapi.json", "/robots.txt"),
    )
    app.add_middleware(TraceIdMiddleware, region=settings.region)
    app.add_middleware(LangMiddleware)

    app.include_router(health_router)
    app.include_router(extract_router)
    app.include_router(amap_router)
    app.include_router(asr_router)
    app.include_router(auth_router)
    app.include_router(translate_router)
    app.include_router(itineraries_router)
    app.include_router(plan_router)
    app.include_router(pois_router)
    app.include_router(navi_router)
    app.include_router(bookings_router)
    app.include_router(trip_items_router)
    app.include_router(share_router)
    app.include_router(backfill_router)
    app.include_router(offers_router)
    app.include_router(profile_router)
    app.include_router(links_router)
    app.include_router(weather_router)
    app.include_router(visa_router)
    app.include_router(feedback_router)
    app.include_router(booking_auto_router)
    app.include_router(payments_router)
    app.include_router(call_router)
    app.include_router(travelers_router)
    app.include_router(tasks_router)
    app.include_router(metrics_router)

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/h5", StaticFiles(directory=static_dir, html=True), name="h5")
    return app


app = create_app()

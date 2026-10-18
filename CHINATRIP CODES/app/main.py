from fastapi import FastAPI

from app import __version__
from app.api.amap import router as amap_router
from app.api.extract import router as extract_router
from app.api.health import router as health_router
from app.api.itineraries import router as itineraries_router
from app.api.navigation import router as navi_router
from app.api.plan import router as plan_router
from app.api.translate import router as translate_router
from app.config import get_settings
from app.middleware.ratelimit import RateLimitMiddleware
from app.middleware.usage import TraceIdMiddleware


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="自助景点规划助手 API",
        summary="ChinaTrip backend (设计文档 v2.0, 国内区先行 · MVP 最小成本)",
        version=__version__,
    )

    # Starlette: last add_middleware = outermost. TraceIdMiddleware added last
    # so it measures everything, including 429s from the rate limiter.
    app.add_middleware(
        RateLimitMiddleware,
        per_minute=settings.rate_limit_per_minute,
        per_hour=settings.rate_limit_per_hour,
    )
    app.add_middleware(TraceIdMiddleware, region=settings.region)

    app.include_router(health_router)
    app.include_router(extract_router)
    app.include_router(amap_router)
    app.include_router(translate_router)
    app.include_router(itineraries_router)
    app.include_router(plan_router)
    app.include_router(navi_router)
    return app


app = create_app()

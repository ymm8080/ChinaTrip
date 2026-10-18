from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = (
        "postgresql+psycopg://chinatrip:chinatrip@localhost:5432/chinatrip"
    )

    # Zhipu GLM cloud API (OpenAI-compatible). Personal key, zero GPU cost.
    llm_backend: str = "mock"  # "mock" | "zhipu"
    glm_api_key: str = ""
    glm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    glm_model: str = "glm-4.6"
    # Flash tier for the classification gate / short translation fast lane
    # (design §6.12: >=80% requests must not reach the main model).
    glm_model_flash: str = "glm-4.5-flash"
    glm_timeout_seconds: float = 60.0

    # Amap personal developer key. Server-side only - never reaches the client.
    amap_api_key: str = ""
    amap_base_url: str = "https://restapi.amap.com/v3"
    amap_timeout_seconds: float = 5.0

    extract_max_text_chars: int = 20_000
    extract_confidence_threshold: float = 0.8

    # CP-SAT solver budget (design §6.9 / iron rule 8: 3s latency budget).
    solver_time_budget_seconds: float = 3.0

    # Request classification gate v1 (design §6.12): rule match -> intent
    # cache -> Flash classify. Cache is in-process for MVP (Redis W7-8).
    intent_cache_ttl_seconds: int = 300
    intent_cache_max_entries: int = 10_000

    # Translation fast lane (design §6.10 MVP: on-device ASR/OCR produces
    # text; server translates via GLM; phrase/menu cache hit = zero LLM).
    translate_max_chars: int = 2_000
    translate_phrase_cache_max_entries: int = 4_096

    # Deployment region, stamped onto every usage-log line (v1.7 §3 prebuild
    # for the Phase-2 overseas amap-via-CN-proxy path; scene follows there).
    region: str = "CN"

    rate_limit_per_minute: int = 60
    rate_limit_per_hour: int = 600

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()

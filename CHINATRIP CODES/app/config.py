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
    glm_model: str = "glm-5.3-flash"
    # Flash tier for the classification gate / short translation fast lane
    # (design §6.12: >=80% requests must not reach the main model).
    glm_model_flash: str = "glm-5.3-flash"
    glm_timeout_seconds: float = 60.0
    # 智谱语音识别（H5 语音输入，替代大陆不可达的 Chrome Web Speech）
    asr_model: str = "glm-asr-2512"
    # 视频链接理解（web_reader 视频壳）：GLM-4.6V-Flash 看画面（免费）+
    # GLM-ASR 转写音轨（imageio-ffmpeg 自带二进制抽音轨，无需系统 ffmpeg）。
    glm_model_vision: str = "glm-4.6v-flash"
    # 4.6v-flash 的免费池在晚高峰整段 429（code 1305）；旧免费模型
    # glm-4v-flash 是独立容量池，同一时刻可用（探针 2026-10-19）。
    glm_vision_fallback_models: str = "glm-4v-flash"
    video_vision_enabled: bool = True

    # Amap personal developer key. Server-side only - never reaches the client.
    amap_api_key: str = ""
    amap_base_url: str = "https://restapi.amap.com/v3"
    amap_timeout_seconds: float = 5.0

    # Offer-center alliance tracking (design v2.3 §6.11): server-side only,
    # appended to channel deeplinks as allianceId/sid when BOTH are non-empty;
    # empty by default = no params appended, URLs pass through untouched.
    alliance_id: str = ""
    alliance_sid: str = ""

    extract_max_text_chars: int = 20_000
    extract_confidence_threshold: float = 0.8

    # 火车时刻（v2.4 行程中心）：数据源链 携程>美团>12306，任一源返回有效
    # 班次即用，全失败降级 MockTrainService（app/services/trains.py）。
    # 携程/美团对个人开发者无公开火车票 API（H5 探测见模块内证据常量），
    # 当前为占位源、链内自动跳过；12306 无需 key，是实际主力源。
    train_remote_enabled: bool = True  # False => 纯 mock，零网络
    train_query_timeout_seconds: float = 5.0
    travel_train_source_order: list[str] = ["ctrip", "meituan", "12306"]
    # 火车班次日批次缓存（app/services/train_cache.py）：独立 SQLite 落库
    # （app/db.py 的 PG 本机不存在，业务 store 均为内存实现）；换 PG 时改
    # DSN（postgresql+psycopg://...），ORM 同一套 metadata 可迁移。
    train_cache_url: str = "sqlite:///data/train_cache.db"
    train_cache_ttl_hours: float = 24.0
    # 规划会话+行程记录的写穿透落盘（app/services/state_persist.py），
    # 重启 uvicorn 不再清空进行中会话与已存行程。
    state_db_url: str = "sqlite:///data/h5_state.db"

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

    # SMTP for email verification codes (app/services/mailer.py). All
    # optional; empty smtp_host = dev mode: no mail is sent, the code is
    # echoed in a WARNING log + API response so registration works locally.
    # Port 465 = implicit SSL, anything else (587) = STARTTLS.
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_from: str = ""  # envelope From; defaults to smtp_user

    # Deployment region, stamped onto every usage-log line (v1.7 §3 prebuild
    # for the Phase-2 overseas amap-via-CN-proxy path; scene follows there).
    region: str = "CN"

    rate_limit_per_minute: int = 60
    rate_limit_per_hour: int = 600

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()

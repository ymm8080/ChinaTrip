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
    # ASR 后端开关（translation_pipeline_design_2026-10-30 P0）：
    # zhipu = 智谱 glm-asr（现状默认）；baidu_voice_trans = 百度翻译语音翻译API；
    # sensevoice = 本地开源（P1 预留）。对应后端键为空时 503 asr_not_configured。
    asr_backend: str = "zhipu"
    baidu_fanyi_appid: str = ""
    baidu_fanyi_key: str = ""
    baidu_vt_from: str = "auto"
    baidu_vt_to: str = "en"
    baidu_vt_endpoint: str = "https://aip.baidubce.com/rpc/2.0/mt/v2/speech-translation"
    baidu_vt_oauth_url: str = "https://aip.baidubce.com/oauth/2.0/token"
    baidu_bce_api_key: str = ""
    baidu_bce_secret_key: str = ""
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
    # 路线规划接口（walking/transit）单独放宽：高德 direction 偶发 >5s
    # （2026-10-20 日志实测 504 后同参数重试即 200），5s 全局超时会误杀。
    amap_route_timeout_seconds: float = 10.0

    # 地图 WebService 提供方（2026-10-27 高德 5 万商用费转百度）：
    # "amap"（默认，存量行为零变化）| "baidu"（个人认证免费配额）。
    # 两个提供方共用上面两个超时配置；BaiduClient 与 AmapClient 方法
    # 同构，工厂见 app.services.map_provider。
    map_provider: str = "amap"
    baidu_ak: str = ""
    baidu_base_url: str = "https://api.map.baidu.com"
    # 腾讯位置服务 WebService key（2026-10-30：refresh_pois 链④ 第三兜底
    # ——坐标行 regeo 第三层 + 无坐标行按名搜地址；有意不进 map_provider 工厂）
    tencent_map_key: str = ""
    tencent_base_url: str = "https://apis.map.qq.com"

    # Offer-center alliance tracking (design v2.3 §6.11): server-side only,
    # appended to channel deeplinks as allianceId/sid when BOTH are non-empty;
    # empty by default = no params appended, URLs pass through untouched.
    alliance_id: str = ""
    alliance_sid: str = ""

    extract_max_text_chars: int = 20_000
    extract_confidence_threshold: float = 0.8

    # 行程导入（2026-10-31，行程页 📥 上传 PDF/Word/Excel → 预览 → 确认生成
    # 行程单）：上传文件字节数上限 + 解析出的纯文本上限（超出 422，防大文件
    # 打爆 LLM 上下文）；OCR 页数上限（扫描版 PDF 渲染页图走 GLM 视觉）。
    import_max_file_bytes: int = 10 * 1024 * 1024
    import_max_text_chars: int = 30_000
    import_max_ocr_pages: int = 10

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
    # 航班时刻（2026-10-28 骨架）：VariFlight 个人开发者 key，注册后填入；
    # 空（默认）→ MockFlightService 确定性占位，零网络零行为变化。API 契约
    # 在 key 注册后按 open.variflight.com 文档校正（app/services/
    # flights_variflight.py，解析/缓存/降级已就位，届时只改 _fetch 一处）。
    flight_api_key: str = ""
    flight_api_timeout_seconds: float = 5.0
    # 规划会话+行程记录的写穿透落盘（app/services/state_persist.py），
    # 重启 uvicorn 不再清空进行中会话与已存行程。
    state_db_url: str = "sqlite:///data/h5_state.db"

    # CP-SAT solver budget (design §6.9 / iron rule 8: 3s latency budget).
    solver_time_budget_seconds: float = 3.0

    # Request classification gate v1 (design §6.12): rule match -> intent
    # cache -> Flash classify. Cache is in-process for MVP (Redis W7-8).
    intent_cache_ttl_seconds: int = 300
    intent_cache_max_entries: int = 10_000

    # 快慢双车道（design §6.12）：快车道答案缓存（短 TTL，命中零计算）
    # 与慢车道任务队列。队列落 SQLite（无 Redis，照 call_store/state_persist
    # 模式），进程内 asyncio worker 轮询消化；取舍见 task_queue.py 模块头。
    fast_lane_answer_ttl_seconds: float = 60.0
    fast_lane_answer_max_entries: int = 4_096
    task_db_url: str = "sqlite:///data/tasks.db"
    task_worker_poll_seconds: float = 0.5

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

    # 公开分享端点（/s/{token}、/api/v1/public/trips/{token}）在全局
    # 限流之上按裸 IP 再收一档：防爬虫扫 token、防公开页被刷。
    share_public_rate_per_minute: int = 30
    share_public_rate_per_hour: int = 200

    # 预约自动化三档（booking_auto.py，2026-10-25）。L2 库存感知的
    # provider 分家（用户纠偏 2026-10-25）：国内票务库存主力=携程联
    # 盟/同程/美团（B 档个人可申请，国内库存最深）；Klook/Trip.com
    # 是外国人下单面（L1/L3 直达与代抢），不作 L2 库存主源。任一
    # provider key 配好 L2 即活（未配诚实降级 L1）。
    ctrip_union_api_key: str = ""
    tongcheng_api_key: str = ""
    meituan_api_key: str = ""
    klook_api_key: str = ""
    tripcom_api_key: str = ""
    # booking 按钮 geo 分流（2026-10-25 用户拍板）：境外 IP→Trip.com、
    # 国内 IP→美团。region_file = 纯文本 IP 段表（CIDR 一行一段，可热
    # 更，免装 geoip 库——用 updatechen/toolong-ssr 类公开 CN 段表或
    # apnic 委派数据自筛；缺文件=全部按境外处理，宁绕国际站不错推国内站）。
    booking_search_template: str = (
        "https://www.trip.com/attractions/search?keyword={keyword}"
    )
    booking_search_template_domestic: str = (
        "https://www.meituan.com/xiuxianyule/{keyword}"
    )
    booking_region_file: str = "data/cn_ip_ranges.txt"

    # 客户付款层（DESIGN/PAYMENTS_PROGRESS.md，2026-10-25）：公司↔客户收款，
    # 铁律 22 的渠道 handoff 不变。Stripe 一个集成覆盖外卡 + 支付宝 + 微信
    # 支付（hosted Checkout，原始卡号不经过本服务器）；mock 后端零网络可跑
    # 全流程（LLM_BACKEND=mock 同款离线开发哲学）。金额 yuan float（repo 惯例），
    # 只在 Stripe adapter 内转 cents。
    payments_backend: str = "mock"  # "mock" | "stripe"
    stripe_api_key: str = ""
    stripe_webhook_secret: str = ""
    payments_default_currency: str = "cny"
    # 空 = 从请求 base_url 推导（本机 dev 即 127.0.0.1:8000）；生产填绝对地址。
    payments_success_url: str = ""
    payments_cancel_url: str = ""
    # 运营侧对已存卡扣款的共享密钥；空 = 扣款端点整体禁用（403）。
    payments_operator_token: str = ""
    payments_db_url: str = "sqlite:///data/payments.db"

    # 出行人资料（DESIGN/CLIENT_DATA_REQUIREMENTS.md，2026-10-27）：代客预订
    # 实名档案。证件号/手机号 Fernet 加密落库，密钥在 db 同目录 .traveler_key
    # 首次自动生成；列表响应只回脱敏形，明文唯一出口是 /export（审计留痕）。
    travelers_db_url: str = "sqlite:///data/travelers.db"

    # 真人通话咨询（DESIGN/paid_call_service_design_2026-10-25，2026-10-25）：
    # 预付费分钟账本 + 服务端权威通话会话（$1=5 分钟，到点强结）。收款走
    # 网关协议，MVP=mock 零网络全流程；支付宝 wap（主通道，个体工商户可办）
    # 与 Stripe（需境外主体）为门控 stub——未配键诚实 503。stripe_api_key/
    # webhook_secret 与上方客户付款层共用，此处不重复。
    call_db_url: str = "sqlite:///data/call_state.db"
    # 套餐目录（JSON str：code/minutes/price_cny/price_usd；service 解析）。
    call_packages_json: str = (
        '[{"code":"call_m5","minutes":5,"price_cny":8.0,"price_usd":1.0},'
        '{"code":"call_m10","minutes":10,"price_cny":16.0,"price_usd":2.0},'
        '{"code":"call_m20","minutes":20,"price_cny":30.0,"price_usd":4.0},'
        '{"code":"call_m60","minutes":60,"price_cny":90.0,"price_usd":12.0}]'
    )
    call_provider: str = "mock"  # "mock" | "alipay" | "stripe"
    # 坐席热线（tel: 一键拨号目标）；空 = direct 直拨降级为展示文案并引导 callback。
    call_hotline_number: str = ""
    call_min_minutes: int = 5
    call_max_minutes: int = 60
    call_waiting_timeout_seconds: int = 120
    # 仅展示换算（售价签 ¥→$）；订单落库锁定单币种，不做动态汇率结算。
    usd_cny_rate: float = 7.2
    # 坐席台共享密钥（X-Agent-Key）；空 = 坐席端点整体禁用（503）。
    agent_console_key: str = ""
    # 支付宝手机网站支付 stub 位（个体工商户签约后填入即活）。
    alipay_app_id: str = ""
    alipay_private_key: str = ""
    alipay_alipay_public_key: str = ""
    alipay_gateway: str = "https://openapi.alipay.com/gateway.do"

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()

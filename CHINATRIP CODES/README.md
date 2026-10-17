# 自助景点规划助手（暂名）ChinaTrip API (W1-2)

自助景点规划助手后端 — 设计文档 v1.8.0（国内区先行），W1-2 CN 区最小闭环。

- LLM = 智谱 GLM 云 API（个人 key，OpenAI 兼容端点，零 GPU 成本；即 v1.6.1 §3.3-3 认可的降级路径）。W0 GPU 底座就绪后切自部署 vLLM = 仅改 `GLM_BASE_URL` 与模型名，适配器零改动；`LLM_BACKEND=mock` 可完全离线开发测试
- 高德 = 个人开发者 Key，仅服务端调用，key 永不进客户端
- 匿名 device_id 单轨（无登录体系；支付/权益基建不建 —— 需公司主体，表结构保留在迁移中）
- PostgreSQL + PostGIS（Alembic 迁移）
- v1.7 预埋：`pois.wgs84_location` 双坐标（境外渲染副本，Phase 2）；用量日志带 `region` 维度（`scene` 随 Phase 2 境外代理链路引入）
- v1.8 行程求解器：OR-Tools CP-SAT 管排期/排序，LLM 管理解与选点（§6.9 分工）。W3-4 spike 起接入，`ortools` 依赖届时引入，W1-2 不预装

## 开发环境

```bash
cd "CHINATRIP CODES"
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt pytest pytest-cov pytest-timeout ruff  # Windows
cp .env.example .env  # 填入 GLM_API_KEY / AMAP_API_KEY

docker compose up -d db            # PostGIS（可选，测试不需要数据库）
.venv/Scripts/python -m alembic upgrade head   # 建表全量
.venv/Scripts/python -m uvicorn app.main:app --reload
```

## 测试 / Lint

```bash
.venv/Scripts/python -m pytest --cov=app --cov-fail-under=75
.venv/Scripts/python -m ruff format app tests && .venv/Scripts/python -m ruff check app tests
```

## API

| 路由 | 说明 |
|---|---|
| `GET /health` | 存活检查 |
| `POST /api/v1/extract` | 链接/文本解析（GLM 或 mock；注入内容隔离标记；置信度 <0.8 待确认；解析期零写权限） |
| `GET /api/v1/amap/poi/search` | 高德 POI 服务端代理（key 不出服务端） |

@echo off
rem ===== 冷启动一键灌数据（新盘装好 Docker 后手动跑一次）=====
rem 前置: Docker Desktop 运行中 + `docker compose up -d db` 已执行
cd /d "D:\CHINATRIP\CHINATRIP CODES"
set "PY=%~dp0..\.venv\Scripts\python.exe"
set "LOG=devlogs\poi_fill_now.log"
if not exist devlogs mkdir devlogs
echo [%date% %time%] === fill now start === >> "%LOG%"

rem 0. 建表/扩列（0006: POI 底库列 + restaurants 表）
"%PY%" -m alembic upgrade head >> "%LOG%" 2>&1 || goto :fail

rem 1. ChinaTravel 种子（只写骨架：名称/坐标/类别；坐标 auto 判定 GCJ-02/WGS84）
"%PY%" -m app.jobs.import_chinatravel --parquet tmp_t\ct_eval\attractions_zh.parquet --kind attraction --assume auto >> "%LOG%" 2>&1 || goto :fail
"%PY%" -m app.jobs.import_chinatravel --parquet tmp_t\ct_eval\poi_zh.parquet --kind restaurant --assume auto >> "%LOG%" 2>&1 || goto :fail

rem 2. 回源升级骨架行（高德匹配 + 携程/高德补地址营业时间）；首轮逐城跑量大些
for %%C in (北京 上海 杭州 苏州 重庆 广州 武汉 成都 南京 深圳) do (
  "%PY%" -m app.jobs.refresh_pois --city %%C --match --limit 500 >> "%LOG%" 2>&1
)

rem 3. 时段属性 + 简介（只填空字段，幂等可重跑）
"%PY%" -m app.jobs.backfill_best_visit --stage heuristic --limit 5000 >> "%LOG%" 2>&1
"%PY%" -m app.jobs.backfill_intro --limit 2000 >> "%LOG%" 2>&1

rem 4. 品质标签（若已有人工下载的黑珍珠 CSV）
if exist data\black_pearl.csv "%PY%" -m app.jobs.tag_quality --csv data\black_pearl.csv --kind black_pearl >> "%LOG%" 2>&1

echo [%date% %time%] === fill now OK === >> "%LOG%"
exit /b 0
:fail
echo [%date% %time%] === fill now FAILED (see %LOG%) ===
exit /b 1

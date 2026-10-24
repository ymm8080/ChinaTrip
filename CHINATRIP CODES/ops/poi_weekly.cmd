@echo off
rem 每周 POI 回填（schtasks 周日 03:30）：时段属性（启发式全量+LLM 小批）+ 简介滴灌
rem 日志: devlogs\poi_weekly.log
cd /d "D:\CHINATRIP\CHINATRIP CODES"
set "PY=%~dp0..\.venv\Scripts\python.exe"
call "%~dp0db_up.cmd"
set "LOG=devlogs\poi_weekly.log"
if not exist devlogs mkdir devlogs
echo [%date% %time%] === poi weekly start === >> "%LOG%"

rem 铁律只升不降：NULL/any 才可写，重跑安全
"%PY%" -m app.jobs.backfill_best_visit --stage heuristic --limit 2000 >> "%LOG%" 2>&1
rem LLM 层有成本，每周小批推进（需 llm_backend=zhipu + glm_api_key）
"%PY%" -m app.jobs.backfill_best_visit --stage llm --limit 50 >> "%LOG%" 2>&1
rem Wikidata 简介+图片（只填空字段，串行限速 0.5s/请求）
"%PY%" -m app.jobs.backfill_intro --limit 100 >> "%LOG%" 2>&1
echo [%date% %time%] === poi weekly done === >> "%LOG%"

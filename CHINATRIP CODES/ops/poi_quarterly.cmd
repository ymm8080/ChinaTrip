@echo off
rem 季度简介全量回填（schtasks 1/4/7/10 月 1 日 03:00）：Wikidata+中文维基百科
rem 日志: devlogs\poi_quarterly.log
cd /d "D:\CHINATRIP\CHINATRIP CODES"
set "PY=%~dp0..\.venv\Scripts\python.exe"
set "LOG=devlogs\poi_quarterly.log"
if not exist devlogs mkdir devlogs
echo [%date% %time%] === poi quarterly start === >> "%LOG%"
rem 只填空字段（intro/photos 已有值绝不覆盖）；3400+ 行约 1-2 小时（0.5s/请求限速）
"%PY%" -m app.jobs.backfill_intro --limit 5000 >> "%LOG%" 2>&1
echo [%date% %time%] === poi quarterly done === >> "%LOG%"

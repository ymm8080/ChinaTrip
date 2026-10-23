@echo off
rem 城市天气抓取（高德天气 API，上游中国气象局；DESIGN/database_design.md §6.2 矩阵行）
rem 时机紧跟高德预报更新点（每日约 8/11/18 时）+1 派生：08:10 / 11:10 / 18:10
rem 默认只抓行程涉及城市（省个人 key 配额，约 100 次/日）；latest-wins 幂等可重跑
rem 日志: devlogs\weather_fetch.log
cd /d "D:\CHINATRIP\CHINATRIP CODES"
set "PY=%~dp0..\.venv\Scripts\python.exe"
set "LOG=devlogs\weather_fetch.log"
if not exist devlogs mkdir devlogs
echo [%date% %time%] === weather fetch start === >> "%LOG%"
"%PY%" -m app.jobs.fetch_weather >> "%LOG%" 2>&1
echo [%date% %time%] === weather fetch done === >> "%LOG%"

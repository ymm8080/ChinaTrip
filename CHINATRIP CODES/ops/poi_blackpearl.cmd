@echo off
rem 每月 2 日 04:30 黑珍珠巡检（定稿：每月 2 日巡检兜改期，与米其林错峰）
rem 无自动下载源：官方年度发榜（内地榜 1/27、海外榜 3/23 前后），发榜日人工导出 CSV 覆盖
rem data\black_pearl.csv；定点拉取 1/28、3/24 同样人工执行。打标幂等（并集，只改已存在行）
rem 日志: devlogs\poi_blackpearl.log
cd /d "D:\CHINATRIP\CHINATRIP CODES"
set "PY=%~dp0..\.venv\Scripts\python.exe"
set "LOG=devlogs\poi_blackpearl.log"
if not exist devlogs mkdir devlogs
echo [%date% %time%] === blackpearl check start === >> "%LOG%"
if exist data\black_pearl.csv (
  "%PY%" -m app.jobs.tag_quality --csv data\black_pearl.csv --kind black_pearl >> "%LOG%" 2>&1
) else (
  echo [%date% %time%] data\black_pearl.csv 不存在 - 人工导出后放入再跑 >> "%LOG%"
)
echo [%date% %time%] === blackpearl check done === >> "%LOG%"

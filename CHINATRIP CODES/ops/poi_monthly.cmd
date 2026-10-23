@echo off
rem 每月 7 日 04:00 米其林标签（定稿实测+1：上游镜像 86% 发布落每月 2-5 日，1 日拉会扑空）
rem 各城错峰发榜 3/4/8/9/10 月，月拉保证发榜月内入库；并集打标，必比登优先展示
rem 日志: devlogs\poi_monthly.log
cd /d "D:\CHINATRIP\CHINATRIP CODES"
set "PY=%~dp0..\.venv\Scripts\python.exe"
set "LOG=devlogs\poi_monthly.log"
if not exist devlogs mkdir devlogs
echo [%date% %time%] === poi monthly start === >> "%LOG%"

rem ngshiheng/michelin-my-maps 月更 CSV（若 404 到仓库核对文件路径）
set "MICH_URL=https://raw.githubusercontent.com/ngshiheng/michelin-my-maps/main/michelin_my_maps.csv"
curl -fsSL --retry 3 -o data\michelin.csv "%MICH_URL%" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [%date% %time%] michelin csv download FAILED >> "%LOG%"
) else (
  rem 只匹配已存在 restaurants 行，绝不新建；未命中进 unmatched 报告
  "%PY%" -m app.jobs.tag_quality --csv data\michelin.csv --kind michelin >> "%LOG%" 2>&1
)

rem 黑珍珠巡检已拆到 poi_blackpearl.cmd（每月 2 日，与定稿错峰一致）
echo [%date% %time%] === poi monthly done === >> "%LOG%"

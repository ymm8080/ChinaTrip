@echo off
rem ===== 注册 POI 刷新计划任务（一次性；新盘装好 Docker 后以当前用户运行）=====
rem 时机对齐 DESIGN/database_design.md v1.3 数据源×刷新矩阵（实测+1 派生）：
rem   02:00 回源刷新 / 06:30 OSM 日增 / 周日 03:30 回填滴灌 / 7 日 04:00 米其林
rem   / 2 日 04:30 黑珍珠巡检 / 季初 03:00 简介全量
rem 注意：交互式任务，仅当前用户登录时执行；漏跑自动补齐——回源按城轮转、
rem OSM 按水位续传、回填只填空/只升不降，全部幂等。

set "OPS=D:\CHINATRIP\CHINATRIP CODES\ops"

schtasks /Create /F /TN "ChinaTrip\POI refresh daily"   /TR "\"%OPS%\poi_refresh_daily.cmd\"" /SC DAILY   /ST 02:00
schtasks /Create /F /TN "ChinaTrip\POI osm daily"       /TR "\"%OPS%\poi_daily.cmd\""         /SC DAILY   /ST 06:30
schtasks /Create /F /TN "ChinaTrip\POI weekly backfill" /TR "\"%OPS%\poi_weekly.cmd\""        /SC WEEKLY  /D SUN /ST 03:30
schtasks /Create /F /TN "ChinaTrip\POI monthly tags"    /TR "\"%OPS%\poi_monthly.cmd\""       /SC MONTHLY /MO 1 /D 7 /ST 04:00
schtasks /Create /F /TN "ChinaTrip\POI blackpearl check" /TR "\"%OPS%\poi_blackpearl.cmd\""   /SC MONTHLY /MO 1 /D 2 /ST 04:30
schtasks /Create /F /TN "ChinaTrip\POI quarterly intro" /TR "\"%OPS%\poi_quarterly.cmd\""     /SC MONTHLY /MO 1 /M JAN,APR,JUL,OCT /D 1 /ST 03:00

rem ===== 天气（高德天气 API，上游中国气象局；预报 8/11/18 时三更新，+1 派生） =====
schtasks /Create /F /TN "ChinaTrip\Weather morning"   /TR "\"%OPS%\weather_fetch.cmd\"" /SC DAILY /ST 08:10
schtasks /Create /F /TN "ChinaTrip\Weather midday"    /TR "\"%OPS%\weather_fetch.cmd\"" /SC DAILY /ST 11:10
schtasks /Create /F /TN "ChinaTrip\Weather evening"   /TR "\"%OPS%\weather_fetch.cmd\"" /SC DAILY /ST 18:10

schtasks /Query /TN "ChinaTrip\POI refresh daily"
echo 注册完成；删除用: schtasks /Delete /TN "ChinaTrip\..." /F

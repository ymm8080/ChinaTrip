@echo off
rem 自研定时引擎宿主（timing_engine.py 的 schtasks 壳）：
rem 每 2 分钟拉起一次 --once（到期即跑、水位续传、失败退避），
rem 与 ZCode 每 2 分钟 LLM 巡检层互补——本层是确定性执行层。
rem 注册：schtasks /Create /TN ChinaTrip\TimingEngine /SC MINUTE /MO 2 /TR "D:\CHINATRIP\CHINATRIP CODES\ops\timing_engine.cmd" /F
cd /d "D:\CHINATRIP\CHINATRIP CODES"
if not exist devlogs mkdir devlogs
"%~dp0..\.venv\Scripts\python.exe" ops\timing_engine.py --once >> devlogs\timing_engine_host.log 2>&1

# 占用方是 fetch_weather 的定时任务——它写的是 weather_reports，多半只是
# 短暂句柄残留；用「先重命名再删」绕开写锁。
import os
src = r"D:\CHINATRIP\DESIGN\rating sources.docx"
dst = r"D:\CHINATRIP\DESIGN\_rating_sources.docx.hold"
try:
    os.rename(src, dst)
    print("renamed to hold")
    os.remove(dst)
    print("removed hold")
except Exception as e:
    print("rename/remove failed:", e)

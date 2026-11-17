# fetch_weather 不该写这个 docx——真正占用者可能是 Word/WPS 或杀软扫描。
# 用 restart 句柄探测：open with FILE_SHARE_DELETE 检查；若都不行，等 90 秒重试一次。
import time, os
src = r"D:\CHINATRIP\DESIGN\rating sources.docx"
for attempt in range(3):
    try:
        os.rename(src, src + ".hold")
        os.rename(src + ".hold", src)  # 放回原名（证明锁释放）
        print("lock released at attempt", attempt)
        break
    except Exception as e:
        print("attempt", attempt, "still locked:", e)
        time.sleep(30)

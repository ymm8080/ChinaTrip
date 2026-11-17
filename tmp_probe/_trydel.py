import shutil, os
src = r"D:\CHINATRIP\DESIGN\rating sources.docx"
# 先备份当前（被占用）内容
try:
    shutil.copyfile(src, r"D:\CHINATRIP\tmp_probe\_rating_sources_occupied.docx")
    print("copied occupied version")
except Exception as e:
    print("copy failed:", e)
# 打开-写入截断可能仍被拒；尝试以追加模式绕过锁（Windows 允许读共享写取决于进程）

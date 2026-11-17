import sys
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
from app.services.agent import plan as P
corpus = ["帮我规划行程：2 天，城市：上海、杭州；偏好：无", "无特别要求", "我要去蜀风雅韵"]
for n in ["蜀风雅韵", "看变脸表演", "看大熊猫"]:
    print(n, P._wish_grounded_in_user_text(n, corpus), P._wish_key(n), P._wish_core(n))

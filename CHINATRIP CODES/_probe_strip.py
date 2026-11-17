import sys, re
sys.path.insert(0, r"D:\chinatrip\CHINATRIP CODES")
from app.services.agent.plan import _strip_llm_questions
print(repr(_strip_llm_questions("已把博物馆移到第2天。要不要顺便把餐厅也调整一下？")))
print(repr(_strip_llm_questions("需要我帮你调整哪一天？")))

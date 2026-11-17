import io
s = io.open(r"app/services/agent/plan.py", encoding="utf-8", newline="").read()
i = s.find("_chain = access_chain_minutes(src, visit)")
print(s[i-1500:i+900])

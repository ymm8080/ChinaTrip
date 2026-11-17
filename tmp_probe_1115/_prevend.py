import io
s = io.open(r"app/services/agent/plan.py", encoding="utf-8", newline="").read()
i = s.find("prev_end = (")
print(repr(s[i-120:i+400]))

import io
s = io.open(r"app/services/agent/hotel_stays.py", encoding="utf-8", newline="").read()
i = s.find("def head_chain_minutes")
print(s[i-1200:i+400])
i2 = s.find("head_chain_minutes(timed[0])")
print("----")
print(s[i2-900:i2+300])

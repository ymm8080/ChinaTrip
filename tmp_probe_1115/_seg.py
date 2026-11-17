import io
s = io.open(r"app/services/itinerary/rules.py", encoding="utf-8", newline="").read()
i = s.find("def access_breakdown")
seg = s[i:i+4000]
print(seg.encode("utf-8").decode("utf-8"))

import io
s = io.open(r"app/services/itinerary/rules.py", encoding="utf-8", newline="").read()
i = s.find("candidates = _service_candidates")
print(repr(s[i-200:i+600]))

import io
s = io.open(r"app/services/itinerary/legs.py", encoding="utf-8", newline="").read()
i = s.find("booking_url")
print(s[i-500:i+200])

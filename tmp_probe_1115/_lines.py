import io
s = io.open(r"app/services/itinerary/legs.py", encoding="utf-8", newline="").read()
lines = s.split("\n")
for i in range(168, 190):
    print(i+1, repr(lines[i]))

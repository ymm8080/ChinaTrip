import io
p = r"app/static/index.html"
s = io.open(p, encoding="utf-8", newline="").read()
print(len(s))
print(s.count("next_leg_detail"))
i = s.find("next_leg_detail")
print(i)
print(repr(s[:200]))

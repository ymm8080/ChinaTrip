import io
s = io.open(r"app/static/index.html", encoding="utf-8", newline="").read()
i = s.find(".leg-link{")
print(repr(s[i-200:i+260]))
j = s.find("--accent:")
print(repr(s[j-300:j+300]))

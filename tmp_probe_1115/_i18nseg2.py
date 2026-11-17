import io
s = io.open(r"app/static/i18n.js", encoding="utf-8", newline="").read()
i = s.find("function tf(")
print(s[i:i+800])

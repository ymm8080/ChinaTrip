import io
s = io.open(r"app/static/index.html", encoding="utf-8", newline="").read()
i = s.find("const leg = I18N.t(")
print(repr(s[i:i+600]))

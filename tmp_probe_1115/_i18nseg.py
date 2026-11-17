import io, re
s = io.open(r"app/static/i18n.js", encoding="utf-8", newline="").read()
i = s.find("tf:")
print(s[i-600:i+700])

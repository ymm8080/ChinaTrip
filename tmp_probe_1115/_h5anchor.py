import io
s = io.open(r"app/static/index.html", encoding="utf-8", newline="").read()
i = s.find('+ leg + "</div>"')
print(repr(s[i-120:i+40]))
print("count:", s.count('+ leg + "</div>"'))

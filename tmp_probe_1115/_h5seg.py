import io
s = io.open(r"app/static/index.html", encoding="utf-8", newline="").read()
i = s.find('const leg = I18N.t("card.to_next")')
print(s[i-2600:i+900])

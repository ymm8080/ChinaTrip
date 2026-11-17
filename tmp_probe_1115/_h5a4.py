import io
s = io.open(r"app/static/index.html", encoding="utf-8", newline="").read()
print("has next_leg_detail:", s.count("next_leg_detail"))
i = s.find("card.to_next")
print("to_next idx", i)
j = s.find("leg + \"</div>\"")
print("leg end idx", j)
print(repr(s[j-260:j+30]) if j>0 else "none")

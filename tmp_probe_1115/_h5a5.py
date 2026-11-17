import io
s = io.open(r"app/static/index.html", encoding="utf-8", newline="").read()
a1 = 'blk.appendChild(el(\'<div class="muted" style="margin:0 2px 6px \' + ind + \'">\' + leg + "</div>"));'
print("count a1:", s.count(a1))
print("exists:", a1 in s)
print("len s", len(s))

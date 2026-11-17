import io, os
p = r"app/services/itinerary/rules.py"
s = io.open(p, encoding="utf-8", newline="").read()
old = '''    a_end = None
    if getattr(a, "end_time", None) is not None:
        a_end = a.end_time.hour * 60 + a.end_time.minute
'''
new = '''    a_end = None
    if getattr(a, "end_time", None) is not None:
        a_end = a.end_time.hour * 60 + a.end_time.minute
'''
print("end block count", s.count(old))
# locate the computed a_end block
i = s.find("    a_end = None")
print(s[i:i+520])

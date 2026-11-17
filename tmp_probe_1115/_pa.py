import io
s = io.open(r"app/services/poi_access.py", encoding="utf-8", newline="").read()
i = s.find("def head_chain_minutes")
print(repr(s[i:i+120]))
j = s.find("return head + int(wait) + int(service) + int(last)")
print(repr(s[j:j+120]))
print(s[j+60:j+400])

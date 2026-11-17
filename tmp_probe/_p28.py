# -*- coding: utf-8 -*-
import io, re
p = r"D:\CHINATRIP\CHINATRIP CODES\app\api\trip_items.py"
t = io.open(p, encoding="utf-8", newline=None).read()
old = "from fastapi import APIRouter, Depends, Header, HTTPException\n"
new = "from fastapi import APIRouter, Depends, Header, HTTPException, Response\n"
assert t.count(old) == 1
t = t.replace(old, new, 1)
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("import ok")

# sw.js: trip-items network-only + bump v89 -> v90
p2 = r"D:\CHINATRIP\CHINATRIP CODES\app\static\sw.js"
t2 = io.open(p2, encoding="utf-8", newline=None).read()
old2 = "const VERSION = 'v89';"
new2 = "const VERSION = 'v90';"
assert t2.count(old2) == 1, t2.count(old2)
t2 = t2.replace(old2, new2, 1)
old3 = """  // API（含跨域 apiBase）：网络优先，断网/超时回落最近缓存
  if (url.pathname.includes('/api/')) {
"""
new3 = """  // 2026-11-14（用户拍板「行程中心显示数据库信息，不吃缓存」）：心愿单
  // 看板永远直连网络——networkFirst 的 3s 超时回缓存会让删掉/去重后的
  // 旧看板闪回；本路径不写缓存、不回缓存。
  if (url.pathname.includes('/api/v1/trip-items')) {
    e.respondWith(fetch(req));
    return;
  }

  // API（含跨域 apiBase）：网络优先，断网/超时回落最近缓存
  if (url.pathname.includes('/api/')) {
"""
assert t2.count(old3) == 1
t2 = t2.replace(old3, new3, 1)
io.open(p2, "w", encoding="utf-8", newline="\r\n").write(t2)
print("sw ok")

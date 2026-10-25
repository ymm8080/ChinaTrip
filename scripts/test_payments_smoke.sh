#!/usr/bin/env bash
# ChinaTrip 支付层冒烟脚本（E1 mock/dev 环境，零真实资金）。
# 用法: bash scripts/test_payments_smoke.sh [BASE_URL]   # 默认 http://127.0.0.1:8000
# 覆盖: health → pay_now 下单→确认→查询 → save_method 存卡→确认 →
#        运营扣款守卫(未配 token=403) → webhook 坏签名(400) → 参数校验(400) → mine 归属。
set -u
BASE="${1:-http://127.0.0.1:8000}"
DEVH="X-Device-ID: smoke-$(date +%s)"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/CHINATRIP CODES/.venv/Scripts/python.exe"
TMPB="$(mktemp)"
FAILS=0

step()  { printf '\n=== %s\n' "$1"; }
check() { if [ "$2" = "$3" ]; then echo "  PASS: $1"; else echo "  FAIL: $1 (want [$2] got [$3])"; FAILS=$((FAILS+1)); fi; }
code()  { curl.exe -s --ssl-no-revoke -m 8 -o "$TMPB" -w '%{http_code}' "$@"; }
field() { "$PY" -c "import json,sys; d=json.load(sys.stdin); v=d.get(sys.argv[1],''); print(v if not isinstance(v,(dict,list)) else json.dumps(v,ensure_ascii=False))" "$1" < "$TMPB"; }

step "1. health ($BASE)"
check "health 200" 200 "$(code "$BASE/health")"

step "2. checkout pay_now (553 CNY)"
check "checkout 200" 200 "$(code -X POST "$BASE/api/v1/payments/checkout" -H "Content-Type: application/json" -H "$DEVH" -d '{"kind":"pay_now","amount_yuan":553,"currency":"cny","description":"smoke pay_now"}')"
PID=$(field payment_id)
check "checkout_url = /h5/?mockpay=<id>" "/h5/?mockpay=$PID" "$(field checkout_url)"
check "status pending" "pending" "$(field status)"
[ -n "$(field refund_summary)" ] && echo "  PASS: refund_summary present（铁律 23）" || { echo "  FAIL: refund_summary empty"; FAILS=$((FAILS+1)); }

step "3. mock confirm → succeeded"
check "confirm 200" 200 "$(code -X POST "$BASE/api/v1/payments/$PID/confirm")"
check "status succeeded" "succeeded" "$(field status)"
[ -n "$(field paid_at)" ] && echo "  PASS: paid_at set" || { echo "  FAIL: paid_at empty"; FAILS=$((FAILS+1)); }

step "4. get payment by id"
check "get 200" 200 "$(code "$BASE/api/v1/payments/$PID")"
check "status still succeeded" "succeeded" "$(field status)"

step "5. save_method 存卡流程"
check "checkout 200" 200 "$(code -X POST "$BASE/api/v1/payments/checkout" -H "Content-Type: application/json" -H "$DEVH" -d '{"kind":"save_method","email":"smoke@test.dev"}')"
PID2=$(field payment_id)
check "confirm 200" 200 "$(code -X POST "$BASE/api/v1/payments/$PID2/confirm")"
check "status method_saved" "method_saved" "$(field status)"
check "saved card label" "Mock Card ••4242" "$(field saved_method_label)"

step "6. 运营扣款守卫（未配 PAYMENTS_OPERATOR_TOKEN → 403）"
check "charge without token 403" 403 "$(code -X POST "$BASE/api/v1/payments/$PID2/charge" -H "Content-Type: application/json" -d '{"amount_yuan":10}')"
check "charge wrong token 403" 403 "$(code -X POST "$BASE/api/v1/payments/$PID2/charge" -H "Content-Type: application/json" -H "X-Operator-Token: wrong" -d '{"amount_yuan":10}')"

step "7. webhook 坏签名 → 400"
check "bad signature 400" 400 "$(code -X POST "$BASE/api/v1/payments/webhook/stripe" -H "Stripe-Signature: t=1,v1=deadbeef" -H "Content-Type: application/json" -d '{"type":"payout.paid","data":{}}')"

step "8. 参数校验（pay_now 缺金额 → 400）"
check "missing amount 400" 400 "$(code -X POST "$BASE/api/v1/payments/checkout" -H "Content-Type: application/json" -H "$DEVH" -d '{"kind":"pay_now"}')"

step "9. mine 归属（两条记录均可见）"
code "$BASE/api/v1/payments/mine" -H "$DEVH" >/dev/null
MINE=$("$PY" -c "
import json,sys
d=json.load(open(sys.argv[1],encoding='utf-8'))
ids={p['id'] for p in d.get('payments',[])}
print('YES' if {'$PID','$PID2'} <= ids else 'NO')
" "$TMPB")
check "mine has both records" "YES" "$MINE"

rm -f "$TMPB"
printf '\n================\n'
if [ "$FAILS" -eq 0 ]; then echo "ALL PASS ✅"; else echo "$FAILS check(s) FAILED ❌"; exit 1; fi

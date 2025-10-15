#!/usr/bin/env bash
set -Eeuo pipefail
APP_BASE="${APP_BASE:-http://127.0.0.1:25119}"
TOKEN="${METRICS_TOKEN:-dev-metrics}"

say_ok(){ echo "✅ $1"; }
say_err(){ echo "❌ $1" >&2; }

# /readyz
rz_code=$(curl -sS -w "%{http_code}" -o /tmp/readyz.json "$APP_BASE/readyz") || { say_err "خطا در اتصال به /readyz"; exit 2; }
[[ "$rz_code" == "200" || "$rz_code" == "503" ]] || { say_err "کد نامعتبر از /readyz: $rz_code"; exit 3; }
grep -q '"status"' /tmp/readyz.json || { say_err "بدنه /readyz معتبر نیست"; exit 4; }
say_ok "/readyz => $rz_code"

# /metrics با توکن
mt_code=$(curl -sS -w "%{http_code}" -o /tmp/metrics.out -H "X-Metrics-Token: $TOKEN" "$APP_BASE/metrics") || { say_err "خطا در اتصال به /metrics"; exit 5; }
[[ "$mt_code" == "200" ]] || { say_err "کد نامعتبر از /metrics: $mt_code"; exit 6; }
say_ok "/metrics => 200"

echo "🎉 اسموک تست پاس شد."

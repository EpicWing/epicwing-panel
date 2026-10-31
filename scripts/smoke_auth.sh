#!/usr/bin/env bash
# Smoke test for the login flow against the real dev database (port 8010).
set -euo pipefail

EMAIL="${1:?Aufruf: bash scripts/smoke_auth.sh <admin-email>}"
BASE="http://127.0.0.1:8010/api/auth"

if ss -ltn | grep ':8010 ' >/dev/null; then
  echo "Port 8010 is in use, please stop the running dev server." >&2
  exit 1
fi

read -rsp "Password for ${EMAIL}: " PASSWORD
echo

cd "$(dirname "$0")/../backend"
source .venv/bin/activate
set -a && source ../.env && set +a

JAR="$(mktemp)"
uvicorn app.main:app --port 8010 >/tmp/epicwing-smoke.log 2>&1 &
PID=$!
trap 'kill "$PID" 2>/dev/null || true; rm -f "$JAR"' EXIT
sleep 3

code() { curl -s -o /dev/null -w "%{http_code}" "$@"; }
payload() {
  EMAIL="$EMAIL" PW="$1" python3 -c \
    'import json,os; print(json.dumps({"email": os.environ["EMAIL"], "password": os.environ["PW"]}))'
}
JSON='Content-Type: application/json'

echo "1) /me without login   (expect 401): $(code "$BASE/me")"
echo "2) wrong password  (expect 401): $(code -X POST "$BASE/login" -H "$JSON" -d "$(payload 'wrong-wrong-wrong')")"

RESPONSE="$(curl -s -c "$JAR" -X POST "$BASE/login" -H "$JSON" -d "$(payload "$PASSWORD")")"
CSRF="$(printf '%s' "$RESPONSE" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("csrf_token", ""))')"
if [ -z "$CSRF" ]; then
  echo "3) Login failed: $RESPONSE"
  exit 1
fi
echo "3) Login              (expect 200): ok"
echo "4) /me with cookie    (expect 200): $(code -b "$JAR" "$BASE/me")"
echo "5) Logout without CSRF (expect 403): $(code -b "$JAR" -X POST "$BASE/logout")"
echo "6) Logout with CSRF    (expect 204): $(code -b "$JAR" -X POST "$BASE/logout" -H "X-CSRF-Token: $CSRF")"
echo "7) /me after logout   (expect 401): $(code -b "$JAR" "$BASE/me")"

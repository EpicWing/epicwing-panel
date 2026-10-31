#!/usr/bin/env bash
# Starts and stops backend (8010) and frontend (5183) for development.
# Usage: bash scripts/dev.sh start|stop|restart|status
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN="$ROOT/.dev"
mkdir -p "$RUN"

listener_pid() {
  ss -ltnp "sport = :$1" | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2 || true
}

# Stops the process on the port, but only if it belongs to this project.
stop_port() {
  local port="$1" pid parent cwd pcwd pcomm
  pid="$(listener_pid "$port")"
  [ -n "$pid" ] || return 0
  cwd="$(readlink "/proc/$pid/cwd" || true)"
  case "$cwd" in
    "$ROOT"/*) ;;
    *) echo "!! Port $port does not belong to EpicWing ($cwd), nothing stopped."; return 1 ;;
  esac
  parent="$(ps -o ppid= -p "$pid" | tr -d ' ')"
  pcwd="$(readlink "/proc/$parent/cwd" || true)"
  pcomm="$(ps -o comm= -p "$parent" || true)"
  case "$pcomm" in
    bash|zsh|fish|sshd) ;;
    *) case "$pcwd" in "$ROOT"/*) kill "$parent" 2>/dev/null || true ;; esac ;;
  esac
  kill "$pid" 2>/dev/null || true
  sleep 1
  echo "Port $port stopped."
}

wait_for() {
  local url="$1"
  for _ in $(seq 1 25); do
    curl -fsS "$url" >/dev/null 2>&1 && return 0
    sleep 1
  done
  return 1
}

start() {
  [ -z "$(listener_pid 8010)" ] || { echo "!! Port 8010 is in use, run 'stop' or 'restart' first."; return 1; }
  [ -z "$(listener_pid 5183)" ] || { echo "!! Port 5183 is in use, run 'stop' or 'restart' first."; return 1; }

  (
    cd "$ROOT/backend"
    # shellcheck disable=SC1091
    source .venv/bin/activate
    set -a
    # shellcheck disable=SC1091
    source ../.env
    set +a
    exec setsid nohup uvicorn app.main:app --reload --port 8010 \
      >"$RUN/backend.log" 2>&1 </dev/null
  ) &

  (
    cd "$ROOT/frontend"
    exec setsid nohup npm run dev >"$RUN/frontend.log" 2>&1 </dev/null
  ) &

  status
}

status() {
  wait_for http://127.0.0.1:8010/api/health \
    && echo "Backend  :8010 ok" \
    || { echo "!! Backend is not responding, see $RUN/backend.log"; return 1; }
  wait_for http://127.0.0.1:5183/api/health \
    && echo "Frontend :5183 ok (proxy to the backend works)" \
    || { echo "!! Frontend or proxy is not responding, see $RUN/frontend.log"; return 1; }
}

case "${1:-}" in
  start) start ;;
  stop) stop_port 8010; stop_port 5183 ;;
  restart) stop_port 8010; stop_port 5183; start ;;
  status) status ;;
  *) echo "Usage: bash scripts/dev.sh start|stop|restart|status"; exit 1 ;;
esac

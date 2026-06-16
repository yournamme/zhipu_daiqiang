#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

APP_HOST="127.0.0.1"
APP_PORT="8787"
FALLBACK_PROXY_URL="http://127.0.0.1:17286"

read_env_value() {
  local key="$1"
  [ -f ".env" ] || return 1

  awk -v key="$key" '
    BEGIN { target = tolower(key) }
    /^[[:space:]]*(#|$)/ { next }
    {
      line = $0
      sub(/\r$/, "", line)
      eq = index(line, "=")
      if (eq == 0) next

      name = substr(line, 1, eq - 1)
      value = substr(line, eq + 1)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", name)
      if (tolower(name) != target) next

      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      if ((value ~ /^".*"$/) || (value ~ /^\047.*\047$/)) {
        value = substr(value, 2, length(value) - 2)
      }
      found = 1
      print value
      exit
    }
    END { if (!found) exit 1 }
  ' ".env"
}

if env_value="$(read_env_value APP_HOST)"; then
  APP_HOST="$env_value"
fi
if env_value="$(read_env_value APP_PORT)"; then
  APP_PORT="$env_value"
fi
if env_value="$(read_env_value FALLBACK_PROXY_URL)"; then
  FALLBACK_PROXY_URL="$env_value"
fi

run_with_timeout() {
  local timeout_seconds="$1"
  shift

  if command -v perl >/dev/null 2>&1; then
    perl -e 'alarm shift @ARGV; exec @ARGV' "$timeout_seconds" "$@"
  else
    "$@"
  fi
}

list_command_paths() {
  local command_name="$1"
  if command -v which >/dev/null 2>&1; then
    which -a "$command_name" 2>/dev/null || true
  else
    command -v "$command_name" 2>/dev/null || true
  fi
}

find_python() {
  local command_name candidate seen
  seen=""

  for command_name in python3.12 python3 python; do
    while IFS= read -r candidate; do
      [ -n "$candidate" ] || continue
      case ":$seen:" in
        *":$candidate:"*) continue ;;
      esac
      seen="${seen}:${candidate}"

      if run_with_timeout 5 "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' >/dev/null 2>&1; then
        printf '%s\n' "$candidate"
        return 0
      fi
    done < <(list_command_paths "$command_name")
  done
  return 1
}

ensure_python_version() {
  local python_bin="$1"
  run_with_timeout 5 "$python_bin" -c 'import sys; version = ".".join(map(str, sys.version_info[:3])); raise SystemExit(0 if sys.version_info >= (3, 12) else "Python 3.12+ is required; found " + version)'
}

stop_listeners_on_port() {
  local port="$1"
  local pids pid

  if ! command -v lsof >/dev/null 2>&1; then
    echo "[AegisFlow] lsof not found; skipping cleanup for port ${port}."
    return 0
  fi

  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  [ -n "$pids" ] || return 0

  for pid in $pids; do
    echo "[AegisFlow] Stopping existing process on port ${port} - PID ${pid} ..."
    kill "$pid" >/dev/null 2>&1 || true
  done

  sleep 1

  for pid in $pids; do
    if kill -0 "$pid" >/dev/null 2>&1; then
      echo "[AegisFlow] Force stopping process on port ${port} - PID ${pid} ..."
      kill -9 "$pid" >/dev/null 2>&1 || true
    fi
  done
}

PYTHON_BIN=".venv/bin/python"

stop_listeners_on_port "$APP_PORT"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "[AegisFlow] Creating virtual environment..."
  PYTHON_CMD="$(find_python)" || {
    echo "[AegisFlow] Python 3.12+ not found. Install Python 3.12+ and ensure python3 is in PATH." >&2
    exit 1
  }
  "$PYTHON_CMD" -m venv .venv
  "$PYTHON_BIN" -m pip install --upgrade pip
else
  ensure_python_version "$PYTHON_BIN"
fi

echo "[AegisFlow] Syncing Python dependencies..."
"$PYTHON_BIN" -m pip install -r requirements.txt

if [ -f "web/package.json" ]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "[AegisFlow] npm not found; skipping Vue frontend build and using legacy page fallback."
  else
    if [ ! -d "web/node_modules" ]; then
      echo "[AegisFlow] Installing Vue frontend dependencies..."
      (cd web && npm install)
    fi
    echo "[AegisFlow] Building Vue frontend..."
    (cd web && npm run build)
  fi
fi

SHOULD_START_PROXY_POOL=0
if [ -n "$FALLBACK_PROXY_URL" ]; then
  case "$FALLBACK_PROXY_URL" in
    *127.0.0.1:1728*|*localhost:1728*)
      SHOULD_START_PROXY_POOL=1
      ;;
  esac
fi

if [ "$SHOULD_START_PROXY_POOL" = "1" ]; then
  echo "[AegisFlow] FALLBACK_PROXY_URL points to localhost; FastAPI will start the built-in Python proxy pool."
  for proxy_port in 17283 17284 17285 17286; do
    stop_listeners_on_port "$proxy_port"
  done
else
  if [ -z "$FALLBACK_PROXY_URL" ]; then
    echo "[AegisFlow] FALLBACK_PROXY_URL is empty; proxy pool mode is disabled."
  else
    echo "[AegisFlow] FALLBACK_PROXY_URL=${FALLBACK_PROXY_URL} is external; FastAPI will not start a local proxy pool."
  fi
fi

echo "[AegisFlow] Starting FastAPI server..."
"$PYTHON_BIN" -m uvicorn app.main:app --host "$APP_HOST" --port "$APP_PORT" --reload

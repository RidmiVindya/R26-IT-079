#!/usr/bin/env bash
#
# Starts all Smart Karawala backend microservices.
#
# Start order and ports:
#   1. AuthService                        -> 8000
#   2. SmartDryingEnvironmentMonitoring   -> 8002
#   3. TimeAndSpoilagePredictionService   -> 8003
#   4. ai-waste-prediction-service        -> 8001
#
# Usage:
#   ./start-services.sh            # start everything with --reload (dev default)
#   ./start-services.sh --no-reload  # start without auto-reload
#   ./start-services.sh --stop     # stop anything this script started
#
# You do NOT need to `deactivate` an active venv first: each service is run via
# its own .venv interpreter by absolute path, so nothing is shadowed.
#
# Ctrl+C stops all services.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$ROOT/Backend/src"
LOG_DIR="$ROOT/logs"
PID_FILE="$LOG_DIR/services.pids"

# How long to wait for a service to answer on its port before giving up.
STARTUP_TIMEOUT_SECONDS=90

# Auto-reload on code changes (matches the usual manual `--reload` workflow).
# Disable with --no-reload.
RELOAD=1

mkdir -p "$LOG_DIR"

# --- helpers ---------------------------------------------------------------

# Pick the interpreter for a service: its own .venv if present, else the repo
# root .venv, else whatever `python` is on PATH.
pick_python() {
  local svc_dir="$1"
  if [ -x "$svc_dir/.venv/Scripts/python.exe" ]; then
    echo "$svc_dir/.venv/Scripts/python.exe"
  elif [ -x "$svc_dir/.venv/bin/python" ]; then
    echo "$svc_dir/.venv/bin/python"
  elif [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
    echo "$ROOT/.venv/Scripts/python.exe"
  elif [ -x "$ROOT/.venv/bin/python" ]; then
    echo "$ROOT/.venv/bin/python"
  else
    command -v python
  fi
}

port_is_open() {
  local port="$1"
  # Prefer curl (present in Git Bash); fall back to bash's /dev/tcp.
  if command -v curl >/dev/null 2>&1; then
    curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$port/" && return 0
    # A 4xx/5xx still means something is listening.
    [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "http://127.0.0.1:$port/")" != "000" ]
  else
    (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null
  fi
}

wait_for_port() {
  local name="$1" port="$2" pid="$3" log="$4"
  local waited=0
  while [ "$waited" -lt "$STARTUP_TIMEOUT_SECONDS" ]; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "  ! $name died during startup. Last lines of $log:"
      tail -n 20 "$log" | sed 's/^/      /'
      return 1
    fi
    if port_is_open "$port"; then
      echo "  > $name is up on port $port (pid $pid)"
      return 0
    fi
    sleep 1
    waited=$((waited + 1))
  done
  echo "  ! $name did not answer on port $port within ${STARTUP_TIMEOUT_SECONDS}s."
  echo "    It may still be starting - check $log"
  return 1
}

# start_service <name> <dir> <port> [extra uvicorn args...]
start_service() {
  local name="$1" dir="$2" port="$3"
  shift 3

  local svc_dir="$SRC/$dir"
  if [ ! -d "$svc_dir" ]; then
    echo "  ! Skipping $name - directory not found: $svc_dir"
    return 1
  fi

  local py log reload_flag=()
  py="$(pick_python "$svc_dir")"
  log="$LOG_DIR/$name.log"
  [ "$RELOAD" -eq 1 ] && reload_flag=(--reload)

  echo "Starting $name on port $port..."
  (
    cd "$svc_dir" || exit 1
    # --port on the command line wins over any PORT in .env, so the ports
    # above are what actually take effect.
    exec "$py" -m uvicorn app.main:app \
      --host 0.0.0.0 --port "$port" "${reload_flag[@]}" "$@"
  ) >"$log" 2>&1 &

  local pid=$!
  echo "$pid" >>"$PID_FILE"
  wait_for_port "$name" "$port" "$pid" "$log"
}

# With --reload uvicorn forks a worker child, so kill the whole tree rather
# than just the pid we recorded (otherwise the worker keeps holding the port).
kill_tree() {
  local pid="$1"
  # Windows/Git Bash: taskkill reliably takes down the child processes too.
  if command -v taskkill >/dev/null 2>&1; then
    taskkill //PID "$pid" //T //F >/dev/null 2>&1 && return 0
  fi
  pkill -P "$pid" 2>/dev/null
  kill "$pid" 2>/dev/null
}

stop_services() {
  if [ ! -f "$PID_FILE" ]; then
    echo "No PID file at $PID_FILE - nothing recorded to stop."
    return 0
  fi
  echo "Stopping services..."
  while read -r pid; do
    [ -z "$pid" ] && continue
    if kill -0 "$pid" 2>/dev/null; then
      kill_tree "$pid" && echo "  stopped pid $pid"
    fi
  done <"$PID_FILE"
  rm -f "$PID_FILE"
  echo "Done."
}

# --- main ------------------------------------------------------------------

case "${1:-}" in
  --stop)
    stop_services
    exit 0
    ;;
  --no-reload)
    RELOAD=0
    ;;
esac

# Reloaders spawn children, so kill the whole process group on exit.
cleanup() {
  echo
  echo "Shutting down..."
  if [ -f "$PID_FILE" ]; then
    while read -r pid; do
      [ -z "$pid" ] && continue
      kill_tree "$pid"
    done <"$PID_FILE"
    rm -f "$PID_FILE"
  fi
  exit 0
}
trap cleanup INT TERM

: >"$PID_FILE"

echo "Smart Karawala - starting backend services"
echo "Logs: $LOG_DIR"
echo

failed=0

start_service "auth"          "AuthService"                      8000 || failed=1
start_service "iot-monitor"   "SmartDryingEnvironmentMonitoring" 8002 || failed=1
start_service "time-spoilage" "TimeAndSpoilagePredictionService" 8003 || failed=1
start_service "waste"         "ai-waste-prediction-service"      8001 || failed=1

echo
if [ "$failed" -eq 0 ]; then
  echo "All services are up:"
else
  echo "Some services did not start cleanly (see notes above). Current mapping:"
fi
cat <<'EOF'
  AuthService                        http://localhost:8000
  ai-waste-prediction-service        http://localhost:8001
  SmartDryingEnvironmentMonitoring   http://localhost:8002
  TimeAndSpoilagePredictionService   http://localhost:8003
EOF
echo
echo "Press Ctrl+C to stop all services (or run: ./start-services.sh --stop)"

# Keep the script in the foreground so Ctrl+C reaches the trap.
wait

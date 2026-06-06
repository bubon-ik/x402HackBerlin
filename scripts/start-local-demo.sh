#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${SIGN402_LOG_DIR:-$ROOT_DIR/.demo-logs}"

RESOURCE_PORT="${X402_DEMO_PORT:-8090}"
GATEWAY_PORT="${SIGN402_GATEWAY_PORT:-8099}"
DASHBOARD_PORT="${SIGN402_DASHBOARD_PORT:-8100}"

MERCHANT_RECEIVER="${X402_MERCHANT_RECEIVER:-ERUMW536MUKV7T2JHM35HUQADFIW4SLELUPBNVR4CBJH34WRD7XMHADD6A}"
PYTHON_BIN="${PYTHON:-python3}"
PAYMENT_PYTHON="${SIGN402_PAYMENT_PYTHON:-$PYTHON_BIN}"

pids=()

cleanup() {
  if [ "${#pids[@]}" -gt 0 ]; then
    kill "${pids[@]}" >/dev/null 2>&1 || true
    wait "${pids[@]}" >/dev/null 2>&1 || true
  fi
}

die() {
  echo "error: $*" >&2
  exit 1
}

detect_firefly_port() {
  if [ "${FIREFLY_PORT:-}" != "" ]; then
    echo "$FIREFLY_PORT"
    return
  fi

  local ports=()
  for port in /dev/cu.usbmodem*; do
    [ -e "$port" ] && ports+=("$port")
  done

  if [ "${#ports[@]}" -eq 0 ]; then
    die "Firefly serial port not found. Connect Firefly and check: ls /dev/cu.usb*"
  fi

  if [ "${#ports[@]}" -gt 1 ]; then
    echo "Multiple Firefly-like ports found:" >&2
    printf '  %s\n' "${ports[@]}" >&2
    die "Set FIREFLY_PORT=/dev/cu.usbmodemXXXX and run again."
  fi

  echo "${ports[0]}"
}

check_port_available() {
  local port="$1"
  local name="$2"

  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Address already in use: $name needs port $port." >&2
    echo "Stop the old terminal/process using port $port, then run this script again." >&2
    echo >&2
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >&2 || true
    exit 1
  fi
}

start_service() {
  local name="$1"
  local dir="$2"
  shift 2

  echo "starting $name ..."
  (
    cd "$dir"
    "$@"
  ) >"$LOG_DIR/$name.log" 2>&1 &

  pids+=("$!")
}

wait_for_health() {
  local name="$1"
  local url="$2"

  for _ in $(seq 1 40); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "$name ready: $url"
      return
    fi
    sleep 0.25
  done

  echo "$name did not become ready. Last log lines:" >&2
  tail -40 "$LOG_DIR/$name.log" >&2 || true
  exit 1
}

main() {
  mkdir -p "$LOG_DIR"
  trap cleanup EXIT INT TERM

  local firefly_port
  firefly_port="$(detect_firefly_port)"

  command -v "$PAYMENT_PYTHON" >/dev/null 2>&1 || [ -x "$PAYMENT_PYTHON" ] || die "Payment executor Python not found: $PAYMENT_PYTHON"

  check_port_available "$RESOURCE_PORT" "resource server"
  check_port_available "$GATEWAY_PORT" "Sign402 Gateway"
  check_port_available "$DASHBOARD_PORT" "dashboard"

  echo "Hermes Sign402 local demo"
  echo "Firefly port: $firefly_port"
  echo "Logs: $LOG_DIR"
  echo

  start_service \
    resource \
    "$ROOT_DIR/demo-resource-server" \
    env X402_MERCHANT_RECEIVER="$MERCHANT_RECEIVER" X402_DEMO_PORT="$RESOURCE_PORT" \
    "$PYTHON_BIN" -m x402_demo

  start_service \
    gateway \
    "$ROOT_DIR/sign402-gateway" \
    env FIREFLY_PORT="$firefly_port" SIGN402_GATEWAY_PORT="$GATEWAY_PORT" \
    "$PAYMENT_PYTHON" -m sign402_gateway

  start_service \
    dashboard \
    "$ROOT_DIR/demo-dashboard" \
    "$PYTHON_BIN" -m http.server "$DASHBOARD_PORT" --bind 127.0.0.1

  wait_for_health "resource" "http://127.0.0.1:$RESOURCE_PORT/health"
  wait_for_health "gateway" "http://127.0.0.1:$GATEWAY_PORT/health"
  wait_for_health "dashboard" "http://127.0.0.1:$DASHBOARD_PORT/"

  cat <<EOF

Local demo is running.

Resource server:
  http://127.0.0.1:$RESOURCE_PORT

Sign402 Gateway:
  http://127.0.0.1:$GATEWAY_PORT

Dashboard:
  http://127.0.0.1:$DASHBOARD_PORT

For Hermes on the server, open one extra terminal and run:

  cloudflared tunnel --url http://127.0.0.1:$GATEWAY_PORT

Then give Hermes the gateway trycloudflare URL.

The resource server stays local. The gateway calls it directly.

Optional low-level protocol tunnel:

  cloudflared tunnel --url http://127.0.0.1:$RESOURCE_PORT

Press Ctrl+C here to stop local services.
EOF

  wait
}

main "$@"

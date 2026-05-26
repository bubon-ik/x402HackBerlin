#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
START_SCRIPT="$ROOT_DIR/scripts/start-local-demo.sh"

test -x "$START_SCRIPT"
bash -n "$START_SCRIPT"

grep -q "demo-resource-server" "$START_SCRIPT"
grep -q "sign402-gateway" "$START_SCRIPT"
grep -q "demo-dashboard" "$START_SCRIPT"
grep -q "8090" "$START_SCRIPT"
grep -q "8099" "$START_SCRIPT"
grep -q "8100" "$START_SCRIPT"
grep -q "check_port_available" "$START_SCRIPT"
grep -q "Address already in use" "$START_SCRIPT"

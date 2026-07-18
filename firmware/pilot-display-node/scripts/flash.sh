#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IDF_PATH="${IDF_PATH:-$HOME/esp/esp-idf-v5.5.3}"
PORT="${1:-/dev/cu.usbmodem2101}"

if [[ ! -f "$IDF_PATH/export.sh" ]]; then
  echo "ESP-IDF 5.5.3 was not found at $IDF_PATH" >&2
  exit 1
fi

if [[ ! -d "$ROOT/build" ]]; then
  echo "Build the firmware before flashing it." >&2
  exit 1
fi

source "$IDF_PATH/export.sh" >/dev/null
cd "$ROOT"
idf.py -p "$PORT" flash

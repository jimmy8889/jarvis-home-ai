#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IDF_PATH="${IDF_PATH:-$HOME/esp/esp-idf-v5.5.3}"

if [[ ! -f "$IDF_PATH/export.sh" ]]; then
  echo "ESP-IDF 5.5.3 was not found at $IDF_PATH" >&2
  exit 1
fi

if [[ -z "${PILOT_WIFI_SSID:-}" || -z "${PILOT_WIFI_PASSWORD:-}" ]]; then
  echo "Set PILOT_WIFI_SSID and PILOT_WIFI_PASSWORD before building." >&2
  exit 1
fi

source "$IDF_PATH/export.sh" >/dev/null
cd "$ROOT"

idf.py build

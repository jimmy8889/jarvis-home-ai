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

core_values=0
[[ -n "${PILOT_CORE_URL:-}" ]] && ((core_values+=1))
[[ -n "${PILOT_DEVICE_ID:-}" ]] && ((core_values+=1))
[[ -n "${PILOT_DEVICE_TOKEN:-}" ]] && ((core_values+=1))
if [[ "$core_values" -ne 0 && "$core_values" -ne 3 ]]; then
  echo "Set PILOT_CORE_URL, PILOT_DEVICE_ID, and PILOT_DEVICE_TOKEN together." >&2
  exit 1
fi

source "$IDF_PATH/export.sh" >/dev/null
cd "$ROOT"

desired_version="$(
  sed -n 's/^CONFIG_APP_PROJECT_VER="\(.*\)"/\1/p' \
    sdkconfig.defaults | head -n 1
)"
configured_version=""
if [[ -f sdkconfig ]]; then
  configured_version="$(
    sed -n 's/^CONFIG_APP_PROJECT_VER="\(.*\)"/\1/p' \
      sdkconfig | head -n 1
  )"
fi
if [[ -n "$configured_version" && "$configured_version" != "$desired_version" ]]; then
  echo "Refreshing generated sdkconfig for firmware ${desired_version}."
  rm -f sdkconfig sdkconfig.old
fi

idf.py build

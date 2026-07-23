#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="esp32-c6-touch-amoled-2.16"
SOURCE="${ROOT}/build/pilot_display_node.bin"
OUTPUT_ROOT="${1:-${ROOT}/.artifacts/ota}"
VERSION="${2:-}"
MANDATORY="${PILOT_OTA_MANDATORY:-false}"

if [[ ! -f "$SOURCE" ]]; then
  echo "Build the firmware before packaging an OTA release." >&2
  exit 1
fi
if [[ -z "$VERSION" ]]; then
  VERSION="$(
    sed -n 's/^CONFIG_APP_PROJECT_VER="\(.*\)"/\1/p' \
      "${ROOT}/sdkconfig.defaults" | head -n 1
  )"
fi
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([+-][a-zA-Z0-9.-]+)?$ ]]; then
  echo "Firmware version is invalid: ${VERSION}" >&2
  exit 2
fi
if [[ "$MANDATORY" != "true" && "$MANDATORY" != "false" ]]; then
  echo "PILOT_OTA_MANDATORY must be true or false." >&2
  exit 2
fi

DESTINATION="${OUTPUT_ROOT%/}/${TARGET}"
FILENAME="pilot-display-${VERSION}.bin"
IMAGE="${DESTINATION}/${FILENAME}"
mkdir -p "$DESTINATION"

if [[ -f "$IMAGE" ]] && ! cmp -s "$SOURCE" "$IMAGE"; then
  echo "Refusing to replace an immutable release image: ${IMAGE}" >&2
  exit 1
fi
if [[ ! -f "$IMAGE" ]]; then
  install -m 0644 "$SOURCE" "$IMAGE"
fi

if command -v sha256sum >/dev/null 2>&1; then
  SHA256="$(sha256sum "$IMAGE" | awk '{print $1}')"
else
  SHA256="$(shasum -a 256 "$IMAGE" | awk '{print $1}')"
fi
SIZE_BYTES="$(wc -c < "$IMAGE" | tr -d '[:space:]')"
MANIFEST_TMP="${DESTINATION}/.latest.json.tmp"

printf '{\n' > "$MANIFEST_TMP"
printf '  "target": "%s",\n' "$TARGET" >> "$MANIFEST_TMP"
printf '  "version": "%s",\n' "$VERSION" >> "$MANIFEST_TMP"
printf '  "filename": "%s",\n' "$FILENAME" >> "$MANIFEST_TMP"
printf '  "sha256": "%s",\n' "$SHA256" >> "$MANIFEST_TMP"
printf '  "size_bytes": %s,\n' "$SIZE_BYTES" >> "$MANIFEST_TMP"
printf '  "mandatory": %s\n' "$MANDATORY" >> "$MANIFEST_TMP"
printf '}\n' >> "$MANIFEST_TMP"
mv "$MANIFEST_TMP" "${DESTINATION}/latest.json"

printf 'Packaged %s (%s bytes, sha256 %s)\n' \
  "${DESTINATION}/latest.json" "$SIZE_BYTES" "$SHA256"

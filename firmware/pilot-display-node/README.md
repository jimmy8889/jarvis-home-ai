# Pilot Display Node

Firmware for the Waveshare `ESP32-C6-Touch-AMOLED-2.16` room node.

Version 0.2 turns the clock into the first bedroom Pilot node:

- 480 x 480 clock and touch-scrollable daily weather pages;
- a 20-second two-percent dim state and a fully dark display after 30 seconds;
- motion, touch, or the physical action button wakes the display;
- a touch and physical push-to-talk control;
- a full-screen, multicolour listening/processing/speaking animation;
- bounded 16 kHz microphone streaming to the authenticated Pilot Core voice API;
- local Home Assistant Assist processing and Piper WAV response playback;
- authenticated, checksum-verified dual-slot OTA with boot rollback;
- NTP synchronization, onboard RTC fallback, and offline clock operation.

The display is turned off while the ESP32 remains awake enough to poll the IMU
and preserve network service. QMI8658 motion is sampled approximately every
80 ms, so a moved bedside device wakes without waiting for a network round
trip. The microphone is opened only after push-to-talk is activated.

## Supported hardware

- ESP32-C6, revision 0.2
- 16 MB flash
- CO5300-compatible 480 x 480 QSPI AMOLED
- AXP2101 power management
- PCF85063 RTC
- CST9217-compatible touch controller
- QMI8658 six-axis IMU
- ES7210 microphone ADC and two onboard microphones
- ES8311 output codec and board speaker output
- GPIO 9 physical action/boot button

The board support layer is based on Waveshare's official
`ESP32-C6-Touch-AMOLED-2.16` repository at commit
`294543798f1a44e2f2c4d2976522323f2beee11d`.

## Toolchain

- ESP-IDF `v5.5.3`
- Python 3.12
- IDF Component Manager dependencies pinned by `main/idf_component.yml` and
  `dependencies.lock`

Install the ESP32-C6 toolchain:

```bash
mkdir -p ~/esp
git clone --recursive --depth 1 --shallow-submodules \
  --branch v5.5.3 \
  https://github.com/espressif/esp-idf.git \
  ~/esp/esp-idf-v5.5.3

cd ~/esp/esp-idf-v5.5.3
PYTHON=/opt/homebrew/bin/python3.12 ./install.sh esp32c6
```

## Build

Credentials are read from the build process environment and remain only in the
firmware binary and ignored local build outputs. They are not written to source,
the generated `sdkconfig`, or the dependency lock. Never add credentials to
source files.

```bash
export PILOT_WIFI_SSID='your-ssid'
export PILOT_WIFI_PASSWORD='your-password'
export PILOT_CORE_URL='http://pilot-core-host:8770'
export PILOT_DEVICE_ID='pilot-bedroom-display'
export PILOT_DEVICE_TOKEN='device-specific-token'
export PILOT_ROOM_NAME='BEDROOM'
./scripts/build.sh
```

`PILOT_CORE_URL`, `PILOT_DEVICE_ID`, and `PILOT_DEVICE_TOKEN` must either all
be present or all be omitted. A build without them remains a local clock, but
weather, voice, reply audio, and OTA are disabled.

## Flash

```bash
./scripts/flash.sh /dev/cu.usbmodem2101
```

Monitor the USB console:

```bash
source ~/esp/esp-idf-v5.5.3/export.sh
idf.py -p /dev/cu.usbmodem2101 monitor
```

Expected diagnostics include:

```text
Pilot display node 0.2.1 starting
Wi-Fi connected
NTP synchronised using time.cloudflare.com
ES7210 microphone and ES8311 speaker codec initialized
Pilot Core features configured
```

## Interaction

- Swipe left from the clock to see today's weather; swipe right to return.
- Tap `TALK TO PILOT` or press GPIO 9 to start listening.
- Tap the listening overlay or press GPIO 9 again to stop early.
- Normal speech end is detected after approximately 1.1 seconds of silence.
- The screen stays awake throughout listening, processing, and response
  playback.
- Touch, button activity, or detectable movement restores normal brightness.

The response path is deliberately local:

```text
onboard microphone
  -> authenticated Pilot Core stream
  -> Home Assistant local Assist pipeline
  -> Piper WAV synthesis
  -> authenticated temporary audio asset
  -> ES8311 output
```

Pilot Core owns Home Assistant credentials. The display stores only its
revocable per-device token.

## OTA releases

Build and package an immutable release:

```bash
./scripts/build.sh
./scripts/package-release.sh
```

The package contains a versioned application image plus `latest.json` with the
target, version, byte length, SHA-256 digest, and mandatory flag. Publish its
target directory from the Pilot Core host:

```bash
deploy/scripts/pilot-firmware-publish \
  --release-dir firmware/pilot-display-node/.artifacts/ota/esp32-c6-touch-amoled-2.16
```

The node checks every six hours while the assistant is idle and the screen is
not fully awake. It downloads only with device authentication, checks declared
size and SHA-256 while writing the inactive OTA slot, and then reboots. The new
image remains pending until it has run for 20 seconds; repeated boot failure
returns to the previous slot.

The validation baseline for version 0.2 is:

- clean ESP-IDF 5.5.3 compilation with the pinned dependency lock;
- application image fits one 4 MB OTA slot;
- all Pilot Core server tests pass;
- Home Assistant exposes a local STT Assist pipeline and Piper WAV output;
- streaming WAV headers with unknown RIFF/data sizes are bounded to the actual
  downloaded payload before playback;
- physical display, touch, IMU, microphones, speaker, and OTA rollback still
  require a connected-board acceptance run for each hardware revision.

If Wi-Fi initialization or association fails, the firmware deliberately keeps
the display running from the RTC instead of rebooting.

## Rollback

Before the first Pilot firmware flash, preserve the complete 16 MB factory
image:

```bash
esptool --port /dev/cu.usbmodem2101 \
  read-flash 0 0x1000000 factory-backup.bin
```

To restore it:

```bash
esptool --port /dev/cu.usbmodem2101 erase-flash
esptool --port /dev/cu.usbmodem2101 \
  --flash-size 16MB \
  write-flash 0 factory-backup.bin
```

Factory images and build outputs are local artifacts and must not be committed.

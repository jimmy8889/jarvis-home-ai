# Pilot Display Node

Firmware for the Waveshare `ESP32-C6-Touch-AMOLED-2.16` room node.

Version 0.1 provides:

- a burn-in-conscious 480 x 480 AMOLED clock interface;
- connection to a configured 2.4 GHz Wi-Fi network;
- NTP synchronization in the `Australia/Brisbane` timezone;
- onboard PCF85063 RTC fallback and refresh after successful NTP sync;
- a native USB Serial/JTAG diagnostic console;
- OTA-ready flash partitions for later Pilot node updates.

The first target is intentionally narrow. Touch, Pilot Core events, Home Assistant
state, microphones, and speaker output are reserved for later firmware versions.

## Supported hardware

- ESP32-C6, revision 0.2
- 16 MB flash
- CO5300-compatible 480 x 480 QSPI AMOLED
- AXP2101 power management
- PCF85063 RTC
- CST9217-compatible touch controller (not enabled in v0.1)

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
./scripts/build.sh
```

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
Pilot display node 0.1.0 starting
Wi-Fi connected
NTP synchronised using time.cloudflare.com
Clock YYYY-MM-DD HH:MM:SS source=NTP wifi=connected
```

The deployed validation baseline is:

- approximately 126 KB free internal RAM immediately before Wi-Fi startup;
- DHCP association and NTP synchronization after cold boot;
- RTC restoration before the network becomes available;
- RTC refresh after successful NTP synchronization;
- continued NTP/connected minute heartbeats after a controlled reset.

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

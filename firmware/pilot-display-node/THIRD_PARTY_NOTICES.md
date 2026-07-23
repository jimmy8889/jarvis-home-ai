# Third-party notices

The hardware support files under `components/` are derived from Waveshare's
official `ESP32-C6-Touch-AMOLED-2.16` examples at commit
`294543798f1a44e2f2c4d2976522323f2beee11d`.

Source:

https://github.com/waveshareteam/ESP32-C6-Touch-AMOLED-2.16

The bundled `XPowersLib` sources retain their MIT license notices. Display,
touch, LVGL, and ESP-IDF dependencies are resolved through Espressif's Component
Manager and retain the licenses distributed with their respective components.

Version 0.2 additionally uses:

- `espressif/esp_codec_dev` 1.4 under Apache-2.0 for the ES7210/ES8311 audio
  codecs;
- `waveshare/qmi8658` 1.0.1 under Apache-2.0 for motion sensing.

The board-specific audio pinout and codec selection were checked against
Waveshare's official ESP-IDF Audio Test and XiaoZhi board definitions from the
same source repository.

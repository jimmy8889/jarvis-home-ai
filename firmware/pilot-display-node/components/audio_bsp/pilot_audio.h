#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "driver/i2c_master.h"
#include "driver/i2s_std.h"
#include "esp_codec_dev.h"
#include "esp_codec_dev_defaults.h"
#include "esp_err.h"

class PilotAudio {
public:
    explicit PilotAudio(i2c_master_bus_handle_t i2c_bus);
    ~PilotAudio();

    esp_err_t Initialize();
    esp_err_t StartCapture(int sample_rate = 16000, float gain_db = 30.0f);
    int Read(int16_t *samples, std::size_t sample_count);
    void StopCapture();

    esp_err_t StartPlayback(int sample_rate, int volume = 65);
    int Write(const int16_t *samples, std::size_t sample_count);
    void StopPlayback();

    bool Available() const { return available_; }
    bool Capturing() const { return capturing_; }
    bool Playing() const { return playing_; }

private:
    void Destroy();

    i2c_master_bus_handle_t i2c_bus_ = nullptr;
    i2s_chan_handle_t tx_handle_ = nullptr;
    i2s_chan_handle_t rx_handle_ = nullptr;
    const audio_codec_data_if_t *data_if_ = nullptr;
    const audio_codec_ctrl_if_t *output_control_ = nullptr;
    const audio_codec_if_t *output_codec_ = nullptr;
    const audio_codec_ctrl_if_t *input_control_ = nullptr;
    const audio_codec_if_t *input_codec_ = nullptr;
    const audio_codec_gpio_if_t *gpio_ = nullptr;
    esp_codec_dev_handle_t output_ = nullptr;
    esp_codec_dev_handle_t input_ = nullptr;
    bool available_ = false;
    bool capturing_ = false;
    bool playing_ = false;
};

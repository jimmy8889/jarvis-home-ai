#include "pilot_audio.h"

#include "driver/gpio.h"
#include "driver/i2s_std.h"
#include "driver/i2s_tdm.h"
#include "esp_codec_dev_defaults.h"
#include "esp_log.h"

namespace {
constexpr char kTag[] = "pilot_audio";
constexpr gpio_num_t kMclk = GPIO_NUM_19;
constexpr gpio_num_t kBclk = GPIO_NUM_20;
constexpr gpio_num_t kWordSelect = GPIO_NUM_22;
constexpr gpio_num_t kDataIn = GPIO_NUM_21;
constexpr gpio_num_t kDataOut = GPIO_NUM_23;
constexpr int kDefaultSampleRate = 16000;
}

PilotAudio::PilotAudio(i2c_master_bus_handle_t i2c_bus) : i2c_bus_(i2c_bus) {
}

PilotAudio::~PilotAudio() {
    Destroy();
}

esp_err_t PilotAudio::Initialize() {
    if (available_) {
        return ESP_OK;
    }

    i2s_chan_config_t channel_config = I2S_CHANNEL_DEFAULT_CONFIG(
        I2S_NUM_0, I2S_ROLE_MASTER
    );
    channel_config.dma_desc_num = 4;
    channel_config.dma_frame_num = 160;
    channel_config.auto_clear = true;
    esp_err_t result = i2s_new_channel(
        &channel_config, &tx_handle_, &rx_handle_
    );
    if (result != ESP_OK) {
        ESP_LOGE(kTag, "Unable to create I2S channels: %s", esp_err_to_name(result));
        return result;
    }

    i2s_std_config_t output_config = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(kDefaultSampleRate),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(
            I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO
        ),
        .gpio_cfg = {
            .mclk = kMclk,
            .bclk = kBclk,
            .ws = kWordSelect,
            .dout = kDataOut,
            .din = I2S_GPIO_UNUSED,
            .invert_flags = {
                .mclk_inv = false,
                .bclk_inv = false,
                .ws_inv = false,
            },
        },
    };
    output_config.clk_cfg.mclk_multiple = I2S_MCLK_MULTIPLE_256;
    result = i2s_channel_init_std_mode(tx_handle_, &output_config);
    if (result != ESP_OK) {
        ESP_LOGE(kTag, "Unable to configure audio output: %s", esp_err_to_name(result));
        Destroy();
        return result;
    }

    i2s_tdm_config_t input_config = {
        .clk_cfg = I2S_TDM_CLK_DEFAULT_CONFIG(kDefaultSampleRate),
        .slot_cfg = I2S_TDM_PHILIPS_SLOT_DEFAULT_CONFIG(
            I2S_DATA_BIT_WIDTH_16BIT,
            I2S_SLOT_MODE_STEREO,
            static_cast<i2s_tdm_slot_mask_t>(
                I2S_TDM_SLOT0 | I2S_TDM_SLOT1 |
                I2S_TDM_SLOT2 | I2S_TDM_SLOT3
            )
        ),
        .gpio_cfg = {
            .mclk = kMclk,
            .bclk = kBclk,
            .ws = kWordSelect,
            .dout = I2S_GPIO_UNUSED,
            .din = kDataIn,
            .invert_flags = {
                .mclk_inv = false,
                .bclk_inv = false,
                .ws_inv = false,
            },
        },
    };
    input_config.clk_cfg.mclk_multiple = I2S_MCLK_MULTIPLE_256;
    input_config.clk_cfg.bclk_div = 8;
    input_config.slot_cfg.total_slot = I2S_TDM_AUTO_SLOT_NUM;
    result = i2s_channel_init_tdm_mode(rx_handle_, &input_config);
    if (result != ESP_OK) {
        ESP_LOGE(kTag, "Unable to configure microphone input: %s", esp_err_to_name(result));
        Destroy();
        return result;
    }
    ESP_ERROR_CHECK(i2s_channel_enable(tx_handle_));
    ESP_ERROR_CHECK(i2s_channel_enable(rx_handle_));

    audio_codec_i2s_cfg_t data_config = {
        .port = I2S_NUM_0,
        .rx_handle = rx_handle_,
        .tx_handle = tx_handle_,
    };
    data_if_ = audio_codec_new_i2s_data(&data_config);
    if (data_if_ == nullptr) {
        Destroy();
        return ESP_ERR_NO_MEM;
    }

    audio_codec_i2c_cfg_t control_config = {
        .port = I2C_NUM_0,
        .addr = ES8311_CODEC_DEFAULT_ADDR,
        .bus_handle = i2c_bus_,
    };
    output_control_ = audio_codec_new_i2c_ctrl(&control_config);
    gpio_ = audio_codec_new_gpio();
    if (output_control_ == nullptr || gpio_ == nullptr) {
        Destroy();
        return ESP_ERR_NO_MEM;
    }

    es8311_codec_cfg_t es8311_config = {};
    es8311_config.ctrl_if = output_control_;
    es8311_config.gpio_if = gpio_;
    es8311_config.codec_mode = ESP_CODEC_DEV_WORK_MODE_DAC;
    es8311_config.pa_pin = GPIO_NUM_NC;
    es8311_config.use_mclk = true;
    es8311_config.hw_gain.pa_voltage = 5.0f;
    es8311_config.hw_gain.codec_dac_voltage = 3.3f;
    output_codec_ = es8311_codec_new(&es8311_config);
    if (output_codec_ == nullptr) {
        Destroy();
        return ESP_ERR_NO_MEM;
    }
    esp_codec_dev_cfg_t output_device_config = {
        .dev_type = ESP_CODEC_DEV_TYPE_OUT,
        .codec_if = output_codec_,
        .data_if = data_if_,
    };
    output_ = esp_codec_dev_new(&output_device_config);

    control_config.addr = ES7210_CODEC_DEFAULT_ADDR;
    input_control_ = audio_codec_new_i2c_ctrl(&control_config);
    es7210_codec_cfg_t es7210_config = {};
    es7210_config.ctrl_if = input_control_;
    es7210_config.mic_selected = (
        ES7210_SEL_MIC1 | ES7210_SEL_MIC2 |
        ES7210_SEL_MIC3 | ES7210_SEL_MIC4
    );
    input_codec_ = es7210_codec_new(&es7210_config);
    if (input_control_ == nullptr || input_codec_ == nullptr) {
        Destroy();
        return ESP_ERR_NO_MEM;
    }
    esp_codec_dev_cfg_t input_device_config = {
        .dev_type = ESP_CODEC_DEV_TYPE_IN,
        .codec_if = input_codec_,
        .data_if = data_if_,
    };
    input_ = esp_codec_dev_new(&input_device_config);
    if (output_ == nullptr || input_ == nullptr) {
        Destroy();
        return ESP_ERR_NO_MEM;
    }

    available_ = true;
    ESP_LOGI(kTag, "ES7210 microphone and ES8311 speaker codec initialized");
    return ESP_OK;
}

esp_err_t PilotAudio::StartCapture(int sample_rate, float gain_db) {
    if (!available_ || input_ == nullptr) {
        return ESP_ERR_INVALID_STATE;
    }
    if (capturing_) {
        return ESP_OK;
    }
    esp_codec_dev_sample_info_t format = {
        .bits_per_sample = 16,
        .channel = 4,
        .channel_mask = ESP_CODEC_DEV_MAKE_CHANNEL_MASK(0),
        .sample_rate = static_cast<uint32_t>(sample_rate),
        .mclk_multiple = 0,
    };
    if (esp_codec_dev_open(input_, &format) != ESP_CODEC_DEV_OK) {
        return ESP_FAIL;
    }
    if (
        esp_codec_dev_set_in_channel_gain(
            input_, ESP_CODEC_DEV_MAKE_CHANNEL_MASK(0), gain_db
        ) != ESP_CODEC_DEV_OK
    ) {
        esp_codec_dev_close(input_);
        return ESP_FAIL;
    }
    capturing_ = true;
    return ESP_OK;
}

int PilotAudio::Read(int16_t *samples, std::size_t sample_count) {
    if (!capturing_ || samples == nullptr || sample_count == 0) {
        return -1;
    }
    const int result = esp_codec_dev_read(
        input_, samples, sample_count * sizeof(int16_t)
    );
    return result == ESP_CODEC_DEV_OK ? static_cast<int>(sample_count) : -1;
}

void PilotAudio::StopCapture() {
    if (capturing_ && input_ != nullptr) {
        esp_codec_dev_close(input_);
    }
    capturing_ = false;
}

esp_err_t PilotAudio::StartPlayback(int sample_rate, int volume) {
    if (!available_ || output_ == nullptr) {
        return ESP_ERR_INVALID_STATE;
    }
    if (playing_) {
        StopPlayback();
    }
    esp_codec_dev_sample_info_t format = {
        .bits_per_sample = 16,
        .channel = 1,
        .channel_mask = 0,
        .sample_rate = static_cast<uint32_t>(sample_rate),
        .mclk_multiple = 0,
    };
    if (esp_codec_dev_open(output_, &format) != ESP_CODEC_DEV_OK) {
        return ESP_FAIL;
    }
    if (esp_codec_dev_set_out_vol(output_, volume) != ESP_CODEC_DEV_OK) {
        esp_codec_dev_close(output_);
        return ESP_FAIL;
    }
    playing_ = true;
    return ESP_OK;
}

int PilotAudio::Write(const int16_t *samples, std::size_t sample_count) {
    if (!playing_ || samples == nullptr || sample_count == 0) {
        return -1;
    }
    const int result = esp_codec_dev_write(
        output_,
        const_cast<int16_t *>(samples),
        sample_count * sizeof(int16_t)
    );
    return result == ESP_CODEC_DEV_OK ? static_cast<int>(sample_count) : -1;
}

void PilotAudio::StopPlayback() {
    if (playing_ && output_ != nullptr) {
        esp_codec_dev_close(output_);
    }
    playing_ = false;
}

void PilotAudio::Destroy() {
    StopCapture();
    StopPlayback();
    available_ = false;
    if (output_ != nullptr) {
        esp_codec_dev_delete(output_);
        output_ = nullptr;
    }
    if (input_ != nullptr) {
        esp_codec_dev_delete(input_);
        input_ = nullptr;
    }
    if (input_codec_ != nullptr) {
        audio_codec_delete_codec_if(input_codec_);
        input_codec_ = nullptr;
    }
    if (input_control_ != nullptr) {
        audio_codec_delete_ctrl_if(input_control_);
        input_control_ = nullptr;
    }
    if (output_codec_ != nullptr) {
        audio_codec_delete_codec_if(output_codec_);
        output_codec_ = nullptr;
    }
    if (output_control_ != nullptr) {
        audio_codec_delete_ctrl_if(output_control_);
        output_control_ = nullptr;
    }
    if (gpio_ != nullptr) {
        audio_codec_delete_gpio_if(gpio_);
        gpio_ = nullptr;
    }
    if (data_if_ != nullptr) {
        audio_codec_delete_data_if(data_if_);
        data_if_ = nullptr;
    }
    if (tx_handle_ != nullptr) {
        i2s_channel_disable(tx_handle_);
        i2s_del_channel(tx_handle_);
        tx_handle_ = nullptr;
    }
    if (rx_handle_ != nullptr) {
        i2s_channel_disable(rx_handle_);
        i2s_del_channel(rx_handle_);
        rx_handle_ = nullptr;
    }
}

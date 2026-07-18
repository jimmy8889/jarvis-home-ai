#pragma once

#include <atomic>
#include <cstddef>
#include <cstdint>

#include "esp_err.h"
#include "esp_http_client.h"

#include "pilot_audio.h"

struct PilotWeather {
    bool available = false;
    char condition[40] = {};
    char forecast_condition[40] = {};
    char temperature_unit[8] = {};
    float temperature = 0;
    float apparent_temperature = 0;
    float high_temperature = 0;
    float low_temperature = 0;
    float humidity = 0;
    float precipitation_probability = 0;
    bool has_apparent_temperature = false;
    bool has_high_temperature = false;
    bool has_low_temperature = false;
    bool has_humidity = false;
    bool has_precipitation_probability = false;
};

struct PilotVoiceResult {
    char transcript[192] = {};
    char response_text[384] = {};
    char conversation_id[96] = {};
};

enum class PilotVoicePhase {
    listening,
    processing,
    speaking,
};

using PilotVoicePhaseCallback = void (*)(PilotVoicePhase phase, void *context);

class PilotClient {
public:
    PilotClient(
        const char *base_url,
        const char *device_id,
        const char *device_token,
        const char *firmware_target,
        const char *firmware_version
    );

    bool Configured() const;
    esp_err_t FetchSnapshot(PilotWeather *weather);
    esp_err_t RunVoiceSession(
        PilotAudio &audio,
        const std::atomic<bool> &stop_requested,
        PilotVoiceResult *result,
        PilotVoicePhaseCallback phase_callback = nullptr,
        void *phase_context = nullptr
    );
    esp_err_t CheckForUpdate(bool install);
    esp_err_t MarkRunningFirmwareValid();

private:
    struct ResponseBuffer {
        char *data;
        std::size_t capacity;
        std::size_t length;
        bool truncated;
    };

    static esp_err_t BufferEventHandler(esp_http_client_event_t *event);
    static esp_err_t FileEventHandler(esp_http_client_event_t *event);

    esp_err_t GetJson(const char *path, char *buffer, std::size_t capacity);
    esp_err_t DownloadFile(const char *path, const char *destination);
    esp_err_t PlayWavFile(PilotAudio &audio, const char *path);
    esp_err_t InstallFirmware(
        const char *download_path,
        const char *expected_sha256,
        std::size_t expected_size
    );
    void ConfigureRequest(void *client) const;
    bool BuildUrl(const char *path, char *output, std::size_t capacity) const;

    const char *base_url_;
    const char *device_id_;
    const char *device_token_;
    const char *firmware_target_;
    const char *firmware_version_;
};

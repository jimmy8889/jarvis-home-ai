#include "pilot_client.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>

#include "cJSON.h"
#include "esp_app_desc.h"
#include "esp_crt_bundle.h"
#include "esp_http_client.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_ota_ops.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "mbedtls/sha256.h"

namespace {
constexpr char kTag[] = "pilot_client";
constexpr char kVoicePathPrefix[] = "/v1/devices/";
constexpr char kVoiceLanguage[] = "en_US";
constexpr int kVoiceSampleRate = 16000;
constexpr int kVoiceChunkSamples = 320;
constexpr int64_t kVoiceMaximumUs = 10'000'000;
constexpr int64_t kNoSpeechTimeoutUs = 5'000'000;
constexpr int64_t kEndSilenceUs = 1'100'000;
constexpr float kVoiceThreshold = 350.0f;
constexpr std::size_t kOtaBufferSize = 4096;
constexpr std::size_t kSnapshotResponseBufferSize = 6144;
constexpr std::size_t kVoiceResponseBufferSize = 4096;

struct FileWriter {
    FILE *file;
    bool failed;
};

template <std::size_t Size>
void copy_json_string(cJSON *object, const char *name, char (&destination)[Size]) {
    cJSON *value = cJSON_GetObjectItemCaseSensitive(object, name);
    if (cJSON_IsString(value) && value->valuestring != nullptr) {
        std::strncpy(destination, value->valuestring, Size - 1);
        destination[Size - 1] = '\0';
    }
}

bool json_number(cJSON *object, const char *name, float *destination) {
    cJSON *value = cJSON_GetObjectItemCaseSensitive(object, name);
    if (!cJSON_IsNumber(value)) {
        return false;
    }
    *destination = static_cast<float>(value->valuedouble);
    return true;
}

bool json_integer(cJSON *object, const char *name, int *destination) {
    cJSON *value = cJSON_GetObjectItemCaseSensitive(object, name);
    if (!cJSON_IsNumber(value)) {
        return false;
    }
    *destination = value->valueint;
    return true;
}

bool parse_temperature_history(
    cJSON *parent,
    const char *name,
    PilotTemperatureHistory *destination
) {
    if (parent == nullptr || destination == nullptr) {
        return false;
    }
    cJSON *value = cJSON_GetObjectItemCaseSensitive(parent, name);
    cJSON *status = value == nullptr
        ? nullptr
        : cJSON_GetObjectItemCaseSensitive(value, "status");
    if (
        !cJSON_IsObject(value) ||
        !cJSON_IsString(status) ||
        status->valuestring == nullptr ||
        std::strcmp(status->valuestring, "ok") != 0
    ) {
        return false;
    }

    PilotTemperatureHistory parsed = {};
    if (
        !json_number(value, "current", &parsed.current) ||
        !json_number(value, "minimum", &parsed.minimum) ||
        !json_number(value, "maximum", &parsed.maximum)
    ) {
        return false;
    }
    copy_json_string(value, "temperature_unit", parsed.temperature_unit);
    json_integer(value, "period_hours", &parsed.period_hours);
    cJSON *samples = cJSON_GetObjectItemCaseSensitive(value, "samples");
    if (cJSON_IsArray(samples)) {
        const int count = std::min(
            cJSON_GetArraySize(samples),
            static_cast<int>(parsed.samples.size())
        );
        for (int index = 0; index < count; ++index) {
            cJSON *sample = cJSON_GetArrayItem(samples, index);
            if (!cJSON_IsNumber(sample)) {
                continue;
            }
            parsed.samples[parsed.sample_count++] =
                static_cast<float>(sample->valuedouble);
        }
    }
    parsed.available = true;
    *destination = parsed;
    return true;
}

struct SemanticVersion {
    uint32_t parts[3];
    const char *prerelease;
    std::size_t prerelease_length;
};

bool parse_version_number(
    const char **cursor,
    uint32_t *destination
) {
    if (cursor == nullptr || *cursor == nullptr || destination == nullptr) {
        return false;
    }
    const char *start = *cursor;
    if (*start < '0' || *start > '9') {
        return false;
    }
    if (*start == '0' && start[1] >= '0' && start[1] <= '9') {
        return false;
    }
    char *end = nullptr;
    const unsigned long value = std::strtoul(start, &end, 10);
    if (end == start || value > UINT32_MAX) {
        return false;
    }
    *destination = static_cast<uint32_t>(value);
    *cursor = end;
    return true;
}

bool valid_version_identifier(const char *start, std::size_t length) {
    if (start == nullptr || length == 0) {
        return false;
    }
    for (std::size_t index = 0; index < length; ++index) {
        const char value = start[index];
        if (
            !((value >= '0' && value <= '9') ||
              (value >= 'A' && value <= 'Z') ||
              (value >= 'a' && value <= 'z') ||
              value == '-')
        ) {
            return false;
        }
    }
    return true;
}

bool parse_semantic_version(const char *value, SemanticVersion *version) {
    if (value == nullptr || version == nullptr) {
        return false;
    }
    const char *cursor = value;
    for (std::size_t index = 0; index < 3; ++index) {
        if (!parse_version_number(&cursor, &version->parts[index])) {
            return false;
        }
        if (index < 2 && *cursor++ != '.') {
            return false;
        }
    }
    version->prerelease = nullptr;
    version->prerelease_length = 0;
    if (*cursor == '-') {
        const char *start = ++cursor;
        const char *identifier = cursor;
        while (*cursor != '\0' && *cursor != '+') {
            if (*cursor == '.') {
                if (!valid_version_identifier(
                        identifier,
                        static_cast<std::size_t>(cursor - identifier)
                    )) {
                    return false;
                }
                identifier = cursor + 1;
            }
            ++cursor;
        }
        if (!valid_version_identifier(
                identifier,
                static_cast<std::size_t>(cursor - identifier)
            )) {
            return false;
        }
        version->prerelease = start;
        version->prerelease_length =
            static_cast<std::size_t>(cursor - start);
    }
    if (*cursor == '+') {
        const char *identifier = ++cursor;
        while (*cursor != '\0') {
            if (*cursor == '.') {
                if (!valid_version_identifier(
                        identifier,
                        static_cast<std::size_t>(cursor - identifier)
                    )) {
                    return false;
                }
                identifier = cursor + 1;
            }
            ++cursor;
        }
        if (!valid_version_identifier(
                identifier,
                static_cast<std::size_t>(cursor - identifier)
            )) {
            return false;
        }
    }
    return *cursor == '\0';
}

int compare_prerelease_identifier(
    const char *left,
    std::size_t left_length,
    const char *right,
    std::size_t right_length
) {
    bool left_numeric = true;
    bool right_numeric = true;
    for (std::size_t index = 0; index < left_length; ++index) {
        left_numeric = left_numeric && left[index] >= '0' && left[index] <= '9';
    }
    for (std::size_t index = 0; index < right_length; ++index) {
        right_numeric =
            right_numeric && right[index] >= '0' && right[index] <= '9';
    }
    if (left_numeric != right_numeric) {
        return left_numeric ? -1 : 1;
    }
    if (left_numeric) {
        while (left_length > 1 && *left == '0') {
            ++left;
            --left_length;
        }
        while (right_length > 1 && *right == '0') {
            ++right;
            --right_length;
        }
        if (left_length != right_length) {
            return left_length < right_length ? -1 : 1;
        }
    }
    const std::size_t shared = std::min(left_length, right_length);
    const int compared = std::memcmp(left, right, shared);
    if (compared != 0) {
        return compared < 0 ? -1 : 1;
    }
    if (left_length == right_length) {
        return 0;
    }
    return left_length < right_length ? -1 : 1;
}

int compare_prerelease(const SemanticVersion &left, const SemanticVersion &right) {
    if (left.prerelease == nullptr || right.prerelease == nullptr) {
        if (left.prerelease == right.prerelease) {
            return 0;
        }
        return left.prerelease == nullptr ? 1 : -1;
    }
    const char *left_cursor = left.prerelease;
    const char *right_cursor = right.prerelease;
    const char *left_end = left.prerelease + left.prerelease_length;
    const char *right_end = right.prerelease + right.prerelease_length;
    while (left_cursor < left_end && right_cursor < right_end) {
        const char *left_dot = static_cast<const char *>(
            std::memchr(left_cursor, '.', left_end - left_cursor)
        );
        const char *right_dot = static_cast<const char *>(
            std::memchr(right_cursor, '.', right_end - right_cursor)
        );
        const char *left_identifier_end =
            left_dot == nullptr ? left_end : left_dot;
        const char *right_identifier_end =
            right_dot == nullptr ? right_end : right_dot;
        const int result = compare_prerelease_identifier(
            left_cursor,
            static_cast<std::size_t>(left_identifier_end - left_cursor),
            right_cursor,
            static_cast<std::size_t>(right_identifier_end - right_cursor)
        );
        if (result != 0) {
            return result;
        }
        left_cursor =
            left_dot == nullptr ? left_end : left_identifier_end + 1;
        right_cursor =
            right_dot == nullptr ? right_end : right_identifier_end + 1;
    }
    if (left_cursor == left_end && right_cursor == right_end) {
        return 0;
    }
    return left_cursor == left_end ? -1 : 1;
}

bool version_is_newer(const char *candidate, const char *current) {
    SemanticVersion candidate_version = {};
    SemanticVersion current_version = {};
    if (
        !parse_semantic_version(candidate, &candidate_version) ||
        !parse_semantic_version(current, &current_version)
    ) {
        return false;
    }
    for (std::size_t index = 0; index < 3; ++index) {
        if (candidate_version.parts[index] != current_version.parts[index]) {
            return candidate_version.parts[index] > current_version.parts[index];
        }
    }
    return compare_prerelease(candidate_version, current_version) > 0;
}

bool write_all(
    esp_http_client_handle_t client,
    const void *data,
    std::size_t length
) {
    const auto *bytes = static_cast<const char *>(data);
    std::size_t offset = 0;
    while (offset < length) {
        const int written = esp_http_client_write(
            client, bytes + offset, static_cast<int>(length - offset)
        );
        if (written <= 0) {
            return false;
        }
        offset += static_cast<std::size_t>(written);
    }
    return true;
}

bool write_chunk(
    esp_http_client_handle_t client,
    const void *data,
    std::size_t length
) {
    char header[20] = {};
    const int header_length = std::snprintf(
        header, sizeof(header), "%zx\r\n", length
    );
    return header_length > 0 &&
           write_all(client, header, static_cast<std::size_t>(header_length)) &&
           write_all(client, data, length) &&
           write_all(client, "\r\n", 2);
}

uint32_t little_u32(const uint8_t *value) {
    return static_cast<uint32_t>(value[0]) |
           (static_cast<uint32_t>(value[1]) << 8) |
           (static_cast<uint32_t>(value[2]) << 16) |
           (static_cast<uint32_t>(value[3]) << 24);
}

uint16_t little_u16(const uint8_t *value) {
    return static_cast<uint16_t>(
        static_cast<uint16_t>(value[0]) |
        (static_cast<uint16_t>(value[1]) << 8)
    );
}
}

PilotClient::PilotClient(
    const char *base_url,
    const char *device_id,
    const char *device_token,
    const char *firmware_target,
    const char *firmware_version
) :
    base_url_(base_url),
    device_id_(device_id),
    device_token_(device_token),
    firmware_target_(firmware_target),
    firmware_version_(firmware_version) {
}

bool PilotClient::Configured() const {
    return base_url_ != nullptr && base_url_[0] != '\0' &&
           device_id_ != nullptr && device_id_[0] != '\0' &&
           device_token_ != nullptr && device_token_[0] != '\0';
}

bool PilotClient::BuildUrl(
    const char *path, char *output, std::size_t capacity
) const {
    if (!Configured() || path == nullptr || output == nullptr || capacity == 0) {
        return false;
    }
    const bool base_has_slash = base_url_[std::strlen(base_url_) - 1] == '/';
    const bool path_has_slash = path[0] == '/';
    const char *separator = base_has_slash || path_has_slash ? "" : "/";
    const int result = std::snprintf(
        output, capacity, "%s%s%s", base_url_, separator, path
    );
    return result > 0 && static_cast<std::size_t>(result) < capacity;
}

void PilotClient::ConfigureRequest(void *raw_client) const {
    auto client = static_cast<esp_http_client_handle_t>(raw_client);
    char authorization[192] = {};
    std::snprintf(
        authorization, sizeof(authorization), "Bearer %s", device_token_
    );
    esp_http_client_set_header(client, "Authorization", authorization);
    esp_http_client_set_header(client, "X-Pilot-Device-Id", device_id_);
    esp_http_client_set_header(client, "Accept", "application/json");
}

esp_err_t PilotClient::BufferEventHandler(esp_http_client_event_t *event) {
    auto *response = static_cast<ResponseBuffer *>(event->user_data);
    if (
        event->event_id != HTTP_EVENT_ON_DATA ||
        response == nullptr ||
        event->data == nullptr ||
        event->data_len <= 0
    ) {
        return ESP_OK;
    }
    const std::size_t remaining = (
        response->capacity > response->length + 1
            ? response->capacity - response->length - 1
            : 0
    );
    const std::size_t copied = std::min(
        remaining, static_cast<std::size_t>(event->data_len)
    );
    if (copied > 0) {
        std::memcpy(response->data + response->length, event->data, copied);
        response->length += copied;
        response->data[response->length] = '\0';
    }
    if (copied != static_cast<std::size_t>(event->data_len)) {
        response->truncated = true;
    }
    return ESP_OK;
}

esp_err_t PilotClient::FileEventHandler(esp_http_client_event_t *event) {
    auto *writer = static_cast<FileWriter *>(event->user_data);
    if (
        event->event_id == HTTP_EVENT_ON_DATA &&
        writer != nullptr &&
        writer->file != nullptr &&
        event->data_len > 0
    ) {
        if (
            std::fwrite(
                event->data, 1, static_cast<std::size_t>(event->data_len), writer->file
            ) != static_cast<std::size_t>(event->data_len)
        ) {
            writer->failed = true;
        }
    }
    return ESP_OK;
}

esp_err_t PilotClient::GetJson(
    const char *path, char *buffer, std::size_t capacity
) {
    char url[512] = {};
    if (!BuildUrl(path, url, sizeof(url)) || buffer == nullptr || capacity < 2) {
        return ESP_ERR_INVALID_ARG;
    }
    ResponseBuffer response = {
        .data = buffer,
        .capacity = capacity,
        .length = 0,
        .truncated = false,
    };
    buffer[0] = '\0';
    esp_http_client_config_t config = {};
    config.url = url;
    config.timeout_ms = 15000;
    config.buffer_size = 2048;
    config.buffer_size_tx = 1024;
    config.event_handler = BufferEventHandler;
    config.user_data = &response;
    if (std::strncmp(url, "https://", 8) == 0) {
        config.crt_bundle_attach = esp_crt_bundle_attach;
    }
    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (client == nullptr) {
        return ESP_ERR_NO_MEM;
    }
    ConfigureRequest(client);
    const esp_err_t result = esp_http_client_perform(client);
    const int status = esp_http_client_get_status_code(client);
    esp_http_client_cleanup(client);
    if (result != ESP_OK) {
        return result;
    }
    if (status != 200) {
        ESP_LOGW(kTag, "Pilot Core GET %s returned HTTP %d", path, status);
        return ESP_FAIL;
    }
    return response.truncated ? ESP_ERR_NO_MEM : ESP_OK;
}

esp_err_t PilotClient::FetchSnapshot(PilotWeather *weather) {
    if (weather == nullptr) {
        return ESP_ERR_INVALID_ARG;
    }
    char path[256] = {};
    std::snprintf(
        path, sizeof(path), "/v1/devices/%s/snapshot", device_id_
    );
    std::unique_ptr<char, decltype(&heap_caps_free)> response(
        static_cast<char *>(
            heap_caps_calloc(
                kSnapshotResponseBufferSize,
                sizeof(char),
                MALLOC_CAP_8BIT
            )
        ),
        &heap_caps_free
    );
    if (response == nullptr) {
        weather->available = false;
        return ESP_ERR_NO_MEM;
    }
    const esp_err_t result = GetJson(
        path, response.get(), kSnapshotResponseBufferSize
    );
    if (result != ESP_OK) {
        weather->available = false;
        return result;
    }

    cJSON *root = cJSON_Parse(response.get());
    if (root == nullptr) {
        weather->available = false;
        return ESP_ERR_INVALID_RESPONSE;
    }
    PilotWeather snapshot = {};
    cJSON *value = cJSON_GetObjectItemCaseSensitive(root, "weather");
    cJSON *status = value == nullptr
        ? nullptr
        : cJSON_GetObjectItemCaseSensitive(value, "status");
    if (
        cJSON_IsObject(value) &&
        cJSON_IsString(status) &&
        status->valuestring != nullptr &&
        std::strcmp(status->valuestring, "ok") == 0
    ) {
        snapshot.available = true;
        copy_json_string(value, "condition", snapshot.condition);
        copy_json_string(
            value, "forecast_condition", snapshot.forecast_condition
        );
        copy_json_string(
            value, "temperature_unit", snapshot.temperature_unit
        );
        copy_json_string(
            value, "wind_speed_unit", snapshot.wind_speed_unit
        );
        copy_json_string(value, "wind_bearing", snapshot.wind_bearing);
        copy_json_string(
            value, "precipitation_unit", snapshot.precipitation_unit
        );
        copy_json_string(
            value, "tomorrow_condition", snapshot.tomorrow_condition
        );
        json_number(value, "temperature", &snapshot.temperature);
        snapshot.has_apparent_temperature = json_number(
            value,
            "apparent_temperature",
            &snapshot.apparent_temperature
        );
        snapshot.has_high_temperature = json_number(
            value, "high_temperature", &snapshot.high_temperature
        );
        snapshot.has_low_temperature = json_number(
            value, "low_temperature", &snapshot.low_temperature
        );
        snapshot.has_humidity = json_number(
            value, "humidity", &snapshot.humidity
        );
        snapshot.has_wind_speed = json_number(
            value, "wind_speed", &snapshot.wind_speed
        );
        snapshot.has_precipitation = json_number(
            value, "precipitation", &snapshot.precipitation
        );
        snapshot.has_precipitation_probability = json_number(
            value,
            "precipitation_probability",
            &snapshot.precipitation_probability
        );
        snapshot.has_tomorrow_high_temperature = json_number(
            value,
            "tomorrow_high_temperature",
            &snapshot.tomorrow_high_temperature
        );
        snapshot.has_tomorrow_low_temperature = json_number(
            value,
            "tomorrow_low_temperature",
            &snapshot.tomorrow_low_temperature
        );
        snapshot.has_tomorrow_precipitation_probability = json_number(
            value,
            "tomorrow_precipitation_probability",
            &snapshot.tomorrow_precipitation_probability
        );
    }

    cJSON *temperature_extremes = cJSON_GetObjectItemCaseSensitive(
        root, "temperature_extremes"
    );
    if (cJSON_IsObject(temperature_extremes)) {
        parse_temperature_history(
            temperature_extremes,
            "outside",
            &snapshot.outside_temperature
        );
        parse_temperature_history(
            temperature_extremes,
            "inside",
            &snapshot.inside_temperature
        );
    }
    cJSON_Delete(root);
    *weather = snapshot;
    if (
        !snapshot.available &&
        !snapshot.outside_temperature.available &&
        !snapshot.inside_temperature.available
    ) {
        return ESP_ERR_NOT_FOUND;
    }
    return ESP_OK;
}

esp_err_t PilotClient::RunVoiceSession(
    PilotAudio &audio,
    const std::atomic<bool> &stop_requested,
    PilotVoiceResult *result,
    PilotVoicePhaseCallback phase_callback,
    void *phase_context
) {
    if (!Configured() || !audio.Available() || result == nullptr) {
        return ESP_ERR_INVALID_STATE;
    }
    char path[256] = {};
    std::snprintf(
        path, sizeof(path), "%s%s/voice", kVoicePathPrefix, device_id_
    );
    char url[512] = {};
    if (!BuildUrl(path, url, sizeof(url))) {
        return ESP_ERR_INVALID_ARG;
    }

    std::unique_ptr<char, decltype(&heap_caps_free)> response_data(
        static_cast<char *>(
            heap_caps_calloc(
                kVoiceResponseBufferSize,
                sizeof(char),
                MALLOC_CAP_8BIT
            )
        ),
        &heap_caps_free
    );
    if (response_data == nullptr) {
        ESP_LOGE(kTag, "Unable to allocate voice response buffer");
        return ESP_ERR_NO_MEM;
    }
    ResponseBuffer response = {
        .data = response_data.get(),
        .capacity = kVoiceResponseBufferSize,
        .length = 0,
        .truncated = false,
    };
    esp_http_client_config_t config = {};
    config.url = url;
    config.method = HTTP_METHOD_POST;
    config.timeout_ms = 45000;
    config.buffer_size = 2048;
    config.buffer_size_tx = 1024;
    config.event_handler = BufferEventHandler;
    config.user_data = &response;
    if (std::strncmp(url, "https://", 8) == 0) {
        config.crt_bundle_attach = esp_crt_bundle_attach;
    }
    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (client == nullptr) {
        return ESP_ERR_NO_MEM;
    }
    ConfigureRequest(client);
    // The ES7210 path emits signed little-endian PCM. RFC 2586 audio/L16 is
    // network byte order, so use an explicit opaque media type and describe
    // the format with the bounded Pilot headers below.
    esp_http_client_set_header(client, "Content-Type", "application/octet-stream");
    esp_http_client_set_header(client, "X-Pilot-Sample-Rate", "16000");
    esp_http_client_set_header(client, "X-Pilot-Language", kVoiceLanguage);

    esp_err_t status = audio.StartCapture(kVoiceSampleRate);
    if (status != ESP_OK) {
        esp_http_client_cleanup(client);
        return status;
    }
    status = esp_http_client_open(client, -1);
    if (status != ESP_OK) {
        audio.StopCapture();
        esp_http_client_cleanup(client);
        return status;
    }
    if (phase_callback != nullptr) {
        phase_callback(PilotVoicePhase::listening, phase_context);
    }

    std::array<int16_t, kVoiceChunkSamples> samples = {};
    const int64_t started = esp_timer_get_time();
    int64_t last_voice = started;
    bool speech_seen = false;
    std::size_t bytes_sent = 0;
    while (!stop_requested.load()) {
        const int64_t now = esp_timer_get_time();
        if (now - started >= kVoiceMaximumUs) {
            break;
        }
        if (audio.Read(samples.data(), samples.size()) < 0) {
            status = ESP_FAIL;
            break;
        }
        float average = 0;
        for (int16_t sample : samples) {
            average += std::abs(static_cast<float>(sample));
        }
        average /= samples.size();
        if (average >= kVoiceThreshold) {
            speech_seen = true;
            last_voice = now;
        }
        if (
            speech_seen && now - started > 800'000 &&
            now - last_voice >= kEndSilenceUs
        ) {
            break;
        }
        if (!speech_seen && now - started >= kNoSpeechTimeoutUs) {
            break;
        }
        const std::size_t bytes = samples.size() * sizeof(int16_t);
        if (!write_chunk(client, samples.data(), bytes)) {
            status = ESP_FAIL;
            break;
        }
        bytes_sent += bytes;
    }
    audio.StopCapture();
    if (phase_callback != nullptr) {
        phase_callback(PilotVoicePhase::processing, phase_context);
    }
    if (status == ESP_OK && !write_all(client, "0\r\n\r\n", 5)) {
        status = ESP_FAIL;
    }
    if (status == ESP_OK) {
        esp_http_client_fetch_headers(client);
        const int http_status = esp_http_client_get_status_code(client);
        std::array<char, 256> read_buffer = {};
        while (true) {
            const int read = esp_http_client_read(
                client, read_buffer.data(), read_buffer.size()
            );
            if (read <= 0) {
                break;
            }
        }
        if (http_status != 200) {
            const int detail_length = static_cast<int>(
                std::min<std::size_t>(response.length, 256)
            );
            ESP_LOGW(
                kTag,
                "Voice request returned HTTP %d: %.*s",
                http_status,
                detail_length,
                response.data
            );
            status = ESP_FAIL;
        }
    }
    esp_http_client_close(client);
    esp_http_client_cleanup(client);
    if (status != ESP_OK || response.truncated || bytes_sent == 0) {
        return status == ESP_OK ? ESP_FAIL : status;
    }

    cJSON *root = cJSON_Parse(response_data.get());
    cJSON *audio_response = root == nullptr
        ? nullptr
        : cJSON_GetObjectItemCaseSensitive(root, "audio");
    char download_path[256] = {};
    if (root != nullptr) {
        copy_json_string(root, "transcript", result->transcript);
        copy_json_string(root, "response_text", result->response_text);
        copy_json_string(root, "conversation_id", result->conversation_id);
    }
    if (cJSON_IsObject(audio_response)) {
        copy_json_string(audio_response, "download_url", download_path);
    }
    cJSON_Delete(root);
    response_data.reset();
    if (download_path[0] == '\0') {
        return ESP_ERR_NOT_FOUND;
    }

    status = DownloadFile(download_path, "/spiffs/pilot-reply.wav");
    if (status == ESP_OK) {
        if (phase_callback != nullptr) {
            phase_callback(PilotVoicePhase::speaking, phase_context);
        }
        status = PlayWavFile(audio, "/spiffs/pilot-reply.wav");
    }
    std::remove("/spiffs/pilot-reply.wav");
    return status;
}

esp_err_t PilotClient::DownloadFile(
    const char *path, const char *destination
) {
    char url[512] = {};
    if (!BuildUrl(path, url, sizeof(url))) {
        return ESP_ERR_INVALID_ARG;
    }
    FILE *file = std::fopen(destination, "wb");
    if (file == nullptr) {
        return ESP_FAIL;
    }
    FileWriter writer = {.file = file, .failed = false};
    esp_http_client_config_t config = {};
    config.url = url;
    config.timeout_ms = 30000;
    config.buffer_size = 2048;
    config.event_handler = FileEventHandler;
    config.user_data = &writer;
    if (std::strncmp(url, "https://", 8) == 0) {
        config.crt_bundle_attach = esp_crt_bundle_attach;
    }
    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (client == nullptr) {
        std::fclose(file);
        return ESP_ERR_NO_MEM;
    }
    ConfigureRequest(client);
    esp_http_client_set_header(client, "Accept", "audio/wav");
    const esp_err_t result = esp_http_client_perform(client);
    const int status = esp_http_client_get_status_code(client);
    esp_http_client_cleanup(client);
    std::fclose(file);
    if (result != ESP_OK || status != 200 || writer.failed) {
        std::remove(destination);
        return result == ESP_OK ? ESP_FAIL : result;
    }
    return ESP_OK;
}

esp_err_t PilotClient::PlayWavFile(PilotAudio &audio, const char *path) {
    FILE *file = std::fopen(path, "rb");
    if (file == nullptr) {
        return ESP_ERR_NOT_FOUND;
    }
    std::array<uint8_t, 12> riff = {};
    if (
        std::fread(riff.data(), 1, riff.size(), file) != riff.size() ||
        std::memcmp(riff.data(), "RIFF", 4) != 0 ||
        std::memcmp(riff.data() + 8, "WAVE", 4) != 0
    ) {
        std::fclose(file);
        return ESP_ERR_INVALID_RESPONSE;
    }

    uint16_t channels = 0;
    uint16_t bits = 0;
    uint32_t sample_rate = 0;
    uint32_t data_bytes = 0;
    while (true) {
        std::array<uint8_t, 8> header = {};
        if (std::fread(header.data(), 1, header.size(), file) != header.size()) {
            break;
        }
        const uint32_t size = little_u32(header.data() + 4);
        if (std::memcmp(header.data(), "fmt ", 4) == 0 && size >= 16) {
            std::array<uint8_t, 16> format = {};
            if (std::fread(format.data(), 1, format.size(), file) != format.size()) {
                break;
            }
            if (little_u16(format.data()) != 1) {
                break;
            }
            channels = little_u16(format.data() + 2);
            sample_rate = little_u32(format.data() + 4);
            bits = little_u16(format.data() + 14);
            if (size > format.size()) {
                std::fseek(file, static_cast<long>(size - format.size()), SEEK_CUR);
            }
        } else if (std::memcmp(header.data(), "data", 4) == 0) {
            data_bytes = size;
            break;
        } else {
            std::fseek(file, static_cast<long>(size), SEEK_CUR);
        }
        if (size % 2 != 0) {
            std::fseek(file, 1, SEEK_CUR);
        }
    }
    const long data_start = std::ftell(file);
    if (data_start < 0 || std::fseek(file, 0, SEEK_END) != 0) {
        std::fclose(file);
        return ESP_ERR_INVALID_RESPONSE;
    }
    const long file_end = std::ftell(file);
    if (
        file_end < data_start ||
        std::fseek(file, data_start, SEEK_SET) != 0
    ) {
        std::fclose(file);
        return ESP_ERR_INVALID_RESPONSE;
    }
    const auto available_bytes = static_cast<uint32_t>(file_end - data_start);
    // Home Assistant's FFmpeg proxy can emit streaming WAV files with
    // 0xffffffff RIFF/data lengths. The response has already been downloaded
    // to a bounded local file, so use its actual payload length in that case.
    if (data_bytes > available_bytes) {
        data_bytes = available_bytes;
    }
    if (
        channels != 1 || bits != 16 || sample_rate < 8000 ||
        sample_rate > 48000 || data_bytes == 0
    ) {
        std::fclose(file);
        return ESP_ERR_NOT_SUPPORTED;
    }

    esp_err_t result = audio.StartPlayback(static_cast<int>(sample_rate));
    std::array<int16_t, 512> samples = {};
    uint32_t remaining = data_bytes;
    while (result == ESP_OK && remaining > 0) {
        const std::size_t wanted = std::min<std::size_t>(
            samples.size() * sizeof(int16_t), remaining
        );
        const std::size_t read = std::fread(samples.data(), 1, wanted, file);
        if (read == 0 || audio.Write(samples.data(), read / sizeof(int16_t)) < 0) {
            result = ESP_FAIL;
            break;
        }
        remaining -= static_cast<uint32_t>(read);
    }
    audio.StopPlayback();
    std::fclose(file);
    return result;
}

esp_err_t PilotClient::CheckForUpdate(bool install) {
    if (!Configured()) {
        return ESP_ERR_INVALID_STATE;
    }
    char path[384] = {};
    std::snprintf(
        path,
        sizeof(path),
        "/v1/devices/%s/firmware?target=%s&current_version=%s",
        device_id_,
        firmware_target_,
        firmware_version_
    );
    std::array<char, 3072> response = {};
    esp_err_t result = GetJson(path, response.data(), response.size());
    if (result != ESP_OK) {
        return result;
    }
    cJSON *root = cJSON_Parse(response.data());
    cJSON *available = root == nullptr
        ? nullptr
        : cJSON_GetObjectItemCaseSensitive(root, "update_available");
    cJSON *release = root == nullptr
        ? nullptr
        : cJSON_GetObjectItemCaseSensitive(root, "release");
    if (!cJSON_IsTrue(available) || !cJSON_IsObject(release)) {
        cJSON_Delete(root);
        return ESP_OK;
    }
    char version[40] = {};
    char sha256[65] = {};
    char download_path[256] = {};
    copy_json_string(release, "version", version);
    copy_json_string(release, "sha256", sha256);
    copy_json_string(release, "download_url", download_path);
    cJSON *size_value = cJSON_GetObjectItemCaseSensitive(release, "size_bytes");
    const std::size_t size = cJSON_IsNumber(size_value)
        ? static_cast<std::size_t>(size_value->valuedouble)
        : 0;
    if (!version_is_newer(version, firmware_version_)) {
        ESP_LOGW(
            kTag,
            "Ignoring non-upgrade firmware %s while running %s",
            version,
            firmware_version_
        );
        cJSON_Delete(root);
        return ESP_OK;
    }
    ESP_LOGI(kTag, "Firmware %s is available", version);
    cJSON_Delete(root);
    if (!install) {
        return ESP_OK;
    }
    return InstallFirmware(download_path, sha256, size);
}

esp_err_t PilotClient::InstallFirmware(
    const char *download_path,
    const char *expected_sha256,
    std::size_t expected_size
) {
    if (
        download_path == nullptr || download_path[0] == '\0' ||
        expected_sha256 == nullptr || std::strlen(expected_sha256) != 64 ||
        expected_size == 0
    ) {
        return ESP_ERR_INVALID_ARG;
    }
    char url[512] = {};
    if (!BuildUrl(download_path, url, sizeof(url))) {
        return ESP_ERR_INVALID_ARG;
    }
    esp_http_client_config_t config = {};
    config.url = url;
    config.timeout_ms = 60000;
    config.buffer_size = 4096;
    if (std::strncmp(url, "https://", 8) == 0) {
        config.crt_bundle_attach = esp_crt_bundle_attach;
    }
    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (client == nullptr) {
        return ESP_ERR_NO_MEM;
    }
    ConfigureRequest(client);
    esp_http_client_set_header(client, "Accept", "application/octet-stream");
    esp_err_t result = esp_http_client_open(client, 0);
    if (result != ESP_OK) {
        esp_http_client_cleanup(client);
        return result;
    }
    const int64_t declared_size = esp_http_client_fetch_headers(client);
    if (
        esp_http_client_get_status_code(client) != 200 ||
        declared_size != static_cast<int64_t>(expected_size)
    ) {
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return ESP_ERR_INVALID_SIZE;
    }

    const esp_partition_t *partition = esp_ota_get_next_update_partition(nullptr);
    esp_ota_handle_t ota = 0;
    if (partition == nullptr) {
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return ESP_ERR_NOT_FOUND;
    }
    result = esp_ota_begin(partition, expected_size, &ota);
    if (result != ESP_OK) {
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return result;
    }
    mbedtls_sha256_context sha = {};
    mbedtls_sha256_init(&sha);
    mbedtls_sha256_starts(&sha, 0);
    auto *buffer = static_cast<uint8_t *>(
        heap_caps_malloc(kOtaBufferSize, MALLOC_CAP_8BIT)
    );
    if (buffer == nullptr) {
        mbedtls_sha256_free(&sha);
        esp_ota_abort(ota);
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return ESP_ERR_NO_MEM;
    }
    std::size_t total = 0;
    while (result == ESP_OK) {
        const int read = esp_http_client_read(
            client, reinterpret_cast<char *>(buffer), kOtaBufferSize
        );
        if (read < 0) {
            result = ESP_FAIL;
            break;
        }
        if (read == 0) {
            break;
        }
        total += static_cast<std::size_t>(read);
        if (total > expected_size) {
            result = ESP_ERR_INVALID_SIZE;
            break;
        }
        mbedtls_sha256_update(&sha, buffer, static_cast<std::size_t>(read));
        result = esp_ota_write(ota, buffer, static_cast<std::size_t>(read));
    }
    heap_caps_free(buffer);
    std::array<uint8_t, 32> digest = {};
    mbedtls_sha256_finish(&sha, digest.data());
    mbedtls_sha256_free(&sha);
    esp_http_client_close(client);
    esp_http_client_cleanup(client);

    char digest_hex[65] = {};
    for (std::size_t index = 0; index < digest.size(); ++index) {
        std::snprintf(
            digest_hex + index * 2,
            sizeof(digest_hex) - index * 2,
            "%02x",
            digest[index]
        );
    }
    if (
        result != ESP_OK || total != expected_size ||
        std::strcmp(digest_hex, expected_sha256) != 0
    ) {
        esp_ota_abort(ota);
        ESP_LOGE(kTag, "Firmware download failed integrity validation");
        return result == ESP_OK ? ESP_ERR_INVALID_CRC : result;
    }
    result = esp_ota_end(ota);
    if (result == ESP_OK) {
        result = esp_ota_set_boot_partition(partition);
    }
    if (result == ESP_OK) {
        ESP_LOGI(kTag, "OTA installed; rebooting into pending image");
        vTaskDelay(pdMS_TO_TICKS(500));
        esp_restart();
    }
    return result;
}

esp_err_t PilotClient::MarkRunningFirmwareValid() {
    const esp_partition_t *running = esp_ota_get_running_partition();
    esp_ota_img_states_t state = ESP_OTA_IMG_UNDEFINED;
    const esp_err_t result = esp_ota_get_state_partition(running, &state);
    if (result == ESP_OK && state == ESP_OTA_IMG_PENDING_VERIFY) {
        ESP_LOGI(kTag, "Marking healthy OTA image valid");
        return esp_ota_mark_app_valid_cancel_rollback();
    }
    return result == ESP_ERR_NOT_SUPPORTED ? ESP_OK : result;
}

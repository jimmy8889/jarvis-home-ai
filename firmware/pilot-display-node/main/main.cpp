#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <string>
#include <sys/time.h>

#include "driver/gpio.h"
#include "esp_app_desc.h"
#include "esp_event.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_netif_sntp.h"
#include "esp_spiffs.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "lvgl.h"
#include "nvs_flash.h"
#include "pcf85063a.h"

#include "display_bsp.h"
#include "i2c_bsp.h"
#include "lvgl_bsp.h"
#include "motion_bsp.h"
#include "pilot_audio.h"
#include "pilot_client.h"
#include "power_bsp.h"
#include "user_config.h"

#ifndef PILOT_WIFI_SSID
#define PILOT_WIFI_SSID ""
#endif

#ifndef PILOT_WIFI_PASSWORD
#define PILOT_WIFI_PASSWORD ""
#endif

#ifndef PILOT_CORE_URL
#define PILOT_CORE_URL ""
#endif

#ifndef PILOT_DEVICE_ID
#define PILOT_DEVICE_ID ""
#endif

#ifndef PILOT_DEVICE_TOKEN
#define PILOT_DEVICE_TOKEN ""
#endif

#ifndef PILOT_ROOM_NAME
#define PILOT_ROOM_NAME "BEDROOM"
#endif

#ifndef PILOT_OTA_AUTO_UPDATE
#define PILOT_OTA_AUTO_UPDATE 1
#endif

namespace {

constexpr char kTag[] = "pilot_display";
constexpr char kTimezone[] = "AEST-10";
constexpr char kNtpServer[] = "time.cloudflare.com";
constexpr char kFirmwareTarget[] = "esp32-c6-touch-amoled-2.16";
constexpr EventBits_t kWifiConnectedBit = BIT0;
constexpr uint8_t kAwakeBrightness = 55;
constexpr uint8_t kDimBrightness = 2;
constexpr TickType_t kDimAfter = pdMS_TO_TICKS(20000);
constexpr TickType_t kOffAfter = pdMS_TO_TICKS(30000);
constexpr TickType_t kWeatherInterval = pdMS_TO_TICKS(30 * 60 * 1000);
constexpr TickType_t kOtaInterval = pdMS_TO_TICKS(6 * 60 * 60 * 1000);
constexpr gpio_num_t kActionButton = GPIO_NUM_9;

enum class ClockSource {
    build,
    rtc,
    ntp,
};

enum class ScreenPower {
    awake,
    dim,
    off,
};

enum class VoiceState {
    idle,
    listening,
    processing,
    speaking,
    error,
};

I2cMasterBus i2c_bus(BSP_I2C_SCL, BSP_I2C_SDA, BSP_I2C_NUM);
DisplayPort *display = nullptr;
MotionSensor *motion = nullptr;
PilotAudio *audio = nullptr;
PilotClient *pilot = nullptr;
pcf85063a_dev_t rtc = {};
bool rtc_available = false;

EventGroupHandle_t wifi_events = nullptr;
SemaphoreHandle_t weather_mutex = nullptr;
SemaphoreHandle_t network_mutex = nullptr;
std::atomic<bool> wifi_connected{false};
std::atomic<bool> time_synchronised{false};
std::atomic<ClockSource> clock_source{ClockSource::build};
std::atomic<ScreenPower> screen_power{ScreenPower::awake};
std::atomic<VoiceState> voice_state{VoiceState::idle};
std::atomic<bool> voice_requested{false};
std::atomic<bool> voice_stop_requested{false};
std::atomic<TickType_t> last_activity_tick{0};
PilotWeather weather = {};
PilotVoiceResult last_voice_result = {};

struct SevenSegmentDigit {
    std::array<lv_obj_t *, 7> segment{};
};

std::array<SevenSegmentDigit, 4> digits{};
std::array<lv_obj_t *, 2> colon_dots{};
std::array<lv_obj_t *, 7> voice_bars{};
lv_obj_t *time_row = nullptr;
lv_obj_t *date_label = nullptr;
lv_obj_t *status_label = nullptr;
lv_obj_t *status_dot = nullptr;
lv_obj_t *weather_temperature = nullptr;
lv_obj_t *weather_condition = nullptr;
lv_obj_t *weather_range = nullptr;
lv_obj_t *weather_details = nullptr;
lv_obj_t *voice_overlay = nullptr;
lv_obj_t *voice_status_label = nullptr;
lv_obj_t *voice_detail_label = nullptr;

constexpr bool kDigitSegments[10][7] = {
    {true, true, true, true, true, true, false},
    {false, true, true, false, false, false, false},
    {true, true, false, true, true, false, true},
    {true, true, true, true, false, false, true},
    {false, true, true, false, false, true, true},
    {true, false, true, true, false, true, true},
    {true, false, true, true, true, true, true},
    {true, true, true, false, false, false, false},
    {true, true, true, true, true, true, true},
    {true, true, true, true, false, true, true},
};

constexpr std::array<uint32_t, 7> kVoiceColours = {
    0x4D7CFE, 0x7A5CFA, 0xC64DF1, 0xF051A5,
    0xFF6B6B, 0xF69B4C, 0x4DD9C0,
};

int month_number(const char *month) {
    constexpr const char *months[] = {
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    };
    for (int index = 0; index < 12; ++index) {
        if (std::strncmp(month, months[index], 3) == 0) {
            return index;
        }
    }
    return 0;
}

time_t build_time() {
    std::tm value = {};
    value.tm_year = std::atoi(__DATE__ + 7) - 1900;
    value.tm_mon = month_number(__DATE__);
    value.tm_mday = std::atoi(__DATE__ + 4);
    value.tm_hour = std::atoi(__TIME__);
    value.tm_min = std::atoi(__TIME__ + 3);
    value.tm_sec = std::atoi(__TIME__ + 6);
    value.tm_isdst = -1;
    return std::mktime(&value);
}

bool valid_datetime(const pcf85063a_datetime_t &value) {
    return value.year >= 2024 && value.year <= 2099 &&
           value.month >= 1 && value.month <= 12 &&
           value.day >= 1 && value.day <= 31 &&
           value.hour <= 23 && value.min <= 59 && value.sec <= 59;
}

void set_system_time(time_t epoch) {
    timeval value = {
        .tv_sec = epoch,
        .tv_usec = 0,
    };
    settimeofday(&value, nullptr);
}

void set_rtc_from_system() {
    if (!rtc_available) {
        return;
    }
    const time_t now = std::time(nullptr);
    std::tm local = {};
    localtime_r(&now, &local);
    const pcf85063a_datetime_t value = {
        .year = static_cast<uint16_t>(local.tm_year + 1900),
        .month = static_cast<uint8_t>(local.tm_mon + 1),
        .day = static_cast<uint8_t>(local.tm_mday),
        .dotw = static_cast<uint8_t>(local.tm_wday),
        .hour = static_cast<uint8_t>(local.tm_hour),
        .min = static_cast<uint8_t>(local.tm_min),
        .sec = static_cast<uint8_t>(local.tm_sec),
    };
    if (pcf85063a_set_time_date(&rtc, value) == ESP_OK) {
        ESP_LOGI(kTag, "RTC updated from synchronized local time");
    }
}

void initialise_clock() {
    setenv("TZ", kTimezone, 1);
    tzset();
    set_system_time(build_time());
    clock_source.store(ClockSource::build);

    if (pcf85063a_init(
            &rtc, i2c_bus.Get_I2cBusHandle(), PCF85063A_ADDRESS
        ) != ESP_OK) {
        ESP_LOGW(kTag, "PCF85063 RTC unavailable; using build time");
        return;
    }
    rtc_available = true;
    pcf85063a_datetime_t rtc_value = {};
    if (
        pcf85063a_get_time_date(&rtc, &rtc_value) == ESP_OK &&
        valid_datetime(rtc_value)
    ) {
        std::tm local = {};
        local.tm_year = rtc_value.year - 1900;
        local.tm_mon = rtc_value.month - 1;
        local.tm_mday = rtc_value.day;
        local.tm_hour = rtc_value.hour;
        local.tm_min = rtc_value.min;
        local.tm_sec = rtc_value.sec;
        local.tm_isdst = -1;
        set_system_time(std::mktime(&local));
        clock_source.store(ClockSource::rtc);
        ESP_LOGI(kTag, "System clock restored from RTC");
    } else {
        ESP_LOGW(kTag, "RTC invalid; seeding from firmware build time");
        set_rtc_from_system();
    }
}

void note_activity() {
    last_activity_tick.store(xTaskGetTickCount());
}

void wifi_event_handler(
    void *,
    esp_event_base_t event_base,
    int32_t event_id,
    void *
) {
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
        return;
    }
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        wifi_connected.store(false);
        xEventGroupClearBits(wifi_events, kWifiConnectedBit);
        ESP_LOGW(kTag, "Wi-Fi disconnected; reconnecting");
        vTaskDelay(pdMS_TO_TICKS(500));
        esp_wifi_connect();
        return;
    }
    if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        wifi_connected.store(true);
        xEventGroupSetBits(wifi_events, kWifiConnectedBit);
        ESP_LOGI(kTag, "Wi-Fi connected");
    }
}

bool initialise_wifi() {
    if (PILOT_WIFI_SSID[0] == '\0') {
        ESP_LOGW(kTag, "Wi-Fi credentials were not supplied at build time");
        return false;
    }
    wifi_events = xEventGroupCreate();
    if (wifi_events == nullptr) {
        return false;
    }
    esp_err_t result = esp_netif_init();
    if (result != ESP_OK) {
        return false;
    }
    result = esp_event_loop_create_default();
    if (result != ESP_OK && result != ESP_ERR_INVALID_STATE) {
        return false;
    }
    if (esp_netif_create_default_wifi_sta() == nullptr) {
        return false;
    }
    const wifi_init_config_t init_config = WIFI_INIT_CONFIG_DEFAULT();
    ESP_LOGI(
        kTag,
        "Starting Wi-Fi with %lu bytes free internal RAM (largest block %lu)",
        static_cast<unsigned long>(heap_caps_get_free_size(MALLOC_CAP_INTERNAL)),
        static_cast<unsigned long>(
            heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL)
        )
    );
    ESP_ERROR_CHECK(esp_wifi_init(&init_config));
    ESP_ERROR_CHECK(esp_event_handler_register(
        WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, nullptr
    ));
    ESP_ERROR_CHECK(esp_event_handler_register(
        IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler, nullptr
    ));
    wifi_config_t config = {};
    std::strncpy(
        reinterpret_cast<char *>(config.sta.ssid),
        PILOT_WIFI_SSID,
        sizeof(config.sta.ssid) - 1
    );
    std::strncpy(
        reinterpret_cast<char *>(config.sta.password),
        PILOT_WIFI_PASSWORD,
        sizeof(config.sta.password) - 1
    );
    config.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    config.sta.pmf_cfg.capable = true;
    config.sta.pmf_cfg.required = false;
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &config));
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_MIN_MODEM));
    ESP_ERROR_CHECK(esp_wifi_start());
    return (
        xEventGroupWaitBits(
            wifi_events,
            kWifiConnectedBit,
            pdFALSE,
            pdTRUE,
            pdMS_TO_TICKS(20000)
        ) & kWifiConnectedBit
    ) != 0;
}

void synchronise_time() {
    if (!wifi_connected.load()) {
        return;
    }
    const esp_sntp_config_t config = ESP_NETIF_SNTP_DEFAULT_CONFIG(kNtpServer);
    ESP_ERROR_CHECK(esp_netif_sntp_init(&config));
    const esp_err_t result = esp_netif_sntp_sync_wait(pdMS_TO_TICKS(20000));
    esp_netif_sntp_deinit();
    if (result == ESP_OK) {
        time_synchronised.store(true);
        clock_source.store(ClockSource::ntp);
        set_rtc_from_system();
        ESP_LOGI(kTag, "NTP synchronized using %s", kNtpServer);
    } else {
        ESP_LOGW(kTag, "NTP sync timed out; retaining RTC time");
    }
}

lv_obj_t *create_segment(
    lv_obj_t *parent, int x, int y, int width, int height
) {
    lv_obj_t *segment = lv_obj_create(parent);
    lv_obj_remove_style_all(segment);
    lv_obj_set_pos(segment, x, y);
    lv_obj_set_size(segment, width, height);
    lv_obj_set_style_radius(segment, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_opa(segment, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(segment, lv_color_hex(0x071313), 0);
    return segment;
}

SevenSegmentDigit create_digit(lv_obj_t *parent, int x) {
    SevenSegmentDigit digit;
    lv_obj_t *container = lv_obj_create(parent);
    lv_obj_remove_style_all(container);
    lv_obj_set_pos(container, x, 4);
    lv_obj_set_size(container, 70, 130);
    lv_obj_clear_flag(container, LV_OBJ_FLAG_SCROLLABLE);
    digit.segment[0] = create_segment(container, 10, 0, 50, 9);
    digit.segment[1] = create_segment(container, 61, 9, 9, 51);
    digit.segment[2] = create_segment(container, 61, 70, 9, 51);
    digit.segment[3] = create_segment(container, 10, 121, 50, 9);
    digit.segment[4] = create_segment(container, 0, 70, 9, 51);
    digit.segment[5] = create_segment(container, 0, 9, 9, 51);
    digit.segment[6] = create_segment(container, 10, 60, 50, 9);
    return digit;
}

void set_digit(SevenSegmentDigit &digit, int value) {
    value = value < 0 || value > 9 ? 0 : value;
    for (std::size_t index = 0; index < digit.segment.size(); ++index) {
        lv_obj_set_style_bg_color(
            digit.segment[index],
            lv_color_hex(kDigitSegments[value][index] ? 0xE8FAF6 : 0x071313),
            0
        );
    }
}

lv_obj_t *create_heading(lv_obj_t *parent, const char *text) {
    lv_obj_t *heading = lv_label_create(parent);
    lv_label_set_text(heading, text);
    lv_obj_set_style_text_color(heading, lv_color_hex(0x6B7A78), 0);
    lv_obj_set_style_text_font(heading, &lv_font_montserrat_16, 0);
    lv_obj_set_style_text_letter_space(heading, 3, 0);
    lv_obj_align(heading, LV_ALIGN_TOP_MID, 0, 45);
    return heading;
}

void request_voice() {
    note_activity();
    if (voice_state.load() == VoiceState::idle) {
        voice_stop_requested.store(false);
        voice_requested.store(true);
    } else {
        voice_stop_requested.store(true);
    }
}

void voice_button_event(lv_event_t *event) {
    if (lv_event_get_code(event) == LV_EVENT_CLICKED) {
        request_voice();
    }
}

void activity_event(lv_event_t *event) {
    if (lv_event_get_code(event) == LV_EVENT_PRESSED) {
        note_activity();
    }
}

lv_obj_t *create_voice_button(lv_obj_t *parent) {
    lv_obj_t *button = lv_button_create(parent);
    lv_obj_set_size(button, 132, 48);
    lv_obj_align(button, LV_ALIGN_BOTTOM_MID, 0, -24);
    lv_obj_set_style_radius(button, 24, 0);
    lv_obj_set_style_bg_color(button, lv_color_hex(0x123A35), 0);
    lv_obj_set_style_bg_color(
        button, lv_color_hex(0x17C3A2), LV_STATE_PRESSED
    );
    lv_obj_set_style_border_width(button, 1, 0);
    lv_obj_set_style_border_color(button, lv_color_hex(0x17C3A2), 0);
    lv_obj_add_event_cb(button, voice_button_event, LV_EVENT_ALL, nullptr);
    lv_obj_add_event_cb(button, activity_event, LV_EVENT_PRESSED, nullptr);

    lv_obj_t *label = lv_label_create(button);
    lv_label_set_text(label, "TALK TO PILOT");
    lv_obj_set_style_text_color(label, lv_color_hex(0xE8FAF6), 0);
    lv_obj_set_style_text_font(label, &lv_font_montserrat_12, 0);
    lv_obj_set_style_text_letter_space(label, 1, 0);
    lv_obj_center(label);
    return button;
}

void create_clock_tile(lv_obj_t *tile) {
    create_heading(tile, "PILOT  /  " PILOT_ROOM_NAME);
    status_dot = lv_obj_create(tile);
    lv_obj_remove_style_all(status_dot);
    lv_obj_set_size(status_dot, 8, 8);
    lv_obj_set_style_radius(status_dot, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_opa(status_dot, LV_OPA_COVER, 0);
    lv_obj_align(status_dot, LV_ALIGN_TOP_MID, 0, 79);

    time_row = lv_obj_create(tile);
    lv_obj_remove_style_all(time_row);
    lv_obj_set_size(time_row, 350, 140);
    lv_obj_align(time_row, LV_ALIGN_CENTER, 0, -32);
    lv_obj_clear_flag(time_row, LV_OBJ_FLAG_SCROLLABLE);
    digits[0] = create_digit(time_row, 0);
    digits[1] = create_digit(time_row, 82);
    digits[2] = create_digit(time_row, 198);
    digits[3] = create_digit(time_row, 280);
    colon_dots[0] = create_segment(time_row, 174, 42, 10, 10);
    colon_dots[1] = create_segment(time_row, 174, 86, 10, 10);

    date_label = lv_label_create(tile);
    lv_obj_set_style_text_color(date_label, lv_color_hex(0xAAB9B6), 0);
    lv_obj_set_style_text_font(date_label, &lv_font_montserrat_16, 0);
    lv_obj_set_style_text_letter_space(date_label, 1, 0);
    lv_obj_align(date_label, LV_ALIGN_BOTTOM_MID, 0, -116);

    status_label = lv_label_create(tile);
    lv_obj_set_style_text_color(status_label, lv_color_hex(0x5C716D), 0);
    lv_obj_set_style_text_font(status_label, &lv_font_montserrat_12, 0);
    lv_obj_set_style_text_letter_space(status_label, 2, 0);
    lv_obj_align(status_label, LV_ALIGN_BOTTOM_MID, 0, -86);
    create_voice_button(tile);
}

void create_weather_tile(lv_obj_t *tile) {
    create_heading(tile, "TODAY  /  WEATHER");
    weather_temperature = lv_label_create(tile);
    lv_label_set_text(weather_temperature, "--");
    lv_obj_set_style_text_color(
        weather_temperature, lv_color_hex(0xE8FAF6), 0
    );
    lv_obj_set_style_text_font(
        weather_temperature, &lv_font_montserrat_48, 0
    );
    lv_obj_align(weather_temperature, LV_ALIGN_TOP_MID, 0, 92);

    weather_condition = lv_label_create(tile);
    lv_label_set_text(weather_condition, "WAITING FOR PILOT CORE");
    lv_obj_set_style_text_color(
        weather_condition, lv_color_hex(0x17C3A2), 0
    );
    lv_obj_set_style_text_font(
        weather_condition, &lv_font_montserrat_24, 0
    );
    lv_obj_set_width(weather_condition, 400);
    lv_obj_set_style_text_align(weather_condition, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(weather_condition, LV_ALIGN_TOP_MID, 0, 164);

    weather_range = lv_label_create(tile);
    lv_label_set_text(weather_range, "HIGH --   /   LOW --");
    lv_obj_set_style_text_color(weather_range, lv_color_hex(0xAAB9B6), 0);
    lv_obj_set_style_text_font(weather_range, &lv_font_montserrat_16, 0);
    lv_obj_set_style_text_letter_space(weather_range, 1, 0);
    lv_obj_align(weather_range, LV_ALIGN_TOP_MID, 0, 221);

    weather_details = lv_label_create(tile);
    lv_label_set_text(weather_details, "SWIPE RIGHT FOR CLOCK");
    lv_obj_set_style_text_color(weather_details, lv_color_hex(0x5C716D), 0);
    lv_obj_set_style_text_font(weather_details, &lv_font_montserrat_12, 0);
    lv_obj_set_width(weather_details, 400);
    lv_obj_set_style_text_align(weather_details, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(weather_details, LV_ALIGN_TOP_MID, 0, 267);
    create_voice_button(tile);
}

void create_voice_overlay(lv_obj_t *screen) {
    voice_overlay = lv_obj_create(screen);
    lv_obj_remove_style_all(voice_overlay);
    lv_obj_set_size(voice_overlay, 480, 480);
    lv_obj_set_style_bg_opa(voice_overlay, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(voice_overlay, lv_color_hex(0x020206), 0);
    lv_obj_add_flag(voice_overlay, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_event_cb(voice_overlay, voice_button_event, LV_EVENT_ALL, nullptr);

    voice_status_label = lv_label_create(voice_overlay);
    lv_label_set_text(voice_status_label, "LISTENING");
    lv_obj_set_style_text_color(
        voice_status_label, lv_color_hex(0xE8FAF6), 0
    );
    lv_obj_set_style_text_font(
        voice_status_label, &lv_font_montserrat_24, 0
    );
    lv_obj_set_style_text_letter_space(voice_status_label, 4, 0);
    lv_obj_align(voice_status_label, LV_ALIGN_TOP_MID, 0, 78);

    lv_obj_t *bar_row = lv_obj_create(voice_overlay);
    lv_obj_remove_style_all(bar_row);
    lv_obj_set_size(bar_row, 330, 120);
    lv_obj_align(bar_row, LV_ALIGN_CENTER, 0, -10);
    for (std::size_t index = 0; index < voice_bars.size(); ++index) {
        voice_bars[index] = lv_obj_create(bar_row);
        lv_obj_remove_style_all(voice_bars[index]);
        lv_obj_set_size(voice_bars[index], 24, 30);
        lv_obj_set_x(voice_bars[index], 18 + static_cast<int>(index) * 45);
        lv_obj_set_y(voice_bars[index], 45);
        lv_obj_set_style_radius(voice_bars[index], LV_RADIUS_CIRCLE, 0);
        lv_obj_set_style_bg_opa(voice_bars[index], LV_OPA_COVER, 0);
        lv_obj_set_style_bg_color(
            voice_bars[index], lv_color_hex(kVoiceColours[index]), 0
        );
    }

    voice_detail_label = lv_label_create(voice_overlay);
    lv_label_set_text(voice_detail_label, "Tap to stop");
    lv_obj_set_style_text_color(
        voice_detail_label, lv_color_hex(0x7C8C89), 0
    );
    lv_obj_set_style_text_font(
        voice_detail_label, &lv_font_montserrat_16, 0
    );
    lv_obj_set_width(voice_detail_label, 390);
    lv_obj_set_style_text_align(voice_detail_label, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(voice_detail_label, LV_ALIGN_BOTTOM_MID, 0, -72);
}

void create_ui() {
    lv_obj_t *screen = lv_screen_active();
    lv_obj_set_style_bg_color(screen, lv_color_hex(0x000000), 0);
    lv_obj_set_style_bg_opa(screen, LV_OPA_COVER, 0);
    lv_obj_clear_flag(screen, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_t *tiles = lv_tileview_create(screen);
    lv_obj_remove_style_all(tiles);
    lv_obj_set_size(tiles, 480, 480);
    lv_obj_add_event_cb(tiles, activity_event, LV_EVENT_PRESSED, nullptr);
    lv_obj_t *clock_tile = lv_tileview_add_tile(
        tiles, 0, 0, LV_DIR_RIGHT
    );
    lv_obj_t *weather_tile = lv_tileview_add_tile(
        tiles, 1, 0, LV_DIR_LEFT
    );
    for (lv_obj_t *tile : {clock_tile, weather_tile}) {
        lv_obj_set_style_bg_color(tile, lv_color_hex(0x000000), 0);
        lv_obj_set_style_bg_opa(tile, LV_OPA_COVER, 0);
        lv_obj_set_style_border_width(tile, 0, 0);
    }
    create_clock_tile(clock_tile);
    create_weather_tile(weather_tile);
    create_voice_overlay(screen);
}

const char *clock_source_name() {
    switch (clock_source.load()) {
        case ClockSource::ntp:
            return "NTP";
        case ClockSource::rtc:
            return "RTC";
        case ClockSource::build:
        default:
            return "BUILD";
    }
}

void update_clock_ui() {
    const time_t now = std::time(nullptr);
    std::tm local = {};
    localtime_r(&now, &local);
    const std::array<int, 4> values = {
        local.tm_hour / 10,
        local.tm_hour % 10,
        local.tm_min / 10,
        local.tm_min % 10,
    };
    for (std::size_t index = 0; index < digits.size(); ++index) {
        set_digit(digits[index], values[index]);
    }
    const lv_color_t colon_color = lv_color_hex(
        local.tm_sec % 2 == 0 ? 0x17C3A2 : 0x071313
    );
    for (lv_obj_t *dot : colon_dots) {
        lv_obj_set_style_bg_color(dot, colon_color, 0);
    }
    char date[64] = {};
    std::strftime(date, sizeof(date), "%A  |  %d %B", &local);
    lv_label_set_text(date_label, date);
    char status[96] = {};
    std::snprintf(
        status,
        sizeof(status),
        "%s  |  %s  |  %s",
        wifi_connected.load() ? "WI-FI" : "OFFLINE",
        clock_source_name(),
        pilot != nullptr && pilot->Configured() ? "CORE" : "LOCAL"
    );
    lv_label_set_text(status_label, status);
    lv_obj_set_style_bg_color(
        status_dot,
        lv_color_hex(
            time_synchronised.load() && wifi_connected.load()
                ? 0x17C3A2
                : 0xB88A20
        ),
        0
    );
    constexpr std::array<std::array<int, 2>, 8> offsets = {{
        {{0, 0}}, {{1, -1}}, {{-1, 1}}, {{2, 0}},
        {{-2, 0}}, {{1, 1}}, {{-1, -1}}, {{0, 2}},
    }};
    const auto &offset = offsets[(local.tm_min / 5) % offsets.size()];
    lv_obj_align(time_row, LV_ALIGN_CENTER, offset[0], -32 + offset[1]);
}

void update_weather_ui() {
    PilotWeather snapshot = {};
    if (
        weather_mutex != nullptr &&
        xSemaphoreTake(weather_mutex, pdMS_TO_TICKS(20)) == pdTRUE
    ) {
        snapshot = weather;
        xSemaphoreGive(weather_mutex);
    }
    if (!snapshot.available) {
        lv_label_set_text(weather_temperature, "--");
        lv_label_set_text(
            weather_condition,
            pilot != nullptr && pilot->Configured()
                ? "WEATHER UNAVAILABLE"
                : "CONNECT PILOT CORE"
        );
        lv_label_set_text(weather_range, "HIGH --   /   LOW --");
        lv_label_set_text(weather_details, "SWIPE RIGHT FOR CLOCK");
        return;
    }
    char temperature[32] = {};
    std::snprintf(
        temperature,
        sizeof(temperature),
        "%.0f%s",
        snapshot.temperature,
        snapshot.temperature_unit[0] != '\0'
            ? snapshot.temperature_unit
            : " C"
    );
    lv_label_set_text(weather_temperature, temperature);
    const char *condition = (
        snapshot.forecast_condition[0] != '\0'
            ? snapshot.forecast_condition
            : snapshot.condition
    );
    char condition_text[64] = {};
    std::strncpy(condition_text, condition, sizeof(condition_text) - 1);
    for (char &character : condition_text) {
        if (character == '-') {
            character = ' ';
        } else {
            character = static_cast<char>(
                std::toupper(static_cast<unsigned char>(character))
            );
        }
    }
    lv_label_set_text(weather_condition, condition_text);

    char range[96] = {};
    std::snprintf(
        range,
        sizeof(range),
        "HIGH %s   /   LOW %s",
        snapshot.has_high_temperature
            ? std::to_string(
                static_cast<int>(std::round(snapshot.high_temperature))
            ).c_str()
            : "--",
        snapshot.has_low_temperature
            ? std::to_string(
                static_cast<int>(std::round(snapshot.low_temperature))
            ).c_str()
            : "--"
    );
    lv_label_set_text(weather_range, range);

    char details[128] = {};
    std::snprintf(
        details,
        sizeof(details),
        "HUMIDITY %s   |   RAIN %s",
        snapshot.has_humidity
            ? std::to_string(
                static_cast<int>(std::round(snapshot.humidity))
            ).c_str()
            : "--",
        snapshot.has_precipitation_probability
            ? std::to_string(
                static_cast<int>(
                    std::round(snapshot.precipitation_probability)
                )
            ).c_str()
            : "--"
    );
    lv_label_set_text(weather_details, details);
}

void update_voice_ui() {
    const VoiceState state = voice_state.load();
    static VoiceState previous = VoiceState::error;
    if (state == VoiceState::idle) {
        if (previous != state) {
            lv_obj_add_flag(voice_overlay, LV_OBJ_FLAG_HIDDEN);
        }
        previous = state;
        return;
    }
    if (previous != state) {
        lv_obj_remove_flag(voice_overlay, LV_OBJ_FLAG_HIDDEN);
        const char *status = "LISTENING";
        const char *detail = "Speak now  /  tap to stop";
        if (state == VoiceState::processing) {
            status = "THINKING";
            detail = "Running locally through Pilot Core";
        } else if (state == VoiceState::speaking) {
            status = "RESPONDING";
            detail = last_voice_result.response_text[0] != '\0'
                ? last_voice_result.response_text
                : "Pilot is speaking";
        } else if (state == VoiceState::error) {
            status = "VOICE OFFLINE";
            detail = "Check Pilot Core and local TTS";
        }
        lv_label_set_text(voice_status_label, status);
        lv_label_set_text(voice_detail_label, detail);
        previous = state;
    }

    const float time = static_cast<float>(lv_tick_get() % 4000) / 260.0f;
    for (std::size_t index = 0; index < voice_bars.size(); ++index) {
        float amplitude = 0.5f;
        if (state == VoiceState::listening) {
            amplitude = 0.5f + 0.5f * std::sin(time + index * 0.9f);
        } else if (state == VoiceState::processing) {
            amplitude = 0.5f + 0.5f * std::sin(time * 0.55f + index * 1.2f);
        } else if (state == VoiceState::speaking) {
            amplitude = 0.5f + 0.5f * std::sin(time * 1.35f + index * 0.7f);
        } else {
            amplitude = 0.15f;
        }
        const int height = 18 + static_cast<int>(amplitude * 82);
        lv_obj_set_height(voice_bars[index], height);
        lv_obj_set_y(voice_bars[index], (120 - height) / 2);
        lv_obj_set_style_bg_color(
            voice_bars[index],
            lv_color_hex(
                state == VoiceState::error ? 0xA33B49 : kVoiceColours[index]
            ),
            0
        );
    }
}

void ui_task(void *) {
    int previous_second = -1;
    int previous_minute = -1;
    while (true) {
        const time_t now = std::time(nullptr);
        std::tm local = {};
        localtime_r(&now, &local);
        if (Lvgl_lock(500) == ESP_OK) {
            if (local.tm_sec != previous_second) {
                previous_second = local.tm_sec;
                update_clock_ui();
                update_weather_ui();
            }
            update_voice_ui();
            Lvgl_unlock();
        }
        if (local.tm_min != previous_minute) {
            previous_minute = local.tm_min;
            char timestamp[32] = {};
            std::strftime(
                timestamp, sizeof(timestamp), "%Y-%m-%d %H:%M:%S", &local
            );
            ESP_LOGI(
                kTag,
                "Clock %s source=%s wifi=%s screen=%d",
                timestamp,
                clock_source_name(),
                wifi_connected.load() ? "connected" : "offline",
                static_cast<int>(screen_power.load())
            );
        }
        vTaskDelay(pdMS_TO_TICKS(50));
    }
}

void set_screen_power(ScreenPower target) {
    if (screen_power.load() == target || display == nullptr) {
        return;
    }
    if (Lvgl_lock(200) != ESP_OK) {
        return;
    }
    display->Set_Backlight(
        target == ScreenPower::awake
            ? kAwakeBrightness
            : target == ScreenPower::dim
                ? kDimBrightness
                : 0
    );
    Lvgl_unlock();
    screen_power.store(target);
    ESP_LOGI(kTag, "Display power state=%d", static_cast<int>(target));
}

void motion_power_task(void *) {
    MotionSample baseline = {};
    bool have_baseline = false;
    while (true) {
        if (motion != nullptr && motion->Available()) {
            MotionSample sample = {};
            if (motion->Read(&sample) == ESP_OK) {
                if (have_baseline) {
                    const float acceleration_delta = std::sqrt(
                        std::pow(sample.accel_x - baseline.accel_x, 2) +
                        std::pow(sample.accel_y - baseline.accel_y, 2) +
                        std::pow(sample.accel_z - baseline.accel_z, 2)
                    );
                    const float gyro = std::sqrt(
                        sample.gyro_x * sample.gyro_x +
                        sample.gyro_y * sample.gyro_y +
                        sample.gyro_z * sample.gyro_z
                    );
                    if (acceleration_delta > 0.32f || gyro > 0.16f) {
                        note_activity();
                    }
                }
                baseline.accel_x = baseline.accel_x * 0.88f + sample.accel_x * 0.12f;
                baseline.accel_y = baseline.accel_y * 0.88f + sample.accel_y * 0.12f;
                baseline.accel_z = baseline.accel_z * 0.88f + sample.accel_z * 0.12f;
                have_baseline = true;
            }
        }
        if (voice_state.load() != VoiceState::idle) {
            note_activity();
        }
        const TickType_t elapsed = (
            xTaskGetTickCount() - last_activity_tick.load()
        );
        if (elapsed >= kOffAfter) {
            set_screen_power(ScreenPower::off);
        } else if (elapsed >= kDimAfter) {
            set_screen_power(ScreenPower::dim);
        } else {
            set_screen_power(ScreenPower::awake);
        }
        vTaskDelay(pdMS_TO_TICKS(80));
    }
}

void voice_phase_callback(PilotVoicePhase phase, void *) {
    if (phase == PilotVoicePhase::listening) {
        voice_state.store(VoiceState::listening);
    } else if (phase == PilotVoicePhase::processing) {
        voice_state.store(VoiceState::processing);
    } else {
        voice_state.store(VoiceState::speaking);
    }
    note_activity();
}

void voice_task(void *) {
    while (true) {
        if (!voice_requested.exchange(false)) {
            vTaskDelay(pdMS_TO_TICKS(50));
            continue;
        }
        note_activity();
        last_voice_result = PilotVoiceResult{};
        if (
            pilot == nullptr || !pilot->Configured() ||
            audio == nullptr || !audio->Available() ||
            !wifi_connected.load()
        ) {
            voice_state.store(VoiceState::error);
            vTaskDelay(pdMS_TO_TICKS(1800));
            voice_state.store(VoiceState::idle);
            continue;
        }

        voice_state.store(VoiceState::listening);
        esp_err_t result = ESP_ERR_TIMEOUT;
        if (
            network_mutex != nullptr &&
            xSemaphoreTake(network_mutex, pdMS_TO_TICKS(3000)) == pdTRUE
        ) {
            result = pilot->RunVoiceSession(
                *audio,
                voice_stop_requested,
                &last_voice_result,
                voice_phase_callback,
                nullptr
            );
            xSemaphoreGive(network_mutex);
        }
        if (result != ESP_OK) {
            ESP_LOGW(kTag, "Voice session failed: %s", esp_err_to_name(result));
            voice_state.store(VoiceState::error);
            vTaskDelay(pdMS_TO_TICKS(1800));
        } else {
            vTaskDelay(pdMS_TO_TICKS(900));
        }
        voice_state.store(VoiceState::idle);
        voice_stop_requested.store(false);
    }
}

void action_button_task(void *) {
    gpio_config_t config = {};
    config.pin_bit_mask = 1ULL << kActionButton;
    config.mode = GPIO_MODE_INPUT;
    config.pull_up_en = GPIO_PULLUP_ENABLE;
    config.pull_down_en = GPIO_PULLDOWN_DISABLE;
    config.intr_type = GPIO_INTR_DISABLE;
    gpio_config(&config);
    int previous = gpio_get_level(kActionButton);
    while (true) {
        const int current = gpio_get_level(kActionButton);
        if (previous == 1 && current == 0) {
            request_voice();
        }
        previous = current;
        vTaskDelay(pdMS_TO_TICKS(30));
    }
}

void fetch_weather() {
    if (
        pilot == nullptr || !pilot->Configured() ||
        network_mutex == nullptr || weather_mutex == nullptr
    ) {
        return;
    }
    PilotWeather latest = {};
    if (xSemaphoreTake(network_mutex, pdMS_TO_TICKS(3000)) != pdTRUE) {
        return;
    }
    const esp_err_t result = pilot->FetchSnapshot(&latest);
    xSemaphoreGive(network_mutex);
    if (xSemaphoreTake(weather_mutex, pdMS_TO_TICKS(100)) == pdTRUE) {
        weather = latest;
        xSemaphoreGive(weather_mutex);
    }
    ESP_LOGI(
        kTag,
        "Weather refresh %s",
        result == ESP_OK ? "succeeded" : esp_err_to_name(result)
    );
}

void network_task(void *) {
    if (initialise_wifi()) {
        synchronise_time();
    } else {
        ESP_LOGW(kTag, "Continuing with offline clock");
    }
    if (wifi_connected.load()) {
        fetch_weather();
    }

    vTaskDelay(pdMS_TO_TICKS(20000));
    if (pilot != nullptr) {
        pilot->MarkRunningFirmwareValid();
    }

    TickType_t last_weather = xTaskGetTickCount() - kWeatherInterval;
    TickType_t last_ota = xTaskGetTickCount() - kOtaInterval;
    while (true) {
        const TickType_t now = xTaskGetTickCount();
        if (
            wifi_connected.load() &&
            pilot != nullptr &&
            pilot->Configured()
        ) {
            if (now - last_weather >= kWeatherInterval) {
                fetch_weather();
                last_weather = now;
            }
            if (
                now - last_ota >= kOtaInterval &&
                voice_state.load() == VoiceState::idle &&
                screen_power.load() != ScreenPower::awake &&
                xSemaphoreTake(network_mutex, pdMS_TO_TICKS(1000)) == pdTRUE
            ) {
                const esp_err_t result = pilot->CheckForUpdate(
                    PILOT_OTA_AUTO_UPDATE != 0
                );
                xSemaphoreGive(network_mutex);
                if (result != ESP_OK) {
                    ESP_LOGW(kTag, "OTA check failed: %s", esp_err_to_name(result));
                }
                last_ota = now;
            }
        }
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

void mount_storage() {
    const esp_vfs_spiffs_conf_t config = {
        .base_path = "/spiffs",
        .partition_label = "storage",
        .max_files = 3,
        .format_if_mount_failed = true,
    };
    const esp_err_t result = esp_vfs_spiffs_register(&config);
    if (result != ESP_OK) {
        ESP_LOGW(kTag, "SPIFFS unavailable: %s", esp_err_to_name(result));
    }
}

}  // namespace

extern "C" void app_main() {
    const esp_app_desc_t *application = esp_app_get_description();
    ESP_LOGI(
        kTag,
        "Pilot display node %s starting",
        application->version
    );
    ESP_ERROR_CHECK(nvs_flash_init());
    weather_mutex = xSemaphoreCreateMutex();
    network_mutex = xSemaphoreCreateMutex();
    last_activity_tick.store(xTaskGetTickCount());

    Custom_PmicPortInit(&i2c_bus, 0x34);
    initialise_clock();
    mount_storage();

    display = new DisplayPort(i2c_bus, BSP_LCD_H_RES, BSP_LCD_V_RES);
    display->DisplayPort_TouchInit();
    display->Set_Backlight(kAwakeBrightness);
    Lvgl_PortInit(*display);
    if (Lvgl_lock(-1) == ESP_OK) {
        create_ui();
        update_clock_ui();
        update_weather_ui();
        Lvgl_unlock();
    }

    motion = new MotionSensor(i2c_bus);
    motion->Initialize();
    audio = new PilotAudio(i2c_bus.Get_I2cBusHandle());
    const esp_err_t audio_result = audio->Initialize();
    if (audio_result != ESP_OK) {
        ESP_LOGW(kTag, "Audio hardware unavailable: %s", esp_err_to_name(audio_result));
    }
    pilot = new PilotClient(
        PILOT_CORE_URL,
        PILOT_DEVICE_ID,
        PILOT_DEVICE_TOKEN,
        kFirmwareTarget,
        application->version
    );
    ESP_LOGI(
        kTag,
        "Pilot Core features %s",
        pilot->Configured() ? "configured" : "disabled"
    );

    xTaskCreate(ui_task, "pilot_ui", 4096, nullptr, 4, nullptr);
    xTaskCreate(
        motion_power_task, "pilot_motion_power", 4096, nullptr, 5, nullptr
    );
    xTaskCreate(voice_task, "pilot_voice", 7168, nullptr, 5, nullptr);
    xTaskCreate(action_button_task, "pilot_button", 2048, nullptr, 4, nullptr);
    xTaskCreate(network_task, "pilot_network", 7168, nullptr, 5, nullptr);
}

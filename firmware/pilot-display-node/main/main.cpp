#include <array>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <sys/time.h>

#include "esp_event.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_netif_sntp.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"
#include "lvgl.h"
#include "nvs_flash.h"
#include "pcf85063a.h"

#include "display_bsp.h"
#include "i2c_bsp.h"
#include "lvgl_bsp.h"
#include "power_bsp.h"
#include "user_config.h"

#ifndef PILOT_WIFI_SSID
#define PILOT_WIFI_SSID ""
#endif

#ifndef PILOT_WIFI_PASSWORD
#define PILOT_WIFI_PASSWORD ""
#endif

namespace {

constexpr char kTag[] = "pilot_display";
constexpr char kTimezone[] = "AEST-10";
constexpr char kNtpServer[] = "time.cloudflare.com";
constexpr EventBits_t kWifiConnectedBit = BIT0;
constexpr uint8_t kDisplayBrightness = 65;

enum class ClockSource {
    build,
    rtc,
    ntp,
};

I2cMasterBus i2c_bus(BSP_I2C_SCL, BSP_I2C_SDA, BSP_I2C_NUM);
DisplayPort *display = nullptr;
pcf85063a_dev_t rtc = {};
bool rtc_available = false;

EventGroupHandle_t wifi_events = nullptr;
std::atomic<bool> wifi_connected{false};
std::atomic<bool> time_synchronised{false};
std::atomic<ClockSource> clock_source{ClockSource::build};

struct SevenSegmentDigit {
    std::array<lv_obj_t *, 7> segment{};
};

std::array<SevenSegmentDigit, 4> digits{};
std::array<lv_obj_t *, 2> colon_dots{};
lv_obj_t *time_row = nullptr;
lv_obj_t *date_label = nullptr;
lv_obj_t *status_label = nullptr;
lv_obj_t *status_dot = nullptr;

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
        ESP_LOGI(kTag, "RTC updated from synchronised local time");
    } else {
        ESP_LOGW(kTag, "Unable to update RTC");
    }
}

void initialise_clock() {
    setenv("TZ", kTimezone, 1);
    tzset();

    const time_t compiled_at = build_time();
    set_system_time(compiled_at);
    clock_source.store(ClockSource::build);

    if (pcf85063a_init(&rtc, i2c_bus.Get_I2cBusHandle(), PCF85063A_ADDRESS) != ESP_OK) {
        ESP_LOGW(kTag, "PCF85063 RTC is unavailable; using build time until NTP sync");
        return;
    }

    rtc_available = true;
    pcf85063a_datetime_t rtc_value = {};
    if (pcf85063a_get_time_date(&rtc, &rtc_value) == ESP_OK && valid_datetime(rtc_value)) {
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
        return;
    }

    ESP_LOGW(kTag, "RTC did not contain a valid time; seeding it from firmware build time");
    set_rtc_from_system();
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
        ESP_LOGE(kTag, "Unable to allocate Wi-Fi event group");
        return false;
    }

    esp_err_t result = esp_netif_init();
    if (result != ESP_OK) {
        ESP_LOGE(kTag, "Network interface init failed: %s", esp_err_to_name(result));
        return false;
    }
    result = esp_event_loop_create_default();
    if (result != ESP_OK && result != ESP_ERR_INVALID_STATE) {
        ESP_LOGE(kTag, "Event loop init failed: %s", esp_err_to_name(result));
        return false;
    }
    if (esp_netif_create_default_wifi_sta() == nullptr) {
        ESP_LOGE(kTag, "Unable to create Wi-Fi station interface");
        return false;
    }

    const wifi_init_config_t init_config = WIFI_INIT_CONFIG_DEFAULT();
    ESP_LOGI(
        kTag,
        "Starting Wi-Fi with %lu bytes free internal RAM (largest block %lu)",
        static_cast<unsigned long>(heap_caps_get_free_size(MALLOC_CAP_INTERNAL)),
        static_cast<unsigned long>(heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL))
    );
    result = esp_wifi_init(&init_config);
    if (result != ESP_OK) {
        ESP_LOGE(kTag, "Wi-Fi driver init failed: %s; clock will remain offline", esp_err_to_name(result));
        return false;
    }
    result = esp_event_handler_register(
        WIFI_EVENT,
        ESP_EVENT_ANY_ID,
        &wifi_event_handler,
        nullptr
    );
    if (result != ESP_OK) {
        ESP_LOGE(kTag, "Wi-Fi event registration failed: %s", esp_err_to_name(result));
        return false;
    }
    result = esp_event_handler_register(
        IP_EVENT,
        IP_EVENT_STA_GOT_IP,
        &wifi_event_handler,
        nullptr
    );
    if (result != ESP_OK) {
        ESP_LOGE(kTag, "IP event registration failed: %s", esp_err_to_name(result));
        return false;
    }

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

    result = esp_wifi_set_mode(WIFI_MODE_STA);
    if (result == ESP_OK) {
        result = esp_wifi_set_config(WIFI_IF_STA, &config);
    }
    if (result == ESP_OK) {
        result = esp_wifi_set_ps(WIFI_PS_MIN_MODEM);
    }
    if (result == ESP_OK) {
        result = esp_wifi_start();
    }
    if (result != ESP_OK) {
        ESP_LOGE(kTag, "Wi-Fi station start failed: %s", esp_err_to_name(result));
        return false;
    }

    const EventBits_t connection_bits = xEventGroupWaitBits(
        wifi_events,
        kWifiConnectedBit,
        pdFALSE,
        pdTRUE,
        pdMS_TO_TICKS(20000)
    );
    return (connection_bits & kWifiConnectedBit) != 0;
}

void synchronise_time() {
    if (!wifi_connected.load()) {
        ESP_LOGW(kTag, "Skipping NTP sync because Wi-Fi is offline");
        return;
    }

    const esp_sntp_config_t config = ESP_NETIF_SNTP_DEFAULT_CONFIG(kNtpServer);
    ESP_ERROR_CHECK(esp_netif_sntp_init(&config));
    const esp_err_t result = esp_netif_sntp_sync_wait(pdMS_TO_TICKS(20000));
    esp_netif_sntp_deinit();

    if (result != ESP_OK) {
        ESP_LOGW(kTag, "NTP sync timed out; retaining RTC time");
        return;
    }

    time_synchronised.store(true);
    clock_source.store(ClockSource::ntp);
    set_rtc_from_system();
    ESP_LOGI(kTag, "NTP synchronised using %s", kNtpServer);
}

lv_obj_t *create_segment(lv_obj_t *parent, int x, int y, int width, int height) {
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

void create_ui() {
    lv_obj_t *screen = lv_screen_active();
    lv_obj_set_style_bg_color(screen, lv_color_hex(0x000000), 0);
    lv_obj_set_style_bg_opa(screen, LV_OPA_COVER, 0);
    lv_obj_clear_flag(screen, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_t *heading = lv_label_create(screen);
    lv_label_set_text(heading, "PILOT  /  OFFICE");
    lv_obj_set_style_text_color(heading, lv_color_hex(0x6B7A78), 0);
    lv_obj_set_style_text_font(heading, &lv_font_montserrat_16, 0);
    lv_obj_set_style_text_letter_space(heading, 3, 0);
    lv_obj_align(heading, LV_ALIGN_TOP_MID, 0, 58);

    status_dot = lv_obj_create(screen);
    lv_obj_remove_style_all(status_dot);
    lv_obj_set_size(status_dot, 8, 8);
    lv_obj_set_style_radius(status_dot, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_opa(status_dot, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(status_dot, lv_color_hex(0xB88A20), 0);
    lv_obj_align(status_dot, LV_ALIGN_TOP_MID, 0, 92);

    time_row = lv_obj_create(screen);
    lv_obj_remove_style_all(time_row);
    lv_obj_set_size(time_row, 350, 140);
    lv_obj_align(time_row, LV_ALIGN_CENTER, 0, -5);
    lv_obj_clear_flag(time_row, LV_OBJ_FLAG_SCROLLABLE);

    digits[0] = create_digit(time_row, 0);
    digits[1] = create_digit(time_row, 82);
    digits[2] = create_digit(time_row, 198);
    digits[3] = create_digit(time_row, 280);

    colon_dots[0] = create_segment(time_row, 174, 42, 10, 10);
    colon_dots[1] = create_segment(time_row, 174, 86, 10, 10);

    date_label = lv_label_create(screen);
    lv_obj_set_style_text_color(date_label, lv_color_hex(0xAAB9B6), 0);
    lv_obj_set_style_text_font(date_label, &lv_font_montserrat_16, 0);
    lv_obj_set_style_text_letter_space(date_label, 1, 0);
    lv_obj_align(date_label, LV_ALIGN_BOTTOM_MID, 0, -92);

    status_label = lv_label_create(screen);
    lv_obj_set_style_text_color(status_label, lv_color_hex(0x5C716D), 0);
    lv_obj_set_style_text_font(status_label, &lv_font_montserrat_12, 0);
    lv_obj_set_style_text_letter_space(status_label, 2, 0);
    lv_obj_align(status_label, LV_ALIGN_BOTTOM_MID, 0, -56);

    lv_obj_t *accent = lv_obj_create(screen);
    lv_obj_remove_style_all(accent);
    lv_obj_set_size(accent, 52, 2);
    lv_obj_set_style_bg_opa(accent, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(accent, lv_color_hex(0x17C3A2), 0);
    lv_obj_align(accent, LV_ALIGN_BOTTOM_MID, 0, -31);
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

void update_ui() {
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
        "%s  |  %s",
        wifi_connected.load() ? "WI-FI" : "OFFLINE",
        clock_source_name()
    );
    lv_label_set_text(status_label, status);
    lv_obj_set_style_bg_color(
        status_dot,
        lv_color_hex(time_synchronised.load() ? 0x17C3A2 : 0xB88A20),
        0
    );

    constexpr std::array<std::array<int, 2>, 8> offsets = {{
        {{0, 0}}, {{1, -1}}, {{-1, 1}}, {{2, 0}},
        {{-2, 0}}, {{1, 1}}, {{-1, -1}}, {{0, 2}},
    }};
    const auto &offset = offsets[(local.tm_min / 5) % offsets.size()];
    lv_obj_align(time_row, LV_ALIGN_CENTER, offset[0], -5 + offset[1]);
}

void ui_task(void *) {
    int previous_minute = -1;
    while (true) {
        if (Lvgl_lock(1000) == ESP_OK) {
            update_ui();
            Lvgl_unlock();
        }

        const time_t now = std::time(nullptr);
        std::tm local = {};
        localtime_r(&now, &local);
        if (local.tm_min != previous_minute) {
            previous_minute = local.tm_min;
            char timestamp[32] = {};
            std::strftime(timestamp, sizeof(timestamp), "%Y-%m-%d %H:%M:%S", &local);
            ESP_LOGI(
                kTag,
                "Clock %s source=%s wifi=%s",
                timestamp,
                clock_source_name(),
                wifi_connected.load() ? "connected" : "offline"
            );
        }
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

void time_sync_task(void *) {
    if (initialise_wifi()) {
        synchronise_time();
    } else {
        ESP_LOGW(kTag, "Continuing with offline clock");
    }
    vTaskDelete(nullptr);
}

}  // namespace

extern "C" void app_main() {
    ESP_LOGI(kTag, "Pilot display node 0.1.0 starting");
    ESP_ERROR_CHECK(nvs_flash_init());

    Custom_PmicPortInit(&i2c_bus, 0x34);
    initialise_clock();

    display = new DisplayPort(i2c_bus, BSP_LCD_H_RES, BSP_LCD_V_RES);
    display->Set_Backlight(kDisplayBrightness);
    Lvgl_PortInit(*display);

    if (Lvgl_lock(-1) == ESP_OK) {
        create_ui();
        update_ui();
        Lvgl_unlock();
    }

    xTaskCreate(ui_task, "pilot_ui", 4096, nullptr, 4, nullptr);
    xTaskCreate(time_sync_task, "pilot_time_sync", 6144, nullptr, 5, nullptr);
}

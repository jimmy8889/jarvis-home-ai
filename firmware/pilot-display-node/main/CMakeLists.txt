idf_component_register(
    SRCS "main.cpp"
    INCLUDE_DIRS "."
    PRIV_REQUIRES
        app_bsp
        esp_event
        heap
        esp_netif
        esp_wifi
        lvgl__lvgl
        nvs_flash
        pmicpower
        port_bsp
        waveshare__pcf85063a
)

set(PILOT_WIFI_SSID "$ENV{PILOT_WIFI_SSID}")
set(PILOT_WIFI_PASSWORD "$ENV{PILOT_WIFI_PASSWORD}")

target_compile_definitions(
    ${COMPONENT_LIB}
    PRIVATE
        "PILOT_WIFI_SSID=\"${PILOT_WIFI_SSID}\""
        "PILOT_WIFI_PASSWORD=\"${PILOT_WIFI_PASSWORD}\""
)

if(PILOT_WIFI_SSID)
    message(STATUS "Pilot display-node Wi-Fi credentials supplied outside source control")
else()
    message(WARNING "Pilot display-node will build without Wi-Fi credentials")
endif()

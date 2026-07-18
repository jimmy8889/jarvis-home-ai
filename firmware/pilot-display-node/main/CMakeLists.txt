idf_component_register(
    SRCS "main.cpp"
    INCLUDE_DIRS "."
    PRIV_REQUIRES
        app_bsp
        audio_bsp
        driver
        esp_event
        heap
        esp_netif
        esp_timer
        esp_wifi
        lvgl__lvgl
        motion_bsp
        nvs_flash
        pilot_client
        pmicpower
        port_bsp
        spiffs
        waveshare__pcf85063a
)

set(PILOT_WIFI_SSID "$ENV{PILOT_WIFI_SSID}")
set(PILOT_WIFI_PASSWORD "$ENV{PILOT_WIFI_PASSWORD}")
set(PILOT_CORE_URL "$ENV{PILOT_CORE_URL}")
set(PILOT_DEVICE_ID "$ENV{PILOT_DEVICE_ID}")
set(PILOT_DEVICE_TOKEN "$ENV{PILOT_DEVICE_TOKEN}")
set(PILOT_ROOM_NAME "$ENV{PILOT_ROOM_NAME}")

if(NOT PILOT_ROOM_NAME)
    set(PILOT_ROOM_NAME "BEDROOM")
endif()

target_compile_definitions(
    ${COMPONENT_LIB}
    PRIVATE
        "PILOT_WIFI_SSID=\"${PILOT_WIFI_SSID}\""
        "PILOT_WIFI_PASSWORD=\"${PILOT_WIFI_PASSWORD}\""
        "PILOT_CORE_URL=\"${PILOT_CORE_URL}\""
        "PILOT_DEVICE_ID=\"${PILOT_DEVICE_ID}\""
        "PILOT_DEVICE_TOKEN=\"${PILOT_DEVICE_TOKEN}\""
        "PILOT_ROOM_NAME=\"${PILOT_ROOM_NAME}\""
)

if(PILOT_WIFI_SSID)
    message(STATUS "Pilot display-node Wi-Fi credentials supplied outside source control")
else()
    message(WARNING "Pilot display-node will build without Wi-Fi credentials")
endif()

if(PILOT_CORE_URL AND PILOT_DEVICE_ID AND PILOT_DEVICE_TOKEN)
    message(STATUS "Pilot display-node Core credentials supplied outside source control")
else()
    message(WARNING "Pilot Core weather, voice, and OTA will be disabled")
endif()

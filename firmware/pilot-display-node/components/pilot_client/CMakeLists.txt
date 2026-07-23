idf_component_register(
    SRCS "pilot_client.cpp"
    INCLUDE_DIRS "."
    REQUIRES
        app_update
        audio_bsp
        esp_app_format
        esp_http_client
        esp_timer
        json
        mbedtls
        nvs_flash
        spiffs
)

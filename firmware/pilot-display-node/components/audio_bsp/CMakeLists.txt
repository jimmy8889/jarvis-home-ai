idf_component_register(
    SRCS "pilot_audio.cpp"
    INCLUDE_DIRS "."
    REQUIRES
        esp_codec_dev
        esp_driver_i2c
        esp_driver_i2s
)

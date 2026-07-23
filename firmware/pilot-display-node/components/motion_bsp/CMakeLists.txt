idf_component_register(
    SRCS "motion_bsp.cpp"
    INCLUDE_DIRS "."
    REQUIRES
        port_bsp
        waveshare__qmi8658
)

#pragma once

#include "esp_err.h"
#include "qmi8658.h"

#include "i2c_bsp.h"

struct MotionSample {
    float accel_x;
    float accel_y;
    float accel_z;
    float gyro_x;
    float gyro_y;
    float gyro_z;
};

class MotionSensor {
public:
    explicit MotionSensor(I2cMasterBus &bus);

    esp_err_t Initialize();
    esp_err_t Read(MotionSample *sample);
    bool Available() const { return available_; }

private:
    I2cMasterBus &bus_;
    qmi8658_dev_t device_ = {};
    bool available_ = false;
};

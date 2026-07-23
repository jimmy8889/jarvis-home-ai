#include "motion_bsp.h"

#include "esp_log.h"

namespace {
constexpr char kTag[] = "pilot_motion";
}

MotionSensor::MotionSensor(I2cMasterBus &bus) : bus_(bus) {
}

esp_err_t MotionSensor::Initialize() {
    esp_err_t result = qmi8658_init(
        &device_,
        bus_.Get_I2cBusHandle(),
        QMI8658_ADDRESS_HIGH
    );
    if (result != ESP_OK) {
        ESP_LOGW(kTag, "QMI8658 unavailable: %s", esp_err_to_name(result));
        return result;
    }

    result = qmi8658_set_accel_range(&device_, QMI8658_ACCEL_RANGE_4G);
    if (result == ESP_OK) {
        result = qmi8658_set_accel_odr(
            &device_, QMI8658_ACCEL_ODR_31_25HZ
        );
    }
    if (result == ESP_OK) {
        result = qmi8658_set_gyro_range(
            &device_, QMI8658_GYRO_RANGE_256DPS
        );
    }
    if (result == ESP_OK) {
        result = qmi8658_set_gyro_odr(
            &device_, QMI8658_GYRO_ODR_31_25HZ
        );
    }
    if (result == ESP_OK) {
        qmi8658_set_accel_unit_mps2(&device_, true);
        qmi8658_set_gyro_unit_rads(&device_, true);
        result = qmi8658_enable_sensors(
            &device_, QMI8658_ENABLE_ACCEL | QMI8658_ENABLE_GYRO
        );
    }
    available_ = result == ESP_OK;
    if (available_) {
        ESP_LOGI(kTag, "QMI8658 motion sensing enabled at 31.25 Hz");
    } else {
        ESP_LOGW(kTag, "QMI8658 configuration failed: %s", esp_err_to_name(result));
    }
    return result;
}

esp_err_t MotionSensor::Read(MotionSample *sample) {
    if (!available_ || sample == nullptr) {
        return ESP_ERR_INVALID_STATE;
    }
    qmi8658_data_t value = {};
    const esp_err_t result = qmi8658_read_sensor_data(&device_, &value);
    if (result == ESP_OK) {
        sample->accel_x = value.accelX;
        sample->accel_y = value.accelY;
        sample->accel_z = value.accelZ;
        sample->gyro_x = value.gyroX;
        sample->gyro_y = value.gyroY;
        sample->gyro_z = value.gyroZ;
    }
    return result;
}

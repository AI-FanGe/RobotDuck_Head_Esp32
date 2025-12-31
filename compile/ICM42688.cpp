// --- START OF ICM42688.cpp ---
#include "ICM42688.h"

ICM42688::ICM42688(TwoWire &bus, uint8_t address) {
  _bus = &bus;
  _address = address;
  _accelScale = 0.0f;
  _gyroScale = 0.0f;
}

int ICM42688::begin() {
  uint8_t who_am_i = 0;
  readRegisters(ICM42688_WHO_AM_I, 1, &who_am_i);
  if(who_am_i != ICM42688_DEVICE_ID) {
    return -1; // Wrong device
  }
  
  // Reset device
  writeRegister(0x4E, 0x01);
  delay(100);

  // Set accel and gyro to standby
  writeRegister(0x4E, 0x1F);
  delay(1);

  // Set accel full scale
  writeRegister(0x4F, (uint8_t)AFS::AFS_16G << 5 | (uint8_t)ODR::ODR_1KHZ);
  _accelScale = 16.0f / 32768.0f;

  // Set gyro full scale
  writeRegister(0x50, (uint8_t)GFS::GFS_2000DPS << 5 | (uint8_t)ODR::ODR_1KHZ);
  _gyroScale = 2000.0f / 32768.0f;

  // Turn on accel and gyro
  writeRegister(0x4E, 0x0F);
  delay(100);
  
  return 0;
}

int ICM42688::readSensor() {
  uint8_t data[14];
  readRegisters(0x1D, 14, data);

  _t =  (int16_t)data[0] << 8 | data[1];
  _ax = (int16_t)data[2] << 8 | data[3];
  _ay = (int16_t)data[4] << 8 | data[5];
  _az = (int16_t)data[6] << 8 | data[7];
  _gx = (int16_t)data[8] << 8 | data[9];
  _gy = (int16_t)data[10] << 8 | data[11];
  _gz = (int16_t)data[12] << 8 | data[13];
  
  return 0;
}

float ICM42688::getAccelX_mss() { return (float)_ax * _accelScale * _G; }
float ICM42688::getAccelY_mss() { return (float)_ay * _accelScale * _G; }
float ICM42688::getAccelZ_mss() { return (float)_az * _accelScale * _G; }

float ICM42688::getGyroX_rads() { return (float)_gx * _gyroScale * _d2r; }
float ICM42688::getGyroY_rads() { return (float)_gy * _gyroScale * _d2r; }
float ICM42688::getGyroZ_rads() { return (float)_gz * _gyroScale * _d2r; }

float ICM42688::getGyroX_dps() { return (float)_gx * _gyroScale; }
float ICM42688::getGyroY_dps() { return (float)_gy * _gyroScale; }
float ICM42688::getGyroZ_dps() { return (float)_gz * _gyroScale; }

float ICM42688::getTemperature_C() { return ((float)_t / _tempScale) + _tempOffset; }

void ICM42688::writeRegister(uint8_t reg, uint8_t data) {
  _bus->beginTransmission(_address);
  _bus->write(reg);
  _bus->write(data);
  _bus->endTransmission();
}

uint8_t ICM42688::readRegister(uint8_t reg) {
  _bus->beginTransmission(_address);
  _bus->write(reg);
  _bus->endTransmission(false);
  _bus->requestFrom(_address, (uint8_t)1);
  uint8_t data = _bus->read();
  return data;
}

void ICM42688::readRegisters(uint8_t reg, uint8_t count, uint8_t *dest) {
  _bus->beginTransmission(_address);
  _bus->write(reg);
  _bus->endTransmission(false);
  _bus->requestFrom(_address, count);
  for(uint8_t i = 0; i < count; i++){
    dest[i] = _bus->read();
  }
}
// --- END OF ICM42688.cpp ---
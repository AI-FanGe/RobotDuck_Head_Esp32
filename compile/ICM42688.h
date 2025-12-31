// --- START OF ICM42688.h ---
#ifndef ICM42688_H
#define ICM42688_H

#include "Arduino.h"
#include "Wire.h"
#include "SPI.h"

// See datasheet for details
#define ICM42688_DEVICE_ID 0x47 
#define ICM42688_WHO_AM_I  0x75

/*
 ICM42688_I2C class definition
 */
class ICM42688
{
  public:
    enum class AFS {
      AFS_16G = 0,
      AFS_8G,
      AFS_4G,
      AFS_2G
    };
    
    enum class GFS {
      GFS_2000DPS = 0,
      GFS_1000DPS,
      GFS_500DPS,
      GFS_250DPS,
      GFS_125DPS,
      GFS_62_5DPS,
      GFS_31_25DPS,
      GFS_15_625DPS
    };

    enum class ODR {
      ODR_32KHZ = 0x01,
      ODR_16KHZ = 0x02,
      ODR_8KHZ  = 0x03,
      ODR_4KHZ  = 0x04,
      ODR_2KHZ  = 0x05,
      ODR_1KHZ  = 0x06,
      ODR_200HZ = 0x07,
      ODR_100HZ = 0x08,
      ODR_50HZ  = 0x09,
      ODR_25HZ  = 0x0A,
      ODR_12_5HZ = 0x0B,
      ODR_500HZ = 0x0F
    };
    
    ICM42688(TwoWire &bus, uint8_t address);
    int begin();
    int readSensor();
    float getAccelX_mss();
    float getAccelY_mss();
    float getAccelZ_mss();
    float getGyroX_rads();
    float getGyroY_rads();
    float getGyroZ_rads();
    float getGyroX_dps();
    float getGyroY_dps();
    float getGyroZ_dps();
    float getTemperature_C();
    
  private:
    TwoWire *_bus;
    uint8_t _address;
    float _accelScale;
    float _gyroScale;
    const float _tempScale = 333.87f;
    const float _tempOffset = 21.0f;
    const float _G = 9.807f;
    const float _d2r = 3.14159265359f/180.0f;
    int16_t _ax, _ay, _az;
    int16_t _gx, _gy, _gz;
    int16_t _t;

    void writeRegister(uint8_t reg, uint8_t data);
    uint8_t readRegister(uint8_t reg);
    void readRegisters(uint8_t reg, uint8_t count, uint8_t *dest);
};

#endif
// --- END OF ICM42688.h ---
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

// ================= I2C 引脚（明确指定） =================
#define I2C_SDA 5   // XIAO ESP32-S3 A4 / SDA
#define I2C_SCL 6   // XIAO ESP32-S3 A5 / SCL

// ================= PCA9685 =================
#define PCA9685_ADDR 0x40
Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver(PCA9685_ADDR);

// ================= 舵机参数 =================
#define SERVO_MIN     102   // 0°
#define SERVO_MAX     512   // 180°
#define SERVO_CENTER  90    // 中立位 / 回正

#define SERVO_COUNT   16    // 实际舵机数量

// ================= 工具函数 =================
uint16_t angleToPulse(int angle) {
  return map(angle, 0, 180, SERVO_MIN, SERVO_MAX);
}

void setAllServos(int angle) {
  uint16_t pulse = angleToPulse(angle);
  for (int ch = 0; ch < SERVO_COUNT; ch++) {
    pwm.setPWM(ch, 0, pulse);
  }
}

void setup() {
  // I2C 初始化
  Wire.begin(I2C_SDA, I2C_SCL);

  // PCA9685 初始化
  pwm.begin();
  pwm.setPWMFreq(50);
  delay(500);

  // ========= 1️⃣ 上电先回中 =========
  setAllServos(SERVO_CENTER);
  delay(1000);

  // ========= 2️⃣ -45° ↔ +45° 摆动 10 次 =========
  for (int i = 0; i < 10; i++) {
    setAllServos(SERVO_CENTER + 15);  // +45°
    delay(500);

    setAllServos(SERVO_CENTER - 15);  // -45°
    delay(500);
  }

  // ========= 3️⃣ 明确、强制回到中立位 =========
  setAllServos(SERVO_CENTER);
  delay(1500);   // 给舵机充分时间稳定
}

void loop() {
  // 空循环：舵机保持在中立位
}

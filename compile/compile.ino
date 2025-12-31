// ===== all_in_one_face.ino — XIAO ESP32S3 Sense: Camera + Mic (PDM) + Speaker (I2S) + PCA9685 + SCServo =====
// ===== 功能：表情舵机(PCA9685) + 机械臂舵机(SCServo) + 摄像头WebSocket + 音频流 =====
// ===== I2S 接线：BCLK=8, LRCLK=7, DIN=9 | SCServo 接线：TX=43(D6), RX=44(D7) =====

#include <WiFi.h>
#include <esp_wifi.h>
#include <esp_system.h>
#include <esp_camera.h>
#include <ArduinoWebsockets.h>
#include "ESP_I2S.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include <cstring>
#include <WiFiClient.h>
#include <math.h>

// ---- 舵机相关 ----
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>
#include <WebServer.h>

// ---- 新增：SCServo 总线舵机（机械臂）----
#include <SCServo.h>

// ---- LED灯带已移除 ----

// ---- 新增：实时表情动画系统 ----
#include "face_animation.h"

using namespace websockets;

// ====================================================================
// WiFi / Server
// ====================================================================
const char* WIFI_SSID   = "shaliyun";
const char* WIFI_PASS   = "aiyanjiushi66";
const char* SERVER_HOST = "192.168.2.7";
const uint16_t SERVER_PORT = 8081;

static const char* CAM_WS_PATH = "/ws/camera";
static const char* AUD_WS_PATH = "/ws_audio";

// ====================================================================
// Camera config
// ====================================================================
#define CAMERA_MODEL_XIAO_ESP32S3
#include "camera_pins.h"

framesize_t g_frame_size = FRAMESIZE_VGA;
#define JPEG_QUALITY  17
#define FB_COUNT      2
volatile int g_target_fps = 0; // 0=不限，>0 则按该 FPS 限速

// 视频统计
volatile unsigned long frame_captured_count = 0;
volatile unsigned long frame_sent_count = 0;
volatile unsigned long frame_dropped_count = 0;
volatile unsigned long last_stats_time = 0;
volatile unsigned long ws_send_fail_count = 0;

// ====================================================================
// Mic (PDM RX)
// ====================================================================
#define I2S_MIC_CLOCK_PIN 42
#define I2S_MIC_DATA_PIN  41

const int SAMPLE_RATE     = 16000;
const int CHUNK_MS        = 20;
const int BYTES_PER_CHUNK = SAMPLE_RATE * CHUNK_MS / 1000 * 2;
const int AUDIO_QUEUE_DEPTH = 10;

// ====================================================================
// Speaker (I2S TX → MAX98357A) —— 按你现在的接线
// ====================================================================
// #define I2S_BCLK   8   // XIAO D9  -> MAX98357 BCLK
// #define I2S_LRCLK  7   // XIAO D8  -> MAX98357 LRC
// #define I2S_DOUT   9   // XIAO D10 -> MAX98357 DIN
#define I2S_SPK_BCLK 8   // BCLK
#define I2S_SPK_LRCK 7   // LRCLK
#define I2S_SPK_DIN  9   // DIN

const int TTS_RATE = 16000;

// ====================================================================
// 舵机: PCA9685 (I2C: SDA=5, SCL=6) - 表情控制
// ====================================================================
Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver();
#define SERVO_FREQ 50
const int SERVO_MIN = 150;   // 0° 脉宽，可微调
const int SERVO_MAX = 600;   // 180° 脉宽，可微调

// ====================================================================
// SCServo 总线舵机（机械臂）- 4 个舵机 ID 1-4
// ====================================================================
// 引脚定义（XIAO ESP32S3）
static const int ARM_BUS_TX = 43;        // XIAO D6
static const int ARM_BUS_RX = 44;        // XIAO D7
static const uint32_t ARM_BUS_BAUD = 1000000;

static const int ARM_DEFAULT_SPEED = 800;
static const int ARM_DEFAULT_ACC   = 30;

SMS_STS armServo;  // SCServo 实例

// 机械臂舵机标定范围
struct ArmServoLimit { int minV; int midV; int maxV; };
static ArmServoLimit ARM_LIMITS[5] = {
  {0, 0, 0},              // ID 0 不使用
  {1050, 2025, 3000},     // ID 1: 左右旋转
  {1500, 2047, 2500},     // ID 2: 前后俯仰
  {1500, 2047, 2500},     // ID 3: 上下俯仰
  {1800, 2047, 2300},     // ID 4: 末端
};

static int armLastPos[5] = {0, 2025, 2047, 2047, 2047};  // 记录上次位置

// 机械臂舵机控制函数（移除 static，供 face_animation.h 调用）
int armClampPos(int id, int pos) {
  if (id < 1 || id > 4) return pos;
  if (pos < ARM_LIMITS[id].minV) pos = ARM_LIMITS[id].minV;
  if (pos > ARM_LIMITS[id].maxV) pos = ARM_LIMITS[id].maxV;
  return pos;
}

void armMoveServo(int id, int pos, int speed, int acc) {
  if (id < 1 || id > 4) return;
  pos = armClampPos(id, pos);
  speed = constrain(speed, 50, 2000);
  acc   = constrain(acc, 0, 255);
  armServo.WritePosEx(id, pos, speed, acc);
  armLastPos[id] = pos;
}

static void armBusBegin() {
  Serial.printf("[ARM-BUS] Serial1 begin: baud=%lu, RX=%d, TX=%d\n",
                (unsigned long)ARM_BUS_BAUD, ARM_BUS_RX, ARM_BUS_TX);
  Serial1.begin(ARM_BUS_BAUD, SERIAL_8N1, ARM_BUS_RX, ARM_BUS_TX);
  Serial1.setTimeout(10);
  armServo.pSerial = &Serial1;
  delay(200);
  Serial.println("[ARM-BUS] SCServo Ready.");
}

// 嘴部舵机（通道8）实时音量驱动
const uint8_t  MOUTH_SERVO_CH        = 9;    // 嘴巴舵机通道改为9
const int      MOUTH_CLOSED_ANGLE    = 29;   // 嘴巴闭合角度
const int      MOUTH_OPEN_ANGLE      = 85;   // 嘴巴最大张开角度
const uint32_t MOUTH_START_DELAY_MS  = 0;
const float    MOUTH_LEVEL_GAMMA     = 0.55f; // 降低gamma让中低音量也能张大嘴
const float    MOUTH_LEVEL_GAIN      = 1.45f; // 提高增益让嘴巴张得更大
TaskHandle_t   mouthTaskHandle       = nullptr;
volatile bool  mouthActive           = false;
volatile bool  mouthPending          = false;
uint32_t       mouthStartDueMs       = 0;
volatile float mouthLevelTarget      = 0.0f;
volatile uint32_t mouthLevelTimestamp = 0;

// ====================================================================
// LED灯带已移除 - 硬件中无LED
// ====================================================================

// 空函数桩（保持接口兼容）
void updateOfflineBreathLed(uint32_t now, EmotionType currentEmo) { }
void enableOfflineBreathLed() { }
void disableOfflineBreathLed() { }

// ====================================================================
// 表情系统：关键帧动画（存储在 ESP32 Flash）
// ====================================================================
#include <Preferences.h>

#define MAX_KEYFRAMES 10       // 每个表情最多10个关键帧
#define MAX_EXPRESSIONS 20     // 最多20个表情
#define SERVO_COUNT 16         // 舵机数量
#define EXPR_NAME_LEN 20       // 表情名称最大长度

// 舵机通道标签（方便调试）
const char* SERVO_LABELS[16] = {
  "CH00", "CH01", "CH02", "CH03", "CH04", "CH05", "CH06", "CH07",
  "嘴巴", "眼球上下", "眼球左右R", "眼皮旋转R", "眼皮眨眼R", "眼球左右L", "眼皮旋转L", "眼皮眨眼L"
};

// 关键帧结构：所有舵机的角度 + 持续时间
struct Keyframe {
  int8_t angles[SERVO_COUNT];  // -1 表示不控制该舵机
  uint16_t duration_ms;        // 过渡到此帧的时间（毫秒）
};

// 表情结构：名称 + 关键帧序列（存储在 Flash）
struct ExpressionData {
  char name[EXPR_NAME_LEN];    // 表情名称
  uint8_t keyframe_count;      // 关键帧数量
  Keyframe keyframes[MAX_KEYFRAMES];
  bool loop;                   // 是否循环播放
  bool valid;                  // 是否有效（用于标记已删除）
};

// 表情存储（RAM 缓存，从 Flash 加载）
ExpressionData expressions[MAX_EXPRESSIONS];
int expressionCount = 0;

// Preferences 用于 Flash 存储
Preferences exprPrefs;

// 表情播放状态
volatile bool exprPlaying = false;
volatile int exprCurrentIndex = -1;
volatile int exprCurrentKeyframe = 0;
volatile uint32_t exprKeyframeStartTime = 0;
float exprServoCurrentAngles[SERVO_COUNT];  // 当前插值角度
int exprServoTargetAngles[SERVO_COUNT];     // 目标角度
TaskHandle_t exprTaskHandle = nullptr;

WebServer server(80);        // HTTP: /servo 控制舵机

// 设置舵机角度
// ★ 优化：关闭串口日志以防止阻塞 I2S 播放任务
#define SERVO_DEBUG 0  // 设为1开启调试日志，0关闭（避免串口阻塞影响音频）

void setServoAngle(uint8_t ch, int angleDeg) {
  static int lastAngles[16] = {-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1};
  
  angleDeg = constrain(angleDeg, 0, 180);
  int pulselen = map(angleDeg, 0, 180, SERVO_MIN, SERVO_MAX);
  pwm.setPWM(ch, 0, pulselen);
  
#if SERVO_DEBUG
  // 只有角度变化时才打印日志
  if (lastAngles[ch] != angleDeg) {
    Serial.printf("[SERVO] ch=%d angle=%d pulselen=%d\n", ch, angleDeg, pulselen);
  }
#endif
  lastAngles[ch] = angleDeg;
}

// /id 用于识别设备
void handleId() {
  server.send(200, "text/plain", "ESP32_FACE_V1");
}

// 根路径
void handleRoot() {
  String msg = "ESP32 face controller online.\n";
  msg += "Use /servo?ch=0&angle=90\n";
  server.send(200, "text/plain", msg);
}

// /servo?ch=0&angle=90
void handleServo() {
  Serial.println("[HTTP] /servo");

  if (!server.hasArg("ch") || !server.hasArg("angle")) {
    server.send(400, "text/plain", "Missing ch or angle parameter");
    return;
  }

  int ch    = server.arg("ch").toInt();
  int angle = server.arg("angle").toInt();

  if (ch < 0 || ch > 15) {
    server.send(400, "text/plain", "ch must be 0-15");
    return;
  }

  angle = constrain(angle, 0, 180);
  setServoAngle((uint8_t)ch, angle);

  String msg = "OK: ch=" + String(ch) + " angle=" + String(angle);
  server.send(200, "text/plain", msg);
}

// ====================================================================
// 最高优先级舵机控制（供树莓派使用，覆盖动画系统）
// ====================================================================
// 舵机安全限制表（每个通道的 min, max）
const int SERVO_LIMITS[16][2] = {
  {0, 180},    // CH 0: 通用
  {0, 180},    // CH 1: 通用
  {0, 180},    // CH 2: 通用
  {0, 180},    // CH 3: 通用
  {0, 180},    // CH 4: 通用
  {40, 120},   // CH 5: 右翅膀 (40上 - 120下)
  {60, 140},   // CH 6: 左翅膀 (140上 - 60下)
  {40, 90},    // CH 7: 屁股 (40翘起 - 90低垂)
  {60, 120},   // CH 8: 眼睛上下
  {29, 85},    // CH 9: 嘴巴
  {30, 140},   // CH 10: 眼球左右(左)
  {30, 140},   // CH 11: 眼球左右(右)
  {50, 130},   // CH 12: 眼皮眨眼(左)
  {50, 130},   // CH 13: 眼皮眨眼(右)
  {45, 135},   // CH 14: 眼皮旋转(左)
  {45, 135},   // CH 15: 眼皮旋转(右)
};

// 最高优先级舵机控制 HTTP 接口
// URL: /servo_priority?ch=<0-15>&angle=<角度>&duration=<毫秒>
// duration 可选，默认 2000ms（2秒后自动释放控制权）
// 设置 duration=0 表示立即控制一次但不保持（即 duration=1）
void handleServoPriority() {
  Serial.println("[HTTP] /servo_priority");

  if (!server.hasArg("ch") || !server.hasArg("angle")) {
    server.send(400, "text/plain", "Missing ch or angle parameter");
    return;
  }

  int ch = server.arg("ch").toInt();
  int angle = server.arg("angle").toInt();
  uint32_t duration = server.hasArg("duration") ? server.arg("duration").toInt() : 2000;

  if (ch < 0 || ch > 15) {
    server.send(400, "text/plain", "ch must be 0-15");
    return;
  }

  // 安全限制
  int minAngle = SERVO_LIMITS[ch][0];
  int maxAngle = SERVO_LIMITS[ch][1];
  angle = constrain(angle, minAngle, maxAngle);

  // 设置外部优先控制
  setExternalServoControl((uint8_t)ch, angle, duration > 0 ? duration : 1);

  String msg = "OK: ch=" + String(ch) + " angle=" + String(angle) + 
               " (limit " + String(minAngle) + "-" + String(maxAngle) + ")" +
               " duration=" + String(duration) + "ms";
  server.send(200, "text/plain", msg);
}

// 释放优先级控制
// URL: /servo_release?ch=<0-15> 或 /servo_release?all=1
void handleServoRelease() {
  Serial.println("[HTTP] /servo_release");

  if (server.hasArg("all") && server.arg("all") == "1") {
    // 释放所有通道
    for (int i = 0; i < 16; i++) {
      releaseExternalServoControl((uint8_t)i);
    }
    server.send(200, "text/plain", "OK: All channels released");
    return;
  }

  if (!server.hasArg("ch")) {
    server.send(400, "text/plain", "Missing ch parameter (or use all=1)");
    return;
  }

  int ch = server.arg("ch").toInt();
  if (ch < 0 || ch > 15) {
    server.send(400, "text/plain", "ch must be 0-15");
    return;
  }

  releaseExternalServoControl((uint8_t)ch);
  server.send(200, "text/plain", "OK: ch=" + String(ch) + " released");
}

// 批量控制多个舵机
// URL: /servo_batch?data=<ch1>,<angle1>,<duration1>;<ch2>,<angle2>,<duration2>;...
void handleServoBatch() {
  Serial.println("[HTTP] /servo_batch");

  if (!server.hasArg("data")) {
    server.send(400, "text/plain", "Missing data parameter. Format: ch1,angle1,duration1;ch2,angle2,duration2;...");
    return;
  }

  String data = server.arg("data");
  int count = 0;
  String result = "OK: ";

  int startIdx = 0;
  while (startIdx < data.length()) {
    int endIdx = data.indexOf(';', startIdx);
    if (endIdx == -1) endIdx = data.length();

    String segment = data.substring(startIdx, endIdx);
    int comma1 = segment.indexOf(',');
    int comma2 = segment.indexOf(',', comma1 + 1);

    if (comma1 > 0) {
      int ch = segment.substring(0, comma1).toInt();
      int angle = segment.substring(comma1 + 1, comma2 > 0 ? comma2 : segment.length()).toInt();
      uint32_t duration = comma2 > 0 ? segment.substring(comma2 + 1).toInt() : 2000;

      if (ch >= 0 && ch <= 15) {
        // 安全限制
        angle = constrain(angle, SERVO_LIMITS[ch][0], SERVO_LIMITS[ch][1]);
        setExternalServoControl((uint8_t)ch, angle, duration > 0 ? duration : 1);
        result += "ch" + String(ch) + "=" + String(angle) + " ";
        count++;
      }
    }

    startIdx = endIdx + 1;
  }

  result += "(" + String(count) + " servos)";
  server.send(200, "text/plain", result);
}

// ====================================================================
// 机械臂 HTTP 接口（SCServo 总线舵机）
// ====================================================================

// /arm/status - 获取机械臂状态
void handleArmStatus() {
  String json = "{";
  json += "\"ip\":\"" + WiFi.localIP().toString() + "\",";
  json += "\"arm_ready\":true,";
  json += "\"p1\":" + String(armLastPos[1]) + ",";
  json += "\"p2\":" + String(armLastPos[2]) + ",";
  json += "\"p3\":" + String(armLastPos[3]) + ",";
  json += "\"p4\":" + String(armLastPos[4]);
  json += "}";
  server.send(200, "application/json", json);
}

// /arm/servo?id=1&pos=2000&speed=800&acc=30 - 控制单个机械臂舵机
void handleArmServoSingle() {
  if (!server.hasArg("id") || !server.hasArg("pos")) {
    server.send(400, "text/plain", "Missing id or pos");
    return;
  }
  int id = server.arg("id").toInt();
  int pos = server.arg("pos").toInt();
  int speed = server.hasArg("speed") ? server.arg("speed").toInt() : ARM_DEFAULT_SPEED;
  int acc   = server.hasArg("acc")   ? server.arg("acc").toInt()   : ARM_DEFAULT_ACC;

  armMoveServo(id, pos, speed, acc);
  server.send(200, "text/plain", "OK");
}

// /arm/batch?p1=..&p2=..&p3=..&p4=..&speed=..&acc=.. - 批量控制机械臂
void handleArmBatch() {
  if (!server.hasArg("p1") || !server.hasArg("p2") || !server.hasArg("p3") || !server.hasArg("p4")) {
    server.send(400, "text/plain", "Missing p1/p2/p3/p4");
    return;
  }

  int p1 = server.arg("p1").toInt();
  int p2 = server.arg("p2").toInt();
  int p3 = server.arg("p3").toInt();
  int p4 = server.arg("p4").toInt();
  int speed = server.hasArg("speed") ? server.arg("speed").toInt() : ARM_DEFAULT_SPEED;
  int acc   = server.hasArg("acc")   ? server.arg("acc").toInt()   : ARM_DEFAULT_ACC;

  armMoveServo(1, p1, speed, acc);
  armMoveServo(2, p2, speed, acc);
  armMoveServo(3, p3, speed, acc);
  armMoveServo(4, p4, speed, acc);

  server.send(200, "text/plain", "OK");
}

// ====================================================================
// 表情播放引擎（Flash 存储版）
// ====================================================================

// 从 Flash 加载所有表情
void loadExpressionsFromFlash() {
  exprPrefs.begin("expressions", true);  // 只读模式
  expressionCount = exprPrefs.getInt("count", 0);
  
  for (int i = 0; i < expressionCount && i < MAX_EXPRESSIONS; i++) {
    String key = "expr" + String(i);
    size_t len = exprPrefs.getBytesLength(key.c_str());
    if (len == sizeof(ExpressionData)) {
      exprPrefs.getBytes(key.c_str(), &expressions[i], sizeof(ExpressionData));
      Serial.printf("[EXPR] Loaded: %s (%d frames)\n", expressions[i].name, expressions[i].keyframe_count);
    }
  }
  exprPrefs.end();
  Serial.printf("[EXPR] Total loaded: %d expressions\n", expressionCount);
}

// 保存所有表情到 Flash
void saveExpressionsToFlash() {
  exprPrefs.begin("expressions", false);  // 读写模式
  exprPrefs.putInt("count", expressionCount);
  
  for (int i = 0; i < expressionCount; i++) {
    String key = "expr" + String(i);
    exprPrefs.putBytes(key.c_str(), &expressions[i], sizeof(ExpressionData));
  }
  exprPrefs.end();
  Serial.printf("[EXPR] Saved %d expressions to Flash\n", expressionCount);
}

// 保存单个表情到 Flash
void saveExpressionToFlash(int index) {
  if (index < 0 || index >= MAX_EXPRESSIONS) return;
  
  exprPrefs.begin("expressions", false);
  String key = "expr" + String(index);
  exprPrefs.putBytes(key.c_str(), &expressions[index], sizeof(ExpressionData));
  if (index >= expressionCount) {
    expressionCount = index + 1;
    exprPrefs.putInt("count", expressionCount);
  }
  exprPrefs.end();
  Serial.printf("[EXPR] Saved expression %d: %s\n", index, expressions[index].name);
}

// 删除表情
void deleteExpression(int index) {
  if (index < 0 || index >= expressionCount) return;
  
  // 移动后面的表情
  for (int i = index; i < expressionCount - 1; i++) {
    memcpy(&expressions[i], &expressions[i + 1], sizeof(ExpressionData));
  }
  expressionCount--;
  
  // 保存到 Flash
  saveExpressionsToFlash();
  Serial.printf("[EXPR] Deleted expression %d\n", index);
}

// 清空所有表情
void clearAllExpressions() {
  expressionCount = 0;
  exprPrefs.begin("expressions", false);
  exprPrefs.clear();
  exprPrefs.end();
  Serial.println("[EXPR] All expressions cleared");
}

// 初始化表情系统
void initExpressionSystem() {
  for (int i = 0; i < SERVO_COUNT; i++) {
    exprServoCurrentAngles[i] = 90.0f;
    exprServoTargetAngles[i] = 90;
  }
  // 从 Flash 加载表情
  loadExpressionsFromFlash();
  
  // 注意：表情动画现在由 face_animation.h 实时控制
  // 不再需要预设关键帧表情
}

// ====================================================================
// 注意：表情动画现在由 face_animation.h 实时控制
// 支持的表情：idle（自动）, angry, sad, happy, speechless, wink, normal
// 所有参数和逻辑与 test.py 完全一致
// ====================================================================

// 播放指定表情（按名称）
void playExpressionByName(const char* name) {
  for (int i = 0; i < expressionCount; i++) {
    if (expressions[i].valid && strcmp(expressions[i].name, name) == 0) {
      playExpression(i);
      return;
    }
  }
  Serial.printf("[EXPR] Unknown expression: %s\n", name);
}

// 播放指定表情（按索引）
void playExpression(int index) {
  if (index < 0 || index >= expressionCount || !expressions[index].valid) {
    Serial.printf("[EXPR] Invalid index: %d\n", index);
    return;
  }
  
  exprCurrentIndex = index;
  exprCurrentKeyframe = 0;
  exprKeyframeStartTime = millis();
  exprPlaying = true;
  
  // 设置第一帧的目标角度
  const Keyframe& kf = expressions[index].keyframes[0];
  for (int i = 0; i < SERVO_COUNT; i++) {
    if (kf.angles[i] >= 0) {
      exprServoTargetAngles[i] = kf.angles[i];
    }
  }
  
  Serial.printf("[EXPR] Playing: %s (frames=%d)\n", 
                expressions[index].name, 
                expressions[index].keyframe_count);
}

// 停止表情播放
void stopExpression() {
  exprPlaying = false;
  exprCurrentIndex = -1;
  Serial.println("[EXPR] Stopped");
}

// 表情播放任务（在主循环中调用）
void updateExpression() {
  if (!exprPlaying || exprCurrentIndex < 0) return;
  
  ExpressionData& expr = expressions[exprCurrentIndex];
  const Keyframe& kf = expr.keyframes[exprCurrentKeyframe];
  
  uint32_t elapsed = millis() - exprKeyframeStartTime;
  float progress = (kf.duration_ms > 0) ? min(1.0f, (float)elapsed / kf.duration_ms) : 1.0f;
  
  // 平滑插值（使用 ease-in-out）
  float smoothProgress = progress < 0.5f 
    ? 2.0f * progress * progress 
    : 1.0f - powf(-2.0f * progress + 2.0f, 2) / 2.0f;
  
  // 更新舵机角度
  for (int i = 0; i < SERVO_COUNT; i++) {
    if (kf.angles[i] >= 0) {
      float target = (float)exprServoTargetAngles[i];
      exprServoCurrentAngles[i] += (target - exprServoCurrentAngles[i]) * smoothProgress * 0.3f;
      
      // 只在表情播放时控制舵机（嘴巴通道8除外，由音频驱动）
      if (i != MOUTH_SERVO_CH || !mouthActive) {
        setServoAngle(i, (int)(exprServoCurrentAngles[i] + 0.5f));
      }
    }
  }
  
  // 检查是否需要切换到下一帧
  if (elapsed >= kf.duration_ms) {
    exprCurrentKeyframe++;
    
    if (exprCurrentKeyframe >= expr.keyframe_count) {
      // 表情播放完成
      if (expr.loop) {
        exprCurrentKeyframe = 0;
      } else {
        exprPlaying = false;
        exprCurrentIndex = -1;
        Serial.printf("[EXPR] Finished: %s\n", expr.name);
        return;
      }
    }
    
    // 设置下一帧的目标角度
    exprKeyframeStartTime = millis();
    const Keyframe& nextKf = expr.keyframes[exprCurrentKeyframe];
    for (int i = 0; i < SERVO_COUNT; i++) {
      if (nextKf.angles[i] >= 0) {
        exprServoTargetAngles[i] = nextKf.angles[i];
      }
    }
  }
}

// HTTP: /expression - 表情管理 API
void handleExpression() {
  Serial.println("[HTTP] /expression");
  
  // 播放表情
  if (server.hasArg("play")) {
    String name = server.arg("play");
    playExpressionByName(name.c_str());
    server.send(200, "text/plain", "OK: playing " + name);
    return;
  }
  
  // 播放表情（按ID）
  if (server.hasArg("id")) {
    int id = server.arg("id").toInt();
    playExpression(id);
    server.send(200, "text/plain", "OK: playing id=" + String(id));
    return;
  }
  
  // 停止播放
  if (server.hasArg("stop")) {
    stopExpression();
    server.send(200, "text/plain", "OK: stopped");
    return;
  }
  
  // 删除表情
  if (server.hasArg("delete")) {
    int id = server.arg("delete").toInt();
    deleteExpression(id);
    server.send(200, "text/plain", "OK: deleted " + String(id));
    return;
  }
  
  // 清空所有
  if (server.hasArg("clear")) {
    clearAllExpressions();
    server.send(200, "text/plain", "OK: all cleared");
    return;
  }
  
  // 获取表情列表
  String json = "{\"count\":" + String(expressionCount) + ",\"expressions\":[";
  for (int i = 0; i < expressionCount; i++) {
    if (i > 0) json += ",";
    json += "{\"id\":" + String(i);
    json += ",\"name\":\"" + String(expressions[i].name) + "\"";
    json += ",\"frames\":" + String(expressions[i].keyframe_count);
    json += ",\"loop\":" + String(expressions[i].loop ? "true" : "false");
    json += "}";
  }
  json += "]}";
  server.send(200, "application/json", json);
}

// 辅助函数：找到匹配的右括号位置（支持嵌套）
int findMatchingBracket(const String& str, int startPos, char openBracket, char closeBracket) {
  int depth = 1;
  for (int i = startPos; i < str.length(); i++) {
    char c = str.charAt(i);
    if (c == openBracket) depth++;
    else if (c == closeBracket) {
      depth--;
      if (depth == 0) return i;
    }
  }
  return -1;
}

// HTTP: /expr_save - 保存表情（POST JSON）
void handleExpressionSave() {
  Serial.println("[HTTP] /expr_save");
  
  if (server.method() != HTTP_POST) {
    server.send(405, "text/plain", "POST only");
    return;
  }
  
  String body = server.arg("plain");
  Serial.printf("[EXPR] Received (%d bytes): %s\n", body.length(), body.c_str());
  
  // 简单 JSON 解析（手动解析避免引入库）
  // 格式: {"name":"xxx","loop":false,"keyframes":[{"duration":300,"angles":[90,90,...]},...]}
  
  ExpressionData newExpr;
  memset(&newExpr, 0, sizeof(newExpr));
  newExpr.valid = true;
  
  // 解析 name
  int nameStart = body.indexOf("\"name\":\"") + 8;
  int nameEnd = body.indexOf("\"", nameStart);
  if (nameStart > 7 && nameEnd > nameStart) {
    String name = body.substring(nameStart, nameEnd);
    name.toCharArray(newExpr.name, EXPR_NAME_LEN);
    Serial.printf("[EXPR] Parsed name: %s\n", newExpr.name);
  }
  
  // 解析 loop
  newExpr.loop = body.indexOf("\"loop\":true") >= 0;
  Serial.printf("[EXPR] Parsed loop: %d\n", newExpr.loop);
  
  // 解析 keyframes - 修复嵌套数组问题
  int kfArrayStart = body.indexOf("\"keyframes\":[");
  if (kfArrayStart >= 0) {
    int kfContentStart = kfArrayStart + 13;  // 跳过 "keyframes":[
    int kfArrayEnd = findMatchingBracket(body, kfContentStart, '[', ']');
    
    if (kfArrayEnd > kfContentStart) {
      String kfStr = body.substring(kfContentStart, kfArrayEnd);
      Serial.printf("[EXPR] Keyframes string length: %d\n", kfStr.length());
      
      int frameIdx = 0;
      int pos = 0;
      
      while (frameIdx < MAX_KEYFRAMES && pos < kfStr.length()) {
        // 找到下一个 { 开始的关键帧对象
        int objStart = kfStr.indexOf("{", pos);
        if (objStart < 0) break;
        
        // 找到匹配的 } （使用辅助函数处理嵌套）
        int objEnd = findMatchingBracket(kfStr, objStart + 1, '{', '}');
        if (objEnd < 0) break;
        
        String frameStr = kfStr.substring(objStart, objEnd + 1);
        Serial.printf("[EXPR] Frame %d: %s\n", frameIdx, frameStr.c_str());
        
        // 解析 duration
        int durStart = frameStr.indexOf("\"duration\":") + 11;
        if (durStart > 10) {
          int durEnd = durStart;
          while (durEnd < frameStr.length()) {
            char c = frameStr.charAt(durEnd);
            if (c == ',' || c == '}' || c == ' ') break;
            durEnd++;
          }
          String durVal = frameStr.substring(durStart, durEnd);
          durVal.trim();
          newExpr.keyframes[frameIdx].duration_ms = durVal.toInt();
          Serial.printf("[EXPR] Frame %d duration: %d\n", frameIdx, newExpr.keyframes[frameIdx].duration_ms);
        }
        
        // 解析 angles 数组
        int angStart = frameStr.indexOf("\"angles\":[");
        if (angStart >= 0) {
          angStart += 10;  // 跳过 "angles":[
          int angEnd = findMatchingBracket(frameStr, angStart, '[', ']');
          if (angEnd > angStart) {
            String angStr = frameStr.substring(angStart, angEnd);
            
            int angIdx = 0;
            int apos = 0;
            while (angIdx < SERVO_COUNT && apos < angStr.length()) {
              // 跳过空格
              while (apos < angStr.length() && (angStr.charAt(apos) == ' ' || angStr.charAt(apos) == '\n' || angStr.charAt(apos) == '\r')) apos++;
              if (apos >= angStr.length()) break;
              
              int comma = angStr.indexOf(",", apos);
              String val;
              if (comma < 0) {
                val = angStr.substring(apos);
                apos = angStr.length();
              } else {
                val = angStr.substring(apos, comma);
                apos = comma + 1;
              }
              val.trim();
              if (val.length() > 0) {
                newExpr.keyframes[frameIdx].angles[angIdx] = val.toInt();
                angIdx++;
              }
            }
            // 填充剩余为 -1
            while (angIdx < SERVO_COUNT) {
              newExpr.keyframes[frameIdx].angles[angIdx++] = -1;
            }
            Serial.printf("[EXPR] Frame %d parsed %d angles\n", frameIdx, angIdx);
          }
        }
        
        frameIdx++;
        pos = objEnd + 1;
      }
      newExpr.keyframe_count = frameIdx;
      Serial.printf("[EXPR] Total keyframes parsed: %d\n", frameIdx);
    }
  }
  
  // 验证解析结果
  if (newExpr.keyframe_count == 0) {
    Serial.println("[EXPR] ERROR: No keyframes parsed!");
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"no keyframes parsed\"}");
    return;
  }
  
  // 检查是否已存在同名表情（更新）
  int existIdx = -1;
  for (int i = 0; i < expressionCount; i++) {
    if (strcmp(expressions[i].name, newExpr.name) == 0) {
      existIdx = i;
      break;
    }
  }
  
  if (existIdx >= 0) {
    // 更新现有表情
    memcpy(&expressions[existIdx], &newExpr, sizeof(ExpressionData));
    saveExpressionToFlash(existIdx);
    Serial.printf("[EXPR] Updated expression %d: %s with %d frames\n", existIdx, newExpr.name, newExpr.keyframe_count);
    server.send(200, "application/json", "{\"ok\":true,\"id\":" + String(existIdx) + ",\"action\":\"updated\",\"frames\":" + String(newExpr.keyframe_count) + "}");
  } else if (expressionCount < MAX_EXPRESSIONS) {
    // 添加新表情
    memcpy(&expressions[expressionCount], &newExpr, sizeof(ExpressionData));
    saveExpressionToFlash(expressionCount);
    Serial.printf("[EXPR] Created expression %d: %s with %d frames\n", expressionCount, newExpr.name, newExpr.keyframe_count);
    expressionCount++;
    server.send(200, "application/json", "{\"ok\":true,\"id\":" + String(expressionCount - 1) + ",\"action\":\"created\",\"frames\":" + String(newExpr.keyframe_count) + "}");
  } else {
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"max expressions reached\"}");
  }
}

// HTTP: /expr_get?id=0 - 获取表情详情
void handleExpressionGet() {
  if (!server.hasArg("id")) {
    server.send(400, "text/plain", "Missing id");
    return;
  }
  
  int id = server.arg("id").toInt();
  if (id < 0 || id >= expressionCount) {
    server.send(404, "text/plain", "Not found");
    return;
  }
  
  ExpressionData& expr = expressions[id];
  String json = "{\"name\":\"" + String(expr.name) + "\"";
  json += ",\"loop\":" + String(expr.loop ? "true" : "false");
  json += ",\"keyframes\":[";
  
  for (int i = 0; i < expr.keyframe_count; i++) {
    if (i > 0) json += ",";
    json += "{\"duration\":" + String(expr.keyframes[i].duration_ms);
    json += ",\"angles\":[";
    for (int j = 0; j < SERVO_COUNT; j++) {
      if (j > 0) json += ",";
      json += String(expr.keyframes[i].angles[j]);
    }
    json += "]}";
  }
  json += "]}";
  
  server.send(200, "application/json", json);
}

// HTTP: /expr_editor - 表情编辑器页面（保存到 ESP32 Flash）
void handleExpressionEditor() {
  String html = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>表情编辑器 - ESP32 存储</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Segoe UI', sans-serif; background: #1a1a2e; color: #eee; padding: 15px; }
    h1 { color: #ffd700; margin-bottom: 15px; font-size: 22px; }
    .container { display: flex; gap: 15px; flex-wrap: wrap; }
    .panel { background: #16213e; border-radius: 10px; padding: 12px; }
    .panel h2 { color: #00d4ff; margin-bottom: 12px; font-size: 14px; border-bottom: 1px solid #333; padding-bottom: 8px; }
    .servo-row { display: flex; align-items: center; margin-bottom: 6px; gap: 4px; }
    .servo-label { width: 80px; font-size: 11px; color: #aaa; }
    .servo-slider { flex: 1; margin: 0 4px; }
    .servo-value { width: 30px; text-align: center; font-family: monospace; font-size: 11px; }
    .servo-check { margin-right: 2px; }
    .servo-limit { width: 35px; padding: 2px; font-size: 10px; background: #0a2040; border: 1px solid #333; color: #888; border-radius: 2px; text-align: center; }
    .servo-limit:focus { border-color: #ffd700; color: #fff; }
    input[type="range"] { -webkit-appearance: none; background: #0f3460; height: 5px; border-radius: 3px; }
    input[type="range"]::-webkit-slider-thumb { -webkit-appearance: none; width: 14px; height: 14px; background: #ffd700; border-radius: 50%; cursor: pointer; }
    .btn { background: #ffd700; color: #000; border: none; padding: 8px 14px; border-radius: 4px; cursor: pointer; font-weight: bold; margin: 3px; font-size: 12px; }
    .btn:hover { background: #ffed4a; }
    .btn:disabled { background: #666; cursor: not-allowed; }
    .btn-danger { background: #e94560; color: #fff; }
    .btn-success { background: #00d4ff; color: #000; }
    .btn-save { background: #00ff88; color: #000; }
    .btn-small { padding: 4px 8px; font-size: 10px; }
    .keyframes { max-height: 250px; overflow-y: auto; margin-bottom: 10px; }
    .keyframe { background: #0f3460; padding: 8px; margin-bottom: 4px; border-radius: 4px; display: flex; justify-content: space-between; align-items: center; font-size: 11px; }
    .keyframe.active { border: 2px solid #ffd700; }
    .input-row { display: flex; gap: 8px; margin-bottom: 8px; align-items: center; }
    .input-row label { width: 70px; font-size: 12px; }
    .input-row input, .input-row select { flex: 1; padding: 6px; background: #0f3460; border: 1px solid #333; color: #fff; border-radius: 3px; font-size: 12px; }
    .saved-list { max-height: 200px; overflow-y: auto; }
    .saved-item { background: #0f3460; padding: 8px; margin-bottom: 4px; border-radius: 4px; display: flex; justify-content: space-between; align-items: center; font-size: 12px; }
    .saved-item:hover { background: #1a4a7a; }
    .status { padding: 8px; border-radius: 4px; margin-top: 10px; font-size: 12px; }
    .status.success { background: #00ff8833; border: 1px solid #00ff88; }
    .status.error { background: #ff000033; border: 1px solid #ff0000; }
    .checkbox-row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
    .checkbox-row input { width: auto; }
    .limit-header { display: flex; align-items: center; gap: 4px; font-size: 10px; color: #666; margin-bottom: 4px; padding-left: 100px; }
    .limit-header span { width: 35px; text-align: center; }
  </style>
</head>
<body>
  <h1>🎭 表情编辑器 <small style="color:#888;font-size:12px;">(保存到 ESP32 Flash)</small></h1>
  
  <div class="container">
    <!-- 左侧：舵机控制 -->
    <div class="panel" style="flex: 2; min-width: 380px;">
      <h2>🎚️ 舵机实时控制 <span style="font-size:10px;color:#888;margin-left:10px;">拖动滑杆实时控制舵机</span></h2>
      <div class="limit-header">
        <span style="flex:1;"></span>
        <span>最小</span>
        <span style="width:30px;"></span>
        <span>最大</span>
      </div>
      <div id="servos"></div>
      <div style="margin-top: 10px;">
        <button class="btn" onclick="captureKeyframe()">📷 捕获关键帧</button>
        <button class="btn btn-success" onclick="resetServos()">🔄 全部归中</button>
        <button class="btn btn-small" onclick="saveLimits()">💾 保存限位</button>
        <button class="btn btn-small" onclick="loadLimits()">📥 加载限位</button>
      </div>
    </div>
    
    <!-- 中间：关键帧编辑 -->
    <div class="panel" style="flex: 1.5; min-width: 280px;">
      <h2>⏱️ 关键帧时间轴</h2>
      <div class="input-row">
        <label>表情名称:</label>
        <input type="text" id="exprName" value="" placeholder="输入表情名称" />
      </div>
      <div class="input-row">
        <label>帧时长:</label>
        <input type="number" id="frameDuration" value="300" min="50" max="5000" /> <span style="font-size:11px;">ms</span>
      </div>
      <div class="checkbox-row">
        <input type="checkbox" id="loopCheck" />
        <label for="loopCheck" style="width:auto;">循环播放</label>
      </div>
      <div class="keyframes" id="keyframes"><div style="color:#666;text-align:center;padding:20px;">暂无关键帧</div></div>
      <div>
        <button class="btn btn-danger" onclick="clearKeyframes()">🗑️ 清空帧</button>
        <button class="btn btn-success" onclick="playPreview()">▶️ 预览</button>
        <button class="btn btn-save" onclick="saveToESP32()">💾 保存到ESP32</button>
      </div>
      <div id="status"></div>
    </div>
    
    <!-- 右侧：已保存的表情 -->
    <div class="panel" style="flex: 1; min-width: 220px;">
      <h2>📁 已保存的表情 <button class="btn" style="float:right;padding:4px 8px;" onclick="loadSavedList()">🔄</button></h2>
      <div class="saved-list" id="savedList"><div style="color:#666;text-align:center;padding:20px;">加载中...</div></div>
      <div style="margin-top: 10px;">
        <button class="btn btn-danger" onclick="clearAllSaved()">🗑️ 清空全部</button>
      </div>
    </div>
  </div>

<script>
const SERVO_LABELS = ['CH00','CH01','CH02','CH03','CH04','CH05','CH06','CH07',
                      '嘴巴','眼球上下','眼球左右R','眼皮旋转R','眼皮眨眼R','眼球左右L','眼皮旋转L','眼皮眨眼L'];
let servoValues = new Array(16).fill(90);
let servoEnabled = new Array(16).fill(true);
let servoMin = new Array(16).fill(0);   // 最小角度限制
let servoMax = new Array(16).fill(180); // 最大角度限制
let keyframes = [];
let currentKeyframe = -1;
let pendingRequests = {};  // 防抖用

function initServos() {
  const container = document.getElementById('servos');
  for (let i = 0; i < 16; i++) {
    const row = document.createElement('div');
    row.className = 'servo-row';
    row.innerHTML = `
      <input type="checkbox" class="servo-check" id="check${i}" checked onchange="toggleServo(${i})">
      <span class="servo-label">${SERVO_LABELS[i]}</span>
      <input type="number" class="servo-limit" id="min${i}" value="0" min="0" max="180" onchange="updateLimit(${i},'min',this.value)" title="最小角度">
      <input type="range" class="servo-slider" id="slider${i}" min="0" max="180" value="90" oninput="onSliderInput(${i}, this.value)">
      <span class="servo-value" id="val${i}">90</span>
      <input type="number" class="servo-limit" id="max${i}" value="180" min="0" max="180" onchange="updateLimit(${i},'max',this.value)" title="最大角度">
    `;
    container.appendChild(row);
  }
  // 加载保存的限位设置
  loadLimitsFromStorage();
}

function toggleServo(ch) { servoEnabled[ch] = document.getElementById('check' + ch).checked; }

function updateLimit(ch, type, val) {
  val = parseInt(val) || 0;
  val = Math.max(0, Math.min(180, val));
  if (type === 'min') {
    servoMin[ch] = val;
    document.getElementById('min' + ch).value = val;
    document.getElementById('slider' + ch).min = val;
    // 如果当前值小于最小值，调整
    if (servoValues[ch] < val) {
      servoValues[ch] = val;
      document.getElementById('slider' + ch).value = val;
      document.getElementById('val' + ch).textContent = val;
      sendServoCommand(ch, val);
    }
  } else {
    servoMax[ch] = val;
    document.getElementById('max' + ch).value = val;
    document.getElementById('slider' + ch).max = val;
    // 如果当前值大于最大值，调整
    if (servoValues[ch] > val) {
      servoValues[ch] = val;
      document.getElementById('slider' + ch).value = val;
      document.getElementById('val' + ch).textContent = val;
      sendServoCommand(ch, val);
    }
  }
}

function onSliderInput(ch, val) {
  val = parseInt(val);
  // 限制在范围内
  val = Math.max(servoMin[ch], Math.min(servoMax[ch], val));
  servoValues[ch] = val;
  document.getElementById('val' + ch).textContent = val;
  document.getElementById('slider' + ch).value = val;
  
  // 使用防抖发送命令，避免请求过于频繁
  sendServoCommand(ch, val);
}

function sendServoCommand(ch, val) {
  // 取消之前的请求（防抖）
  if (pendingRequests[ch]) {
    clearTimeout(pendingRequests[ch]);
  }
  // 立即发送，但对同一通道进行防抖
  pendingRequests[ch] = setTimeout(() => {
    fetch('/servo?ch=' + ch + '&angle=' + val)
      .then(r => { if(!r.ok) console.warn('Servo cmd failed:', ch, val); })
      .catch(e => console.warn('Servo error:', e));
    delete pendingRequests[ch];
  }, 20); // 20ms防抖间隔
}

function resetServos() {
  for (let i = 0; i < 16; i++) {
    const mid = Math.round((servoMin[i] + servoMax[i]) / 2);
    servoValues[i] = mid;
    document.getElementById('slider' + i).value = mid;
    document.getElementById('val' + i).textContent = mid;
    sendServoCommand(i, mid);
  }
}

function captureKeyframe() {
  const duration = parseInt(document.getElementById('frameDuration').value) || 300;
  const angles = servoValues.map((v, i) => servoEnabled[i] ? v : -1);
  keyframes.push({ angles: angles.slice(), duration });
  renderKeyframes();
  showStatus('已捕获关键帧 #' + keyframes.length, 'success');
}

function renderKeyframes() {
  const container = document.getElementById('keyframes');
  if (keyframes.length === 0) {
    container.innerHTML = '<div style="color:#666;text-align:center;padding:20px;">暂无关键帧</div>';
    return;
  }
  container.innerHTML = '';
  keyframes.forEach((kf, i) => {
    const div = document.createElement('div');
    div.className = 'keyframe' + (i === currentKeyframe ? ' active' : '');
    const activeCount = kf.angles.filter(a => a >= 0).length;
    div.innerHTML = `
      <span>帧${i+1}: ${kf.duration}ms, ${activeCount}个舵机</span>
      <div>
        <button class="btn" style="padding:3px 6px;font-size:10px;" onclick="loadKeyframe(${i})">加载</button>
        <button class="btn" style="padding:3px 6px;font-size:10px;" onclick="updateKeyframe(${i})">更新</button>
        <button class="btn btn-danger" style="padding:3px 6px;font-size:10px;" onclick="deleteKeyframe(${i})">删</button>
      </div>
    `;
    container.appendChild(div);
  });
}

function loadKeyframe(idx) {
  currentKeyframe = idx;
  const kf = keyframes[idx];
  for (let i = 0; i < 16; i++) {
    if (kf.angles[i] >= 0) {
      let val = Math.max(servoMin[i], Math.min(servoMax[i], kf.angles[i]));
      servoValues[i] = val;
      document.getElementById('slider' + i).value = val;
      document.getElementById('val' + i).textContent = val;
      document.getElementById('check' + i).checked = true;
      servoEnabled[i] = true;
      sendServoCommand(i, val);
    } else {
      document.getElementById('check' + i).checked = false;
      servoEnabled[i] = false;
    }
  }
  document.getElementById('frameDuration').value = kf.duration;
  renderKeyframes();
}

function updateKeyframe(idx) {
  const duration = parseInt(document.getElementById('frameDuration').value) || 300;
  const angles = servoValues.map((v, i) => servoEnabled[i] ? v : -1);
  keyframes[idx] = { angles: angles.slice(), duration };
  renderKeyframes();
  showStatus('已更新关键帧 #' + (idx+1), 'success');
}

function deleteKeyframe(idx) {
  keyframes.splice(idx, 1);
  if (currentKeyframe >= keyframes.length) currentKeyframe = keyframes.length - 1;
  renderKeyframes();
}

function clearKeyframes() {
  if (keyframes.length === 0 || confirm('确定清空所有关键帧？')) {
    keyframes = [];
    currentKeyframe = -1;
    renderKeyframes();
  }
}

async function playPreview() {
  if (keyframes.length === 0) { showStatus('没有关键帧可预览', 'error'); return; }
  for (let i = 0; i < keyframes.length; i++) {
    loadKeyframe(i);
    await new Promise(r => setTimeout(r, keyframes[i].duration));
  }
  showStatus('预览完成', 'success');
}

async function saveToESP32() {
  const name = document.getElementById('exprName').value.trim();
  if (!name) { showStatus('请输入表情名称', 'error'); return; }
  if (keyframes.length === 0) { showStatus('请先添加关键帧', 'error'); return; }
  
  const data = {
    name: name,
    loop: document.getElementById('loopCheck').checked,
    keyframes: keyframes
  };
  
  console.log('Saving expression:', JSON.stringify(data));
  
  try {
    const res = await fetch('/expr_save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
    const result = await res.json();
    if (result.ok) {
      showStatus('保存成功！ID=' + result.id + ' (' + result.action + ')', 'success');
      loadSavedList();
    } else {
      showStatus('保存失败: ' + result.error, 'error');
    }
  } catch (e) {
    showStatus('保存失败: ' + e.message, 'error');
  }
}

async function loadSavedList() {
  try {
    const res = await fetch('/expression');
    const data = await res.json();
    const container = document.getElementById('savedList');
    if (data.count === 0) {
      container.innerHTML = '<div style="color:#666;text-align:center;padding:20px;">暂无保存的表情</div>';
      return;
    }
    container.innerHTML = '';
    data.expressions.forEach(expr => {
      const div = document.createElement('div');
      div.className = 'saved-item';
      div.innerHTML = `
        <span>${expr.name} (${expr.frames}帧${expr.loop ? ',循环' : ''})</span>
        <div>
          <button class="btn" style="padding:3px 6px;font-size:10px;" onclick="playExpr('${expr.name}')">▶</button>
          <button class="btn" style="padding:3px 6px;font-size:10px;" onclick="editExpr(${expr.id})">编辑</button>
          <button class="btn btn-danger" style="padding:3px 6px;font-size:10px;" onclick="deleteExpr(${expr.id})">删</button>
        </div>
      `;
      container.appendChild(div);
    });
  } catch (e) {
    document.getElementById('savedList').innerHTML = '<div style="color:#f66;padding:10px;">加载失败</div>';
  }
}

function playExpr(name) { fetch('/expression?play=' + encodeURIComponent(name)); showStatus('播放: ' + name, 'success'); }

async function editExpr(id) {
  try {
    const res = await fetch('/expr_get?id=' + id);
    const data = await res.json();
    document.getElementById('exprName').value = data.name;
    document.getElementById('loopCheck').checked = data.loop;
    keyframes = data.keyframes.map(kf => ({
      angles: kf.angles.slice(),
      duration: kf.duration
    }));
    currentKeyframe = -1;
    renderKeyframes();
    showStatus('已加载表情: ' + data.name + ' (' + keyframes.length + '帧)', 'success');
  } catch (e) {
    showStatus('加载失败', 'error');
  }
}

async function deleteExpr(id) {
  if (!confirm('确定删除这个表情？')) return;
  await fetch('/expression?delete=' + id);
  loadSavedList();
  showStatus('已删除', 'success');
}

async function clearAllSaved() {
  if (!confirm('确定清空所有保存的表情？此操作不可恢复！')) return;
  await fetch('/expression?clear=1');
  loadSavedList();
  showStatus('已清空全部', 'success');
}

function showStatus(msg, type) {
  const el = document.getElementById('status');
  el.className = 'status ' + type;
  el.textContent = msg;
  setTimeout(() => { el.textContent = ''; el.className = ''; }, 3000);
}

// 限位设置存储到localStorage
function saveLimits() {
  const limits = { min: servoMin, max: servoMax };
  localStorage.setItem('servoLimits', JSON.stringify(limits));
  showStatus('限位设置已保存', 'success');
}

function loadLimits() {
  loadLimitsFromStorage();
  showStatus('限位设置已加载', 'success');
}

function loadLimitsFromStorage() {
  try {
    const saved = localStorage.getItem('servoLimits');
    if (saved) {
      const limits = JSON.parse(saved);
      for (let i = 0; i < 16; i++) {
        if (limits.min && limits.min[i] !== undefined) {
          servoMin[i] = limits.min[i];
          const minEl = document.getElementById('min' + i);
          const slider = document.getElementById('slider' + i);
          if (minEl) minEl.value = limits.min[i];
          if (slider) slider.min = limits.min[i];
        }
        if (limits.max && limits.max[i] !== undefined) {
          servoMax[i] = limits.max[i];
          const maxEl = document.getElementById('max' + i);
          const slider = document.getElementById('slider' + i);
          if (maxEl) maxEl.value = limits.max[i];
          if (slider) slider.max = limits.max[i];
        }
      }
    }
  } catch(e) { console.warn('Load limits failed:', e); }
}

initServos();
loadSavedList();
</script>
</body>
</html>
)rawliteral";
  server.send(200, "text/html", html);
}

// ====================================================================
// LED 控制函数（已移除 - 无硬件）
// ====================================================================
// 空函数桩保持WebSocket命令兼容
void setEmotionLed(const char* emotion) { }
void updateLedBreathing(float level) { }

// ====================================================================
// 嘴部舵机控制
// ====================================================================

void requestMouthStart(){
  mouthPending = true;
  mouthActive = false;
  mouthStartDueMs = millis() + MOUTH_START_DELAY_MS;
  mouthLevelTarget = 0.0f;
  mouthLevelTimestamp = millis();
}

void requestMouthIdle(){
  mouthPending = false;
  mouthActive = false;
  mouthLevelTarget = 0.0f;
  mouthLevelTimestamp = millis();
  
  // ★ 通知表情系统音频嘴巴已停止
  faceAnimSetAudioMouth(false, 0.0f);
  
  // ★ 关键：强制禁用表情嘴部控制，防止与语音嘴巴冲突
  // 这样 taskMouthDriver 会使用闭合状态而不是表情的嘴部值
  faceAnim.exprMouthActive = false;
  faceAnim.mouthR = MOUTH_R_NEUTRAL;
  faceAnim.mouthL = MOUTH_L_NEUTRAL;
  faceAnim.mouthU = MOUTH_U_NEUTRAL;
  faceAnim.mouthLower = MOUTH_LOWER_CLOSED;
  
  // ★ 设置所有嘴巴舵机到闭合状态
  setServoAngle(CH_MOUTH_LOWER, MOUTH_LOWER_CLOSED);  // CH3 下嘴唇
  setServoAngle(CH_MOUTH_R, MOUTH_R_NEUTRAL);         // CH0 右嘴角
  setServoAngle(CH_MOUTH_L, MOUTH_L_NEUTRAL);         // CH1 左嘴角
  setServoAngle(CH_MOUTH_U, MOUTH_U_NEUTRAL);         // CH2 上嘴唇
  setServoAngle(MOUTH_SERVO_CH, MOUTH_CLOSED_ANGLE);  // CH9 兼容
}

void updateMouthLevel(float level){
  if (level < 0.0f) level = 0.0f;
  if (level > 1.2f) level = 1.2f;
  mouthLevelTarget = level;
  mouthLevelTimestamp = millis();
}

// ======== ESP32 本地元音识别（简化频谱分析）========
// 通过过零率和高低频能量比来判断元音
char analyzeVowelLocal(const int16_t* samples, size_t count, float rms) {
  if (count < 64 || rms < 0.02f) return 'E';  // 太短或太安静
  
  // 1. 计算过零率 (Zero Crossing Rate)
  // 高过零率 → 高频成分多 → I/E
  // 低过零率 → 低频成分多 → U/O
  int zeroCrossings = 0;
  for (size_t i = 1; i < count; i++) {
    if ((samples[i-1] >= 0 && samples[i] < 0) || 
        (samples[i-1] < 0 && samples[i] >= 0)) {
      zeroCrossings++;
    }
  }
  float zcr = (float)zeroCrossings / (float)count;  // 归一化过零率
  
  // 2. 计算高频/低频能量比
  // 简单方法：比较相邻样本差值（高频=变化大）vs 低通滤波后的能量
  uint64_t highFreqEnergy = 0;
  uint64_t lowFreqEnergy = 0;
  int32_t lowPass = samples[0];
  
  for (size_t i = 1; i < count; i++) {
    // 高频：样本变化量
    int32_t diff = samples[i] - samples[i-1];
    highFreqEnergy += (int64_t)diff * diff;
    
    // 低频：简单低通滤波
    lowPass = (lowPass * 7 + samples[i]) / 8;  // 0.875 系数
    lowFreqEnergy += (int64_t)lowPass * lowPass;
  }
  
  float hfRatio = (float)highFreqEnergy / (float)(lowFreqEnergy + 1);
  
  // 3. 根据特征判断元音
  // I: 高过零率 + 高频能量高（扁嘴，舌头前）
  // U: 低过零率 + 低频能量高（嘟嘴）
  // O: 中低过零率 + 低频能量高（圆嘴）
  // A: 中等过零率 + 能量分布均匀（大张嘴）
  // E: 默认/中性
  
  if (zcr > 0.35f && hfRatio > 0.8f) {
    return 'I';  // 高频多 → 衣
  } else if (zcr < 0.15f && hfRatio < 0.3f) {
    return 'U';  // 低频多 → 乌
  } else if (zcr < 0.22f && hfRatio < 0.5f) {
    return 'O';  // 中低频 → 哦
  } else if (zcr > 0.2f && zcr < 0.35f && hfRatio > 0.4f && hfRatio < 0.9f) {
    return 'A';  // 中频均匀 → 啊
  } else {
    return 'E';  // 默认 → 呃
  }
}

void feedMouthLevelFromSamples(const int16_t* samples, size_t count){
  if (!samples || count == 0) {
    return;
  }
  uint64_t sumSq = 0;
  int32_t peak = 0;
  for (size_t i = 0; i < count; ++i) {
    int32_t sample = samples[i];
    int32_t absSample = sample >= 0 ? sample : -sample;
    if (absSample > peak) peak = absSample;
    sumSq += (int64_t)sample * (int64_t)sample;
  }
  float rms = sqrtf((float)sumSq / (float)count) / 32768.0f;
  float pk  = (float)peak / 32768.0f;
  float level = rms;
  if (pk > level) level = pk;
  if (level < 0.0f) level = 0.0f;
  if (level > 1.0f) level = 1.0f;
  
  // ★ ESP32 本地元音识别
  if (level > 0.03f) {
    char vowel = analyzeVowelLocal(samples, count, level);
    setCurrentVowel(vowel);
  }
  
  level = powf(level, MOUTH_LEVEL_GAMMA) * MOUTH_LEVEL_GAIN;
  if (level > 1.2f) level = 1.2f;
  updateMouthLevel(level);
}

// ======== 混合嘴型控制：Python发送元音类型 + ESP32本地音量控制开合 ========
// 当前元音（由 Python 通过 MOUTH:A 等命令设置）
volatile char currentVowel = 'E';  // 默认中性元音
volatile uint32_t vowelLastUpdateMs = 0;
volatile char activeVowel = 'E';   // 实际用于驱动嘴型的元音（节流后）
volatile uint32_t activeVowelStartMs = 0;

// ★ 元音分组：判断是否同组（同组不切换，减少抖动）
// 组1: A, O - 大张嘴
// 组2: E, I, U - 小口
int getVowelGroup(char v) {
  if (v == 'A' || v == 'a' || v == 'O' || v == 'o') return 1;
  return 2;
}

// ★ 元音节流：确保每个元音持续足够时间，舵机能到位
#define VOWEL_MIN_DURATION_MS 80  // 最小持续时间

void setCurrentVowel(char v) {
  currentVowel = v;
  vowelLastUpdateMs = millis();
  
  // 节流逻辑：只有当前元音持续够久 或 切换到不同组 才真正切换
  uint32_t now = millis();
  bool durationOk = (now - activeVowelStartMs) >= VOWEL_MIN_DURATION_MS;
  bool differentGroup = getVowelGroup(v) != getVowelGroup(activeVowel);
  
  if (durationOk || differentGroup) {
    activeVowel = v;
    activeVowelStartMs = now;
  }
}

void taskMouthDriver(void*){
  Serial.println("[MOUTH] driver task started (hybrid: vowel + volume)");
  
  // 当前角度（平滑用）
  float currentLower = MOUTH_LOWER_CLOSED;
  float currentR = MOUTH_R_NEUTRAL;
  float currentL = MOUTH_L_NEUTRAL;
  float currentU = MOUTH_U_NEUTRAL;
  
  bool lastMouthActive = false;
  
  // ★ 随机咧嘴状态
  bool isSmirking = false;           // 是否正在咧嘴
  int smirkDirection = 0;            // 咧嘴方向：1=右上左下, -1=左上右下
  uint32_t smirkStartMs = 0;         // 咧嘴开始时间
  uint32_t smirkDurationMs = 0;      // 咧嘴持续时间
  uint32_t nextSmirkCheckMs = 0;     // 下次检查咧嘴的时间
  
  for(;;){
    uint32_t now = millis();
    if (mouthPending && !mouthActive){
      if ((int32_t)(now - mouthStartDueMs) >= 0){
        mouthPending = false;
        mouthActive = true;
      }
    }

    if (!mouthActive){
      mouthLevelTarget = 0.0f;
    } else {
      int32_t since = (int32_t)(now - mouthLevelTimestamp);
      if (since > 260){
        mouthLevelTarget *= 0.85f;
        mouthLevelTimestamp = now;
      }
      if (since > 650){
        mouthLevelTarget = 0.0f;
      }
    }

    float level = mouthActive ? mouthLevelTarget : 0.0f;
    if (level < 0.0f) level = 0.0f;
    if (level > 1.2f) level = 1.2f;
    
    // ★ 通知表情系统音频嘴巴状态（始终同步）
    if (mouthActive != lastMouthActive) {
      faceAnimSetAudioMouth(mouthActive, level);
      lastMouthActive = mouthActive;
    } else {
      // 持续同步状态，无论 mouthActive 是 true 还是 false
      faceAnimSetAudioMouth(mouthActive, level);
    }
    
    // ======== 混合嘴型控制 ========
    // 元音决定嘴型形状，音量决定开合幅度
    if (mouthActive && level > 0.02f) {
      // 获取当前元音的基础嘴型
      MouthShape baseShape;
      
      // 元音超时（500ms没更新）则使用默认的音量驱动模式
      // ★ 使用节流后的 activeVowel，确保嘴型稳定
      bool vowelValid = (now - vowelLastUpdateMs) < 500;
      char vowel = vowelValid ? activeVowel : 'E';
      
      switch (vowel) {
        case 'A': case 'a': baseShape = MOUTH_SHAPE_A; break;
        case 'O': case 'o': baseShape = MOUTH_SHAPE_O; break;
        case 'E': case 'e': baseShape = MOUTH_SHAPE_E; break;
        case 'I': case 'i': baseShape = MOUTH_SHAPE_I; break;
        case 'U': case 'u': baseShape = MOUTH_SHAPE_U; break;
        default: baseShape = MOUTH_SHAPE_E; break;
      }
      
      // 根据音量调整开合幅度（0-1 映射到闭嘴-目标嘴型）
      float intensity = level;
      if (intensity > 1.0f) intensity = 1.0f;
      
      // ★ 嘴角直接使用嘴型表的极限值（全范围运动）
      // 只要有声音就直接到达目标嘴型，不受音量缩放
      // 上嘴唇和下嘴唇仍然受音量影响控制开合程度
      float targetR = baseShape.rightCorner;  // 嘴角直接到极限
      float targetL = baseShape.leftCorner;   // 嘴角直接到极限
      float targetU = MOUTH_U_NEUTRAL + (baseShape.upperLip - MOUTH_U_NEUTRAL) * intensity;
      float targetLower = MOUTH_LOWER_CLOSED + (baseShape.lowerLip - MOUTH_LOWER_CLOSED) * intensity;
      
      // ★ 随机咧嘴效果：偶尔一边嘴角上扬另一边下降
      // 概率触发，持续一段时间后恢复
      if (now >= nextSmirkCheckMs) {
        nextSmirkCheckMs = now + 200 + random(300);  // 每200-500ms检查一次
        
        if (!isSmirking && intensity > 0.3f) {
          // 15%概率触发咧嘴（音量足够时）
          if (random(100) < 15) {
            isSmirking = true;
            smirkDirection = (random(2) == 0) ? 1 : -1;  // 随机方向
            smirkStartMs = now;
            smirkDurationMs = 150 + random(200);  // 持续150-350ms
          }
        }
      }
      
      // 应用咧嘴偏移
      if (isSmirking) {
        uint32_t smirkElapsed = now - smirkStartMs;
        if (smirkElapsed < smirkDurationMs) {
          // 咧嘴幅度：先增后减的平滑曲线
          float smirkPhase = (float)smirkElapsed / smirkDurationMs;
          float smirkIntensity = sin(smirkPhase * 3.14159f) * intensity;  // 正弦曲线
          
          // 咧嘴偏移量（一边上扬，另一边下降或不变）
          float smirkOffset = 8.0f * smirkIntensity;  // 最大8度偏移
          
          if (smirkDirection > 0) {
            // 右嘴角上扬，左嘴角略下（或不变）
            targetR -= smirkOffset;  // 右嘴角上扬（数值减小）
            targetL -= smirkOffset * 0.3f;  // 左嘴角略微下降
          } else {
            // 左嘴角上扬，右嘴角略下
            targetL += smirkOffset;  // 左嘴角上扬（数值增大）
            targetR += smirkOffset * 0.3f;  // 右嘴角略微下降
          }
        } else {
          isSmirking = false;  // 咧嘴结束
        }
      }
      
      // 限制嘴角范围
      targetR = constrain(targetR, MOUTH_R_UP, MOUTH_R_DOWN);
      targetL = constrain(targetL, MOUTH_L_DOWN, MOUTH_L_UP);
      
      // ★ 平滑插值
      // 下嘴唇运动范围大(85-140)，需要较快速率才能在元音持续期内到位
      // 元音最小持续80ms，15ms循环 → 约5次机会到位
      float lowerOpenRate = 0.55f;   // 下嘴唇张开速率（提高，确保能张到最大）
      float lowerCloseRate = 0.30f;  // 下嘴唇闭合速率
      float cornerRate = 0.40f;      // 嘴角变化速率
      float upperRate = 0.35f;       // 上嘴唇变化速率
      
      currentLower += (targetLower - currentLower) * ((targetLower > currentLower) ? lowerOpenRate : lowerCloseRate);
      currentR += (targetR - currentR) * cornerRate;
      currentL += (targetL - currentL) * cornerRate;
      currentU += (targetU - currentU) * upperRate;
      
      // 应用到舵机
      setServoAngle(CH_MOUTH_LOWER, (int)(currentLower + 0.5f));
      setServoAngle(CH_MOUTH_R, (int)(currentR + 0.5f));
      setServoAngle(CH_MOUTH_L, (int)(currentL + 0.5f));
      setServoAngle(CH_MOUTH_U, (int)(currentU + 0.5f));
      
      // 兼容旧通道 CH9
      setServoAngle(MOUTH_SERVO_CH, (int)(currentLower + 0.5f));
      
    } else {
      // ★ 音频不活跃时，执行闭嘴复位
      // 默认目标：完全闭合
      float targetLower = MOUTH_LOWER_CLOSED;
      float targetR = MOUTH_R_NEUTRAL;
      float targetL = MOUTH_L_NEUTRAL;
      float targetU = MOUTH_U_NEUTRAL;
      
      // ★ 只有表情嘴部激活时才使用表情的目标值
      // 表情结束后 exprMouthActive = false，会使用闭合值
      if (faceAnim.exprMouthActive) {
        targetLower = (float)faceAnim.mouthLower;
        targetR = (float)faceAnim.mouthR;
        targetL = (float)faceAnim.mouthL;
        targetU = (float)faceAnim.mouthU;
      }
      
      // ★ 增加闭嘴速度：0.5 比原来的 0.3 更快
      float closeRate = 0.5f;
      
      currentLower += (targetLower - currentLower) * closeRate;
      currentR += (targetR - currentR) * closeRate;
      currentL += (targetL - currentL) * closeRate;
      currentU += (targetU - currentU) * closeRate;
      
      // ★ 如果接近目标值，直接设置到目标（避免无限逼近）
      if (fabsf(currentLower - targetLower) < 1.0f) currentLower = targetLower;
      if (fabsf(currentR - targetR) < 1.0f) currentR = targetR;
      if (fabsf(currentL - targetL) < 1.0f) currentL = targetL;
      if (fabsf(currentU - targetU) < 1.0f) currentU = targetU;
      
      // ★ 设置舵机
      setServoAngle(CH_MOUTH_LOWER, (int)(currentLower + 0.5f));
      setServoAngle(CH_MOUTH_R, (int)(currentR + 0.5f));
      setServoAngle(CH_MOUTH_L, (int)(currentL + 0.5f));
      setServoAngle(CH_MOUTH_U, (int)(currentU + 0.5f));
      setServoAngle(MOUTH_SERVO_CH, (int)(currentLower + 0.5f));
    }
    
    vTaskDelay(pdMS_TO_TICKS(15));
  }
}

// ====================================================================
// WebSocket / Queues / I2S
// ====================================================================
WebsocketsClient wsCam;
WebsocketsClient wsAud;
volatile bool cam_ws_ready = false;
volatile bool aud_ws_ready = false;
volatile bool snapshot_in_progress = false;

typedef camera_fb_t* fb_ptr_t;
QueueHandle_t qFrames;

typedef struct {
  size_t n;
  uint8_t data[BYTES_PER_CHUNK];
} AudioChunk;
QueueHandle_t qAudio;

#define TTS_QUEUE_DEPTH 48
typedef struct { uint16_t n; uint8_t data[2048]; } TTSChunk;
QueueHandle_t qTTS;
volatile bool tts_playing = false;

I2SClass i2sIn;   // PDM RX (Mic)
I2SClass i2sOut;  // STD TX (Speaker)
volatile bool run_audio_stream = false;

// ====================================================================
// Camera
// ====================================================================
bool apply_framesize(framesize_t fs) {
  sensor_t* s = esp_camera_sensor_get();
  if (!s) return false;
  int r = s->set_framesize(s, fs);
  if (r == 0) { g_frame_size = fs; return true; }
  return false;
}

bool init_camera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM; config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM; config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM; config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM; config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM; config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM; config.pin_href = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM; config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn  = PWDN_GPIO_NUM; config.pin_reset = RESET_GPIO_NUM;

  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size   = g_frame_size;
  config.jpeg_quality = JPEG_QUALITY;
  config.fb_count     = FB_COUNT;
  config.fb_location  = CAMERA_FB_IN_PSRAM;
  config.grab_mode    = CAMERA_GRAB_LATEST;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) { Serial.printf("[CAM] init failed: 0x%x\n", err); return false; }

  sensor_t * s = esp_camera_sensor_get();
  if (s) {
    s->set_hmirror(s, 1);  // 水平镜像（0=关闭，图像不翻转）
    s->set_vflip(s, 0);    // 垂直翻转（需要的话改成 1）

    s->set_brightness(s, 0);
    s->set_contrast(s, 1);
    s->set_saturation(s, 1);
    s->set_gain_ctrl(s, 1);      // 自动增益控制
    s->set_exposure_ctrl(s, 1);  // ★ 开启自动曝光控制（防止闪烁）
    s->set_whitebal(s, 1);
    s->set_awb_gain(s, 1);
    s->set_aec2(s, 1);           // ★ 开启 AEC2（自动曝光控制2，更稳定）
    s->set_aec_value(s, 300);    // 初始曝光值（自动曝光开启时作为起始值）
    s->set_gainceiling(s, GAINCEILING_4X);  // 限制最大增益，减少噪点
  }
  return true;
}

inline void enqueue_frame(camera_fb_t* fb) {
  if (!fb) return;
  if (xQueueSend(qFrames, &fb, 0) != pdPASS) {
    fb_ptr_t drop = nullptr;
    if (xQueueReceive(qFrames, &drop, 0) == pdPASS) {
      if (drop) {
        esp_camera_fb_return(drop);
        frame_dropped_count++;
      }
    }
    xQueueSend(qFrames, &fb, 0);
  }
}

void taskCamCapture(void*) {
  unsigned long last_log = 0;
  unsigned long capture_fail_count = 0;

  for(;;){
    if (snapshot_in_progress) { vTaskDelay(pdMS_TO_TICKS(5)); continue; }

    if (cam_ws_ready) {
      camera_fb_t* fb = esp_camera_fb_get();
      if (fb) {
        frame_captured_count++;
        if (fb->format != PIXFORMAT_JPEG) {
          esp_camera_fb_return(fb);
          capture_fail_count++;
        } else {
          enqueue_frame(fb);
        }
      } else {
        capture_fail_count++;
        vTaskDelay(pdMS_TO_TICKS(2));
      }

      unsigned long now = millis();
      if (now - last_log > 5000) {
        int queue_waiting = uxQueueMessagesWaiting(qFrames);
        Serial.printf("[CAM-CAP] captured=%lu, queue=%d, fail=%lu\n",
                      frame_captured_count, queue_waiting, capture_fail_count);
        last_log = now;
        capture_fail_count = 0;
      }
    } else {
      vTaskDelay(pdMS_TO_TICKS(20));
    }
  }
}

void taskCamSend(void*) {
  static TickType_t lastTick = 0;
  unsigned long last_log = 0;
  unsigned long send_timeout_count = 0;
  unsigned long last_sent_time = 0;

  for(;;){
    fb_ptr_t fb = nullptr;
    if (xQueueReceive(qFrames, &fb, pdMS_TO_TICKS(100)) == pdPASS) {
      if (fb && cam_ws_ready) {
        if (g_target_fps > 0) {
          const int period_ms = 1000 / g_target_fps;
          TickType_t nowTick = xTaskGetTickCount();
          int elapsed = (nowTick - lastTick) * portTICK_PERIOD_MS;
          if (elapsed < period_ms) vTaskDelay(pdMS_TO_TICKS(period_ms - elapsed));
          lastTick = xTaskGetTickCount();
        }

        unsigned long send_start = millis();
        bool ok = wsCam.sendBinary((const char*)fb->buf, fb->len);
        unsigned long send_time = millis() - send_start;

        if (ok) {
          frame_sent_count++;
          last_sent_time = millis();
          if (send_time > 100) {
            Serial.printf("[CAM-SEND] WARNING: send took %lu ms (size=%u)\n", send_time, fb->len);
          }
        } else {
          ws_send_fail_count++;
          Serial.println("[CAM-SEND] ERROR: WebSocket send failed, closing...");
          esp_camera_fb_return(fb);
          wsCam.close();
          cam_ws_ready = false;
          continue;
        }

        esp_camera_fb_return(fb);

        unsigned long now = millis();
        if (now - last_log > 5000) {
          unsigned long gap = now - last_sent_time;
          Serial.printf("[CAM-SEND] sent=%lu, dropped=%lu, ws_fail=%lu, last_gap=%lu ms\n",
                        frame_sent_count, frame_dropped_count, ws_send_fail_count, gap);
          last_log = now;
        }

      } else if (fb) {
        esp_camera_fb_return(fb);
      }
    } else {
      unsigned long now = millis();
      if (cam_ws_ready && last_sent_time > 0 && (now - last_sent_time) > 3000) {
        Serial.printf("[CAM-SEND] WARNING: No frame sent for %lu ms\n", now - last_sent_time);
        send_timeout_count++;
      }
    }
  }
}

// ====================================================================
// Mic (PDM RX)
// ====================================================================
void init_i2s_in(){
  i2sIn.setPinsPdmRx(I2S_MIC_CLOCK_PIN, I2S_MIC_DATA_PIN);
  if (!i2sIn.begin(I2S_MODE_PDM_RX, SAMPLE_RATE, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO)) {
    Serial.println("[I2S IN] init failed");
    while(1) { delay(1000); }
  }
  Serial.println("[I2S IN] PDM RX @16kHz 16bit MONO ready");
}

void taskMicCapture(void*){
  const int samples_per_chunk = BYTES_PER_CHUNK / 2;
  for(;;){
    if (run_audio_stream && aud_ws_ready) {
      AudioChunk ch; ch.n = BYTES_PER_CHUNK;
      int16_t* out = reinterpret_cast<int16_t*>(ch.data);
      int i = 0;
      while (i < samples_per_chunk){
        int v = i2sIn.read();
        if (v == -1) { delay(1); continue; }
        out[i++] = (int16_t)v;
      }
      if (xQueueSend(qAudio, &ch, 0) != pdPASS){
        AudioChunk dump;
        xQueueReceive(qAudio, &dump, 0);
        xQueueSend(qAudio, &ch, 0);
      }
    } else {
      vTaskDelay(pdMS_TO_TICKS(5));
    }
  }
}

void taskMicUpload(void*){
  for(;;){
    if (run_audio_stream && aud_ws_ready){
      AudioChunk ch;
      if (xQueueReceive(qAudio, &ch, pdMS_TO_TICKS(100)) == pdPASS){
        wsAud.sendBinary((const char*)ch.data, ch.n);
      }
    } else {
      vTaskDelay(pdMS_TO_TICKS(10));
    }
  }
}

// ====================================================================
// Speaker (I2S TX) + HTTP /stream.wav (chunked-safe)
// ====================================================================
void init_i2s_out(){
  i2sOut.setPins(I2S_SPK_BCLK, I2S_SPK_LRCK, I2S_SPK_DIN);
  if (!i2sOut.begin(I2S_MODE_STD, TTS_RATE, I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_STEREO)) {
    Serial.println("[I2S OUT] init failed");
    while(1){ delay(1000); }
  }
  Serial.println("[I2S OUT] STD TX @16kHz 32bit STEREO ready");
}

struct WavFmt {
  uint16_t audioFormat;
  uint16_t numChannels;
  uint32_t sampleRate;
  uint32_t byteRate;
  uint16_t blockAlign;
  uint16_t bitsPerSample;
};

static inline void mono16_to_stereo32_msb(const int16_t* in, size_t nSamp, int32_t* outLR, float gain = 0.7f) {
  for (size_t i = 0; i < nSamp; ++i) {
    int32_t s = (int32_t)((float)in[i] * gain);
    // 限幅处理：防止溢出导致爆破音
    if (s > 32767) s = 32767;
    if (s < -32768) s = -32768;
    int32_t v32 = s << 16;
    outLR[i*2 + 0] = v32;
    outLR[i*2 + 1] = v32;
  }
}

// ====================================================================
// 音频双缓冲系统 - 解决播放卡顿问题
// ★ 优化实时性：减小预缓冲时间
// ====================================================================
#define AUDIO_RING_BUF_SIZE  8192    // 环形缓冲区大小（约0.25秒@16kHz）
#define AUDIO_CHUNK_SIZE     320     // 每块10ms@16kHz = 320字节（与服务端同步）
#define AUDIO_PREBUFFER_MS   40      // 预缓冲40ms（原100ms）

// 环形缓冲区（线程安全）
typedef struct {
  uint8_t data[AUDIO_RING_BUF_SIZE];
  volatile size_t writePos;
  volatile size_t readPos;
  volatile size_t fillLevel;
  SemaphoreHandle_t mutex;
} AudioRingBuffer;

AudioRingBuffer audioRingBuf;
volatile bool audioPlayerReady = false;  // 播放器是否准备好
volatile bool audioNeedPrebuffer = true; // 是否需要预缓冲
volatile uint32_t audioSampleRate = 16000;

void initAudioRingBuffer() {
  audioRingBuf.writePos = 0;
  audioRingBuf.readPos = 0;
  audioRingBuf.fillLevel = 0;
  // ★ 优化：mutex 只创建一次，避免多次 stop/start 导致内存泄漏
  if (audioRingBuf.mutex == nullptr) {
    audioRingBuf.mutex = xSemaphoreCreateMutex();
  }
}

void resetAudioRingBuffer() {
  xSemaphoreTake(audioRingBuf.mutex, portMAX_DELAY);
  audioRingBuf.writePos = 0;
  audioRingBuf.readPos = 0;
  audioRingBuf.fillLevel = 0;
  audioNeedPrebuffer = true;
  xSemaphoreGive(audioRingBuf.mutex);
}

// 写入数据到环形缓冲区（HTTP读取任务调用）
bool writeAudioRingBuffer(const uint8_t* data, size_t len) {
  if (len == 0) return true;
  
  xSemaphoreTake(audioRingBuf.mutex, portMAX_DELAY);
  size_t freeSpace = AUDIO_RING_BUF_SIZE - audioRingBuf.fillLevel;
  if (len > freeSpace) {
    // 缓冲区满，丢弃旧数据（保持实时性）
    size_t drop = len - freeSpace;
    audioRingBuf.readPos = (audioRingBuf.readPos + drop) % AUDIO_RING_BUF_SIZE;
    audioRingBuf.fillLevel -= drop;
    freeSpace = len;
  }
  
  // 写入数据
  size_t firstPart = AUDIO_RING_BUF_SIZE - audioRingBuf.writePos;
  if (firstPart >= len) {
    memcpy(audioRingBuf.data + audioRingBuf.writePos, data, len);
  } else {
    memcpy(audioRingBuf.data + audioRingBuf.writePos, data, firstPart);
    memcpy(audioRingBuf.data, data + firstPart, len - firstPart);
  }
  audioRingBuf.writePos = (audioRingBuf.writePos + len) % AUDIO_RING_BUF_SIZE;
  audioRingBuf.fillLevel += len;
  xSemaphoreGive(audioRingBuf.mutex);
  return true;
}

// 读取数据从环形缓冲区（I2S播放任务调用）
size_t readAudioRingBuffer(uint8_t* data, size_t maxLen) {
  xSemaphoreTake(audioRingBuf.mutex, portMAX_DELAY);
  size_t available = audioRingBuf.fillLevel;
  size_t toRead = (available < maxLen) ? available : maxLen;
  
  if (toRead > 0) {
    size_t firstPart = AUDIO_RING_BUF_SIZE - audioRingBuf.readPos;
    if (firstPart >= toRead) {
      memcpy(data, audioRingBuf.data + audioRingBuf.readPos, toRead);
    } else {
      memcpy(data, audioRingBuf.data + audioRingBuf.readPos, firstPart);
      memcpy(data + firstPart, audioRingBuf.data, toRead - firstPart);
    }
    audioRingBuf.readPos = (audioRingBuf.readPos + toRead) % AUDIO_RING_BUF_SIZE;
    audioRingBuf.fillLevel -= toRead;
  }
  xSemaphoreGive(audioRingBuf.mutex);
  return toRead;
}

size_t getAudioRingBufferLevel() {
  xSemaphoreTake(audioRingBuf.mutex, portMAX_DELAY);
  size_t level = audioRingBuf.fillLevel;
  xSemaphoreGive(audioRingBuf.mutex);
  return level;
}

// --- HTTP 音频双缓冲播放系统 ---
// 分成两个任务：读取任务(Core 0) 和 播放任务(Core 1)
static TaskHandle_t taskHttpReadHandle = nullptr;
static TaskHandle_t taskI2SPlayHandle = nullptr;
static volatile bool http_play_running = false;
static volatile bool i2s_play_running = false;

// I2S 播放任务 - 高优先级，运行在 Core 1
// 独立从环形缓冲区读取数据，不受网络影响
void taskI2SPlay(void*) {
  Serial.println("[I2S-PLAY] Task started on Core 1");
  
  static int32_t outLR[512 * 2];  // 输出缓冲区
  static uint8_t inbuf[1024];      // 输入缓冲区
  
  uint32_t lastActiveMs = millis();
  bool mouthStarted = false;
  
  // ★ 优化：添加 underflow 计数用于诊断
  static uint32_t underflowCount = 0;
  static uint32_t lastLogMs = 0;
  
  while (i2s_play_running) {
    // 等待预缓冲完成
    if (audioNeedPrebuffer) {
      size_t prebufBytes = audioSampleRate * 2 * AUDIO_PREBUFFER_MS / 1000;
      if (getAudioRingBufferLevel() < prebufBytes) {
        vTaskDelay(pdMS_TO_TICKS(5));
        continue;
      }
      audioNeedPrebuffer = false;
      audioPlayerReady = true;
      underflowCount = 0;  // 重置计数
      Serial.printf("[I2S-PLAY] Prebuffer done, level=%d bytes\n", getAudioRingBufferLevel());
    }
    
    // ★ 优化实时性：减小每次读取的字节数（5ms 更频繁读取）
    size_t bytesPerChunk = audioSampleRate * 2 * 5 / 1000;  // 5ms @16kHz = 160 字节
    if (bytesPerChunk > sizeof(inbuf)) bytesPerChunk = sizeof(inbuf);
    
    // 从环形缓冲区读取数据
    size_t got = readAudioRingBuffer(inbuf, bytesPerChunk);
    
    // ★ 低频日志：每秒打印一次状态（用于诊断是否发生 underflow）
    uint32_t nowMs = millis();
    if (nowMs - lastLogMs > 1000) {
      lastLogMs = nowMs;
      if (audioPlayerReady) {
        Serial.printf("[AUDIO] level=%uB underflow=%u\n",
                      (unsigned)getAudioRingBufferLevel(),
                      (unsigned)underflowCount);
      }
    }
    
    if (got > 0) {
      lastActiveMs = millis();
      
      // 启动嘴巴动画
      if (!mouthStarted) {
        requestMouthStart();
        mouthStarted = true;
      }
      
      // 处理嘴巴动画
      size_t samp = got / 2;
      feedMouthLevelFromSamples((const int16_t*)inbuf, samp);
      
      // 转换格式
      mono16_to_stereo32_msb((const int16_t*)inbuf, samp, outLR, 0.7f);
      
      // 写入 I2S（这里可能会阻塞，但不影响HTTP读取）
      size_t bytes = samp * 2 * sizeof(int32_t);
      size_t off = 0;
      while (off < bytes && i2s_play_running) {
        size_t wrote = i2sOut.write((uint8_t*)outLR + off, bytes - off);
        if (wrote == 0) {
          vTaskDelay(pdMS_TO_TICKS(1));
        } else {
          off += wrote;
        }
      }
    } else {
      // ★ 缓冲区空 = underflow
      if (audioPlayerReady) {
        underflowCount++;
      }
      
      // 缓冲区空
      if (mouthStarted && (millis() - lastActiveMs > 300)) {
        // 300ms无数据，停止嘴巴动画
        requestMouthIdle();
        mouthStarted = false;
      }
      vTaskDelay(pdMS_TO_TICKS(2));
    }
  }
  
  if (mouthStarted) {
    requestMouthIdle();
  }
  Serial.println("[I2S-PLAY] Task stopped");
  vTaskDelete(nullptr);
}

// HTTP 读取任务 - 运行在 Core 0
void taskHttpRead(void*) {
  Serial.println("[HTTP-READ] Task started on Core 0");
  
  WiFiClient cli;
  
  // ★ 优化：使用固定 char buffer 代替 String，避免堆碎片和频繁分配
  static char lineBuffer[128];  // 固定行缓冲区（chunked size 通常很短）

  // 新版 readLine：使用固定 buffer，无堆分配
  auto readLineFixed = [&](char* buf, size_t bufSize, uint32_t timeout_ms)->int {
    size_t pos = 0;
    uint32_t t0 = millis();
    while (millis() - t0 < timeout_ms) {
      while (cli.available()) {
        char c = (char)cli.read();
        if (c == '\r') continue;
        if (c == '\n') {
          buf[pos] = '\0';
          return (int)pos;
        }
        if (pos < bufSize - 1) {
          buf[pos++] = c;
        } else {
          // 缓冲区满，截断
          buf[pos] = '\0';
          return (int)pos;
        }
      }
      vTaskDelay(pdMS_TO_TICKS(1));
    }
    buf[pos] = '\0';
    return -1;  // 超时
  };
  
  // 兼容层：保持原来的 String 接口用于 HTTP header 解析（非热路径）
  auto readLine = [&](String& out, uint32_t timeout_ms)->bool {
    int len = readLineFixed(lineBuffer, sizeof(lineBuffer), timeout_ms);
    if (len < 0) return false;
    out = String(lineBuffer);
    return true;
  };

  auto readNRaw = [&](uint8_t* dst, size_t n, uint32_t timeout_ms)->bool {
    size_t got = 0;
    uint32_t t0 = millis();
    while (got < n) {
      if (!cli.connected()) return false;
      int avail = cli.available();
      if (avail > 0) {
        int take = (int)min((size_t)avail, n - got);
        int r = cli.read(dst + got, take);
        if (r > 0) { got += r; continue; }
      }
      if (millis() - t0 > timeout_ms) return false;
      vTaskDelay(pdMS_TO_TICKS(1));
    }
    return true;
  };

  // ★ 优化：chunked 解析使用固定 buffer，避免 String 堆分配
  auto makeBodyReader = [&](bool& is_chunked, uint32_t& chunk_left){
    return [&](uint8_t* dst, size_t n, uint32_t timeout_ms)->bool {
      size_t filled = 0;
      uint32_t t0 = millis();
      while (filled < n) {
        if (!cli.connected()) return false;
        if (is_chunked) {
          if (chunk_left == 0) {
            // ★ 使用固定 buffer 解析 chunk size，不用 String
            int len = readLineFixed(lineBuffer, sizeof(lineBuffer), timeout_ms);
            if (len < 0) return false;
            
            // 去掉分号后面的扩展参数
            char* semi = strchr(lineBuffer, ';');
            if (semi) *semi = '\0';
            
            // 去掉首尾空格（简单实现）
            char* p = lineBuffer;
            while (*p == ' ' || *p == '\t') p++;
            
            uint32_t sz = 0;
            if (sscanf(p, "%x", &sz) != 1) return false;
            if (sz == 0) { 
              // 最后一个 chunk，读取尾部 CRLF
              readLineFixed(lineBuffer, sizeof(lineBuffer), 200); 
              return false; 
            }
            chunk_left = sz;
          }
          size_t need = (size_t)min<uint32_t>(chunk_left, (uint32_t)(n - filled));
          while (cli.available() < (int)need) {
            if (millis() - t0 > timeout_ms) return false;
            if (!cli.connected()) return false;
            vTaskDelay(pdMS_TO_TICKS(1));
          }
          int r = cli.read(dst + filled, need);
          if (r <= 0) {
            if (millis() - t0 > timeout_ms) return false;
            vTaskDelay(pdMS_TO_TICKS(1)); continue;
          }
          filled     += r;
          chunk_left -= r;
          if (chunk_left == 0) {
            char crlf[2];
            if (!readNRaw((uint8_t*)crlf, 2, 200)) return false;
          }
        } else {
          if (!readNRaw(dst + filled, n - filled, timeout_ms)) return false;
          filled = n;
        }
      }
      return true;
    };
  };

  const uint32_t BODY_TIMEOUT_MS = 2000;  // 增加超时时间

  while (http_play_running) {
    resetAudioRingBuffer();  // 重置缓冲区
    
    if (!cli.connected()) {
      Serial.println("[HTTP-READ] Connecting...");
      if (!cli.connect(SERVER_HOST, SERVER_PORT)) { 
        vTaskDelay(pdMS_TO_TICKS(500)); 
        continue; 
      }
      String req =
        String("GET /stream.wav HTTP/1.1\r\n") +
        "Host: " + SERVER_HOST + ":" + String(SERVER_PORT) + "\r\n" +
        "Connection: keep-alive\r\n\r\n";
      cli.print(req);
    }

    bool header_ok  = false;
    bool is_chunked = false;
    uint32_t content_len = 0;
    {
      String line; uint32_t t0 = millis();
      while (millis() - t0 < 3000) {
        if (!readLine(line, 1000)) { if (!cli.connected()) break; continue; }
        String u = line; u.toLowerCase();
        if (u.startsWith("transfer-encoding:")) { if (u.indexOf("chunked") >= 0) is_chunked = true; }
        else if (u.startsWith("content-length:")) { content_len = (uint32_t) strtoul(u.substring(strlen("content-length:")).c_str(), nullptr, 10); }
        if (line.length() == 0) { header_ok = true; break; }
      }
    }
    if (!header_ok) { cli.stop(); vTaskDelay(pdMS_TO_TICKS(300)); continue; }

    uint32_t chunk_left = 0;
    auto readBody = makeBodyReader(is_chunked, chunk_left);

    uint8_t hdr12[12];
    if (!readBody(hdr12, 12, 1000)) { cli.stop(); vTaskDelay(pdMS_TO_TICKS(300)); continue; }
    if (memcmp(hdr12, "RIFF", 4) != 0 || memcmp(hdr12 + 8, "WAVE", 4) != 0) { cli.stop(); vTaskDelay(pdMS_TO_TICKS(300)); continue; }

    bool  gotFmt = false, gotData = false;
    uint8_t chdr[8];
    uint16_t audioFormat=0, numChannels=0, bitsPerSample=0;
    uint32_t sampleRate=0;

    while (!gotData) {
      if (!readBody(chdr, 8, 1000)) { cli.stop(); vTaskDelay(pdMS_TO_TICKS(300)); goto reconnect; }
      uint32_t sz = (uint32_t)chdr[4] | ((uint32_t)chdr[5]<<8) | ((uint32_t)chdr[6]<<16) | ((uint32_t)chdr[7]<<24);

      if (memcmp(chdr, "fmt ", 4) == 0) {
        if (sz < 16) { cli.stop(); vTaskDelay(pdMS_TO_TICKS(300)); goto reconnect; }
        uint8_t fmtbuf[32];
        size_t toread = min(sz, (uint32_t)sizeof(fmtbuf));
        if (!readBody(fmtbuf, toread, 1000)) { cli.stop(); vTaskDelay(pdMS_TO_TICKS(300)); goto reconnect; }
        if (sz > toread) {
          size_t left = sz - toread;
          while (left) { uint8_t dump[128]; size_t d = min(left, sizeof(dump));
            if (!readBody(dump, d, 1000)) { cli.stop(); vTaskDelay(pdMS_TO_TICKS(300)); goto reconnect; }
            left -= d;
          }
        }
        audioFormat   = (uint16_t)(fmtbuf[0] | (fmtbuf[1] << 8));
        numChannels   = (uint16_t)(fmtbuf[2] | (fmtbuf[3] << 8));
        sampleRate    = (uint32_t)(fmtbuf[4] | (fmtbuf[5] << 8) | (fmtbuf[6] << 16) | (fmtbuf[7] << 24));
        bitsPerSample = (uint16_t)(fmtbuf[14] | (fmtbuf[15] << 8));
        gotFmt = true;
      }
      else if (memcmp(chdr, "data", 4) == 0) {
        if (!gotFmt) { cli.stop(); vTaskDelay(pdMS_TO_TICKS(300)); goto reconnect; }
        gotData = true;
      }
      else {
        size_t left = sz;
        while (left) { uint8_t dump[128]; size_t d = min(left, sizeof(dump));
          if (!readBody(dump, d, 1000)) { cli.stop(); vTaskDelay(pdMS_TO_TICKS(300)); goto reconnect; }
          left -= d;
        }
      }
    }

    if (!(audioFormat==1 && numChannels==1 && bitsPerSample==16 &&
          (sampleRate==8000 || sampleRate==12000 || sampleRate==16000))) {
      Serial.printf("[HTTP-READ] Unsupported: ch=%u bits=%u sr=%u\n",
                    numChannels, bitsPerSample, sampleRate);
      cli.stop(); vTaskDelay(pdMS_TO_TICKS(300)); continue;
    }
    
    Serial.printf("[HTTP-READ] WAV ok: %u/16bit/mono\n", sampleRate);
    
    // 更新采样率（播放任务会使用）
    if (audioSampleRate != sampleRate) {
      audioSampleRate = sampleRate;
      i2sOut.begin(I2S_MODE_STD, (int)sampleRate, I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_STEREO);
      Serial.printf("[I2S OUT] Reconfig to %u Hz\n", sampleRate);
    }
    
    // 重置缓冲，准备预缓冲
    resetAudioRingBuffer();

    // ★ 优化实时性：更频繁读取更小的块
    uint8_t readBuf[640];  // 20ms@16kHz = 640字节
    while (http_play_running) {
      uint32_t bytesPerRead = sampleRate * 2 * 10 / 1000;  // 10ms（与服务端同步）
      if (bytesPerRead > sizeof(readBuf)) bytesPerRead = sizeof(readBuf);
      
      if (!readBody(readBuf, bytesPerRead, BODY_TIMEOUT_MS)) { 
        break; 
      }
      
      // 写入环形缓冲区
      writeAudioRingBuffer(readBuf, bytesPerRead);
      
      // 让出一点 CPU（不要太长，保持读取速度）
      taskYIELD();
    }

  reconnect:
    audioPlayerReady = false;
    cli.stop();
    vTaskDelay(pdMS_TO_TICKS(200));
  }

  cli.stop();
  Serial.println("[HTTP-READ] Task stopped");
  vTaskDelete(nullptr);
}

void startStreamWav(){
  if (taskHttpReadHandle || taskI2SPlayHandle) return;
  
  // 初始化环形缓冲区
  initAudioRingBuffer();
  resetAudioRingBuffer();
  
  http_play_running = true;
  i2s_play_running = true;
  
  // 启动 I2S 播放任务 - Core 1，高优先级
  xTaskCreatePinnedToCore(taskI2SPlay, "i2s_play", 4096, nullptr, 5, &taskI2SPlayHandle, 1);
  
  // 启动 HTTP 读取任务 - Core 0
  xTaskCreatePinnedToCore(taskHttpRead, "http_read", 8192, nullptr, 3, &taskHttpReadHandle, 0);
  
  Serial.println("[AUDIO] Dual-buffer audio system started");
}

void stopStreamWav(){
  if (!taskHttpReadHandle && !taskI2SPlayHandle) return;
  
  http_play_running = false;
  i2s_play_running = false;
  
  vTaskDelay(pdMS_TO_TICKS(100));
  
  taskHttpReadHandle = nullptr;
  taskI2SPlayHandle = nullptr;
  
  resetAudioRingBuffer();
  requestMouthIdle();
  
  Serial.println("[AUDIO] Audio system stopped");
}

// ====================================================================
// TTS（二进制分片）保留但默认不启用
// ====================================================================
void taskTTSPlay(void*){
  static int32_t stereo32Buf[1024*2];
  for(;;){
    if (!tts_playing){ vTaskDelay(pdMS_TO_TICKS(5)); continue; }
    TTSChunk ch;
    if (xQueueReceive(qTTS, &ch, pdMS_TO_TICKS(50)) == pdPASS){
      size_t inSamp  = ch.n / 2;
      int16_t* inPtr = (int16_t*)ch.data;
      size_t outPairs = 0;
      for (size_t i = 0; i < inSamp; ++i){
        int32_t s = (int32_t)inPtr[i];
        s = (s * 19660) / 32768;
        int32_t v32 = s << 16;
        stereo32Buf[outPairs*2 + 0] = v32;
        stereo32Buf[outPairs*2 + 1] = v32;
        outPairs++;
        if (outPairs >= 1024){
          size_t bytes = outPairs * 2 * sizeof(int32_t);
          size_t off = 0;
          while (off < bytes){
            size_t wrote = i2sOut.write((uint8_t*)stereo32Buf + off, bytes - off);
            if (wrote == 0) vTaskDelay(pdMS_TO_TICKS(1)); else off += wrote;
          }
          outPairs = 0;
        }
      }
      if (outPairs){
        size_t bytes = outPairs * 2 * sizeof(int32_t);
        size_t off = 0;
        while (off < bytes){
          size_t wrote = i2sOut.write((uint8_t*)stereo32Buf + off, bytes - off);
          if (wrote == 0) vTaskDelay(pdMS_TO_TICKS(1)); else off += wrote;
        }
      }
    }
  }
}

inline void tts_reset_queue(){ if (qTTS) xQueueReset(qTTS); }

// ====================================================================
// 离线模式变量（需要在 setup 之前声明）
// ====================================================================
bool offlineModeActive = true;      // 离线模式（上电时为 true）
uint32_t offlineExprNextMs = 0;     // 离线模式下下次随机表情时间

// 离线模式下可用的表情列表
const EmotionType offlineExpressions[] = {EMO_HAPPY, EMO_ANGRY, EMO_SAD, EMO_SPEECHLESS, EMO_WINK};
const int offlineExpressionCount = sizeof(offlineExpressions) / sizeof(offlineExpressions[0]);

// ====================================================================
// Setup / Loop
// ====================================================================
void setup() {
  Serial.begin(115200);
  delay(300);

  // WiFi
  // ========== 网络配置（可选，设为 false 则完全离线运行）==========
  #define ENABLE_WIFI true  // 改为 true 启用网络，false 离线运行
  
  #if ENABLE_WIFI
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  esp_wifi_set_ps(WIFI_PS_NONE);
  esp_wifi_set_protocol(WIFI_IF_STA, WIFI_PROTOCOL_11B | WIFI_PROTOCOL_11G | WIFI_PROTOCOL_11N);
  WiFi.setTxPower(WIFI_POWER_19_5dBm);

  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("[WiFi] connecting");
  uint32_t wifiStartMs = millis();
  const uint32_t WIFI_TIMEOUT_MS = 8000;  // 8秒超时
  while (WiFi.status() != WL_CONNECTED && millis() - wifiStartMs < WIFI_TIMEOUT_MS) {
    delay(300);
    Serial.print(".");
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println(" OK " + WiFi.localIP().toString());
  } else {
    Serial.println(" TIMEOUT - Running in offline mode");
  }
  #else
  Serial.println("[WiFi] DISABLED - Running in offline mode");
  #endif

  // Camera
  if (!init_camera()) { Serial.println("[CAM] init failed, reboot..."); delay(1500); esp_restart(); }

  // I2S Mic & Speaker
  init_i2s_in();
  init_i2s_out();

  // 队列
  qFrames = xQueueCreate(3, sizeof(fb_ptr_t));
  qAudio  = xQueueCreate(AUDIO_QUEUE_DEPTH, sizeof(AudioChunk));
  qTTS    = xQueueCreate(TTS_QUEUE_DEPTH, sizeof(TTSChunk));

  // 任务
  xTaskCreatePinnedToCore(taskCamCapture, "cam_cap", 10240, NULL, 4, NULL, 1);
  xTaskCreatePinnedToCore(taskCamSend,    "cam_snd",  8192, NULL, 3, NULL, 1);
  xTaskCreatePinnedToCore(taskMicCapture, "mic_cap",   4096, NULL, 2, NULL, 0);
  xTaskCreatePinnedToCore(taskMicUpload,  "mic_upl",   4096, NULL, 2, NULL, 1);
  xTaskCreatePinnedToCore(taskTTSPlay,    "tts_play",  4096, NULL, 2, NULL, 0);

  // 舵机 I2C + PCA9685（表情控制）
  Wire.begin(5, 6);          // SDA=5, SCL=6
  Wire.setClock(400000);     // ★ 优化：提升 I2C 到 400kHz，减少舵机控制占用 CPU 时间
  pwm.begin();
  pwm.setPWMFreq(SERVO_FREQ);
  delay(200);

  // SCServo 总线舵机初始化（机械臂）
  armBusBegin();
  // 机械臂归中位
  for (int id = 1; id <= 4; id++) {
    armMoveServo(id, ARM_LIMITS[id].midV, ARM_DEFAULT_SPEED, ARM_DEFAULT_ACC);
  }
  Serial.println("[ARM] SCServo arm initialized, all servos to mid position");

  // ★ 初始化嘴部舵机到正确位置
  setServoAngle(CH_MOUTH_R, MOUTH_R_NEUTRAL);       // CH0 右嘴角
  setServoAngle(CH_MOUTH_L, MOUTH_L_NEUTRAL);       // CH1 左嘴角
  setServoAngle(CH_MOUTH_U, MOUTH_U_NEUTRAL);       // CH2 上嘴唇
  setServoAngle(CH_MOUTH_LOWER, MOUTH_LOWER_CLOSED); // CH3 下嘴唇 = 45（闭合）
  
  // 其他舵机归到 90°
  for (int ch = 4; ch < 8; ch++) {
    setServoAngle(ch, 90);
  }
  requestMouthIdle();
  xTaskCreatePinnedToCore(taskMouthDriver, "mouth_drv", 2048, nullptr, 1, &mouthTaskHandle, 1);

  // LED 灯带已移除

  // 初始化关键帧表情系统（Flash存储）
  initExpressionSystem();
  Serial.println("[EXPR] Keyframe expression system initialized");
  
  // 初始化实时表情动画系统（idle自动执行）
  faceAnimInit();
  faceAnimEnable(true);  // 上电即启用动画（离线模式）
  enableOfflineBreathLed();  // 上电时启用离线呼吸灯
  offlineExprNextMs = millis() + randInt(OFFLINE_EXPR_INTERVAL_MIN, OFFLINE_EXPR_INTERVAL_MAX);  // 初始化随机表情计时器
  Serial.println("[FACE] Real-time face animation initialized and enabled (offline mode)");

  #if ENABLE_WIFI
  // HTTP 路由（仅网络模式）
  server.on("/", handleRoot);
  server.on("/id", handleId);
  server.on("/servo", handleServo);
  server.on("/servo_priority", handleServoPriority);  // 最高优先级舵机控制
  server.on("/servo_release", handleServoRelease);    // 释放优先级控制
  server.on("/servo_batch", handleServoBatch);        // 批量舵机控制（PCA9685）
  // 机械臂 SCServo 路由
  server.on("/arm/status", handleArmStatus);          // 机械臂状态
  server.on("/arm/servo", handleArmServoSingle);      // 单个机械臂舵机
  server.on("/arm/batch", handleArmBatch);            // 批量机械臂控制
  // LED路由已移除（无硬件）
  server.on("/expression", handleExpression);
  server.on("/expr_editor", handleExpressionEditor);
  server.on("/expr_save", HTTP_POST, handleExpressionSave);
  server.on("/expr_get", handleExpressionGet);
  server.begin();
  Serial.println("[HTTP] server started (servo + arm + expression + priority control)");
  #endif

  // WebSocket 回调
  wsCam.onEvent([](WebsocketsEvent ev, String){
    if (ev == WebsocketsEvent::ConnectionOpened)  {
      cam_ws_ready = true;
      Serial.println("[WS-CAM] open");
      frame_sent_count = 0;
      frame_dropped_count = 0;
      ws_send_fail_count = 0;
      last_stats_time = millis();
    }
    if (ev == WebsocketsEvent::ConnectionClosed)  {
      cam_ws_ready = false;
      Serial.printf("[WS-CAM] closed (sent=%lu, dropped=%lu, fail=%lu)\n",
                    frame_sent_count, frame_dropped_count, ws_send_fail_count);
    }
  });

  wsCam.onMessage([](WebsocketsMessage msg){
    if (msg.isText()){
      String cmd = msg.data(); cmd.trim();
      if (cmd.startsWith("SET:FRAMESIZE=")) {
        String v = cmd.substring(strlen("SET:FRAMESIZE="));
        v.toUpperCase();
        framesize_t fs = g_frame_size;
        if (v == "SVGA") fs = FRAMESIZE_SVGA;
        else if (v == "XGA") fs = FRAMESIZE_XGA;
        else if (v == "VGA") fs = FRAMESIZE_VGA;
        if (apply_framesize(fs)) Serial.printf("[CAM] framesize set to %s\n", v.c_str());
        else Serial.printf("[CAM] framesize set failed: %s\n", v.c_str());
      }
      else if (cmd.startsWith("SET:QUALITY=")) {
        int q = cmd.substring(strlen("SET:QUALITY=")).toInt();
        q = constrain(q, 5, 40);
        sensor_t* s = esp_camera_sensor_get();
        if (s) { s->set_quality(s, q); Serial.printf("[CAM] quality=%d\n", q); }
      }
      else if (cmd.startsWith("SET:FPS=")) {
        int f = cmd.substring(strlen("SET:FPS=")).toInt();
        g_target_fps = (f <= 0 ? 0 : constrain(f, 5, 60));
        Serial.printf("[CAM] target_fps=%d\n", g_target_fps);
      }
      else if (cmd == "SNAP:HQ") {
        Serial.println("[CAM] SNAP:HQ request");
        if (snapshot_in_progress) return;
        snapshot_in_progress = true;
        sensor_t* s = esp_camera_sensor_get();
        framesize_t old_fs = g_frame_size;
        int old_q = JPEG_QUALITY;
        framesize_t target_fs = FRAMESIZE_SXGA;
        if (s) {
          s->set_framesize(s, target_fs);
          s->set_quality(s, 18);
        }
        vTaskDelay(pdMS_TO_TICKS(500));
        camera_fb_t* fb = esp_camera_fb_get();
        if (fb && fb->format == PIXFORMAT_JPEG) {
          wsCam.send("SNAP:BEGIN");
          bool ok = wsCam.sendBinary((const char*)fb->buf, fb->len);
          wsCam.send("SNAP:END");
          if (!ok) { Serial.println("[CAM] SNAP send failed"); }
          esp_camera_fb_return(fb);
        } else {
          if (fb) esp_camera_fb_return(fb);
          Serial.println("[CAM] SNAP: capture failed");
        }
        if (s) {
          s->set_framesize(s, old_fs);
          s->set_quality(s, old_q);
        }
        snapshot_in_progress = false;
      }
    }
  });

  wsAud.onEvent([](WebsocketsEvent ev, String){
    if (ev == WebsocketsEvent::ConnectionOpened)  { aud_ws_ready = true;  Serial.println("[WS-AUD] open"); }
    if (ev == WebsocketsEvent::ConnectionClosed)  {
      aud_ws_ready = false;
      Serial.println("[WS-AUD] closed");
      requestMouthIdle();
      stopStreamWav();
    }
  });

  wsAud.onMessage([](WebsocketsMessage msg){
    if (!msg.isText()) return;

    String s = msg.data();
    s.trim();

    // 1) SDK 出错后的“重启”逻辑，保留原来的语义
    if (s == "RESTART") {
      Serial.println("[WS-AUD] RESTART from server");
      // 暂停麦克风上传，清空队列
      run_audio_stream = false;
      xQueueReset(qAudio);
      delay(50);

      // 主动向服务器申请新的 ASR 会话
      wsAud.send("START");
      run_audio_stream = true;
      Serial.println("[WS-AUD] mic stream restarted, START sent to server");
    }

    // 2) 完全停止上行（用于 AI 说话时禁用 ASR）
    else if (s == "STOP") {
      Serial.println("[WS-AUD] STOP from server, pause mic upload");
      run_audio_stream = false;
      xQueueReset(qAudio);   // 清掉还没上传的残留数据
    }

    // 3) 从服务器恢复：恢复 mic 上传 + 向服务器发 START 开启新识别
    else if (s == "START") {
      Serial.println("[WS-AUD] START from server, resume mic + request ASR");
      // 先恢复本地上传
      run_audio_stream = true;
      xQueueReset(qAudio);
      delay(20);
      // 再给服务器发 START，让 /ws_audio 那边开一个全新的 Recognition
      wsAud.send("START");
      requestMouthIdle();
    }

    // 4) 情绪命令：EMO:happy / EMO:sad / EMO:angry 等
    else if (s.startsWith("EMO:")) {
      String emotion = s.substring(4);
      emotion.trim();
      Serial.printf("[WS-AUD] Emotion command: %s\n", emotion.c_str());
      setEmotionLed(emotion.c_str());
    }

    // 5) 表情命令：EXPR:happy / EXPR:sad / EXPR:angry 等
    // 使用实时表情动画系统
    else if (s.startsWith("EXPR:")) {
      String exprName = s.substring(5);
      exprName.trim();
      Serial.printf("[WS-AUD] Expression command: %s\n", exprName.c_str());
      faceAnimSetEmotionByName(exprName.c_str());
    }

    // 7) 眼球追踪命令：EYE:lr,ud 或 EYE:IDLE
    // 由服务端人脸检测发送，控制眼球跟随人脸
    else if (s.startsWith("EYE:")) {
      String params = s.substring(4);
      params.trim();
      if (params == "IDLE" || params == "idle") {
        // 停止追踪，恢复随机眼球运动
        faceAnimStopEyeTrack();
      } else {
        // 解析 lr,ud 格式
        int comma = params.indexOf(',');
        if (comma > 0) {
          int lr = params.substring(0, comma).toInt();
          int ud = params.substring(comma + 1).toInt();
          faceAnimSetEyeTrack(lr, ud);
        }
      }
    }
    
    // 8) 嘴型控制命令：MOUTH:vowel 或 MOUTH:vowel,volume
    // 元音决定嘴型形状，音量由 ESP32 本地实时计算
    else if (s.startsWith("MOUTH:")) {
      String params = s.substring(6);
      params.trim();
      if (params.length() > 0) {
        char vowel = params.charAt(0);
        setCurrentVowel(vowel);
        // Serial.printf("[WS] MOUTH: vowel=%c\n", vowel);
      }
    }
    
    // 9) 眼皮控制命令：EYELID:xxx
    // 用于手部遮挡时的眼皮动画
    else if (s.startsWith("EYELID:")) {
      String cmd = s.substring(7);
      cmd.trim();
      if (cmd == "BLINK_FAST") {
        // 快速眨眼几下
        faceAnimEyelidBlinkFast();
        Serial.println("[WS] EYELID: 快速眨眼");
      } else if (cmd == "CLOSE_BOTH") {
        // 双眼闭上
        faceAnimEyelidCloseBoth();
        Serial.println("[WS] EYELID: 双眼闭合");
      } else if (cmd == "PEEK_LEFT") {
        // 睁开左眼偷看
        faceAnimEyelidPeek(true);
        Serial.println("[WS] EYELID: 左眼偷看");
      } else if (cmd == "PEEK_RIGHT") {
        // 睁开右眼偷看
        faceAnimEyelidPeek(false);
        Serial.println("[WS] EYELID: 右眼偷看");
      } else if (cmd == "NORMAL") {
        // 恢复正常
        faceAnimEyelidNormal();
        Serial.println("[WS] EYELID: 恢复正常");
      }
    }

    // 其他指令暂时忽略
  });

}

// ==================== 非阻塞重连定时器 ====================
uint32_t lastCamRetryMs = 0;
uint32_t lastAudRetryMs = 0;
#define CAM_RETRY_INTERVAL_MS 2000  // CAM重连间隔2秒
#define AUD_RETRY_INTERVAL_MS 3000  // AUD重连间隔3秒
bool wsConnectedOnce = false;       // 是否曾经连接成功过（用于区分在线/离线模式）
// 离线模式变量已在前面声明

// ====================================================================
// 串口命令处理（供树莓派通过USB控制）
// ====================================================================
// 命令格式：
//   SERVO:ch,angle,duration    - 优先级舵机控制（duration可选，默认2000ms）
//   RELEASE:ch                 - 释放单个通道
//   RELEASE:ALL                - 释放所有通道
//   BATCH:ch1,a1,d1;ch2,a2,d2  - 批量控制
//   EXPR:name                  - 播放表情（idle/happy/angry/sad/speechless/wink）
//   PING                       - 测试连接，返回PONG

String serialBuffer = "";

void processSerialCommand(String cmd) {
  cmd.trim();
  if (cmd.length() == 0) return;
  
  Serial.printf("[SERIAL] CMD: %s\n", cmd.c_str());
  
  if (cmd == "PING") {
    Serial.println("PONG");
    return;
  }
  
  if (cmd.startsWith("SERVO:")) {
    // 格式: SERVO:ch,angle[,duration]
    String params = cmd.substring(6);
    int comma1 = params.indexOf(',');
    int comma2 = params.indexOf(',', comma1 + 1);
    
    if (comma1 > 0) {
      int ch = params.substring(0, comma1).toInt();
      int angle = params.substring(comma1 + 1, comma2 > 0 ? comma2 : params.length()).toInt();
      uint32_t duration = comma2 > 0 ? params.substring(comma2 + 1).toInt() : 2000;
      
      if (ch >= 0 && ch <= 15) {
        // 安全限制
        angle = constrain(angle, SERVO_LIMITS[ch][0], SERVO_LIMITS[ch][1]);
        setExternalServoControl((uint8_t)ch, angle, duration > 0 ? duration : 1);
        Serial.printf("OK:SERVO ch=%d angle=%d duration=%d\n", ch, angle, duration);
      } else {
        Serial.println("ERR:SERVO ch must be 0-15");
      }
    } else {
      Serial.println("ERR:SERVO format is SERVO:ch,angle[,duration]");
    }
    return;
  }
  
  if (cmd.startsWith("RELEASE:")) {
    String param = cmd.substring(8);
    param.trim();
    if (param == "ALL" || param == "all") {
      for (int i = 0; i < 16; i++) {
        releaseExternalServoControl((uint8_t)i);
      }
      Serial.println("OK:RELEASE ALL");
    } else {
      int ch = param.toInt();
      if (ch >= 0 && ch <= 15) {
        releaseExternalServoControl((uint8_t)ch);
        Serial.printf("OK:RELEASE ch=%d\n", ch);
      } else {
        Serial.println("ERR:RELEASE ch must be 0-15 or ALL");
      }
    }
    return;
  }
  
  if (cmd.startsWith("BATCH:")) {
    // 格式: BATCH:ch1,a1,d1;ch2,a2,d2;...
    String data = cmd.substring(6);
    int count = 0;
    
    int startIdx = 0;
    while (startIdx < data.length()) {
      int endIdx = data.indexOf(';', startIdx);
      if (endIdx == -1) endIdx = data.length();
      
      String segment = data.substring(startIdx, endIdx);
      int comma1 = segment.indexOf(',');
      int comma2 = segment.indexOf(',', comma1 + 1);
      
      if (comma1 > 0) {
        int ch = segment.substring(0, comma1).toInt();
        int angle = segment.substring(comma1 + 1, comma2 > 0 ? comma2 : segment.length()).toInt();
        uint32_t duration = comma2 > 0 ? segment.substring(comma2 + 1).toInt() : 2000;
        
        if (ch >= 0 && ch <= 15) {
          angle = constrain(angle, SERVO_LIMITS[ch][0], SERVO_LIMITS[ch][1]);
          setExternalServoControl((uint8_t)ch, angle, duration > 0 ? duration : 1);
          count++;
        }
      }
      startIdx = endIdx + 1;
    }
    Serial.printf("OK:BATCH %d servos\n", count);
    return;
  }
  
  if (cmd.startsWith("EXPR:")) {
    String exprName = cmd.substring(5);
    exprName.trim();
    faceAnimSetEmotionByName(exprName.c_str());
    Serial.printf("OK:EXPR %s\n", exprName.c_str());
    return;
  }
  
  // LED命令已移除（无硬件）
  
  Serial.printf("ERR:Unknown command: %s\n", cmd.c_str());
}

void checkSerialCommands() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (serialBuffer.length() > 0) {
        processSerialCommand(serialBuffer);
        serialBuffer = "";
      }
    } else {
      serialBuffer += c;
      // 防止缓冲区溢出
      if (serialBuffer.length() > 200) {
        serialBuffer = "";
      }
    }
  }
}

// ★ 脖子舵机实际控制函数
// ★ 关键改进：只发送待执行的命令，避免每帧重复发送导致震颤
void applyNeckServos() {
  for (int id = 1; id <= 4; id++) {
    if (neckCmds[id].pending) {
      neckCmds[id].pending = false;
      // ★ 只发送一次命令，让 SCServo 自己完成平滑运动
      armMoveServo(id, neckCmds[id].targetPos, neckCmds[id].speed, neckCmds[id].acc);
      // Serial.printf("[NECK] 发送命令: ID=%d pos=%d speed=%d acc=%d\n", 
      //   id, neckCmds[id].targetPos, neckCmds[id].speed, neckCmds[id].acc);
    }
  }
}

void loop() {
  uint32_t now = millis();
  
  // 串口命令处理（树莓派通过USB控制，始终可用）
  checkSerialCommands();
  
#if ENABLE_WIFI
  // ========== 网络模式 ==========
  // 舵机 HTTP 请求
  server.handleClient();

  // WebSocket 连接维护（非阻塞）
  bool camOK = wsCam.available();
  bool audOK = wsAud.available();
  
  if (!camOK) {
    // 非阻塞重连：检查是否到达重连时间
    if (now - lastCamRetryMs >= CAM_RETRY_INTERVAL_MS) {
      lastCamRetryMs = now;
      if (wsCam.connect(SERVER_HOST, SERVER_PORT, CAM_WS_PATH)) {
        Serial.println("[WS-CAM] connected");
        camOK = true;
      } else {
        Serial.println("[WS-CAM] retry...");
      }
    }
  }

  if (!audOK) {
    // 非阻塞重连：检查是否到达重连时间
    if (now - lastAudRetryMs >= AUD_RETRY_INTERVAL_MS) {
      lastAudRetryMs = now;
      if (wsAud.connect(SERVER_HOST, SERVER_PORT, AUD_WS_PATH)) {
        Serial.println("[WS-AUD] connected");
        audOK = true;
        delay(50);  // 短暂等待连接稳定
        run_audio_stream = true;
        wsAud.send("START");
        startStreamWav();
      } else {
        Serial.println("[WS-AUD] retry...");
      }
    }
  }

  // 在线/离线模式判断
  if (camOK && audOK) {
    // 在线模式：两个 WebSocket 都连接成功
    if (offlineModeActive) {
      offlineModeActive = false;
      wsConnectedOnce = true;
      disableOfflineBreathLed();  // 禁用离线呼吸灯（在线模式由服务端控制）
      Serial.println("[MAIN] Online mode: Both WebSocket connected!");
    }
    // 实时表情动画更新（服务端可通过 EXPR:xxx 指令控制）
    faceAnimUpdate();
    // ★ 应用脖子舵机位置
    applyNeckServos();
  } else {
    // 离线模式：未连接或断开连接
    if (!offlineModeActive && wsConnectedOnce) {
      offlineModeActive = true;
      offlineExprNextMs = now + randInt(OFFLINE_EXPR_INTERVAL_MIN, OFFLINE_EXPR_INTERVAL_MAX);
      enableOfflineBreathLed();
      Serial.println("[MAIN] Offline mode: WebSocket disconnected");
    }
    
    // 离线动画
    faceAnimUpdate();
    // ★ 应用脖子舵机位置
    applyNeckServos();
    updateOfflineBreathLed(now, faceAnim.currentEmotion);
    
    // 随机表情
    if (faceAnim.currentEmotion == EMO_IDLE && now >= offlineExprNextMs) {
      offlineExprNextMs = now + randInt(OFFLINE_EXPR_INTERVAL_MIN, OFFLINE_EXPR_INTERVAL_MAX);
      if (randFloat(0, 1) < OFFLINE_EXPR_PROB) {
        int idx = random(offlineExpressionCount);
        EmotionType expr = offlineExpressions[idx];
        faceAnimSetEmotion(expr);
        Serial.printf("[MAIN] Offline: %s\n", EMOTION_NAMES[expr]);
      }
    }
  }

  wsCam.poll();
  wsAud.poll();
  
#else
  // ========== 完全离线模式（无网络）==========
  // 动画更新
  faceAnimUpdate();
  // ★ 应用脖子舵机位置
  applyNeckServos();
  
  // 呼吸灯
  updateOfflineBreathLed(now, faceAnim.currentEmotion);
  
  // 偶尔随机表情
  if (faceAnim.currentEmotion == EMO_IDLE && now >= offlineExprNextMs) {
    offlineExprNextMs = now + randInt(OFFLINE_EXPR_INTERVAL_MIN, OFFLINE_EXPR_INTERVAL_MAX);
    if (randFloat(0, 1) < OFFLINE_EXPR_PROB) {
      int idx = random(offlineExpressionCount);
      EmotionType expr = offlineExpressions[idx];
      faceAnimSetEmotion(expr);
      Serial.printf("[OFFLINE] Expression: %s\n", EMOTION_NAMES[expr]);
    }
  }
#endif

  delay(2);
}


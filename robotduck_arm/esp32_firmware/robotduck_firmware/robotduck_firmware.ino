#include <WiFi.h>
#include <esp_camera.h>
#include <ArduinoWebsockets.h>
#include <WebServer.h>
#include <SCServo.h>

// 选一个你实际硬件对应的
#define CAMERA_MODEL_XIAO_ESP32S3
// #define CAMERA_MODEL_AI_THINKER
// #define CAMERA_MODEL_M5STACK_PSRAM

// 重要：请把你 compile.ino 工程里的 camera_pins.h 拷贝到本文件同目录
#include "camera_pins.h"

using namespace websockets;

// ===================== WiFi & WS (参考 compile.ino) =====================
static const char* WIFI_SSID = "shaliyun";
static const char* WIFI_PASS = "aiyanjiushi66";

// 你的电脑 IP（非常关键）：ESP32 会主动连到电脑的 WS Server
static const char* SERVER_HOST = "192.168.2.2";
static const uint16_t SERVER_PORT = 8081;
static const char* CAM_WS_PATH = "/ws/camera";

// ===================== Camera Params (参考 compile.ino) =====================
framesize_t g_frame_size = FRAMESIZE_VGA;
static const int JPEG_QUALITY = 17;
static const int FB_COUNT = 2;
volatile int g_target_fps = 15;

WebsocketsClient wsCam;
volatile bool cam_ws_ready = false;
volatile bool snapshot_in_progress = false;

// ===================== Frame Queue (参考 compile.ino) =====================
typedef camera_fb_t* fb_ptr_t;
QueueHandle_t qFrames;

static volatile unsigned long frame_sent_count = 0;
static volatile unsigned long frame_dropped_count = 0;
static volatile unsigned long ws_send_fail_count = 0;
static volatile unsigned long frame_captured_count = 0;

// ===================== SCServo (参考 prepation.ino) =====================
static const int BUS_TX = 43;               // XIAO D6
static const int BUS_RX = 44;               // XIAO D7
static const uint32_t BUS_BAUD = 1000000;

static const int DEFAULT_SPEED = 800;
static const int DEFAULT_ACC   = 30;

SMS_STS st;

// 你的 4 个舵机标定范围（可按需调整）
struct ServoLimit { int minV; int midV; int maxV; };
static ServoLimit LIMITS[5] = {
  {0,0,0},
  {1050, 2025, 3000},   // 1
  {1500, 2047, 2500},   // 2
  {1500, 2047, 2500},   // 3
  {1800, 2047, 2300},   // 4
};

static int lastPos[5] = {0, 2025, 2047, 2047, 2047};

// ===================== HTTP Server =====================
WebServer server(80);

static void busBegin() {
  Serial.printf("[BUS] Serial1 begin: baud=%lu, RX=%d, TX=%d\n",
                (unsigned long)BUS_BAUD, BUS_RX, BUS_TX);
  Serial1.begin(BUS_BAUD, SERIAL_8N1, BUS_RX, BUS_TX); // RX,TX 顺序别写反
  Serial1.setTimeout(10);
  st.pSerial = &Serial1;
  delay(200);
  Serial.println("[BUS] Ready.");
}

static int clampPos(int id, int pos) {
  if (id < 1 || id > 4) return pos;
  if (pos < LIMITS[id].minV) pos = LIMITS[id].minV;
  if (pos > LIMITS[id].maxV) pos = LIMITS[id].maxV;
  return pos;
}

static void moveServoRaw(int id, int pos, int speed, int acc) {
  if (id < 1 || id > 4) return;
  pos = clampPos(id, pos);
  speed = constrain(speed, 50, 2000);
  acc   = constrain(acc,   0,  255);
  st.WritePosEx(id, pos, speed, acc);
  lastPos[id] = pos;
}

static void handleStatus() {
  String json = "{";
  json += "\"ip\":\"" + WiFi.localIP().toString() + "\",";
  json += "\"ws_ready\":" + String(cam_ws_ready ? "true" : "false") + ",";
  json += "\"p1\":" + String(lastPos[1]) + ",";
  json += "\"p2\":" + String(lastPos[2]) + ",";
  json += "\"p3\":" + String(lastPos[3]) + ",";
  json += "\"p4\":" + String(lastPos[4]);
  json += "}";
  server.send(200, "application/json", json);
}

static void handleServoSingle() {
  if (!server.hasArg("id") || !server.hasArg("pos")) {
    server.send(400, "text/plain", "Missing id or pos");
    return;
  }
  int id = server.arg("id").toInt();
  int pos = server.arg("pos").toInt();
  int speed = server.hasArg("speed") ? server.arg("speed").toInt() : DEFAULT_SPEED;
  int acc   = server.hasArg("acc")   ? server.arg("acc").toInt()   : DEFAULT_ACC;

  moveServoRaw(id, pos, speed, acc);
  server.send(200, "text/plain", "OK");
}

static void handleServoBatch() {
  // /arm/batch?p1=..&p2=..&p3=..&p4=..&speed=..&acc=..
  if (!server.hasArg("p1") || !server.hasArg("p2") || !server.hasArg("p3") || !server.hasArg("p4")) {
    server.send(400, "text/plain", "Missing p1/p2/p3/p4");
    return;
  }

  int p1 = server.arg("p1").toInt();
  int p2 = server.arg("p2").toInt();
  int p3 = server.arg("p3").toInt();
  int p4 = server.arg("p4").toInt();
  int speed = server.hasArg("speed") ? server.arg("speed").toInt() : DEFAULT_SPEED;
  int acc   = server.hasArg("acc")   ? server.arg("acc").toInt()   : DEFAULT_ACC;

  moveServoRaw(1, p1, speed, acc);
  moveServoRaw(2, p2, speed, acc);
  moveServoRaw(3, p3, speed, acc);
  moveServoRaw(4, p4, speed, acc);

  server.send(200, "text/plain", "OK");
}

// ===================== Camera (参考 compile.ino) =====================
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

  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href  = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn  = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;

  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size   = g_frame_size;
  config.jpeg_quality = JPEG_QUALITY;
  config.fb_count     = FB_COUNT;
  config.fb_location  = CAMERA_FB_IN_PSRAM;
  config.grab_mode    = CAMERA_GRAB_LATEST;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("[CAM] init failed: 0x%x\n", err);
    return false;
  }

  sensor_t * s = esp_camera_sensor_get();
  if (s) {
    s->set_hmirror(s, 1);  // 与 compile.ino 保持一致
    s->set_vflip(s, 0);

    s->set_brightness(s, 0);
    s->set_contrast(s, 1);
    s->set_saturation(s, 1);
    s->set_gain_ctrl(s, 1);
    s->set_exposure_ctrl(s, 0);
    s->set_whitebal(s, 1);
    s->set_awb_gain(s, 1);
    s->set_aec2(s, 0);
    s->set_aec_value(s, 100);
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
    if (xQueueSend(qFrames, &fb, 0) != pdPASS) {
      esp_camera_fb_return(fb);
      frame_dropped_count++;
    }
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
          unsigned long gap = (last_sent_time > 0) ? (now - last_sent_time) : 0;
          Serial.printf("[CAM-SEND] sent=%lu, dropped=%lu, ws_fail=%lu, last_gap=%lu ms\n",
                        frame_sent_count, frame_dropped_count, ws_send_fail_count, gap);
          last_log = now;
        }
      } else if (fb) {
        esp_camera_fb_return(fb);
      }
    }
  }
}

// ===================== WS Handlers (参考 compile.ino) =====================
static void setup_ws_callbacks() {
  wsCam.onEvent([](WebsocketsEvent ev, String){
    if (ev == WebsocketsEvent::ConnectionOpened)  {
      cam_ws_ready = true;
      Serial.println("[WS-CAM] open");
      frame_sent_count = 0;
      frame_dropped_count = 0;
      ws_send_fail_count = 0;
    }
    if (ev == WebsocketsEvent::ConnectionClosed) {
      cam_ws_ready = false;
      Serial.printf("[WS-CAM] closed (sent=%lu, dropped=%lu, fail=%lu)\n",
                    frame_sent_count, frame_dropped_count, ws_send_fail_count);
    }
  });

  wsCam.onMessage([](WebsocketsMessage msg){
    if (!msg.isText()) return;
    String cmd = msg.data(); cmd.trim();

    if (cmd.startsWith("SET:FRAMESIZE=")) {
      String v = cmd.substring(strlen("SET:FRAMESIZE="));
      v.toUpperCase();
      framesize_t fs = g_frame_size;
      if (v == "VGA") fs = FRAMESIZE_VGA;
      else if (v == "SVGA") fs = FRAMESIZE_SVGA;
      else if (v == "XGA") fs = FRAMESIZE_XGA;

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
  });
}

// ===================== Setup / Loop =====================
static void connect_ws_if_needed() {
  static unsigned long last_try = 0;
  unsigned long now = millis();
  if (cam_ws_ready) return;
  if (now - last_try < 1500) return;
  last_try = now;

  Serial.printf("[WS-CAM] connecting to ws://%s:%u%s ...\n", SERVER_HOST, SERVER_PORT, CAM_WS_PATH);
  if (wsCam.connect(SERVER_HOST, SERVER_PORT, CAM_WS_PATH)) {
    Serial.println("[WS-CAM] connected");
  } else {
    Serial.println("[WS-CAM] retry...");
  }
}

void setup() {
  Serial.begin(115200);
  delay(300);

  Serial.println();
  Serial.println("=====================================================");
  Serial.println("RobotDuck Firmware: Camera WS + SCServo HTTP Control");
  Serial.println("=====================================================");

  // WiFi
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("[WiFi] connecting");
  unsigned long t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 15000) {
    delay(300);
    Serial.print(".");
  }
  Serial.println();
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("[WiFi] OK, IP=");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("[WiFi] FAILED (still try running)");
  }

  // Servo bus
  busBegin();
  for (int id = 1; id <= 4; id++) moveServoRaw(id, LIMITS[id].midV, DEFAULT_SPEED, DEFAULT_ACC);

  // Camera
  if (!init_camera()) {
    Serial.println("[CAM] init failed, reboot...");
    delay(1500);
    esp_restart();
  }

  // Queue + tasks
  qFrames = xQueueCreate(3, sizeof(fb_ptr_t));
  xTaskCreatePinnedToCore(taskCamCapture, "cam_cap", 4096, NULL, 2, NULL, 1);
  xTaskCreatePinnedToCore(taskCamSend,    "cam_send",4096, NULL, 2, NULL, 1);

  // HTTP
  server.on("/status", HTTP_GET, handleStatus);
  server.on("/arm/servo", HTTP_GET, handleServoSingle);
  server.on("/arm/batch", HTTP_GET, handleServoBatch);
  server.begin();
  Serial.println("[HTTP] server started: /status /arm/servo /arm/batch");

  // WS
  setup_ws_callbacks();
}

void loop() {
  server.handleClient();
  wsCam.poll();
  connect_ws_if_needed();
  delay(2);
}

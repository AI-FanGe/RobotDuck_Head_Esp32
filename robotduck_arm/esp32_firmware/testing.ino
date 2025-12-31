#include <Arduino.h>
#include <SCServo.h>

// ===================== 硬件配置：XIAO ESP32-S3 =====================
// D6=GPIO43(TX), D7=GPIO44(RX)
static const int BUS_TX = 43;
static const int BUS_RX = 44;
static const uint32_t BUS_BAUD = 1000000;

// 如果你编译报错：没有 writeByte()
// 就把这个改成 0，然后用 WriteByte()
#define USE_WRITEBYTE_LOWER 1

static const int DEFAULT_SPEED = 800;   // 保守点更安全
static const int DEFAULT_ACC   = 30;

SMS_STS st;

// ===================== 关节标定（先用默认，后面你会改） =====================
struct JointCalib {
  int minPos;   // 0..4095
  int maxPos;   // 0..4095
  bool invert;
};

JointCalib cal[4] = {
  {1050, 3000, false}, // id=1
  {1500, 2500, false}, // id=2
  {1500, 2500, false}, // id=3
  {1800, 2300, false}, // id=4
};

// ===================== 工具函数 =====================
static inline int clampi(int v, int lo, int hi) {
  if (v < lo) return lo;
  if (v > hi) return hi;
  return v;
}

static int map01ToPos(int jointIdx, float p01) {
  if (jointIdx < 0 || jointIdx > 3) return 2047;
  if (p01 < 0) p01 = 0;
  if (p01 > 1) p01 = 1;
  if (cal[jointIdx].invert) p01 = 1.0f - p01;
  int pos = (int)(cal[jointIdx].minPos + p01 * (cal[jointIdx].maxPos - cal[jointIdx].minPos));
  return clampi(pos, cal[jointIdx].minPos, cal[jointIdx].maxPos);
}

static void busBegin() {
  Serial.printf("[BUS] Serial1 begin: baud=%lu, RX=%d, TX=%d\n",
                (unsigned long)BUS_BAUD, BUS_RX, BUS_TX);
  Serial1.begin(BUS_BAUD, SERIAL_8N1, BUS_RX, BUS_TX); // 注意顺序：RX,TX
  Serial1.setTimeout(10);
  st.pSerial = &Serial1;
  delay(200);
  Serial.println("[BUS] Ready.");
}

static void scanServos(int maxId) {
  maxId = clampi(maxId, 1, 253);
  Serial.printf("[SCAN] scanning id=1..%d (ReadPos)\n", maxId);
  int found = 0;
  for (int id = 1; id <= maxId; id++) {
    int pos = st.ReadPos(id);
    if (pos >= 0) {
      found++;
      Serial.printf("[SCAN] FOUND id=%d pos=%d\n", id, pos);
    }
    delay(10);
  }
  Serial.printf("[SCAN] done. found=%d\n", found);
}

static bool readAndLog(int id) {
  int pos = st.ReadPos(id);
  if (pos < 0) {
    Serial.printf("[READ] id=%d FAIL (no response)\n", id);
    return false;
  }
  int vol  = st.ReadVoltage(id);
  int tmp  = st.ReadTemper(id);
  int load = st.ReadLoad(id);
  Serial.printf("[READ] id=%d pos=%d voltage=%d temp=%d load=%d\n", id, pos, vol, tmp, load);
  return true;
}

static void moveServoRaw(int id, int pos4095, int speed, int acc) {
  pos4095 = clampi(pos4095, 0, 4095);
  Serial.printf("[MOVE] id=%d pos=%d speed=%d acc=%d\n", id, pos4095, speed, acc);
  st.WritePosEx(id, pos4095, speed, acc);
}

static void moveJoint01(int jointIdx, float p01, int speed, int acc) {
  int id = jointIdx + 1;
  int pos = map01ToPos(jointIdx, p01);
  Serial.printf("[MOVE01] joint=%d(id=%d) p=%.3f -> pos=%d (min=%d max=%d inv=%d)\n",
                jointIdx + 1, id, p01, pos, cal[jointIdx].minPos, cal[jointIdx].maxPos, cal[jointIdx].invert);
  st.WritePosEx(id, pos, speed, acc);
}

// ===================== 编号：自动找唯一舵机ID =====================
static int findSingleServoId(int &countFound) {
  countFound = 0;
  int lastId = -1;
  Serial.println("[AUTOID] Searching for responding servos on bus (1..253)...");
  for (int id = 1; id <= 253; id++) {
    int pos = st.ReadPos(id);
    if (pos >= 0) {
      countFound++;
      lastId = id;
      Serial.printf("[AUTOID] found id=%d pos=%d\n", id, pos);
      delay(5);
    }
  }
  Serial.printf("[AUTOID] total found=%d\n", countFound);
  return lastId;
}

static bool changeServoId(int oldId, int newId) {
  oldId = clampi(oldId, 1, 253);
  newId = clampi(newId, 1, 253);

  Serial.printf("[SETID] Request: oldId=%d -> newId=%d\n", oldId, newId);

  int posOld = st.ReadPos(oldId);
  if (posOld < 0) {
    Serial.printf("[SETID] FAIL: oldId=%d no response.\n", oldId);
    return false;
  }
  Serial.printf("[SETID] oldId=%d responds. pos=%d\n", oldId, posOld);

  Serial.println("[SETID] Unlock EEPROM...");
  st.unLockEprom(oldId);
  delay(50);

  Serial.println("[SETID] Writing new ID to register(5) ...");
#if USE_WRITEBYTE_LOWER
  st.writeByte(oldId, 5, newId);   // 常见版本是 writeByte
#else
  st.WriteByte(oldId, 5, newId);   // 有些版本是 WriteByte
#endif
  delay(100);

  Serial.println("[SETID] Lock EEPROM...");
  st.LockEprom(newId);
  delay(50);

  int posNew = st.ReadPos(newId);
  if (posNew >= 0) {
    Serial.printf("[SETID] SUCCESS: newId=%d responds. pos=%d\n", newId, posNew);
    Serial.println("[SETID] Tip: power-cycle once to be safe.");
    return true;
  } else {
    Serial.printf("[SETID] WARN: newId=%d no response yet.\n", newId);
    Serial.println("[SETID] Try power-cycle and scan again.");
    return false;
  }
}

// ===================== 命令行 =====================
static void printHelp() {
  Serial.println("======== Commands ========");
  Serial.println("help");
  Serial.println("scan [maxId]");
  Serial.println("read <id>");
  Serial.println("move <id> <pos0..4095> [speed] [acc]");
  Serial.println("home                     -> move id1..4 to 2047");
  Serial.println("norm <p1> <p2> <p3> <p4>  -> joint1..4 normalized 0..1");
  Serial.println("autoid <newId>            -> ONLY ONE servo connected");
  Serial.println("setid <oldId> <newId>");
  Serial.println("==========================");
}

static void processLine(String line) {
  line.trim();
  if (line.length() == 0) return;
  Serial.printf("[CMD] %s\n", line.c_str());

  if (line.equalsIgnoreCase("help")) { printHelp(); return; }

  if (line.startsWith("scan")) {
    int maxId = 10;
    sscanf(line.c_str(), "scan %d", &maxId);
    scanServos(maxId);
    return;
  }

  if (line.startsWith("read")) {
    int id = -1;
    if (sscanf(line.c_str(), "read %d", &id) == 1 && id > 0) readAndLog(id);
    else Serial.println("[ERR] usage: read <id>");
    return;
  }

  if (line.startsWith("move")) {
    int id, pos, speed = DEFAULT_SPEED, acc = DEFAULT_ACC;
    int n = sscanf(line.c_str(), "move %d %d %d %d", &id, &pos, &speed, &acc);
    if (n >= 2) moveServoRaw(id, pos, speed, acc);
    else Serial.println("[ERR] usage: move <id> <pos> [speed] [acc]");
    return;
  }

  if (line.equalsIgnoreCase("home")) {
    Serial.println("[HOME] move id1..4 to 2047");
    for (int id = 1; id <= 4; id++) {
      moveServoRaw(id, 2047, 800, 30);
      delay(30);
    }
    return;
  }

  if (line.startsWith("norm")) {
    float p1, p2, p3, p4;
    if (sscanf(line.c_str(), "norm %f %f %f %f", &p1, &p2, &p3, &p4) == 4) {
      moveJoint01(0, p1, 800, 30); delay(5);
      moveJoint01(1, p2, 800, 30); delay(5);
      moveJoint01(2, p3, 800, 30); delay(5);
      moveJoint01(3, p4, 800, 30);
    } else {
      Serial.println("[ERR] usage: norm <p1> <p2> <p3> <p4>");
    }
    return;
  }

  if (line.startsWith("autoid")) {
    int newId = -1;
    if (sscanf(line.c_str(), "autoid %d", &newId) == 1 && newId > 0) {
      int cnt = 0;
      int oldId = findSingleServoId(cnt);
      if (cnt == 0) { Serial.println("[AUTOID] FAIL: no servo found."); return; }
      if (cnt > 1) { Serial.println("[AUTOID] FAIL: connect ONLY ONE servo."); return; }
      changeServoId(oldId, newId);
    } else Serial.println("[ERR] usage: autoid <newId>");
    return;
  }

  if (line.startsWith("setid")) {
    int oldId=-1, newId=-1;
    if (sscanf(line.c_str(), "setid %d %d", &oldId, &newId) == 2) changeServoId(oldId, newId);
    else Serial.println("[ERR] usage: setid <oldId> <newId>");
    return;
  }

  Serial.println("[ERR] unknown command. type: help");
}

void setup() {
  Serial.begin(115200);
  delay(300);

  Serial.println();
  Serial.println("=====================================================");
  Serial.println("XIAO ESP32-S3 Bus Servo Controller (UART) - COMBINED");
  Serial.printf("Pins: BUS_TX=%d (D6), BUS_RX=%d (D7), BAUD=%lu\n", BUS_TX, BUS_RX, (unsigned long)BUS_BAUD);
  Serial.println("Wiring: TX->TX, RX->RX, GND->GND ; Jumper=A (UART mode)");
  Serial.println("=====================================================");

  busBegin();
  printHelp();
  Serial.println("[READY] Try: scan 10");
}

void loop() {
  static String buf;
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (buf.length() > 0) { processLine(buf); buf = ""; }
    } else {
      buf += c;
      if (buf.length() > 200) buf.remove(0, 100);
    }
  }
}

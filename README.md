# 🦆 RobotDuck 智能语音交互机器人

<img width="1547" height="866" alt="image" src="https://github.com/user-attachments/assets/caf178b6-8df7-41b0-a72d-47dc4d721b0b" />

<img width="1561" height="870" alt="image" src="https://github.com/user-attachments/assets/0f85f778-57d9-441c-a2ab-f7a361369a44" />

基于 XIAO ESP32-S3 Sense 的智能语音交互机器人，集成了表情动画、语音对话、视觉问答、机械臂控制等功能。

## ✨ 功能特性

- 🎤 **实时语音对话** - 基于阿里云 FunASR 的实时语音识别 + 通义千问大模型
- 🗣️ **语音合成** - 基于阿里云 CosyVoice 的高质量 TTS，支持多种音色
- 🎭 **表情动画** - 16 通道舵机控制，支持眨眼、眼球跟踪、嘴型同步等
- 👁️ **视觉问答** - 基于通义千问 VL 模型，流式输出快速响应
- 🤖 **机械臂控制** - 4 自由度 SCServo 总线舵机机械臂
- 👋 **手势躲避** - 基于 MediaPipe 的手势检测，自动躲避触摸
- 🎵 **音色克隆** - 录制几秒声音即可克隆你的音色
- 🌐 **Web 控制界面** - 实时预览摄像头画面、控制舵机、调试表情

---

## 📦 硬件清单
<img width="1439" height="872" alt="image" src="https://github.com/user-attachments/assets/1ac002ed-0f35-4130-b84c-3e189a74cf6a" />
<img width="1120" height="767" alt="image" src="https://github.com/user-attachments/assets/a8eda06f-cea1-4077-8a06-cddb3bac19f8" />

### 主控板
| 型号 | 数量 | 说明 |
|------|------|------|
| XIAO ESP32-S3 Sense | 1 | 主控制器，带摄像头和麦克风 |

### 舵机
| 型号 | 数量 | 说明 |
|------|------|------|
| PCA9685 舵机驱动板 | 1 | 16 通道 PWM 舵机控制 |
| SG90 舵机 | 11 个 | 表情舵机（眼睛、嘴巴、翅膀等） |

### 音频模块
| 型号 | 数量 | 说明 |
|------|------|------|
| MAX98357A I2S 功放 | 1 | I2S 音频输出，驱动扬声器 |
| 小型扬声器 | 1 | 3W 4Ω 或类似规格 |

### 电源
| 型号 | 说明 |
|------|------|
| 5V 3A 电源 | 为舵机供电 |
| 3.3V 稳压 （同一个5V也行） | ESP32 本身供电 |

---

## 🔌 硬件接线

### XIAO ESP32-S3 Sense 引脚对照表

| D序号 | GPIO | 功能 |
|-------|------|------|
| D0 | GPIO1 | - |
| D1 | GPIO2 | - |
| D2 | GPIO3 | - |
| D3 | GPIO4 | - |
| **D4** | GPIO5 | **PCA9685 SDA** (I2C 数据线) |
| **D5** | GPIO6 | **PCA9685 SCL** (I2C 时钟线) |
| **D6** | GPIO43 | **SCServo TX** (机械臂串口) |
| **D7** | GPIO44 | **SCServo RX** (机械臂串口) |
| **D8** | GPIO7 | **MAX98357 LRCLK** (I2S) |
| **D9** | GPIO8 | **MAX98357 BCLK** (I2S) |
| **D10** | GPIO9 | **MAX98357 DIN** (I2S) |

### 1️⃣ PCA9685 舵机驱动板

```
PCA9685          XIAO ESP32-S3
  SDA     ────>    D4 (GPIO5)
  SCL     ────>    D5 (GPIO6)
  VCC     ────>    5V（外部电源）
  GND     ────>    GND
```

### 2️⃣ MAX98357A I2S 功放

```
MAX98357         XIAO ESP32-S3
  BCLK    ────>    D9 (GPIO8)
  LRC     ────>    D8 (GPIO7)
  DIN     ────>    D10 (GPIO9)
  VIN     ────>    5V
  GND     ────>    GND
  GAIN    ────>    悬空或接 VIN（15dB增益）
```



### 4️⃣ PCA9685 舵机通道分配

| 通道 | 功能 | 角度范围 |
|------|------|----------|
| CH0 | 右嘴角 | 75°(咧开) ~ 100°(撇嘴) |
| CH1 | 左嘴角 | 110°(咧开) ~ 85°(撇嘴) |
| CH2 | 上嘴唇 | 75°(上) ~ 112°(下) |
| CH3 | 下嘴唇(开合) | 85°(闭) ~ 140°(张) |
| CH4 | 未使用 | - |
| CH5 | 未使用 | - |
| CH6 | 未使用 | - |
| CH7 | 未使用 | - |
| CH8 | 眼睛上下 | 60° ~ 120° |
| CH9 | 未使用 | - |
| CH10 | 眼球左右(左) | 30° ~ 140° |
| CH11 | 眼球左右(右) | 30° ~ 140° |
| CH12 | 眼皮眨眼(左) | 50°(关) ~ 130°(张) |
| CH13 | 眼皮眨眼(右) | 130°(关) ~ 50°(张) |
| CH14 | 眼皮旋转(左) | 45° ~ 135° |
| CH15 | 眼皮旋转(右) | 45° ~ 135° |

---

## 💻 软件安装

### 1. Python 环境

```bash
# 推荐 Python 3.10 或 3.11
python --version

# 创建虚拟环境（可选）
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# 安装依赖
pip install -r requirements.txt
```

### 2. 环境变量配置

创建 `.env` 文件（或设置系统环境变量）：

```env
# 阿里云百炼 API Key（必需）
DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxx

# OSS 配置（视觉问答、音色克隆需要）
OSS_ACCESS_KEY_ID=your_access_key_id
OSS_ACCESS_KEY_SECRET=your_access_key_secret
OSS_ENDPOINT=oss-cn-hangzhou.aliyuncs.com
OSS_BUCKET=your_bucket_name
OSS_PUBLIC_BASE=https://your_bucket.oss-cn-hangzhou.aliyuncs.com

# 可选配置
TTS_MODEL=cosyvoice-v3-plus
DEFAULT_VOICE=longanhuan
VISION_MODEL=qwen-vl-max
```

### 3. ESP32 固件烧录

1. 安装 Arduino IDE 2.0+
2. 添加 ESP32 开发板支持：
   - 文件 → 首选项 → 附加开发板管理器网址
   - 添加：`https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json`
3. 安装依赖库：
   - `ArduinoWebsockets`
   - `Adafruit PWM Servo Driver Library`
   - `SCServo`
4. 修改 `compile/compile.ino` 中的 WiFi 配置：
   ```cpp
   const char* WIFI_SSID   = "你的WiFi名称";
   const char* WIFI_PASS   = "你的WiFi密码";
   const char* SERVER_HOST = "电脑IP地址";
   const uint16_t SERVER_PORT = 8081;
   ```
5. 选择开发板：`XIAO_ESP32S3`
6. 上传固件

### 4. 启动服务

```bash
# 启动主服务（端口 8081）
python app_main.py

# 或者启动机械臂独立模式
python robotduck_arm/main.py
```

---

## 🌐 Web 界面

启动服务后，访问以下地址：

| 地址 | 功能 |
|------|------|
| `http://localhost:8081/` | 主控制界面（摄像头预览、语音对话） |
| `http://localhost:8081/static/vision.html` | 视觉调试界面 |

---

## 🎤 语音指令

| 指令示例 | 功能 |
|----------|------|
| "你好" / 任意对话 | 普通对话 |
| "帮我看一下这是什么" | 视觉问答（流式） |
| "克隆我的声音" / "用我的声音说话" | 音色克隆 |
| "用四川话和我聊" | 方言模式 |
| "恢复默认" | 重置所有设置 |

---

## 📁 项目结构

```
developnewgood/
├── app_main.py              # 主程序入口
├── audio_stream.py          # 音频流处理
├── audio_player.py          # 音频播放
├── voice_adapter.py         # TTS 适配器
├── requirements.txt         # Python 依赖
│
├── compile/                 # ESP32 固件
│   ├── compile.ino          # 主固件代码
│   ├── face_animation.h     # 表情动画系统
│   └── camera_pins.h        # 摄像头引脚定义
│
├── robotduck_arm/           # 机械臂模块
│   ├── main.py              # 独立运行入口
│   ├── config.py            # 配置参数
│   ├── control.py           # 控制逻辑
│   ├── vision.py            # 视觉处理
│   └── esp32_firmware/      # ESP32 测试固件
│
├── robotduck_voice_assistant/  # 语音助手核心
│   ├── asr.py               # 语音识别
│   ├── cosyvoice.py         # TTS 引擎
│   ├── dispatcher.py        # 意图路由
│   ├── state.py             # 状态管理
│   └── workflows.py         # 工作流（视觉问答等）
│
├── static/                  # 前端静态文件
├── templates/               # HTML 模板
├── model/                   # AI 模型文件
└── runtime/                 # 运行时临时文件
```

---


## 🙏 致谢

- [阿里云百炼](https://bailian.console.aliyun.com/) - AI 模型服务
- [XIAO ESP32-S3](https://wiki.seeedstudio.com/xiao_esp32s3_getting_started/) - 硬件平台
- [MediaPipe](https://mediapipe.dev/) - 手势检测


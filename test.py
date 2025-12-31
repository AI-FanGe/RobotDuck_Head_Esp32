import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import requests
import json
import os
import time
import threading
import random
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy

# ======= 写死 ESP32 的 IP 和端口 =======
ESP32_IP = "192.168.2.34"   # 用串口里显示的 IP
ESP32_PORT = 80
SERVO_PATH = "/servo"
EXPRESSIONS_FILE = "expressions.json"  # 表情保存文件
SERVO_CONFIG_FILE = "servo_config.json"  # 舵机配置文件

# ======= 舵机保护参数 =======
MAX_ANGLE_CHANGE = 60  # 单次最大角度变化（度）
MIN_MOVE_INTERVAL = 0.05  # 最小移动间隔（秒）
ENABLE_PROTECTION = True  # 是否启用保护

# 创建全局 Session 对象，复用 TCP 连接以提高速度
session = requests.Session()
session.headers.update({'Connection': 'keep-alive'})

# 记录每个舵机的最后状态
last_angles = [90] * 16  # 初始角度
last_update_time = [0] * 16  # 最后更新时间

# ======= 眼皮舵机与角度定义 =======
EYELID_LEFT_CH = 12
EYELID_RIGHT_CH = 13

# 左眼：50=关，110=正常，130=最大张开
EYELID_LEFT_CLOSED = 50
EYELID_LEFT_NORMAL = 110
EYELID_LEFT_MAX_OPEN = 130

# 右眼：130=关，70=正常，50=最大张开（与左眼镜像）
EYELID_RIGHT_CLOSED = 130
EYELID_RIGHT_NORMAL = 70
EYELID_RIGHT_MAX_OPEN = 50

# ======= 眼球 Idle 动画参数 =======
# --- 眨眼参数 ---
BLINK_INTERVAL_MIN = 2.0        # 眨眼最小间隔（秒）
BLINK_INTERVAL_MAX = 4.0        # 眨眼最大间隔（秒）
BLINK_CLOSE_DURATION = 0.06     # 闭眼持续时间（秒）
BLINK_OPEN_DURATION = 0.06      # 睁眼持续时间（秒）

# --- 眼皮微动参数 ---
EYELID_JITTER_MIN = -10          # 眼皮微动最小偏移（度）
EYELID_JITTER_MAX = 10           # 眼皮微动最大偏移（度）
EYELID_JITTER_INTERVAL_MIN = 0.12  # 眼皮微动更新最小间隔（秒）
EYELID_JITTER_INTERVAL_MAX = 0.35  # 眼皮微动更新最大间隔（秒）

# --- 眼皮抬眼阈值 ---
EYELID_LOOKUP_THRESHOLD = 0.7   # 抬眼时眼皮张到最大的阈值（0-1，数值越小越容易触发）
EYELID_LOOKDOWN_THRESHOLD = 0.3 # 低头时眼皮略闭的阈值

# --- 眼球大跳参数 ---
EYE_FAST_MOVE_DURATION_MIN = 0.08   # 大跳最短时间（秒）
EYE_FAST_MOVE_DURATION_MAX = 0.18   # 大跳最长时间（秒）
EYE_FAST_MOVE_STEP_MIN = 0.5        # 大跳最小幅度（占总行程比例）
EYE_FAST_MOVE_STEP_MAX = 0.7        # 大跳最大幅度（占总行程比例）
EYE_HOLD_AFTER_FAST_MIN = 0.8       # 大跳后停顿最短时间（秒）
EYE_HOLD_AFTER_FAST_MAX = 1.2       # 大跳后停顿最长时间（秒）

# --- 眼球微动/缓动参数 ---
EYE_MICRO_DURATION_MIN = 1.0        # 微动阶段最短持续时间（秒）
EYE_MICRO_DURATION_MAX = 2.2        # 微动阶段最长持续时间（秒）
EYE_MICRO_AMP_UD = 0.25             # 微动上下幅度（占总行程比例）
EYE_MICRO_AMP_H = 0.35              # 微动左右幅度（占总行程比例）
EYE_MICRO_SEG_DURATION_MIN = 0.1    # 单段微动最短时间（秒）
EYE_MICRO_SEG_DURATION_MAX = 0.22   # 单段微动最长时间（秒）
EYE_MICRO_HOLD_MIN = 0.02           # 微动间停顿最短时间（秒）
EYE_MICRO_HOLD_MAX = 0.08           # 微动间停顿最长时间（秒）

# --- 左右扫视参数 ---
EYE_SWEEP_PROBABILITY = 0.35        # 左右扫视触发概率（0-1）
EYE_SWEEP_AMP_H = 0.75              # 扫视左右幅度（占总行程比例）
EYE_SWEEP_AMP_UD = 0.12             # 扫视上下抖动幅度（占总行程比例）
EYE_SWEEP_CYCLES_MIN = 2            # 扫视来回最少次数
EYE_SWEEP_CYCLES_MAX = 4            # 扫视来回最多次数
EYE_SWEEP_SEG_DURATION_MIN = 0.06   # 扫视单段最短时间（秒）
EYE_SWEEP_SEG_DURATION_MAX = 0.12   # 扫视单段最长时间（秒）
EYE_SWEEP_GAP_MIN = 0.02            # 扫视间隔最短时间（秒）
EYE_SWEEP_GAP_MAX = 0.06            # 扫视间隔最长时间（秒）

# --- 扫视后小微动参数 ---
EYE_SWEEP_MICRO_AMP_H = 0.2         # 扫视后小微动左右幅度（占总行程比例）
EYE_SWEEP_MICRO_AMP_UD = 0.08       # 扫视后小微动上下幅度（占总行程比例）
EYE_SWEEP_MICRO_CYCLES_MIN = 2      # 扫视后小微动次数最少
EYE_SWEEP_MICRO_CYCLES_MAX = 4      # 扫视后小微动次数最多
EYE_SWEEP_MICRO_DURATION_MIN = 0.08 # 扫视后小微动单段最短时间（秒）
EYE_SWEEP_MICRO_DURATION_MAX = 0.15 # 扫视后小微动单段最长时间（秒）

# --- 眼球上下偏好 ---
# 【重要】方向已反转：大数字=抬眼，小数字=低头（范围42-120）
EYE_LOOKUP_PROBABILITY = 0.75       # 大跳时看向上方（抬眼/大数字）的概率
EYE_MID_PROBABILITY = 0.2           # 大跳时看向中间的概率
EYE_LOOKDOWN_PROBABILITY = 0.05     # 大跳时看向下方（低头/小数字）的概率
EYE_UD_UP_BIAS = 0.8                # 微动时抬眼偏好（0.5=均匀，越大=越常抬眼）

# --- 全局发呆参数 ---
EYE_IDLE_PAUSE_PROBABILITY = 0.18   # 发呆停顿概率（0-1）
EYE_IDLE_PAUSE_MIN = 0.8            # 发呆最短时间（秒）
EYE_IDLE_PAUSE_MAX = 1.4            # 发呆最长时间（秒）

# --- 刷新率 ---
EYE_MOVE_FPS = 10                   # 眼球移动刷新率（Hz）

# ======= 嘴巴卖萌参数 =======
MOUTH_CH = 9                        # 嘴巴舵机通道
MOUTH_CLOSED = 35                   # 嘴巴闭合角度
MOUTH_MAX_OPEN = 85                 # 嘴巴最大张开角度

# --- 嘴巴卖萌触发 ---
MOUTH_CUTE_PROBABILITY = 0.08       # 每次大跳后触发卖萌的概率（0-1）
MOUTH_CUTE_WITH_BLINK_PROB = 0.25   # 眨眼时同时卖萌的概率
MOUTH_CUTE_INTERVAL_MIN = 8.0       # 两次卖萌之间的最小间隔（秒）
MOUTH_CUTE_INTERVAL_MAX = 20.0      # 两次卖萌之间的最大间隔（秒）

# --- 卖萌方式1：慢开快合 ---
MOUTH_SLOW_OPEN_PROB = 0.6          # 选择"慢开快合"的概率（vs 开合n次）
MOUTH_SLOW_OPEN_DURATION_MIN = 0.4  # 慢慢张开最短时间（秒）
MOUTH_SLOW_OPEN_DURATION_MAX = 0.8  # 慢慢张开最长时间（秒）
MOUTH_SLOW_OPEN_AMOUNT_MIN = 0.4    # 张开幅度最小（占总行程比例）
MOUTH_SLOW_OPEN_AMOUNT_MAX = 0.8    # 张开幅度最大（占总行程比例）
MOUTH_FAST_CLOSE_DURATION = 0.08    # 快速合上时间（秒）
MOUTH_HOLD_OPEN_MIN = 0.1           # 张开后保持时间最小（秒）
MOUTH_HOLD_OPEN_MAX = 0.3           # 张开后保持时间最大（秒）

# --- 卖萌方式2：开合开合n次 ---
MOUTH_FLAP_COUNT_MIN = 2            # 开合次数最少
MOUTH_FLAP_COUNT_MAX = 4            # 开合次数最多
MOUTH_FLAP_OPEN_DURATION = 0.06     # 每次张开时间（秒）
MOUTH_FLAP_CLOSE_DURATION = 0.06    # 每次合上时间（秒）
MOUTH_FLAP_AMOUNT_MIN = 0.3         # 开合幅度最小（占总行程比例）
MOUTH_FLAP_AMOUNT_MAX = 0.6         # 开合幅度最大（占总行程比例）
MOUTH_FLAP_GAP_MIN = 0.02           # 开合间隔最小（秒）
MOUTH_FLAP_GAP_MAX = 0.08           # 开合间隔最大（秒）

# --- 卖萌方式3：嘟嘴（微微张开保持） ---
MOUTH_POUT_AMOUNT_MIN = 0.15        # 嘟嘴幅度最小
MOUTH_POUT_AMOUNT_MAX = 0.3         # 嘟嘴幅度最大
MOUTH_POUT_OPEN_DURATION = 0.1      # 嘟嘴张开时间
MOUTH_POUT_HOLD_MIN = 0.8           # 嘟嘴保持最短
MOUTH_POUT_HOLD_MAX = 1.5           # 嘟嘴保持最长
MOUTH_POUT_CLOSE_DURATION_MIN = 0.3 # 嘟嘴慢慢合上最短
MOUTH_POUT_CLOSE_DURATION_MAX = 0.5 # 嘟嘴慢慢合上最长

# --- 卖萌方式4：惊讶（快速张大） ---
MOUTH_SURPRISE_AMOUNT_MIN = 0.7     # 惊讶幅度最小
MOUTH_SURPRISE_AMOUNT_MAX = 1.0     # 惊讶幅度最大
MOUTH_SURPRISE_OPEN_DURATION = 0.08 # 惊讶张开时间（很快）
MOUTH_SURPRISE_HOLD_MIN = 0.3       # 惊讶保持最短
MOUTH_SURPRISE_HOLD_MAX = 0.6       # 惊讶保持最长
MOUTH_SURPRISE_CLOSE_DURATION_MIN = 0.2  # 惊讶合上最短
MOUTH_SURPRISE_CLOSE_DURATION_MAX = 0.4  # 惊讶合上最长

# --- 卖萌方式5：咀嚼（小幅度不规则开合） ---
MOUTH_CHEW_COUNT_MIN = 3            # 咀嚼次数最少
MOUTH_CHEW_COUNT_MAX = 6            # 咀嚼次数最多
MOUTH_CHEW_AMOUNT_MIN = 0.1         # 咀嚼幅度最小
MOUTH_CHEW_AMOUNT_MAX = 0.35        # 咀嚼幅度最大
MOUTH_CHEW_DURATION_MIN = 0.08      # 单次咀嚼最短
MOUTH_CHEW_DURATION_MAX = 0.15      # 单次咀嚼最长

# --- 卖萌方式6：打哈欠（慢慢张到最大） ---
MOUTH_YAWN_OPEN_DURATION_MIN = 0.6  # 哈欠张开最短
MOUTH_YAWN_OPEN_DURATION_MAX = 1.0  # 哈欠张开最长
MOUTH_YAWN_HOLD_MIN = 0.5           # 哈欠保持最短
MOUTH_YAWN_HOLD_MAX = 1.0           # 哈欠保持最长
MOUTH_YAWN_CLOSE_DURATION_MIN = 0.4 # 哈欠合上最短
MOUTH_YAWN_CLOSE_DURATION_MAX = 0.7 # 哈欠合上最长

# --- 卖萌方式7：微笑抖动 ---
MOUTH_SMILE_AMOUNT_MIN = 0.1        # 微笑幅度最小
MOUTH_SMILE_AMOUNT_MAX = 0.25       # 微笑幅度最大
MOUTH_SMILE_JITTER_COUNT_MIN = 3    # 抖动次数最少
MOUTH_SMILE_JITTER_COUNT_MAX = 6    # 抖动次数最多
MOUTH_SMILE_JITTER_AMP = 0.08       # 抖动幅度（占总行程比例）
MOUTH_SMILE_JITTER_DURATION = 0.05  # 单次抖动时间
MOUTH_SMILE_HOLD_MIN = 0.3          # 微笑后保持最短
MOUTH_SMILE_HOLD_MAX = 0.6          # 微笑后保持最长

# --- 嘴巴动作权重（用于随机选择）---
MOUTH_ACTION_WEIGHTS = {
    "slow_open": 25,      # 慢开快合
    "flap": 20,           # 开合n次
    "pout": 15,           # 嘟嘴
    "surprise": 10,       # 惊讶
    "chew": 10,           # 咀嚼
    "yawn": 8,            # 打哈欠
    "smile": 12,          # 微笑抖动
}

# ======= 情绪模式参数 =======
# --- 眼皮旋转舵机通道 ---
EYELID_ROTATE_LEFT_CH = 14       # 左眼皮旋转
EYELID_ROTATE_RIGHT_CH = 15      # 右眼皮旋转

# --- 眼皮旋转角度定义 ---
# 左侧：60（生气/向上斜）- 85（正常）- 110（伤心/向下斜）
# 右侧：120（生气/向上斜）- 95（正常）- 70（伤心/向下斜）
EYELID_ROTATE_LEFT_ANGRY = 60    # 左眼皮生气角度
EYELID_ROTATE_LEFT_NORMAL = 85   # 左眼皮正常角度
EYELID_ROTATE_LEFT_SAD = 110     # 左眼皮伤心角度

EYELID_ROTATE_RIGHT_ANGRY = 120  # 右眼皮生气角度
EYELID_ROTATE_RIGHT_NORMAL = 95  # 右眼皮正常角度
EYELID_ROTATE_RIGHT_SAD = 70     # 右眼皮伤心角度

# --- 情绪切换过渡时间 ---
EMOTION_TRANSITION_DURATION = 1.0  # 情绪切换过渡时间（秒）- 加快一倍
EMOTION_TRANSITION_FPS = 30        # 过渡动画帧率

# --- 生气模式参数 ---
ANGRY_EYELID_OPEN_LEFT = 80      # 生气时左眼皮张开程度（比正常小）
ANGRY_EYELID_OPEN_RIGHT = 100    # 生气时右眼皮张开程度
ANGRY_MOUTH_FLAP_COUNT = 3       # 生气时嘴巴快速活动次数
ANGRY_MOUTH_FLAP_SPEED = 0.05    # 生气时嘴巴开合速度（秒）
ANGRY_DURATION_MIN = 3.0         # 生气持续最短时间
ANGRY_DURATION_MAX = 5.0         # 生气持续最长时间

# --- 伤心模式参数 ---
SAD_EYELID_OPEN_LEFT = 85        # 伤心时左眼皮张开程度（比正常小）
SAD_EYELID_OPEN_RIGHT = 95       # 伤心时右眼皮张开程度
SAD_EYE_LOOK_DOWN_PROB = 0.7     # 伤心时眼睛往下看的概率
SAD_DURATION_MIN = 4.0           # 伤心持续最短时间
SAD_DURATION_MAX = 6.0           # 伤心持续最长时间

# --- 开心模式参数 ---
HAPPY_EYELID_CLOSED_LEFT = 70    # 开心时左眼皮眯眼程度
HAPPY_EYELID_CLOSED_RIGHT = 110  # 开心时右眼皮眯眼程度
HAPPY_ROTATE_LEFT = 65           # 开心时左眼皮旋转（上斜）
HAPPY_ROTATE_RIGHT = 115         # 开心时右眼皮旋转（上斜）
HAPPY_ROTATE_SWING_AMP = 10      # 开心时眼皮旋转摆动幅度
HAPPY_ROTATE_SWING_DURATION = 0.25  # 开心时摆动周期
HAPPY_MOUTH_OPEN = 75            # 开心时嘴巴张开角度
HAPPY_LAUGH_COUNT_MIN = 3        # 开心时笑的次数最少
HAPPY_LAUGH_COUNT_MAX = 5        # 开心时笑的次数最多
HAPPY_DURATION_MIN = 3.0         # 开心持续最短时间
HAPPY_DURATION_MAX = 5.0         # 开心持续最长时间

# --- 无语模式参数 ---
SPEECHLESS_EYELID_CLOSED_LEFT = 65   # 无语时左眼皮眯眼程度
SPEECHLESS_EYELID_CLOSED_RIGHT = 115 # 无语时右眼皮眯眼程度
SPEECHLESS_EYE_UP_ANGLE = 115        # 无语时眼球上翻角度（大数字=抬眼）
SPEECHLESS_HOLD_MIN = 1.5            # 无语保持最短时间
SPEECHLESS_HOLD_MAX = 2.5            # 无语保持最长时间
SPEECHLESS_DURATION_MIN = 2.0        # 无语持续最短时间
SPEECHLESS_DURATION_MAX = 4.0        # 无语持续最长时间

# --- Wink模式参数 ---
WINK_EYE_OPEN_LEFT = EYELID_LEFT_MAX_OPEN   # wink时左眼张大
WINK_EYE_OPEN_RIGHT = EYELID_RIGHT_MAX_OPEN # wink时右眼张大
WINK_WHICH_EYE = "random"            # wink哪只眼：left/right/random
WINK_CLOSE_DURATION = 0.08           # wink闭眼时间（快速）
WINK_OPEN_DURATION = 0.06            # wink睁眼时间（快速）
WINK_COUNT_MIN = 1                   # wink次数最少
WINK_COUNT_MAX = 2                   # wink次数最多
WINK_EYE_TURN_AMOUNT = 35            # wink时眼球转动幅度
WINK_MOUTH_OPEN_COUNT = 2            # wink后嘴巴张开次数
WINK_MOUTH_OPEN_DURATION = 0.15      # wink后嘴巴张开时间
WINK_DURATION_MIN = 2.0              # wink持续最短时间
WINK_DURATION_MAX = 3.0              # wink持续最长时间

# 默认舵机配置（名称、最小角度、最大角度、默认角度）
DEFAULT_SERVO_CONFIG = {
    0: {"name": "CH 00", "min": 0, "max": 180, "default": 90},
    1: {"name": "CH 01", "min": 0, "max": 180, "default": 90},
    2: {"name": "CH 02", "min": 0, "max": 180, "default": 90},
    3: {"name": "CH 03", "min": 0, "max": 180, "default": 90},
    4: {"name": "CH 04", "min": 0, "max": 180, "default": 90},
    5: {"name": "CH 05", "min": 0, "max": 180, "default": 90},
    6: {"name": "CH 06", "min": 0, "max": 180, "default": 90},
    7: {"name": "CH 07", "min": 0, "max": 180, "default": 90},
    8: {"name": "眼睛上下", "min":60, "max": 120, "default": 90},
    9: {"name": "嘴巴", "min": 35, "max": 85, "default": 85},
    10: {"name": "眼球左右(左)", "min": 30, "max": 140, "default": 90},
    11: {"name": "眼球左右(右)", "min": 30, "max": 140, "default": 90},
    12: {"name": "眼皮眨眼(左)", "min": 0, "max": 180, "default": 90},
    13: {"name": "眼皮眨眼(右)", "min": 0, "max": 180, "default": 90},
    14: {"name": "眼皮旋转(左)", "min": 0, "max": 180, "default": 90},
    15: {"name": "眼皮旋转(右)", "min": 0, "max": 180, "default": 90}
}

# 全局舵机配置
SERVO_CONFIG = deepcopy(DEFAULT_SERVO_CONFIG)


def load_servo_config():
    """加载舵机配置"""
    global SERVO_CONFIG
    if os.path.exists(SERVO_CONFIG_FILE):
        try:
            with open(SERVO_CONFIG_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                # 转换键为整数
                SERVO_CONFIG = {int(k): v for k, v in loaded.items()}
            print(f"[加载] 已加载舵机配置")
        except Exception as e:
            print(f"[错误] 加载舵机配置失败: {e}")
            SERVO_CONFIG = deepcopy(DEFAULT_SERVO_CONFIG)
    else:
        SERVO_CONFIG = deepcopy(DEFAULT_SERVO_CONFIG)


def save_servo_config():
    """保存舵机配置"""
    try:
        with open(SERVO_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(SERVO_CONFIG, f, ensure_ascii=False, indent=2)
        print(f"[保存] 舵机配置已保存")
    except Exception as e:
        print(f"[错误] 保存舵机配置失败: {e}")


def get_servo_label(ch: int) -> str:
    """获取舵机通道的友好标签"""
    return SERVO_CONFIG.get(ch, {}).get("name", f"CH {ch:02d}")


def get_servo_limits(ch: int) -> tuple:
    """获取舵机角度限制 (min, max)"""
    config = SERVO_CONFIG.get(ch, {"min": 0, "max": 180})
    return config.get("min", 0), config.get("max", 180)


def get_servo_default(ch: int) -> int:
    """获取舵机默认角度"""
    return SERVO_CONFIG.get(ch, {}).get("default", 90)


def clamp_angle(ch: int, angle: int) -> int:
    """限制角度在舵机的有效范围内"""
    min_angle, max_angle = get_servo_limits(ch)
    return max(min_angle, min(max_angle, int(angle)))


def set_servo(ch: int, angle: int, force: bool = False):
    """
    发送 HTTP 请求到 ESP32，设置指定通道舵机角度
    ch:    PCA9685 通道号 0~15
    angle: 角度 0~180
    force: 是否强制执行（跳过保护检查）
    """
    global last_angles, last_update_time
    
    # 应用舵机角度限制
    angle = clamp_angle(ch, angle)
    
    # 舵机保护机制
    if ENABLE_PROTECTION and not force:
        # 检查角度变化是否过大
        angle_change = abs(angle - last_angles[ch])
        if angle_change > MAX_ANGLE_CHANGE:
            label = get_servo_label(ch)
            print(f"[警告] {label}(通道{ch}) 角度变化过大 ({angle_change}°)，限制为 {MAX_ANGLE_CHANGE}°")
            # 限制角度变化
            if angle > last_angles[ch]:
                angle = last_angles[ch] + MAX_ANGLE_CHANGE
            else:
                angle = last_angles[ch] - MAX_ANGLE_CHANGE
        
        # 检查更新频率是否过快
        current_time = time.time()
        time_since_last = current_time - last_update_time[ch]
        if time_since_last < MIN_MOVE_INTERVAL:
            wait_time = MIN_MOVE_INTERVAL - time_since_last
            time.sleep(wait_time)
    
    url = f"http://{ESP32_IP}:{ESP32_PORT}{SERVO_PATH}"
    params = {"ch": ch, "angle": angle}
    try:
        # 使用全局 session 复用连接，大幅提升速度
        r = session.get(url, params=params, timeout=0.5)
        label = get_servo_label(ch)
        print(f"[REQ] {label}(通道{ch}): {angle}°")
        
        # 更新记录
        last_angles[ch] = angle
        last_update_time[ch] = time.time()
        
        return True
    except Exception as e:
        label = get_servo_label(ch)
        print(f"[ERR] {label}(通道{ch}): {e}")
        return False


def ease_in_out(t: float) -> float:
    """缓动函数：平滑加速减速"""
    return t * t * (3 - 2 * t)


def ease_in(t: float) -> float:
    """缓动函数：加速"""
    return t * t


def ease_out(t: float) -> float:
    """缓动函数：减速"""
    return t * (2 - t)


def linear(t: float) -> float:
    """线性"""
    return t


# 缓动函数映射
EASING_FUNCTIONS = {
    "linear": linear,
    "ease_in": ease_in,
    "ease_out": ease_out,
    "ease_in_out": ease_in_out
}


class ServoUI:
    def __init__(self, root):
        self.root = root
        self.root.title("ESP32 舵机控制 & 表情管理系统")
        self.root.geometry("1400x900")
        
        # 加载舵机配置
        load_servo_config()
        
        # 表情列表
        self.expressions = []
        self.load_expressions()
        
        # 当前编辑的表情
        self.current_expression = None
        self.current_expression_index = -1
        
        # 序列执行控制
        self.is_running = False
        self.sequence_thread = None
        
        # 眼球 idle 控制
        self.eye_idle_running = False
        self.eye_idle_thread = None
        self.blinking = False
        self._eyelid_next_update_time = 0.0
        self._eyelid_jitter_left = 0.0
        
        # 情绪模式控制
        self.current_emotion = "normal"  # 当前情绪: normal/angry/sad/happy/speechless/wink
        self.emotion_running = False     # 是否正在执行情绪动画
        self.emotion_thread = None       # 情绪动画线程
        self._eyelid_jitter_right = 0.0
        
        # 创建主容器 - 三栏布局
        main_container = ttk.Frame(root)
        main_container.pack(fill="both", expand=True, padx=10, pady=10)
        
        # 左侧面板 - 实时控制
        left_frame = ttk.LabelFrame(main_container, text="舵机实时控制", padding=10)
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        
        # 中间面板 - 表情管理
        middle_frame = ttk.LabelFrame(main_container, text="表情管理", padding=10)
        middle_frame.grid(row=0, column=1, sticky="nsew", padx=5)
        
        # 右侧面板 - 表情编辑器
        right_frame = ttk.LabelFrame(main_container, text="表情编辑器", padding=10)
        right_frame.grid(row=0, column=2, sticky="nsew", padx=(5, 0))
        
        # 配置权重
        main_container.columnconfigure(0, weight=2)  # 舵机控制
        main_container.columnconfigure(1, weight=1)  # 表情管理
        main_container.columnconfigure(2, weight=2)  # 表情编辑
        main_container.rowconfigure(0, weight=1)
        
        # ========== 左侧：实时控制 ==========
        self.setup_realtime_control(left_frame)
        
        # ========== 中间：表情管理 ==========
        self.setup_expression_manager(middle_frame)
        
        # ========== 右侧：表情编辑器 ==========
        self.setup_expression_editor(right_frame)
    
    def setup_realtime_control(self, parent):
        """设置实时控制面板"""
        # 滚动区域
        canvas = tk.Canvas(parent, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # ====== 1. ESP32 连接 & 保护设置 ======
        info_frame = ttk.LabelFrame(scrollable_frame, text="ESP32 连接 & 保护", padding=10)
        info_frame.pack(fill="x", pady=(0, 10))
        
        ttk.Label(info_frame, text=f"地址: http://{ESP32_IP}:{ESP32_PORT}",
                  font=("Arial", 10, "bold")).pack()
        
        # 保护开关
        protection_frame = ttk.Frame(info_frame)
        protection_frame.pack(fill="x", pady=(5, 0))
        
        self.protection_var = tk.IntVar(value=1 if ENABLE_PROTECTION else 0)
        ttk.Checkbutton(protection_frame, text="启用舵机保护（限制角度变化和速度）", 
                       variable=self.protection_var,
                       command=self.toggle_protection).pack(side="left")
        
        ttk.Label(protection_frame, text=f"最大变化: {MAX_ANGLE_CHANGE}°", 
                 foreground="gray").pack(side="left", padx=(10, 0))
        
        # 舵机配置按钮
        config_frame = ttk.Frame(info_frame)
        config_frame.pack(fill="x", pady=(5, 0))
        ttk.Button(config_frame, text="⚙️ 舵机配置", 
                  command=self.open_servo_config).pack(side="left", padx=2)
        ttk.Button(config_frame, text="🔄 复位所有舵机", 
                  command=self.reset_all_servos).pack(side="left", padx=2)
        
        # ====== 2. 单独通道控制（0~15）======
        channels_frame = ttk.LabelFrame(scrollable_frame, text="单独通道控制 (0-15)", padding=10)
        channels_frame.pack(fill="x", pady=(0, 10))
        
        self.sliders = {}
        self.angle_labels = {}
        
        for ch in range(16):
            frame = ttk.Frame(channels_frame)
            frame.pack(fill="x", pady=2)
            
            # 使用自定义标签
            label_text = get_servo_label(ch)
            min_angle, max_angle = get_servo_limits(ch)
            ttk.Label(frame, text=f"{label_text}:", width=14).pack(side="left")
            
            # 显示范围
            ttk.Label(frame, text=f"[{min_angle}-{max_angle}]", 
                     foreground="gray", width=8).pack(side="left")
            
            # 先创建 angle_label，再创建 slider
            angle_label = ttk.Label(frame, text=f"{get_servo_default(ch)}°", width=5)
            self.angle_labels[ch] = angle_label
            
            slider = ttk.Scale(frame, from_=min_angle, to=max_angle, orient="horizontal",
                             command=lambda v, c=ch: self.on_slider_change(c, v))
            slider.set(get_servo_default(ch))
            slider.pack(side="left", fill="x", expand=True, padx=5)
            
            # 绑定鼠标点击事件，支持点击跳转
            slider.bind("<Button-1>", lambda e, c=ch: self.slider_click(e, c))
            
            angle_label.pack(side="left")
            
            self.sliders[ch] = slider
        
        # ====== 3. 镜像控制 ======
        mirror_frame = ttk.LabelFrame(scrollable_frame, text="镜像控制", padding=10)
        mirror_frame.pack(fill="x", pady=(0, 10))
        
        select_frame = ttk.Frame(mirror_frame)
        select_frame.pack(fill="x", pady=(0, 5))
        
        # 创建带标签的选项列表
        mirror_options = [f"{i}:{get_servo_label(i)}" for i in range(16)]
        
        ttk.Label(select_frame, text="通道 A:").pack(side="left", padx=(0, 5))
        self.mirror_a_var = tk.StringVar(value="10")  # 默认右眼眼球左右
        mirror_a = ttk.Combobox(select_frame, textvariable=self.mirror_a_var,
                               values=mirror_options,
                               state="readonly", width=18)
        mirror_a.pack(side="left", padx=(0, 10))
        
        ttk.Label(select_frame, text="通道 B:").pack(side="left", padx=(0, 5))
        self.mirror_b_var = tk.StringVar(value="13")  # 默认左眼眼球左右
        mirror_b = ttk.Combobox(select_frame, textvariable=self.mirror_b_var,
                               values=mirror_options,
                               state="readonly", width=18)
        mirror_b.pack(side="left")
        
        slider_frame = ttk.Frame(mirror_frame)
        slider_frame.pack(fill="x")
        
        ttk.Label(slider_frame, text="镜像角度:", width=10).pack(side="left")
        
        # 先创建 label，再创建 slider
        self.mirror_angle_label = ttk.Label(slider_frame, text="90°", width=5)
        
        self.mirror_slider = ttk.Scale(slider_frame, from_=0, to=180, orient="horizontal",
                                      command=self.on_mirror_change)
        self.mirror_slider.set(90)
        self.mirror_slider.pack(side="left", fill="x", expand=True, padx=5)
        
        # 绑定鼠标点击事件
        self.mirror_slider.bind("<Button-1>", lambda e: self.slider_click_mirror(e))
        
        self.mirror_angle_label.pack(side="left")
        
        # ====== 4. 组控制 ======
        group_frame = ttk.LabelFrame(scrollable_frame, text="组控制（多选）", padding=10)
        group_frame.pack(fill="x", pady=(0, 10))
        
        # 复选框网格（改为垂直布局以显示完整标签）
        cb_container = ttk.Frame(group_frame)
        cb_container.pack(fill="both", expand=True, pady=(0, 5))
        
        self.group_vars = {}
        for i in range(16):
            var = tk.IntVar(value=0)
            self.group_vars[i] = var
            # 使用自定义标签
            label_text = get_servo_label(i)
            cb = ttk.Checkbutton(cb_container, text=f"{i}:{label_text}", variable=var)
            cb.grid(row=i%8, column=i//8, sticky="w", padx=5, pady=1)
        
        # 快捷按钮
        btn_frame = ttk.Frame(group_frame)
        btn_frame.pack(fill="x", pady=(0, 5))
        ttk.Button(btn_frame, text="全选", command=self.select_all).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="全不选", command=self.select_none).pack(side="left", padx=2)
        
        # 组角度滑杆
        slider_frame = ttk.Frame(group_frame)
        slider_frame.pack(fill="x")
        
        ttk.Label(slider_frame, text="组角度:", width=10).pack(side="left")
        
        # 先创建 label，再创建 slider
        self.group_angle_label = ttk.Label(slider_frame, text="90°", width=5)
        
        self.group_slider = ttk.Scale(slider_frame, from_=0, to=180, orient="horizontal",
                                     command=self.on_group_change)
        self.group_slider.set(90)
        self.group_slider.pack(side="left", fill="x", expand=True, padx=5)
        
        # 绑定鼠标点击事件
        self.group_slider.bind("<Button-1>", lambda e: self.slider_click_group(e))
        
        self.group_angle_label.pack(side="left")
    
    def setup_expression_manager(self, parent):
        """设置表情管理面板"""
        # 顶部按钮区
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill="x", pady=(0, 10))
        
        ttk.Button(btn_frame, text="➕ 新建表情", 
                  command=self.new_expression).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="🎲 随机生成", 
                  command=self.generate_random_expression).pack(side="left", padx=2)
        
        # 表情列表区域
        list_frame = ttk.LabelFrame(parent, text="表情列表", padding=10)
        list_frame.pack(fill="both", expand=True, pady=(0, 10))
        
        # 创建列表框和滚动条
        list_container = ttk.Frame(list_frame)
        list_container.pack(fill="both", expand=True)
        
        scrollbar = ttk.Scrollbar(list_container)
        scrollbar.pack(side="right", fill="y")
        
        self.expression_listbox = tk.Listbox(list_container, yscrollcommand=scrollbar.set,
                                            font=("Arial", 10), height=12)
        self.expression_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.expression_listbox.yview)
        
        # 双击编辑
        self.expression_listbox.bind("<Double-1>", lambda e: self.edit_expression())
        
        # 列表操作按钮
        list_btn_frame = ttk.Frame(list_frame)
        list_btn_frame.pack(fill="x", pady=(5, 0))
        
        ttk.Button(list_btn_frame, text="▶️ 播放", 
                  command=self.play_expression).pack(side="left", padx=2)
        ttk.Button(list_btn_frame, text="✏️ 编辑", 
                  command=self.edit_expression).pack(side="left", padx=2)
        ttk.Button(list_btn_frame, text="📋 复制", 
                  command=self.duplicate_expression).pack(side="left", padx=2)
        ttk.Button(list_btn_frame, text="🗑️ 删除", 
                  command=self.delete_expression).pack(side="left", padx=2)
        
        # 导入导出区域
        io_frame = ttk.LabelFrame(parent, text="导入/导出", padding=10)
        io_frame.pack(fill="x", pady=(0, 10))
        
        ttk.Button(io_frame, text="📤 导出选中表情", 
                  command=self.export_selected_expression).pack(fill="x", pady=2)
        ttk.Button(io_frame, text="📤 导出所有表情", 
                  command=self.export_all_expressions).pack(fill="x", pady=2)
        ttk.Button(io_frame, text="📥 导入表情", 
                  command=self.import_expressions).pack(fill="x", pady=2)
        
        # 播放控制
        play_frame = ttk.LabelFrame(parent, text="播放控制", padding=10)
        play_frame.pack(fill="x")
        
        # 全局速度倍率
        speed_frame = ttk.Frame(play_frame)
        speed_frame.pack(fill="x", pady=(0, 5))
        ttk.Label(speed_frame, text="速度倍率:").pack(side="left")
        self.speed_var = tk.DoubleVar(value=1.0)
        speed_spin = ttk.Spinbox(speed_frame, from_=0.1, to=5.0, increment=0.1,
                                textvariable=self.speed_var, width=6)
        speed_spin.pack(side="left", padx=5)
        
        # 循环播放
        self.loop_var = tk.IntVar(value=0)
        ttk.Checkbutton(play_frame, text="循环播放", 
                       variable=self.loop_var).pack(anchor="w")
        
        # 停止按钮
        ttk.Button(play_frame, text="⏹️ 停止播放", 
                  command=self.stop_playback).pack(fill="x", pady=(5, 0))
        
        # 状态显示
        self.status_label = ttk.Label(play_frame, text="就绪", 
                                     foreground="green", font=("Arial", 9))
        self.status_label.pack(fill="x", pady=(5, 0))
        
        # 眼球 Idle 控制
        eye_idle_frame = ttk.LabelFrame(play_frame, text="眼球 Idle 动画", padding=5)
        eye_idle_frame.pack(fill="x", pady=(10, 0))
        
        ttk.Button(eye_idle_frame, text="👁 启动眼球 Idle", 
                  command=self.start_eye_idle).pack(fill="x", pady=2)
        ttk.Button(eye_idle_frame, text="🛑 停止眼球 Idle", 
                  command=self.stop_eye_idle).pack(fill="x", pady=2)
        
        # 情绪模式控制
        emotion_frame = ttk.LabelFrame(play_frame, text="情绪模式", padding=5)
        emotion_frame.pack(fill="x", pady=(10, 0))
        
        # 第一行情绪按钮
        emotion_row1 = ttk.Frame(emotion_frame)
        emotion_row1.pack(fill="x", pady=2)
        ttk.Button(emotion_row1, text="😠 生气", width=8,
                  command=self.start_angry_mode).pack(side="left", padx=2, expand=True)
        ttk.Button(emotion_row1, text="😢 伤心", width=8,
                  command=self.start_sad_mode).pack(side="left", padx=2, expand=True)
        ttk.Button(emotion_row1, text="😄 开心", width=8,
                  command=self.start_happy_mode).pack(side="left", padx=2, expand=True)
        
        # 第二行情绪按钮
        emotion_row2 = ttk.Frame(emotion_frame)
        emotion_row2.pack(fill="x", pady=2)
        ttk.Button(emotion_row2, text="😑 无语", width=8,
                  command=self.start_speechless_mode).pack(side="left", padx=2, expand=True)
        ttk.Button(emotion_row2, text="😉 Wink", width=8,
                  command=self.start_wink_mode).pack(side="left", padx=2, expand=True)
        ttk.Button(emotion_row2, text="😐 复位", width=8,
                  command=self.reset_emotion).pack(side="left", padx=2, expand=True)
        
        # 当前情绪状态显示
        self.emotion_label = ttk.Label(emotion_frame, text="当前: 正常", 
                                       foreground="gray", font=("Arial", 9))
        self.emotion_label.pack(fill="x", pady=(5, 0))
        
        # 刷新列表
        self.refresh_expression_list()
    
    def setup_expression_editor(self, parent):
        """设置表情编辑器面板"""
        # 表情名称
        name_frame = ttk.Frame(parent)
        name_frame.pack(fill="x", pady=(0, 10))
        
        ttk.Label(name_frame, text="表情名称:").pack(side="left")
        self.expr_name_var = tk.StringVar(value="")
        ttk.Entry(name_frame, textvariable=self.expr_name_var, width=20).pack(side="left", padx=5)
        
        # 随机范围设置
        random_frame = ttk.Frame(name_frame)
        random_frame.pack(side="right")
        ttk.Label(random_frame, text="随机范围:±").pack(side="left")
        self.random_range_var = tk.IntVar(value=10)
        ttk.Spinbox(random_frame, from_=0, to=30, textvariable=self.random_range_var,
                   width=4).pack(side="left")
        ttk.Label(random_frame, text="°").pack(side="left")
        
        # 动作帧列表
        frames_frame = ttk.LabelFrame(parent, text="动作帧列表", padding=10)
        frames_frame.pack(fill="both", expand=True, pady=(0, 10))
        
        # 动作帧列表框
        frame_list_container = ttk.Frame(frames_frame)
        frame_list_container.pack(fill="both", expand=True)
        
        frame_scrollbar = ttk.Scrollbar(frame_list_container)
        frame_scrollbar.pack(side="right", fill="y")
        
        self.frame_listbox = tk.Listbox(frame_list_container, yscrollcommand=frame_scrollbar.set,
                                       font=("Arial", 9), height=8)
        self.frame_listbox.pack(side="left", fill="both", expand=True)
        frame_scrollbar.config(command=self.frame_listbox.yview)
        
        # 动作帧操作按钮
        frame_btn_frame = ttk.Frame(frames_frame)
        frame_btn_frame.pack(fill="x", pady=(5, 0))
        
        ttk.Button(frame_btn_frame, text="📸 从当前捕获", 
                  command=self.capture_frame).pack(side="left", padx=2)
        ttk.Button(frame_btn_frame, text="➕ 新建帧", 
                  command=self.new_frame).pack(side="left", padx=2)
        ttk.Button(frame_btn_frame, text="✏️ 编辑帧", 
                  command=self.edit_frame).pack(side="left", padx=2)
        ttk.Button(frame_btn_frame, text="🗑️ 删除帧", 
                  command=self.delete_frame).pack(side="left", padx=2)
        
        frame_btn_frame2 = ttk.Frame(frames_frame)
        frame_btn_frame2.pack(fill="x", pady=(5, 0))
        
        ttk.Button(frame_btn_frame2, text="⬆️ 上移", 
                  command=self.move_frame_up).pack(side="left", padx=2)
        ttk.Button(frame_btn_frame2, text="⬇️ 下移", 
                  command=self.move_frame_down).pack(side="left", padx=2)
        ttk.Button(frame_btn_frame2, text="▶️ 预览帧", 
                  command=self.preview_frame).pack(side="left", padx=2)
        
        # 帧设置区域
        frame_settings = ttk.LabelFrame(parent, text="当前帧设置", padding=10)
        frame_settings.pack(fill="x", pady=(0, 10))
        
        # 过渡时间
        time_frame = ttk.Frame(frame_settings)
        time_frame.pack(fill="x", pady=2)
        ttk.Label(time_frame, text="过渡时间(秒):").pack(side="left")
        self.frame_duration_var = tk.DoubleVar(value=0.5)
        ttk.Spinbox(time_frame, from_=0.0, to=10.0, increment=0.1,
                   textvariable=self.frame_duration_var, width=6).pack(side="left", padx=5)
        
        # 缓动类型
        easing_frame = ttk.Frame(frame_settings)
        easing_frame.pack(fill="x", pady=2)
        ttk.Label(easing_frame, text="缓动效果:").pack(side="left")
        self.frame_easing_var = tk.StringVar(value="linear")
        easing_combo = ttk.Combobox(easing_frame, textvariable=self.frame_easing_var,
                                   values=["linear", "ease_in", "ease_out", "ease_in_out"],
                                   state="readonly", width=12)
        easing_combo.pack(side="left", padx=5)
        
        # 保存按钮
        save_frame = ttk.Frame(parent)
        save_frame.pack(fill="x")
        
        ttk.Button(save_frame, text="💾 保存表情", 
                  command=self.save_current_expression).pack(side="left", padx=2, fill="x", expand=True)
        ttk.Button(save_frame, text="🔙 取消", 
                  command=self.cancel_edit).pack(side="left", padx=2)
    
    # ========== 实时控制回调 ==========
    def toggle_protection(self):
        """切换舵机保护开关"""
        global ENABLE_PROTECTION
        ENABLE_PROTECTION = bool(self.protection_var.get())
        status = "已启用" if ENABLE_PROTECTION else "已禁用"
        print(f"[保护] 舵机保护 {status}")
    
    def open_servo_config(self):
        """打开舵机配置窗口"""
        config_win = tk.Toplevel(self.root)
        config_win.title("舵机配置")
        config_win.geometry("600x700")
        
        # 滚动区域
        canvas = tk.Canvas(config_win, highlightthickness=0)
        scrollbar = ttk.Scrollbar(config_win, orient="vertical", command=canvas.yview)
        scrollable = ttk.Frame(canvas)
        
        scrollable.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # 标题行
        header = ttk.Frame(scrollable)
        header.pack(fill="x", padx=10, pady=5)
        ttk.Label(header, text="通道", width=6).pack(side="left")
        ttk.Label(header, text="名称", width=16).pack(side="left", padx=5)
        ttk.Label(header, text="最小角度", width=10).pack(side="left", padx=5)
        ttk.Label(header, text="最大角度", width=10).pack(side="left", padx=5)
        ttk.Label(header, text="默认角度", width=10).pack(side="left", padx=5)
        
        # 配置条目
        entries = []
        for ch in range(16):
            frame = ttk.Frame(scrollable)
            frame.pack(fill="x", padx=10, pady=2)
            
            config = SERVO_CONFIG.get(ch, DEFAULT_SERVO_CONFIG[ch])
            
            ttk.Label(frame, text=f"CH {ch:02d}", width=6).pack(side="left")
            
            name_entry = ttk.Entry(frame, width=16)
            name_entry.insert(0, config.get("name", f"CH {ch:02d}"))
            name_entry.pack(side="left", padx=5)
            
            min_entry = ttk.Entry(frame, width=8)
            min_entry.insert(0, str(config.get("min", 0)))
            min_entry.pack(side="left", padx=5)
            
            max_entry = ttk.Entry(frame, width=8)
            max_entry.insert(0, str(config.get("max", 180)))
            max_entry.pack(side="left", padx=5)
            
            default_entry = ttk.Entry(frame, width=8)
            default_entry.insert(0, str(config.get("default", 90)))
            default_entry.pack(side="left", padx=5)
            
            entries.append((name_entry, min_entry, max_entry, default_entry))
        
        # 按钮区
        btn_frame = ttk.Frame(scrollable)
        btn_frame.pack(fill="x", padx=10, pady=10)
        
        def save_config():
            global SERVO_CONFIG
            try:
                for ch, (name_e, min_e, max_e, default_e) in enumerate(entries):
                    SERVO_CONFIG[ch] = {
                        "name": name_e.get().strip() or f"CH {ch:02d}",
                        "min": max(0, min(180, int(min_e.get()))),
                        "max": max(0, min(180, int(max_e.get()))),
                        "default": max(0, min(180, int(default_e.get())))
                    }
                save_servo_config()
                self.refresh_sliders()
                config_win.destroy()
                messagebox.showinfo("成功", "舵机配置已保存！")
            except ValueError:
                messagebox.showerror("错误", "请输入有效的数值！")
        
        def reset_config():
            global SERVO_CONFIG
            SERVO_CONFIG = deepcopy(DEFAULT_SERVO_CONFIG)
            for ch, (name_e, min_e, max_e, default_e) in enumerate(entries):
                config = DEFAULT_SERVO_CONFIG[ch]
                name_e.delete(0, tk.END)
                name_e.insert(0, config["name"])
                min_e.delete(0, tk.END)
                min_e.insert(0, str(config["min"]))
                max_e.delete(0, tk.END)
                max_e.insert(0, str(config["max"]))
                default_e.delete(0, tk.END)
                default_e.insert(0, str(config["default"]))
        
        ttk.Button(btn_frame, text="保存配置", command=save_config).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="恢复默认", command=reset_config).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="取消", command=config_win.destroy).pack(side="left", padx=5)
    
    def refresh_sliders(self):
        """刷新滑杆显示"""
        for ch in range(16):
            min_angle, max_angle = get_servo_limits(ch)
            self.sliders[ch].configure(from_=min_angle, to=max_angle)
    
    def reset_all_servos(self):
        """复位所有舵机到默认角度"""
        for ch in range(16):
            default_angle = get_servo_default(ch)
            self.sliders[ch].set(default_angle)
            self.angle_labels[ch].config(text=f"{default_angle}°")
            set_servo(ch, default_angle, force=True)
    
    def slider_click(self, event, ch):
        """滑杆点击事件 - 支持点击跳转"""
        slider = self.sliders[ch]
        min_angle, max_angle = get_servo_limits(ch)
        # 计算点击位置对应的值
        slider_width = slider.winfo_width()
        click_pos = event.x
        value_range = max_angle - min_angle
        new_value = min_angle + (click_pos / slider_width) * value_range
        new_value = max(min_angle, min(max_angle, new_value))
        
        slider.set(new_value)
        self.on_slider_change(ch, new_value)
    
    def slider_click_mirror(self, event):
        """镜像滑杆点击事件"""
        slider_width = self.mirror_slider.winfo_width()
        click_pos = event.x
        new_value = (click_pos / slider_width) * 180
        new_value = max(0, min(180, new_value))
        
        self.mirror_slider.set(new_value)
        self.on_mirror_change(new_value)
    
    def slider_click_group(self, event):
        """组滑杆点击事件"""
        slider_width = self.group_slider.winfo_width()
        click_pos = event.x
        new_value = (click_pos / slider_width) * 180
        new_value = max(0, min(180, new_value))
        
        self.group_slider.set(new_value)
        self.on_group_change(new_value)
    
    def on_slider_change(self, ch, value):
        """单个滑杆改变"""
        angle = int(float(value))
        self.angle_labels[ch].config(text=f"{angle}°")
        set_servo(ch, angle)
    
    def on_mirror_change(self, value):
        """镜像控制"""
        angle_a = int(float(value))
        angle_b = 180 - angle_a
        
        # 从"10:眼球左右(右)"格式中提取通道号
        try:
            ch_a_str = self.mirror_a_var.get().split(':')[0]
            ch_b_str = self.mirror_b_var.get().split(':')[0]
            ch_a = int(ch_a_str)
            ch_b = int(ch_b_str)
        except (ValueError, IndexError):
            return
        
        self.mirror_angle_label.config(text=f"{angle_a}°")
        
        # 应用角度限制
        angle_a = clamp_angle(ch_a, angle_a)
        angle_b = clamp_angle(ch_b, angle_b)
        
        set_servo(ch_a, angle_a)
        set_servo(ch_b, angle_b)
        
        # 同步更新滑杆
        self.sliders[ch_a].set(angle_a)
        self.sliders[ch_b].set(angle_b)
        self.angle_labels[ch_a].config(text=f"{angle_a}°")
        self.angle_labels[ch_b].config(text=f"{angle_b}°")
    
    def on_group_change(self, value):
        """组控制（高效并发执行）"""
        angle = int(float(value))
        self.group_angle_label.config(text=f"{angle}°")
        
        # 获取所有选中的通道
        selected_channels = [ch for ch, var in self.group_vars.items() if var.get() == 1]
        
        if not selected_channels:
            return
        
        # 使用线程池并发发送命令
        with ThreadPoolExecutor(max_workers=16) as executor:
            futures = {executor.submit(set_servo, ch, clamp_angle(ch, angle)): ch 
                      for ch in selected_channels}
            
            # 等待所有命令完成
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    ch = futures[future]
                    print(f"[错误] 通道 {ch} 执行失败: {e}")
        
        # 更新UI
        for ch in selected_channels:
            clamped_angle = clamp_angle(ch, angle)
            self.sliders[ch].set(clamped_angle)
            self.angle_labels[ch].config(text=f"{clamped_angle}°")
    
    def select_all(self):
        """全选通道"""
        for var in self.group_vars.values():
            var.set(1)
    
    def select_none(self):
        """全不选通道"""
        for var in self.group_vars.values():
            var.set(0)
    
    # ========== 表情管理功能 ==========
    def get_current_angles(self):
        """获取当前所有舵机角度"""
        return {str(i): int(float(self.sliders[i].get())) for i in range(16)}
    
    def set_all_angles(self, angles_dict, force=False):
        """设置指定舵机角度（高效并发执行）"""
        if not angles_dict:
            return
            
        # 使用线程池并发发送所有舵机命令
        with ThreadPoolExecutor(max_workers=16) as executor:
            futures = {}
            for ch_str, angle in angles_dict.items():
                ch = int(ch_str)
                clamped_angle = clamp_angle(ch, angle)
                futures[executor.submit(set_servo, ch, clamped_angle, force)] = ch
            
            # 等待所有任务完成
            for future in as_completed(futures):
                ch = futures[future]
                try:
                    future.result()
                except Exception as e:
                    print(f"[错误] 通道 {ch} 执行失败: {e}")
        
        # 更新UI（必须在主线程）
        for ch_str, angle in angles_dict.items():
            ch = int(ch_str)
            clamped_angle = clamp_angle(ch, angle)
            self.sliders[ch].set(clamped_angle)
            self.angle_labels[ch].config(text=f"{clamped_angle}°")
    
    def new_expression(self):
        """新建表情"""
        name = simpledialog.askstring("新建表情", "请输入表情名称:")
        if name:
            new_expr = {
                "name": name,
                "random_range": 10,
                "frames": []
            }
            self.expressions.append(new_expr)
            self.save_expressions()
            self.refresh_expression_list()
            
            # 自动进入编辑模式
            self.current_expression = deepcopy(new_expr)
            self.current_expression_index = len(self.expressions) - 1
            self.load_expression_to_editor()
    
    def edit_expression(self):
        """编辑选中的表情"""
        selection = self.expression_listbox.curselection()
        if not selection:
            messagebox.showwarning("警告", "请先选择一个表情！")
            return
        
        idx = selection[0]
        self.current_expression = deepcopy(self.expressions[idx])
        self.current_expression_index = idx
        self.load_expression_to_editor()
    
    def load_expression_to_editor(self):
        """加载表情到编辑器"""
        if self.current_expression is None:
            return
        
        self.expr_name_var.set(self.current_expression.get("name", ""))
        self.random_range_var.set(self.current_expression.get("random_range", 10))
        self.refresh_frame_list()
    
    def refresh_frame_list(self):
        """刷新动作帧列表"""
        self.frame_listbox.delete(0, tk.END)
        if self.current_expression is None:
            return
        
        for i, frame in enumerate(self.current_expression.get("frames", [])):
            servos_count = len(frame.get("servos", {}))
            duration = frame.get("duration", 0.5)
            easing = frame.get("easing", "linear")
            self.frame_listbox.insert(tk.END, 
                f"{i+1}. [{servos_count}舵机] {duration}s {easing}")
    
    def capture_frame(self):
        """从当前舵机状态捕获动作帧"""
        if self.current_expression is None:
            messagebox.showwarning("警告", "请先创建或选择一个表情！")
            return
        
        # 打开选择舵机的对话框
        self.open_servo_selection_dialog(self.get_current_angles())
    
    def open_servo_selection_dialog(self, angles_dict=None):
        """打开舵机选择对话框"""
        if angles_dict is None:
            angles_dict = {str(i): get_servo_default(i) for i in range(16)}
        
        dialog = tk.Toplevel(self.root)
        dialog.title("选择舵机和设置参数")
        dialog.geometry("600x700")
        
        # 舵机选择区
        servo_frame = ttk.LabelFrame(dialog, text="选择要包含的舵机", padding=10)
        servo_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # 滚动区域
        canvas = tk.Canvas(servo_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(servo_frame, orient="vertical", command=canvas.yview)
        scrollable = ttk.Frame(canvas)
        
        scrollable.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        servo_vars = {}
        angle_entries = {}
        
        for ch in range(16):
            frame = ttk.Frame(scrollable)
            frame.pack(fill="x", pady=2)
            
            var = tk.IntVar(value=1)  # 默认全选
            servo_vars[ch] = var
            
            ttk.Checkbutton(frame, text=f"{ch}: {get_servo_label(ch)}", 
                           variable=var, width=20).pack(side="left")
            
            min_a, max_a = get_servo_limits(ch)
            ttk.Label(frame, text=f"[{min_a}-{max_a}]", foreground="gray").pack(side="left", padx=5)
            
            angle_entry = ttk.Entry(frame, width=6)
            angle_entry.insert(0, str(angles_dict.get(str(ch), get_servo_default(ch))))
            angle_entry.pack(side="left", padx=5)
            angle_entries[ch] = angle_entry
            
            ttk.Label(frame, text="°").pack(side="left")
        
        # 快捷选择
        quick_frame = ttk.Frame(dialog)
        quick_frame.pack(fill="x", padx=10, pady=5)
        
        def select_all_servos():
            for var in servo_vars.values():
                var.set(1)
        
        def select_none_servos():
            for var in servo_vars.values():
                var.set(0)
        
        ttk.Button(quick_frame, text="全选", command=select_all_servos).pack(side="left", padx=2)
        ttk.Button(quick_frame, text="全不选", command=select_none_servos).pack(side="left", padx=2)
        
        # 过渡设置
        settings_frame = ttk.LabelFrame(dialog, text="过渡设置", padding=10)
        settings_frame.pack(fill="x", padx=10, pady=5)
        
        duration_frame = ttk.Frame(settings_frame)
        duration_frame.pack(fill="x", pady=2)
        ttk.Label(duration_frame, text="过渡时间(秒):").pack(side="left")
        duration_var = tk.DoubleVar(value=0.5)
        ttk.Spinbox(duration_frame, from_=0.0, to=10.0, increment=0.1,
                   textvariable=duration_var, width=6).pack(side="left", padx=5)
        
        easing_frame = ttk.Frame(settings_frame)
        easing_frame.pack(fill="x", pady=2)
        ttk.Label(easing_frame, text="缓动效果:").pack(side="left")
        easing_var = tk.StringVar(value="linear")
        ttk.Combobox(easing_frame, textvariable=easing_var,
                    values=["linear", "ease_in", "ease_out", "ease_in_out"],
                    state="readonly", width=12).pack(side="left", padx=5)
        
        # 确认按钮
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill="x", padx=10, pady=10)
        
        def confirm():
            try:
                servos = {}
                for ch, var in servo_vars.items():
                    if var.get() == 1:
                        angle = int(angle_entries[ch].get())
                        angle = clamp_angle(ch, angle)
                        servos[str(ch)] = angle
                
                if not servos:
                    messagebox.showwarning("警告", "请至少选择一个舵机！")
                    return
                
                new_frame = {
                    "servos": servos,
                    "duration": duration_var.get(),
                    "easing": easing_var.get()
                }
                
                self.current_expression["frames"].append(new_frame)
                self.refresh_frame_list()
                dialog.destroy()
            except ValueError:
                messagebox.showerror("错误", "请输入有效的角度值！")
        
        ttk.Button(btn_frame, text="确认添加", command=confirm).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="取消", command=dialog.destroy).pack(side="left", padx=5)
    
    def new_frame(self):
        """新建空白动作帧"""
        if self.current_expression is None:
            messagebox.showwarning("警告", "请先创建或选择一个表情！")
            return
        
        self.open_servo_selection_dialog()
    
    def edit_frame(self):
        """编辑选中的动作帧"""
        if self.current_expression is None:
            return
        
        selection = self.frame_listbox.curselection()
        if not selection:
            messagebox.showwarning("警告", "请先选择一个动作帧！")
            return
        
        idx = selection[0]
        frame = self.current_expression["frames"][idx]
        
        # 打开编辑对话框
        self.open_frame_edit_dialog(idx, frame)
    
    def open_frame_edit_dialog(self, frame_idx, frame_data):
        """打开帧编辑对话框"""
        dialog = tk.Toplevel(self.root)
        dialog.title(f"编辑动作帧 {frame_idx + 1}")
        dialog.geometry("600x700")
        
        # 舵机选择区
        servo_frame = ttk.LabelFrame(dialog, text="舵机设置", padding=10)
        servo_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # 滚动区域
        canvas = tk.Canvas(servo_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(servo_frame, orient="vertical", command=canvas.yview)
        scrollable = ttk.Frame(canvas)
        
        scrollable.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        servo_vars = {}
        angle_entries = {}
        existing_servos = frame_data.get("servos", {})
        
        for ch in range(16):
            frame = ttk.Frame(scrollable)
            frame.pack(fill="x", pady=2)
            
            is_selected = str(ch) in existing_servos
            var = tk.IntVar(value=1 if is_selected else 0)
            servo_vars[ch] = var
            
            ttk.Checkbutton(frame, text=f"{ch}: {get_servo_label(ch)}", 
                           variable=var, width=20).pack(side="left")
            
            min_a, max_a = get_servo_limits(ch)
            ttk.Label(frame, text=f"[{min_a}-{max_a}]", foreground="gray").pack(side="left", padx=5)
            
            angle_entry = ttk.Entry(frame, width=6)
            angle_entry.insert(0, str(existing_servos.get(str(ch), get_servo_default(ch))))
            angle_entry.pack(side="left", padx=5)
            angle_entries[ch] = angle_entry
            
            ttk.Label(frame, text="°").pack(side="left")
        
        # 过渡设置
        settings_frame = ttk.LabelFrame(dialog, text="过渡设置", padding=10)
        settings_frame.pack(fill="x", padx=10, pady=5)
        
        duration_frame = ttk.Frame(settings_frame)
        duration_frame.pack(fill="x", pady=2)
        ttk.Label(duration_frame, text="过渡时间(秒):").pack(side="left")
        duration_var = tk.DoubleVar(value=frame_data.get("duration", 0.5))
        ttk.Spinbox(duration_frame, from_=0.0, to=10.0, increment=0.1,
                   textvariable=duration_var, width=6).pack(side="left", padx=5)
        
        easing_frame = ttk.Frame(settings_frame)
        easing_frame.pack(fill="x", pady=2)
        ttk.Label(easing_frame, text="缓动效果:").pack(side="left")
        easing_var = tk.StringVar(value=frame_data.get("easing", "linear"))
        ttk.Combobox(easing_frame, textvariable=easing_var,
                    values=["linear", "ease_in", "ease_out", "ease_in_out"],
                    state="readonly", width=12).pack(side="left", padx=5)
        
        # 确认按钮
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill="x", padx=10, pady=10)
        
        def confirm():
            try:
                servos = {}
                for ch, var in servo_vars.items():
                    if var.get() == 1:
                        angle = int(angle_entries[ch].get())
                        angle = clamp_angle(ch, angle)
                        servos[str(ch)] = angle
                
                if not servos:
                    messagebox.showwarning("警告", "请至少选择一个舵机！")
                    return
                
                self.current_expression["frames"][frame_idx] = {
                    "servos": servos,
                    "duration": duration_var.get(),
                    "easing": easing_var.get()
                }
                
                self.refresh_frame_list()
                dialog.destroy()
            except ValueError:
                messagebox.showerror("错误", "请输入有效的角度值！")
        
        ttk.Button(btn_frame, text="保存修改", command=confirm).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="取消", command=dialog.destroy).pack(side="left", padx=5)
    
    def delete_frame(self):
        """删除选中的动作帧"""
        if self.current_expression is None:
            return
        
        selection = self.frame_listbox.curselection()
        if not selection:
            messagebox.showwarning("警告", "请先选择一个动作帧！")
            return
        
        idx = selection[0]
        if messagebox.askyesno("确认", f"确定要删除动作帧 {idx + 1} 吗？"):
            del self.current_expression["frames"][idx]
            self.refresh_frame_list()
    
    def move_frame_up(self):
        """上移动作帧"""
        if self.current_expression is None:
            return
        
        selection = self.frame_listbox.curselection()
        if not selection:
            return
        
        idx = selection[0]
        frames = self.current_expression["frames"]
        if idx > 0:
            frames[idx], frames[idx-1] = frames[idx-1], frames[idx]
            self.refresh_frame_list()
            self.frame_listbox.selection_set(idx-1)
    
    def move_frame_down(self):
        """下移动作帧"""
        if self.current_expression is None:
            return
        
        selection = self.frame_listbox.curselection()
        if not selection:
            return
        
        idx = selection[0]
        frames = self.current_expression["frames"]
        if idx < len(frames) - 1:
            frames[idx], frames[idx+1] = frames[idx+1], frames[idx]
            self.refresh_frame_list()
            self.frame_listbox.selection_set(idx+1)
    
    def preview_frame(self):
        """预览选中的动作帧"""
        if self.current_expression is None:
            return
        
        selection = self.frame_listbox.curselection()
        if not selection:
            messagebox.showwarning("警告", "请先选择一个动作帧！")
            return
        
        idx = selection[0]
        frame = self.current_expression["frames"][idx]
        self.set_all_angles(frame.get("servos", {}), force=True)
    
    def save_current_expression(self):
        """保存当前编辑的表情"""
        if self.current_expression is None:
            messagebox.showwarning("警告", "没有正在编辑的表情！")
            return
        
        name = self.expr_name_var.get().strip()
        if not name:
            messagebox.showwarning("警告", "表情名称不能为空！")
            return
        
        self.current_expression["name"] = name
        self.current_expression["random_range"] = self.random_range_var.get()
        
        if self.current_expression_index >= 0:
            self.expressions[self.current_expression_index] = deepcopy(self.current_expression)
        else:
            self.expressions.append(deepcopy(self.current_expression))
            self.current_expression_index = len(self.expressions) - 1
        
        self.save_expressions()
        self.refresh_expression_list()
        messagebox.showinfo("成功", f"表情 '{name}' 已保存！")
    
    def cancel_edit(self):
        """取消编辑"""
        self.current_expression = None
        self.current_expression_index = -1
        self.expr_name_var.set("")
        self.refresh_frame_list()
    
    def duplicate_expression(self):
        """复制选中的表情"""
        selection = self.expression_listbox.curselection()
        if not selection:
            messagebox.showwarning("警告", "请先选择一个表情！")
            return
        
        idx = selection[0]
        expr = deepcopy(self.expressions[idx])
        expr["name"] = expr["name"] + " (副本)"
        self.expressions.append(expr)
        self.save_expressions()
        self.refresh_expression_list()
    
    def delete_expression(self):
        """删除选中的表情"""
        selection = self.expression_listbox.curselection()
        if not selection:
            messagebox.showwarning("警告", "请先选择一个表情！")
            return
        
        idx = selection[0]
        expr_name = self.expressions[idx]["name"]
        
        if messagebox.askyesno("确认", f"确定要删除表情 '{expr_name}' 吗？"):
            del self.expressions[idx]
            self.save_expressions()
            self.refresh_expression_list()
            
            # 如果正在编辑被删除的表情，清空编辑器
            if self.current_expression_index == idx:
                self.cancel_edit()
    
    def play_expression(self):
        """播放选中的表情"""
        selection = self.expression_listbox.curselection()
        if not selection:
            messagebox.showwarning("警告", "请先选择一个表情！")
            return
        
        if self.is_running:
            messagebox.showwarning("警告", "正在播放中...")
            return
        
        idx = selection[0]
        expr = self.expressions[idx]
        
        # 在新线程中执行
        self.is_running = True
        self.sequence_thread = threading.Thread(target=self._play_expression_thread, args=(expr,))
        self.sequence_thread.daemon = True
        self.sequence_thread.start()
    
    def _play_expression_thread(self, expression):
        """播放表情的线程"""
        try:
            frames = expression.get("frames", [])
            if not frames:
                self.root.after(0, lambda: messagebox.showwarning("警告", "表情没有动作帧！"))
                return
            
            speed_factor = self.speed_var.get()
            if speed_factor <= 0:
                speed_factor = 1.0
            
            while True:
                for i, frame in enumerate(frames):
                    if not self.is_running:
                        break
                    
                    # 更新状态
                    self.root.after(0, lambda idx=i, total=len(frames): 
                                   self.status_label.config(
                                       text=f"播放中: {idx+1}/{total}", 
                                       foreground="blue"))
                    
                    # 执行动作帧过渡
                    self._execute_frame_transition(frame, speed_factor)
                
                if not self.is_running or not self.loop_var.get():
                    break
            
            if self.is_running:
                self.root.after(0, lambda: self.status_label.config(text="播放完成", foreground="green"))
        except Exception as e:
            print(f"[错误] 播放失败: {e}")
            self.root.after(0, lambda: self.status_label.config(text=f"错误: {e}", foreground="red"))
        finally:
            self.is_running = False
    
    def _execute_frame_transition(self, frame, speed_factor):
        """执行动作帧过渡"""
        target_servos = frame.get("servos", {})
        duration = frame.get("duration", 0.5) / speed_factor
        easing_name = frame.get("easing", "linear")
        easing_func = EASING_FUNCTIONS.get(easing_name, linear)
        
        if duration <= 0:
            # 直接设置
            self.root.after(0, lambda: self.set_all_angles(target_servos, force=True))
            return
        
        # 获取当前角度
        start_angles = {}
        for ch_str in target_servos.keys():
            ch = int(ch_str)
            start_angles[ch_str] = int(float(self.sliders[ch].get()))
        
        # 平滑过渡
        steps = max(1, int(duration * 50))  # 50Hz 刷新率
        step_time = duration / steps
        
        for step in range(steps + 1):
            if not self.is_running:
                break
            
            t = step / steps
            eased_t = easing_func(t)
            
            # 计算插值角度
            interpolated = {}
            for ch_str, target in target_servos.items():
                start = start_angles.get(ch_str, target)
                current = int(start + (target - start) * eased_t)
                interpolated[ch_str] = current
            
            # 应用角度
            self.root.after(0, lambda angles=interpolated: self.set_all_angles(angles, force=True))
            time.sleep(step_time)
    
    def stop_playback(self):
        """停止播放"""
        if self.is_running:
            self.is_running = False
            self.status_label.config(text="已停止", foreground="orange")
    
    # ==================== 眼球 Idle 动画 ====================
    def start_eye_idle(self):
        """启动眼球 idle 动画"""
        if self.eye_idle_running:
            return
        self.eye_idle_running = True
        self.status_label.config(text="眼球 Idle 中", foreground="blue")
        self.eye_idle_thread = threading.Thread(target=self._eye_idle_thread, daemon=True)
        self.eye_idle_thread.start()
    
    def stop_eye_idle(self):
        """停止眼球 idle 动画"""
        if not self.eye_idle_running:
            return
        self.eye_idle_running = False
        # 不强等等待线程结束，这里只更新状态，真正结束在线程循环里判断
        self.status_label.config(text="Idle 已停止", foreground="orange")
    
    # ==================== 情绪模式 ====================
    def _transition_eyelid_rotate(self, target_left, target_right, duration=None):
        """
        平滑过渡眼皮旋转角度
        target_left: 左眼皮旋转目标角度
        target_right: 右眼皮旋转目标角度
        duration: 过渡时间（秒），默认使用 EMOTION_TRANSITION_DURATION
        """
        if duration is None:
            duration = EMOTION_TRANSITION_DURATION
        
        start_left = last_angles[EYELID_ROTATE_LEFT_CH]
        start_right = last_angles[EYELID_ROTATE_RIGHT_CH]
        
        steps = max(1, int(duration * EMOTION_TRANSITION_FPS))
        step_time = duration / steps
        
        for step in range(steps + 1):
            if not self.emotion_running:
                break
            
            t = step / steps
            # ease_in_out 缓动
            eased_t = t * t * (3 - 2 * t)
            
            cur_left = start_left + (target_left - start_left) * eased_t
            cur_right = start_right + (target_right - start_right) * eased_t
            
            set_servo(EYELID_ROTATE_LEFT_CH, int(cur_left))
            set_servo(EYELID_ROTATE_RIGHT_CH, int(cur_right))
            
            time.sleep(step_time)
    
    def _stop_emotion(self):
        """停止当前情绪动画"""
        self.emotion_running = False
        if self.emotion_thread and self.emotion_thread.is_alive():
            self.emotion_thread.join(timeout=0.5)
    
    def reset_emotion(self):
        """复位到正常状态"""
        self._stop_emotion()
        self.current_emotion = "normal"
        self.emotion_running = True
        
        # 启动复位线程
        def reset_thread():
            # 平滑过渡眼皮旋转到正常
            self._transition_eyelid_rotate(
                EYELID_ROTATE_LEFT_NORMAL, 
                EYELID_ROTATE_RIGHT_NORMAL
            )
            
            # 眼皮张开到正常
            set_servo(EYELID_LEFT_CH, EYELID_LEFT_NORMAL)
            set_servo(EYELID_RIGHT_CH, EYELID_RIGHT_NORMAL)
            
            # 嘴巴闭合
            set_servo(MOUTH_CH, MOUTH_CLOSED)
            
            self.emotion_running = False
            self.root.after(0, lambda: self.emotion_label.config(text="当前: 正常", foreground="gray"))
        
        self.emotion_thread = threading.Thread(target=reset_thread, daemon=True)
        self.emotion_thread.start()
        self.emotion_label.config(text="复位中...", foreground="gray")
    
    def start_angry_mode(self):
        """启动生气模式"""
        self._stop_emotion()
        self.current_emotion = "angry"
        self.emotion_running = True
        self.emotion_label.config(text="当前: 生气 😠", foreground="red")
        
        self.emotion_thread = threading.Thread(target=self._angry_thread, daemon=True)
        self.emotion_thread.start()
    
    def _angry_thread(self):
        """生气模式动画线程"""
        ch_ud = 8
        ch_h_left, ch_h_right = 10, 11
        min_ud, max_ud = get_servo_limits(ch_ud)
        min_h, max_h = get_servo_limits(ch_h_left)
        
        # 先过渡眼皮旋转到生气角度（向上斜）
        self._transition_eyelid_rotate(
            EYELID_ROTATE_LEFT_ANGRY,
            EYELID_ROTATE_RIGHT_ANGRY
        )
        
        if not self.emotion_running:
            return
        
        # 眼皮张开程度变小（眯眼生气）
        set_servo(EYELID_LEFT_CH, ANGRY_EYELID_OPEN_LEFT)
        set_servo(EYELID_RIGHT_CH, ANGRY_EYELID_OPEN_RIGHT)
        
        # 初始眼球位置：稍微向上瞪
        cur_ud = max_ud - (max_ud - min_ud) * 0.3  # 略微抬眼
        cur_h = (min_h + max_h) // 2
        set_servo(ch_ud, int(cur_ud))
        set_servo(ch_h_left, int(cur_h))
        set_servo(ch_h_right, int(cur_h))
        
        duration = random.uniform(ANGRY_DURATION_MIN, ANGRY_DURATION_MAX)
        end_time = time.time() + duration
        
        while self.emotion_running and time.time() < end_time:
            # 生气时眼球快速左右扫视（像在瞪人）
            if random.random() < 0.4:
                # 快速左右扫视
                side = random.choice([-1, 1])
                target_h = cur_h + side * random.uniform(30, 50)
                target_h = max(min_h + 10, min(max_h - 10, target_h))
                
                # 快速移动
                steps = 5
                for step in range(steps + 1):
                    if not self.emotion_running:
                        break
                    t = step / steps
                    h = cur_h + (target_h - cur_h) * t
                    set_servo(ch_h_left, int(h))
                    set_servo(ch_h_right, int(h))
                    time.sleep(0.02)
                cur_h = target_h
            
            # 生气时偶尔嘴巴快速活动
            if random.random() < 0.3:
                mouth_range = MOUTH_MAX_OPEN - MOUTH_CLOSED
                for _ in range(ANGRY_MOUTH_FLAP_COUNT):
                    if not self.emotion_running:
                        break
                    set_servo(MOUTH_CH, MOUTH_CLOSED + int(mouth_range * 0.5))
                    time.sleep(ANGRY_MOUTH_FLAP_SPEED)
                    set_servo(MOUTH_CH, MOUTH_CLOSED)
                    time.sleep(ANGRY_MOUTH_FLAP_SPEED)
            
            # 眼皮和眼球轻微抖动
            jitter = random.randint(-5, 5)
            set_servo(EYELID_LEFT_CH, ANGRY_EYELID_OPEN_LEFT + jitter)
            set_servo(EYELID_RIGHT_CH, ANGRY_EYELID_OPEN_RIGHT - jitter)
            
            # 眼球上下微动
            ud_jitter = random.randint(-5, 5)
            set_servo(ch_ud, int(cur_ud + ud_jitter))
            
            time.sleep(0.15)
        
        if self.emotion_running:
            self.root.after(0, self.reset_emotion)
    
    def start_sad_mode(self):
        """启动伤心模式"""
        self._stop_emotion()
        self.current_emotion = "sad"
        self.emotion_running = True
        self.emotion_label.config(text="当前: 伤心 😢", foreground="blue")
        
        self.emotion_thread = threading.Thread(target=self._sad_thread, daemon=True)
        self.emotion_thread.start()
    
    def _sad_thread(self):
        """伤心模式动画线程"""
        ch_ud = 8
        ch_h_left, ch_h_right = 10, 11
        min_ud, max_ud = get_servo_limits(ch_ud)
        min_h, max_h = get_servo_limits(ch_h_left)
        
        # 过渡眼皮旋转到伤心角度（向下斜）
        self._transition_eyelid_rotate(
            EYELID_ROTATE_LEFT_SAD,
            EYELID_ROTATE_RIGHT_SAD
        )
        
        if not self.emotion_running:
            return
        
        # 眼皮张开程度变小
        set_servo(EYELID_LEFT_CH, SAD_EYELID_OPEN_LEFT)
        set_servo(EYELID_RIGHT_CH, SAD_EYELID_OPEN_RIGHT)
        
        # 嘴巴闭合
        set_servo(MOUTH_CH, MOUTH_CLOSED)
        
        # 初始眼球位置：向下看
        cur_ud = min_ud + (max_ud - min_ud) * 0.3  # 低头
        cur_h = (min_h + max_h) // 2
        set_servo(ch_ud, int(cur_ud))
        set_servo(ch_h_left, int(cur_h))
        set_servo(ch_h_right, int(cur_h))
        
        duration = random.uniform(SAD_DURATION_MIN, SAD_DURATION_MAX)
        end_time = time.time() + duration
        
        while self.emotion_running and time.time() < end_time:
            # 伤心时眼睛缓慢移动
            if random.random() < 0.6:
                # 决定新的目标位置
                if random.random() < SAD_EYE_LOOK_DOWN_PROB:
                    # 往下看（小数字=低头）
                    target_ud = random.uniform(min_ud + 5, min_ud + (max_ud - min_ud) * 0.4)
                else:
                    # 偶尔中间
                    target_ud = random.uniform(min_ud + (max_ud - min_ud) * 0.3, 
                                              min_ud + (max_ud - min_ud) * 0.5)
                
                # 左右缓慢移动
                target_h = cur_h + random.uniform(-20, 20)
                target_h = max(min_h + 20, min(max_h - 20, target_h))
                
                # 缓慢移动眼球
                steps = 15
                step_time = 0.04
                for step in range(steps + 1):
                    if not self.emotion_running:
                        break
                    t = step / steps
                    eased_t = t * t * (3 - 2 * t)  # ease_in_out
                    
                    ud = cur_ud + (target_ud - cur_ud) * eased_t
                    h = cur_h + (target_h - cur_h) * eased_t
                    
                    set_servo(ch_ud, int(ud))
                    set_servo(ch_h_left, int(h))
                    set_servo(ch_h_right, int(h))
                    time.sleep(step_time)
                
                cur_ud = target_ud
                cur_h = target_h
            
            # 缓慢的眼皮微动
            jitter = random.randint(-3, 3)
            set_servo(EYELID_LEFT_CH, SAD_EYELID_OPEN_LEFT + jitter)
            set_servo(EYELID_RIGHT_CH, SAD_EYELID_OPEN_RIGHT - jitter)
            
            time.sleep(random.uniform(0.3, 0.6))
        
        if self.emotion_running:
            self.root.after(0, self.reset_emotion)
    
    def start_happy_mode(self):
        """启动开心模式"""
        self._stop_emotion()
        self.current_emotion = "happy"
        self.emotion_running = True
        self.emotion_label.config(text="当前: 开心 😄", foreground="orange")
        
        self.emotion_thread = threading.Thread(target=self._happy_thread, daemon=True)
        self.emotion_thread.start()
    
    def _happy_thread(self):
        """开心模式动画线程"""
        ch_ud = 8
        ch_h_left, ch_h_right = 10, 11
        min_ud, max_ud = get_servo_limits(ch_ud)
        min_h, max_h = get_servo_limits(ch_h_left)
        
        # 眼皮旋转到上斜（开心的样子）
        self._transition_eyelid_rotate(
            HAPPY_ROTATE_LEFT,
            HAPPY_ROTATE_RIGHT
        )
        
        if not self.emotion_running:
            return
        
        # 眼睛眯成缝
        set_servo(EYELID_LEFT_CH, HAPPY_EYELID_CLOSED_LEFT)
        set_servo(EYELID_RIGHT_CH, HAPPY_EYELID_CLOSED_RIGHT)
        
        # 嘴巴张大笑
        set_servo(MOUTH_CH, HAPPY_MOUTH_OPEN)
        
        # 初始眼球位置
        cur_ud = (min_ud + max_ud) // 2
        cur_h = (min_h + max_h) // 2
        
        duration = random.uniform(HAPPY_DURATION_MIN, HAPPY_DURATION_MAX)
        end_time = time.time() + duration
        
        laugh_count = random.randint(HAPPY_LAUGH_COUNT_MIN, HAPPY_LAUGH_COUNT_MAX)
        swing_phase = 0
        
        for laugh_idx in range(laugh_count):
            if not self.emotion_running or time.time() >= end_time:
                break
            
            # 每次笑时眼球快速左右移动（充满活力）
            for _ in range(3):
                if not self.emotion_running:
                    break
                
                # 眼皮在上斜附近轻微摆动
                swing_offset = HAPPY_ROTATE_SWING_AMP * (1 if swing_phase % 2 == 0 else -1)
                set_servo(EYELID_ROTATE_LEFT_CH, int(HAPPY_ROTATE_LEFT + swing_offset))
                set_servo(EYELID_ROTATE_RIGHT_CH, int(HAPPY_ROTATE_RIGHT - swing_offset))
                swing_phase += 1
                
                # 眼球快速左右移动
                target_h = cur_h + random.uniform(-35, 35)
                target_h = max(min_h + 15, min(max_h - 15, target_h))
                
                # 快速移动
                steps = 4
                for step in range(steps + 1):
                    if not self.emotion_running:
                        break
                    t = step / steps
                    h = cur_h + (target_h - cur_h) * t
                    set_servo(ch_h_left, int(h))
                    set_servo(ch_h_right, int(h))
                    time.sleep(0.02)
                cur_h = target_h
                
                # 嘴巴随笑声开合
                set_servo(MOUTH_CH, HAPPY_MOUTH_OPEN + random.randint(-10, 10))
                
                time.sleep(HAPPY_ROTATE_SWING_DURATION)
            
            # 笑之间短暂停顿，眼球回到中间
            time.sleep(random.uniform(0.15, 0.3))
        
        # 保持开心表情一会
        time.sleep(0.3)
        
        if self.emotion_running:
            self.root.after(0, self.reset_emotion)
    
    def start_speechless_mode(self):
        """启动无语模式"""
        self._stop_emotion()
        self.current_emotion = "speechless"
        self.emotion_running = True
        self.emotion_label.config(text="当前: 无语 😑", foreground="purple")
        
        self.emotion_thread = threading.Thread(target=self._speechless_thread, daemon=True)
        self.emotion_thread.start()
    
    def _speechless_thread(self):
        """
        无语模式动画线程
        流程：眯眼 -> 眼球向上翻 -> 回到中立 -> 向左/右看 -> 再向上翻白眼
        """
        ch_ud = 8
        ch_h_left, ch_h_right = 10, 11
        min_ud, max_ud = get_servo_limits(ch_ud)
        min_h, max_h = get_servo_limits(ch_h_left)
        
        # 眼皮旋转到正常（水平）
        set_servo(EYELID_ROTATE_LEFT_CH, EYELID_ROTATE_LEFT_NORMAL)
        set_servo(EYELID_ROTATE_RIGHT_CH, EYELID_ROTATE_RIGHT_NORMAL)
        
        # 嘴巴紧闭
        set_servo(MOUTH_CH, MOUTH_CLOSED)
        
        # 初始位置
        mid_ud = (min_ud + max_ud) // 2
        mid_h = (min_h + max_h) // 2
        set_servo(ch_ud, mid_ud)
        set_servo(ch_h_left, mid_h)
        set_servo(ch_h_right, mid_h)
        
        if not self.emotion_running:
            return
        
        # ===== 第1步：眼皮眯起来 =====
        steps = 15
        for step in range(steps + 1):
            if not self.emotion_running:
                return
            t = step / steps
            left_lid = EYELID_LEFT_NORMAL + (SPEECHLESS_EYELID_CLOSED_LEFT - EYELID_LEFT_NORMAL) * t
            right_lid = EYELID_RIGHT_NORMAL + (SPEECHLESS_EYELID_CLOSED_RIGHT - EYELID_RIGHT_NORMAL) * t
            set_servo(EYELID_LEFT_CH, int(left_lid))
            set_servo(EYELID_RIGHT_CH, int(right_lid))
            time.sleep(0.02)
        
        time.sleep(0.2)
        
        if not self.emotion_running:
            return
        
        # ===== 第2步：眼球慢慢向上翻到接近最大 =====
        target_ud = max_ud - 5  # 接近最大（抬眼）
        steps = 25
        for step in range(steps + 1):
            if not self.emotion_running:
                return
            t = step / steps
            eased_t = t * t * (3 - 2 * t)  # ease_in_out
            cur_ud = mid_ud + (target_ud - mid_ud) * eased_t
            set_servo(ch_ud, int(cur_ud))
            time.sleep(0.03)
        
        time.sleep(0.5)  # 保持一下
        
        if not self.emotion_running:
            return
        
        # ===== 第3步：眼球回到中立位 =====
        steps = 20
        for step in range(steps + 1):
            if not self.emotion_running:
                return
            t = step / steps
            eased_t = t * t * (3 - 2 * t)
            cur_ud = target_ud + (mid_ud - target_ud) * eased_t
            set_servo(ch_ud, int(cur_ud))
            time.sleep(0.025)
        
        time.sleep(0.3)
        
        if not self.emotion_running:
            return
        
        # ===== 第4步：眼球向左或右转一下 =====
        side = random.choice([-1, 1])  # -1左，1右
        side_h = mid_h + side * 40
        side_h = max(min_h + 10, min(max_h - 10, side_h))
        
        steps = 12
        for step in range(steps + 1):
            if not self.emotion_running:
                return
            t = step / steps
            h = mid_h + (side_h - mid_h) * t
            set_servo(ch_h_left, int(h))
            set_servo(ch_h_right, int(h))
            time.sleep(0.025)
        
        time.sleep(0.4)  # 看一下
        
        if not self.emotion_running:
            return
        
        # ===== 第5步：再向上翻白眼 =====
        # 眼球回到中间同时向上
        steps = 20
        for step in range(steps + 1):
            if not self.emotion_running:
                return
            t = step / steps
            eased_t = t * t  # ease_in
            
            # 水平回中间
            h = side_h + (mid_h - side_h) * eased_t
            set_servo(ch_h_left, int(h))
            set_servo(ch_h_right, int(h))
            
            # 同时向上翻
            ud = mid_ud + (target_ud - mid_ud) * eased_t
            set_servo(ch_ud, int(ud))
            
            time.sleep(0.03)
        
        # 保持翻白眼
        time.sleep(random.uniform(1.0, 1.5))
        
        if self.emotion_running:
            self.root.after(0, self.reset_emotion)
    
    def start_wink_mode(self):
        """启动Wink模式"""
        self._stop_emotion()
        self.current_emotion = "wink"
        self.emotion_running = True
        self.emotion_label.config(text="当前: Wink 😉", foreground="green")
        
        self.emotion_thread = threading.Thread(target=self._wink_thread, daemon=True)
        self.emotion_thread.start()
    
    def _wink_thread(self):
        """Wink模式动画线程"""
        ch_ud = 8
        ch_h_left, ch_h_right = 10, 11
        min_h, max_h = get_servo_limits(ch_h_left)
        min_ud, max_ud = get_servo_limits(ch_ud)
        
        # 眼皮旋转到正常
        set_servo(EYELID_ROTATE_LEFT_CH, EYELID_ROTATE_LEFT_NORMAL)
        set_servo(EYELID_ROTATE_RIGHT_CH, EYELID_ROTATE_RIGHT_NORMAL)
        
        # 眼睛先张大
        set_servo(EYELID_LEFT_CH, WINK_EYE_OPEN_LEFT)
        set_servo(EYELID_RIGHT_CH, WINK_EYE_OPEN_RIGHT)
        
        # 眼球看向中间
        cur_ud = (min_ud + max_ud) // 2
        cur_h = (min_h + max_h) // 2
        set_servo(ch_ud, int(cur_ud))
        set_servo(ch_h_left, int(cur_h))
        set_servo(ch_h_right, int(cur_h))
        
        time.sleep(0.2)
        
        if not self.emotion_running:
            return
        
        # 决定wink哪只眼睛和眼球转动方向
        if WINK_WHICH_EYE == "random":
            wink_eye = random.choice(["left", "right"])
        else:
            wink_eye = WINK_WHICH_EYE
        
        # 眼球转动方向（随机选择）
        turn_direction = random.choice([-1, 1])  # -1左，1右
        
        wink_count = random.randint(WINK_COUNT_MIN, WINK_COUNT_MAX)
        
        for wink_idx in range(wink_count):
            if not self.emotion_running:
                break
            
            # Wink的同时眼球向一个方向转
            target_h = cur_h + turn_direction * WINK_EYE_TURN_AMOUNT
            target_h = max(min_h + 10, min(max_h - 10, target_h))
            
            # 快速wink + 眼球同时转动
            if wink_eye == "left":
                # 快速闭眼
                set_servo(EYELID_LEFT_CH, EYELID_LEFT_CLOSED)
                # 同时眼球转动
                set_servo(ch_h_left, int(target_h))
                set_servo(ch_h_right, int(target_h))
                time.sleep(WINK_CLOSE_DURATION)
                
                # 快速睁开
                set_servo(EYELID_LEFT_CH, WINK_EYE_OPEN_LEFT)
            else:
                # 快速闭眼
                set_servo(EYELID_RIGHT_CH, EYELID_RIGHT_CLOSED)
                # 同时眼球转动
                set_servo(ch_h_left, int(target_h))
                set_servo(ch_h_right, int(target_h))
                time.sleep(WINK_CLOSE_DURATION)
                
                # 快速睁开
                set_servo(EYELID_RIGHT_CH, WINK_EYE_OPEN_RIGHT)
            
            cur_h = target_h
            time.sleep(WINK_OPEN_DURATION)
            
            # wink之间间隔
            if wink_idx < wink_count - 1:
                time.sleep(0.15)
        
        if not self.emotion_running:
            return
        
        # Wink后嘴巴张大几次（笑）
        mouth_range = MOUTH_MAX_OPEN - MOUTH_CLOSED
        for i in range(WINK_MOUTH_OPEN_COUNT):
            if not self.emotion_running:
                break
            
            # 张开嘴巴
            set_servo(MOUTH_CH, MOUTH_CLOSED + int(mouth_range * 0.7))
            time.sleep(WINK_MOUTH_OPEN_DURATION)
            
            # 合上
            set_servo(MOUTH_CH, MOUTH_CLOSED)
            time.sleep(WINK_MOUTH_OPEN_DURATION * 0.5)
        
        # 保持一会
        time.sleep(0.3)
        
        if self.emotion_running:
            self.root.after(0, self.reset_emotion)
    
    def _compute_eyelid_base(self, cur_ud: int):
        """根据当前眼球抬眼程度，计算基础眼皮角度"""
        ch_ud = 8
        min_ud, max_ud = get_servo_limits(ch_ud)
        rng = max(1, max_ud - min_ud)
        # ratio: 0=最小值(低头), 1=最大值(抬眼)  【大数字=抬眼】
        ratio = (cur_ud - min_ud) / rng
        
        # 抬眼（数值大，ratio高）时完全张开
        if ratio >= EYELID_LOOKUP_THRESHOLD:
            left = EYELID_LEFT_MAX_OPEN
            right = EYELID_RIGHT_MAX_OPEN
        # 明显向下时略微闭合一些
        elif ratio <= EYELID_LOOKDOWN_THRESHOLD:
            left = (EYELID_LEFT_NORMAL + EYELID_LEFT_CLOSED) / 2
            right = (EYELID_RIGHT_NORMAL + EYELID_RIGHT_CLOSED) / 2
        else:
            # 中间区域保持在"正常略开"附近
            left = EYELID_LEFT_NORMAL
            right = EYELID_RIGHT_NORMAL
        
        return left, right
    
    def _apply_idle_eyelids(self, cur_ud: int):
        """
        在 idle 模式下，根据当前眼球上下角度，更新眼皮角度：
        - 抬眼时张到最大
        - 平时围绕正常角度做轻微微动
        """
        if not self.eye_idle_running or self.is_running or self.blinking:
            return
        
        base_left, base_right = self._compute_eyelid_base(cur_ud)
        
        now = time.time()
        # 控制微动节奏
        if now >= self._eyelid_next_update_time:
            self._eyelid_jitter_left = random.uniform(EYELID_JITTER_MIN, EYELID_JITTER_MAX)
            self._eyelid_jitter_right = random.uniform(EYELID_JITTER_MIN, EYELID_JITTER_MAX)
            self._eyelid_next_update_time = now + random.uniform(EYELID_JITTER_INTERVAL_MIN, EYELID_JITTER_INTERVAL_MAX)
        
        left_angle = clamp_angle(EYELID_LEFT_CH, int(base_left + self._eyelid_jitter_left))
        right_angle = clamp_angle(EYELID_RIGHT_CH, int(base_right + self._eyelid_jitter_right))
        
        set_servo(EYELID_LEFT_CH, left_angle)
        set_servo(EYELID_RIGHT_CH, right_angle)
    
    def _blink_once(self, with_mouth_cute=False):
        """
        眨眼：快速从关 -> 开到最大
        （闭合一下再快速张到最大，让动作更有存在感）
        with_mouth_cute: 是否同时触发嘴巴卖萌
        """
        if not self.eye_idle_running or self.is_running:
            return
        
        self.blinking = True
        try:
            # 先闭眼
            set_servo(EYELID_LEFT_CH, EYELID_LEFT_CLOSED)
            set_servo(EYELID_RIGHT_CH, EYELID_RIGHT_CLOSED)
            time.sleep(BLINK_CLOSE_DURATION)
            
            if not self.eye_idle_running or self.is_running:
                return
            
            # 再快速张到最大
            set_servo(EYELID_LEFT_CH, EYELID_LEFT_MAX_OPEN)
            set_servo(EYELID_RIGHT_CH, EYELID_RIGHT_MAX_OPEN)
            time.sleep(BLINK_OPEN_DURATION)
            
            # 眨眼时可能触发嘴巴卖萌（在后台线程执行，不阻塞眨眼）
            if with_mouth_cute:
                threading.Thread(target=self._mouth_cute_action, daemon=True).start()
        finally:
            self.blinking = False
    
    def _mouth_cute_action(self):
        """
        嘴巴卖萌动作：根据权重随机选择一种卖萌方式
        1. 慢开快合：慢慢张开嘴巴，然后快速合上
        2. 开合n次：像说话一样开合几次
        3. 嘟嘴：微微张开保持一会
        4. 惊讶：快速张大嘴巴
        5. 咀嚼：小幅度不规则开合
        6. 打哈欠：慢慢张到最大
        7. 微笑抖动：微微张开并轻微抖动
        """
        if not self.eye_idle_running or self.is_running:
            return
        
        # 根据权重随机选择动作
        actions = list(MOUTH_ACTION_WEIGHTS.keys())
        weights = list(MOUTH_ACTION_WEIGHTS.values())
        action = random.choices(actions, weights=weights, k=1)[0]
        
        action_map = {
            "slow_open": self._mouth_slow_open_fast_close,
            "flap": self._mouth_flap,
            "pout": self._mouth_pout,
            "surprise": self._mouth_surprise,
            "chew": self._mouth_chew,
            "yawn": self._mouth_yawn,
            "smile": self._mouth_smile_jitter,
        }
        
        if action in action_map:
            action_map[action]()
    
    def _mouth_slow_open_fast_close(self):
        """
        卖萌方式1：慢慢张开嘴巴，保持一下，然后快速合上
        """
        if not self.eye_idle_running or self.is_running:
            return
        
        mouth_range = MOUTH_MAX_OPEN - MOUTH_CLOSED
        
        # 计算张开的目标角度
        open_amount = random.uniform(MOUTH_SLOW_OPEN_AMOUNT_MIN, MOUTH_SLOW_OPEN_AMOUNT_MAX)
        target_angle = MOUTH_CLOSED + int(mouth_range * open_amount)
        
        # 慢慢张开
        open_duration = random.uniform(MOUTH_SLOW_OPEN_DURATION_MIN, MOUTH_SLOW_OPEN_DURATION_MAX)
        steps = max(1, int(open_duration * 30))  # 30fps
        step_time = open_duration / steps
        
        for step in range(steps + 1):
            if not self.eye_idle_running or self.is_running:
                # 中断时确保嘴巴闭合
                set_servo(MOUTH_CH, MOUTH_CLOSED)
                return
            
            t = step / steps
            # ease_out 缓动：开始快，结束慢
            eased_t = 1 - (1 - t) ** 2
            current_angle = MOUTH_CLOSED + int((target_angle - MOUTH_CLOSED) * eased_t)
            set_servo(MOUTH_CH, current_angle)
            time.sleep(step_time)
        
        # 保持张开状态
        hold_time = random.uniform(MOUTH_HOLD_OPEN_MIN, MOUTH_HOLD_OPEN_MAX)
        time.sleep(hold_time)
        
        if not self.eye_idle_running or self.is_running:
            set_servo(MOUTH_CH, MOUTH_CLOSED)
            return
        
        # 快速合上
        set_servo(MOUTH_CH, MOUTH_CLOSED)
        time.sleep(MOUTH_FAST_CLOSE_DURATION)
    
    def _mouth_flap(self):
        """
        卖萌方式2：开合开合n次，像在说"啊啊啊"
        """
        if not self.eye_idle_running or self.is_running:
            return
        
        mouth_range = MOUTH_MAX_OPEN - MOUTH_CLOSED
        
        # 决定开合次数和幅度
        flap_count = random.randint(MOUTH_FLAP_COUNT_MIN, MOUTH_FLAP_COUNT_MAX)
        flap_amount = random.uniform(MOUTH_FLAP_AMOUNT_MIN, MOUTH_FLAP_AMOUNT_MAX)
        target_angle = MOUTH_CLOSED + int(mouth_range * flap_amount)
        
        for i in range(flap_count):
            if not self.eye_idle_running or self.is_running:
                set_servo(MOUTH_CH, MOUTH_CLOSED)
                return
            
            # 张开
            set_servo(MOUTH_CH, target_angle)
            time.sleep(MOUTH_FLAP_OPEN_DURATION)
            
            if not self.eye_idle_running or self.is_running:
                set_servo(MOUTH_CH, MOUTH_CLOSED)
                return
            
            # 合上
            set_servo(MOUTH_CH, MOUTH_CLOSED)
            time.sleep(MOUTH_FLAP_CLOSE_DURATION)
            
            # 开合之间的小间隔（最后一次不需要）
            if i < flap_count - 1:
                gap = random.uniform(MOUTH_FLAP_GAP_MIN, MOUTH_FLAP_GAP_MAX)
                time.sleep(gap)
        
        # 确保最终嘴巴闭合
        set_servo(MOUTH_CH, MOUTH_CLOSED)
    
    def _mouth_pout(self):
        """
        卖萌方式3：嘟嘴 - 微微张开保持一会，然后慢慢合上
        """
        if not self.eye_idle_running or self.is_running:
            return
        
        mouth_range = MOUTH_MAX_OPEN - MOUTH_CLOSED
        
        # 嘟嘴幅度（小幅度）
        pout_amount = random.uniform(MOUTH_POUT_AMOUNT_MIN, MOUTH_POUT_AMOUNT_MAX)
        target_angle = MOUTH_CLOSED + int(mouth_range * pout_amount)
        
        # 快速张开到嘟嘴位置
        set_servo(MOUTH_CH, target_angle)
        time.sleep(MOUTH_POUT_OPEN_DURATION)
        
        if not self.eye_idle_running or self.is_running:
            set_servo(MOUTH_CH, MOUTH_CLOSED)
            return
        
        # 保持嘟嘴
        hold_time = random.uniform(MOUTH_POUT_HOLD_MIN, MOUTH_POUT_HOLD_MAX)
        time.sleep(hold_time)
        
        if not self.eye_idle_running or self.is_running:
            set_servo(MOUTH_CH, MOUTH_CLOSED)
            return
        
        # 慢慢合上
        close_duration = random.uniform(MOUTH_POUT_CLOSE_DURATION_MIN, MOUTH_POUT_CLOSE_DURATION_MAX)
        steps = max(1, int(close_duration * 30))
        step_time = close_duration / steps
        
        for step in range(steps + 1):
            if not self.eye_idle_running or self.is_running:
                set_servo(MOUTH_CH, MOUTH_CLOSED)
                return
            t = step / steps
            current_angle = target_angle + int((MOUTH_CLOSED - target_angle) * t)
            set_servo(MOUTH_CH, current_angle)
            time.sleep(step_time)
        
        set_servo(MOUTH_CH, MOUTH_CLOSED)
    
    def _mouth_surprise(self):
        """
        卖萌方式4：惊讶 - 快速张大嘴巴，保持，慢慢合上
        """
        if not self.eye_idle_running or self.is_running:
            return
        
        mouth_range = MOUTH_MAX_OPEN - MOUTH_CLOSED
        
        # 惊讶幅度（大幅度）
        surprise_amount = random.uniform(MOUTH_SURPRISE_AMOUNT_MIN, MOUTH_SURPRISE_AMOUNT_MAX)
        target_angle = MOUTH_CLOSED + int(mouth_range * surprise_amount)
        
        # 快速张大
        set_servo(MOUTH_CH, target_angle)
        time.sleep(MOUTH_SURPRISE_OPEN_DURATION)
        
        if not self.eye_idle_running or self.is_running:
            set_servo(MOUTH_CH, MOUTH_CLOSED)
            return
        
        # 保持惊讶
        hold_time = random.uniform(MOUTH_SURPRISE_HOLD_MIN, MOUTH_SURPRISE_HOLD_MAX)
        time.sleep(hold_time)
        
        if not self.eye_idle_running or self.is_running:
            set_servo(MOUTH_CH, MOUTH_CLOSED)
            return
        
        # 慢慢合上
        close_duration = random.uniform(MOUTH_SURPRISE_CLOSE_DURATION_MIN, MOUTH_SURPRISE_CLOSE_DURATION_MAX)
        steps = max(1, int(close_duration * 30))
        step_time = close_duration / steps
        
        for step in range(steps + 1):
            if not self.eye_idle_running or self.is_running:
                set_servo(MOUTH_CH, MOUTH_CLOSED)
                return
            t = step / steps
            # ease_in 缓动：开始慢，结束快
            eased_t = t * t
            current_angle = target_angle + int((MOUTH_CLOSED - target_angle) * eased_t)
            set_servo(MOUTH_CH, current_angle)
            time.sleep(step_time)
        
        set_servo(MOUTH_CH, MOUTH_CLOSED)
    
    def _mouth_chew(self):
        """
        卖萌方式5：咀嚼 - 小幅度不规则开合，像在嚼东西
        """
        if not self.eye_idle_running or self.is_running:
            return
        
        mouth_range = MOUTH_MAX_OPEN - MOUTH_CLOSED
        
        chew_count = random.randint(MOUTH_CHEW_COUNT_MIN, MOUTH_CHEW_COUNT_MAX)
        
        for i in range(chew_count):
            if not self.eye_idle_running or self.is_running:
                set_servo(MOUTH_CH, MOUTH_CLOSED)
                return
            
            # 每次咀嚼幅度略有不同
            chew_amount = random.uniform(MOUTH_CHEW_AMOUNT_MIN, MOUTH_CHEW_AMOUNT_MAX)
            target_angle = MOUTH_CLOSED + int(mouth_range * chew_amount)
            
            # 张开
            chew_duration = random.uniform(MOUTH_CHEW_DURATION_MIN, MOUTH_CHEW_DURATION_MAX)
            set_servo(MOUTH_CH, target_angle)
            time.sleep(chew_duration)
            
            if not self.eye_idle_running or self.is_running:
                set_servo(MOUTH_CH, MOUTH_CLOSED)
                return
            
            # 合上（不完全合上，留一点）
            close_to = MOUTH_CLOSED + int(mouth_range * random.uniform(0, 0.1))
            set_servo(MOUTH_CH, close_to)
            time.sleep(chew_duration * 0.8)
        
        # 最终完全合上
        set_servo(MOUTH_CH, MOUTH_CLOSED)
    
    def _mouth_yawn(self):
        """
        卖萌方式6：打哈欠 - 慢慢张到最大，保持，慢慢合上
        """
        if not self.eye_idle_running or self.is_running:
            return
        
        mouth_range = MOUTH_MAX_OPEN - MOUTH_CLOSED
        target_angle = MOUTH_CLOSED + int(mouth_range * 0.95)  # 张到接近最大
        
        # 慢慢张开（ease_in_out）
        open_duration = random.uniform(MOUTH_YAWN_OPEN_DURATION_MIN, MOUTH_YAWN_OPEN_DURATION_MAX)
        steps = max(1, int(open_duration * 30))
        step_time = open_duration / steps
        
        for step in range(steps + 1):
            if not self.eye_idle_running or self.is_running:
                set_servo(MOUTH_CH, MOUTH_CLOSED)
                return
            t = step / steps
            # ease_in_out 缓动
            eased_t = t * t * (3 - 2 * t)
            current_angle = MOUTH_CLOSED + int((target_angle - MOUTH_CLOSED) * eased_t)
            set_servo(MOUTH_CH, current_angle)
            time.sleep(step_time)
        
        if not self.eye_idle_running or self.is_running:
            set_servo(MOUTH_CH, MOUTH_CLOSED)
            return
        
        # 保持张大（哈欠顶点）
        hold_time = random.uniform(MOUTH_YAWN_HOLD_MIN, MOUTH_YAWN_HOLD_MAX)
        time.sleep(hold_time)
        
        if not self.eye_idle_running or self.is_running:
            set_servo(MOUTH_CH, MOUTH_CLOSED)
            return
        
        # 慢慢合上
        close_duration = random.uniform(MOUTH_YAWN_CLOSE_DURATION_MIN, MOUTH_YAWN_CLOSE_DURATION_MAX)
        steps = max(1, int(close_duration * 30))
        step_time = close_duration / steps
        
        for step in range(steps + 1):
            if not self.eye_idle_running or self.is_running:
                set_servo(MOUTH_CH, MOUTH_CLOSED)
                return
            t = step / steps
            eased_t = t * t * (3 - 2 * t)
            current_angle = target_angle + int((MOUTH_CLOSED - target_angle) * eased_t)
            set_servo(MOUTH_CH, current_angle)
            time.sleep(step_time)
        
        set_servo(MOUTH_CH, MOUTH_CLOSED)
    
    def _mouth_smile_jitter(self):
        """
        卖萌方式7：微笑抖动 - 微微张开嘴巴并轻微抖动
        """
        if not self.eye_idle_running or self.is_running:
            return
        
        mouth_range = MOUTH_MAX_OPEN - MOUTH_CLOSED
        
        # 微笑基础位置
        smile_amount = random.uniform(MOUTH_SMILE_AMOUNT_MIN, MOUTH_SMILE_AMOUNT_MAX)
        base_angle = MOUTH_CLOSED + int(mouth_range * smile_amount)
        jitter_range = int(mouth_range * MOUTH_SMILE_JITTER_AMP)
        
        # 先张开到微笑位置
        set_servo(MOUTH_CH, base_angle)
        time.sleep(0.1)
        
        if not self.eye_idle_running or self.is_running:
            set_servo(MOUTH_CH, MOUTH_CLOSED)
            return
        
        # 轻微抖动
        jitter_count = random.randint(MOUTH_SMILE_JITTER_COUNT_MIN, MOUTH_SMILE_JITTER_COUNT_MAX)
        
        for _ in range(jitter_count):
            if not self.eye_idle_running or self.is_running:
                set_servo(MOUTH_CH, MOUTH_CLOSED)
                return
            
            # 随机抖动方向
            jitter = random.randint(-jitter_range, jitter_range)
            jitter_angle = max(MOUTH_CLOSED, min(MOUTH_MAX_OPEN, base_angle + jitter))
            set_servo(MOUTH_CH, jitter_angle)
            time.sleep(MOUTH_SMILE_JITTER_DURATION)
        
        # 回到微笑位置保持一会
        set_servo(MOUTH_CH, base_angle)
        hold_time = random.uniform(MOUTH_SMILE_HOLD_MIN, MOUTH_SMILE_HOLD_MAX)
        time.sleep(hold_time)
        
        if not self.eye_idle_running or self.is_running:
            set_servo(MOUTH_CH, MOUTH_CLOSED)
            return
        
        # 慢慢合上
        steps = 10
        step_time = 0.02
        for step in range(steps + 1):
            if not self.eye_idle_running or self.is_running:
                set_servo(MOUTH_CH, MOUTH_CLOSED)
                return
            t = step / steps
            current_angle = base_angle + int((MOUTH_CLOSED - base_angle) * t)
            set_servo(MOUTH_CH, current_angle)
            time.sleep(step_time)
        
        set_servo(MOUTH_CH, MOUTH_CLOSED)
    
    def _move_eyes(self, start_ud, end_ud, start_h, end_h, duration, easing_name="ease_in_out"):
        """
        从起始角度平滑移动到目标角度
        start_ud / end_ud: 上下舵机角度（通道 8）
        start_h / end_h: 左右舵机角度（通道 10 / 11，同步）
        """
        ch_ud, ch_left, ch_right = 8, 10, 11
        easing_func = EASING_FUNCTIONS.get(easing_name, linear)
        
        duration = max(0.01, duration)
        steps = max(1, int(duration * EYE_MOVE_FPS))
        step_time = duration / steps
        
        for step in range(steps + 1):
            if not self.eye_idle_running or self.is_running:
                break
            
            t = step / steps
            eased_t = easing_func(t)
            
            cur_ud = start_ud + (end_ud - start_ud) * eased_t
            cur_h = start_h + (end_h - start_h) * eased_t
            
            cur_ud_i = clamp_angle(ch_ud, int(cur_ud))
            cur_h_i = clamp_angle(ch_left, int(cur_h))
            
            set_servo(ch_ud, cur_ud_i)
            set_servo(ch_left, cur_h_i)
            set_servo(ch_right, cur_h_i)
            # 在 idle 模式下，根据抬眼程度实时调整眼皮
            self._apply_idle_eyelids(cur_ud_i)
            
            time.sleep(step_time)
        
        # 返回最后角度，便于后续作为新的起点
        return (
            clamp_angle(ch_ud, int(end_ud)),
            clamp_angle(ch_left, int(end_h)),
        )
    
    def _micro_eye_motion(self, base_ud, base_h, total_duration):
        """
        缓动：围绕当前注视点做中等偏大幅度、快速而灵活的来回运动，
        并加入明显的左右扫视，以模拟人静止注视时的微动与轻微扫视。
        """
        ch_ud, ch_left = 8, 10
        min_ud, max_ud = get_servo_limits(ch_ud)
        min_h, max_h = get_servo_limits(ch_left)
        
        range_ud = max_ud - min_ud
        range_h = max_h - min_h
        
        # 基础缓动幅度
        amp_ud = range_ud * EYE_MICRO_AMP_UD
        amp_h = range_h * EYE_MICRO_AMP_H
        
        start_time = time.time()
        cur_ud, cur_h = base_ud, base_h
        
        while self.eye_idle_running and not self.is_running and (time.time() - start_time) < total_duration:
            # 一部分时间做"快速左右扫视"模式，突出左右在看
            if random.random() < EYE_SWEEP_PROBABILITY:
                # 左右扫视的水平幅度（仍然围绕当前注视点，不是大跳）
                sweep_amp_h = range_h * EYE_SWEEP_AMP_H
                # 竖直方向只做轻微抖动，保持在同一大致高度
                sweep_amp_ud = range_ud * EYE_SWEEP_AMP_UD
                
                # 决定这次扫视往返的次数
                cycles = random.randint(EYE_SWEEP_CYCLES_MIN, EYE_SWEEP_CYCLES_MAX)
                
                for _ in range(cycles):
                    if not self.eye_idle_running or self.is_running:
                        break
                    
                    # 先快速向一侧偏移
                    side = random.choice([-1, 1])
                    target_h = base_h + side * random.uniform(sweep_amp_h * 0.6, sweep_amp_h)
                    # 竖直方向轻微抖动，主要抬眼（数值增大），较少低头
                    target_ud = base_ud + random.uniform(-sweep_amp_ud * (1 - EYE_UD_UP_BIAS), sweep_amp_ud * EYE_UD_UP_BIAS)
                    
                    target_ud = clamp_angle(ch_ud, int(target_ud))
                    target_h = clamp_angle(ch_left, int(target_h))
                    
                    seg_duration = random.uniform(EYE_SWEEP_SEG_DURATION_MIN, EYE_SWEEP_SEG_DURATION_MAX)
                    cur_ud, cur_h = self._move_eyes(
                        cur_ud, target_ud,
                        cur_h, target_h,
                        seg_duration,
                        easing_name="ease_in_out"
                    )
                    
                    if not self.eye_idle_running or self.is_running:
                        break
                    
                    # 再快速扫回到另一侧或回到基准附近
                    if random.random() < 0.5:
                        # 扫到另一侧
                        target_h_back = base_h - side * random.uniform(sweep_amp_h * 0.6, sweep_amp_h)
                    else:
                        # 回到基准附近
                        target_h_back = base_h + random.uniform(-sweep_amp_h * 0.4, sweep_amp_h * 0.4)
                    # 竖直方向主要抬眼（数值增大），较少低头
                    target_ud_back = base_ud + random.uniform(-sweep_amp_ud * (1 - EYE_UD_UP_BIAS), sweep_amp_ud * EYE_UD_UP_BIAS)
                    
                    target_ud_back = clamp_angle(ch_ud, int(target_ud_back))
                    target_h_back = clamp_angle(ch_left, int(target_h_back))
                    
                    seg_duration_back = random.uniform(EYE_SWEEP_SEG_DURATION_MIN, EYE_SWEEP_SEG_DURATION_MAX)
                    cur_ud, cur_h = self._move_eyes(
                        cur_ud, target_ud_back,
                        cur_h, target_h_back,
                        seg_duration_back,
                        easing_name="ease_in_out"
                    )
                    
                    # 很短的间隔，形成连续的左右扫视感
                    short_gap = random.uniform(EYE_SWEEP_GAP_MIN, EYE_SWEEP_GAP_MAX)
                    end_gap = time.time() + short_gap
                    while self.eye_idle_running and not self.is_running and time.time() < end_gap:
                        time.sleep(0.02)
                
                # === 扫视完成后，加入小幅度的左右微微移动 ===
                micro_amp_h = range_h * EYE_SWEEP_MICRO_AMP_H
                micro_amp_ud = range_ud * EYE_SWEEP_MICRO_AMP_UD
                micro_cycles = random.randint(EYE_SWEEP_MICRO_CYCLES_MIN, EYE_SWEEP_MICRO_CYCLES_MAX)
                
                for _ in range(micro_cycles):
                    if not self.eye_idle_running or self.is_running:
                        break
                    
                    # 小幅度左右微动，抬眼偏好
                    micro_target_h = cur_h + random.uniform(-micro_amp_h, micro_amp_h)
                    micro_target_ud = cur_ud + random.uniform(-micro_amp_ud * (1 - EYE_UD_UP_BIAS), micro_amp_ud * EYE_UD_UP_BIAS)
                    
                    micro_target_h = clamp_angle(ch_left, int(micro_target_h))
                    micro_target_ud = clamp_angle(ch_ud, int(micro_target_ud))
                    
                    micro_duration = random.uniform(EYE_SWEEP_MICRO_DURATION_MIN, EYE_SWEEP_MICRO_DURATION_MAX)
                    cur_ud, cur_h = self._move_eyes(
                        cur_ud, micro_target_ud,
                        cur_h, micro_target_h,
                        micro_duration,
                        easing_name="ease_in_out"
                    )
                    
                    # 短暂停顿
                    micro_gap = random.uniform(0.02, 0.06)
                    end_micro_gap = time.time() + micro_gap
                    while self.eye_idle_running and not self.is_running and time.time() < end_micro_gap:
                        time.sleep(0.02)
            else:
                # 普通缓动：在注视点附近做中等偏大的、上下左右都有的小范围运动
                # 竖直方向主要抬眼（数值增大），较少低头
                target_ud = base_ud + random.uniform(-amp_ud * (1 - EYE_UD_UP_BIAS), amp_ud * EYE_UD_UP_BIAS)
                target_h = base_h + random.uniform(-amp_h, amp_h)
                
                target_ud = clamp_angle(ch_ud, int(target_ud))
                target_h = clamp_angle(ch_left, int(target_h))
                
                # 单段缓动时间
                seg_duration = random.uniform(EYE_MICRO_SEG_DURATION_MIN, EYE_MICRO_SEG_DURATION_MAX)
                cur_ud, cur_h = self._move_eyes(
                    cur_ud, target_ud,
                    cur_h, target_h,
                    seg_duration,
                    easing_name="ease_in_out"
                )
                
                # 很短的停顿，形成连续的一小段快速缓动序列
                hold = random.uniform(EYE_MICRO_HOLD_MIN, EYE_MICRO_HOLD_MAX)
                end_hold = time.time() + hold
                while self.eye_idle_running and not self.is_running and time.time() < end_hold:
                    time.sleep(0.02)
        
        return cur_ud, cur_h
    
    def _eye_idle_thread(self):
        """眼球 idle 主循环：快速大幅移动 + 基于目标点的缓动循环"""
        ch_ud, ch_left = 8, 10
        min_ud, max_ud = get_servo_limits(ch_ud)
        min_h, max_h = get_servo_limits(ch_left)
        
        range_ud = max_ud - min_ud
        range_h = max_h - min_h
        
        # 快速移动幅度
        min_step_ud = range_ud * EYE_FAST_MOVE_STEP_MIN
        max_step_ud = range_ud * EYE_FAST_MOVE_STEP_MAX
        min_step_h = range_h * EYE_FAST_MOVE_STEP_MIN
        max_step_h = range_h * EYE_FAST_MOVE_STEP_MAX
        
        # 以当前舵机角度作为起点
        cur_ud = last_angles[ch_ud]
        cur_h = last_angles[ch_left]
        
        # 若当前角度不在范围，纠正一次
        cur_ud = clamp_angle(ch_ud, cur_ud)
        cur_h = clamp_angle(ch_left, cur_h)
        
        set_servo(ch_ud, cur_ud)
        set_servo(ch_left, cur_h)
        set_servo(11, cur_h)
        # 初始化眼皮为正常略开状态
        self._apply_idle_eyelids(cur_ud)
        # 初始化嘴巴为闭合状态
        set_servo(MOUTH_CH, MOUTH_CLOSED)
        
        try:
            # 眨眼调度
            next_blink_time = time.time() + random.uniform(BLINK_INTERVAL_MIN, BLINK_INTERVAL_MAX)
            # 嘴巴卖萌调度
            next_mouth_cute_time = time.time() + random.uniform(MOUTH_CUTE_INTERVAL_MIN, MOUTH_CUTE_INTERVAL_MAX)
            
            while self.eye_idle_running:
                # 如果正在播放表情，暂停 idle 只保持轻微等待
                if self.is_running:
                    time.sleep(0.1)
                    continue
                
                # 全局随机停顿，让眼神偶尔"发呆"一下
                if random.random() < EYE_IDLE_PAUSE_PROBABILITY:
                    pause_t = random.uniform(EYE_IDLE_PAUSE_MIN, EYE_IDLE_PAUSE_MAX)
                    end_pause = time.time() + pause_t
                    while self.eye_idle_running and not self.is_running and time.time() < end_pause:
                        time.sleep(0.05)
                
                if not self.eye_idle_running or self.is_running:
                    continue
                
                # 到点就眨一次眼
                now = time.time()
                if now >= next_blink_time:
                    # 眨眼时有概率同时触发嘴巴卖萌
                    with_mouth = (now >= next_mouth_cute_time) or (random.random() < MOUTH_CUTE_WITH_BLINK_PROB)
                    self._blink_once(with_mouth_cute=with_mouth)
                    next_blink_time = now + random.uniform(BLINK_INTERVAL_MIN, BLINK_INTERVAL_MAX)
                    if with_mouth:
                        # 重置嘴巴卖萌计时
                        next_mouth_cute_time = now + random.uniform(MOUTH_CUTE_INTERVAL_MIN, MOUTH_CUTE_INTERVAL_MAX)
                    if not self.eye_idle_running or self.is_running:
                        continue
                
                # 生成新注视点（快速大幅移动）
                # 【方向已反转】大数字=抬眼，小数字=低头（范围42-120）
                # 上下范围分区：上1/3为"抬眼区"，中间1/3为"中间区"，下1/3为"低头区"
                lookup_bound = max_ud - range_ud * 0.33   # 抬眼区下限（数值大=抬眼）
                mid_bound = max_ud - range_ud * 0.66      # 中间区下限
                for _ in range(20):
                    # 垂直方向大部分时间在"抬眼区"（数值大），偶尔到中间，很少向下
                    r = random.random()
                    if r < EYE_LOOKUP_PROBABILITY:
                        # 抬眼区（数值最大的1/3）
                        target_ud = random.uniform(lookup_bound, max_ud - 5)
                    elif r < EYE_LOOKUP_PROBABILITY + EYE_MID_PROBABILITY:
                        # 中间区
                        target_ud = random.uniform(mid_bound, lookup_bound)
                    else:
                        # 偶尔向下看一下（数值小）
                        target_ud = random.uniform(min_ud + 5, mid_bound)
                    target_h = random.uniform(min_h + 5, max_h - 5)
                    
                    du = abs(target_ud - cur_ud)
                    dh = abs(target_h - cur_h)
                    
                    # 至少有一个方向移动量在目标区间内，且两个方向都不超过最大位移
                    if ((du >= min_step_ud or dh >= min_step_h) and
                        du <= max_step_ud and dh <= max_step_h):
                        break
                
                # 快速移动到新位置
                duration = random.uniform(EYE_FAST_MOVE_DURATION_MIN, EYE_FAST_MOVE_DURATION_MAX)
                cur_ud, cur_h = self._move_eyes(
                    cur_ud, target_ud,
                    cur_h, target_h,
                    duration,
                    easing_name="ease_out"
                )
                
                if not self.eye_idle_running:
                    break
                
                # 快速移动后短暂停顿，再进入缓动
                hold_after_fast = random.uniform(EYE_HOLD_AFTER_FAST_MIN, EYE_HOLD_AFTER_FAST_MAX)
                end_hold_fast = time.time() + hold_after_fast
                while self.eye_idle_running and not self.is_running and time.time() < end_hold_fast:
                    time.sleep(0.05)
                
                # 大跳后有概率触发嘴巴卖萌（与眼球动作配合，更自然）
                now = time.time()
                if now >= next_mouth_cute_time or random.random() < MOUTH_CUTE_PROBABILITY:
                    # 在后台线程执行卖萌，不阻塞眼球动作
                    threading.Thread(target=self._mouth_cute_action, daemon=True).start()
                    next_mouth_cute_time = now + random.uniform(MOUTH_CUTE_INTERVAL_MIN, MOUTH_CUTE_INTERVAL_MAX)
                
                # 在新注视点附近做一段"缓动"（中等偏大幅度来回运动）
                micro_duration = random.uniform(EYE_MICRO_DURATION_MIN, EYE_MICRO_DURATION_MAX)
                cur_ud, cur_h = self._micro_eye_motion(cur_ud, cur_h, micro_duration)
        finally:
            # 线程退出时确保嘴巴闭合
            set_servo(MOUTH_CH, MOUTH_CLOSED)
            # 标记状态
            self.eye_idle_running = False
    
    def generate_random_expression(self):
        """基于选中的表情生成随机变体"""
        selection = self.expression_listbox.curselection()
        if not selection:
            messagebox.showwarning("警告", "请先选择一个表情作为模板！")
            return
        
        idx = selection[0]
        template = self.expressions[idx]
        random_range = template.get("random_range", 10)
        
        # 创建随机变体
        new_expr = deepcopy(template)
        new_expr["name"] = template["name"] + f" (随机#{random.randint(1, 999)})"
        
        # 对每一帧的每个舵机添加随机偏移
        for frame in new_expr.get("frames", []):
            servos = frame.get("servos", {})
            for ch_str, angle in servos.items():
                ch = int(ch_str)
                # 在范围内随机偏移
                offset = random.randint(-random_range, random_range)
                new_angle = clamp_angle(ch, angle + offset)
                servos[ch_str] = new_angle
        
        self.expressions.append(new_expr)
        self.save_expressions()
        self.refresh_expression_list()
        
        messagebox.showinfo("成功", f"已生成随机表情: {new_expr['name']}")
    
    def refresh_expression_list(self):
        """刷新表情列表显示"""
        self.expression_listbox.delete(0, tk.END)
        for i, expr in enumerate(self.expressions):
            frames_count = len(expr.get("frames", []))
            self.expression_listbox.insert(tk.END, f"{i+1}. {expr['name']} [{frames_count}帧]")
    
    # ========== 导入导出功能 ==========
    def export_selected_expression(self):
        """导出选中的表情"""
        selection = self.expression_listbox.curselection()
        if not selection:
            messagebox.showwarning("警告", "请先选择一个表情！")
            return
        
        idx = selection[0]
        expr = self.expressions[idx]
        
        filepath = filedialog.asksaveasfilename(
            title="导出表情",
            defaultextension=".json",
            filetypes=[("JSON文件", "*.json")],
            initialfilename=f"{expr['name']}.json"
        )
        
        if filepath:
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(expr, f, ensure_ascii=False, indent=2)
                messagebox.showinfo("成功", f"表情已导出到: {filepath}")
            except Exception as e:
                messagebox.showerror("错误", f"导出失败: {e}")
    
    def export_all_expressions(self):
        """导出所有表情"""
        if not self.expressions:
            messagebox.showwarning("警告", "没有可导出的表情！")
            return
        
        filepath = filedialog.asksaveasfilename(
            title="导出所有表情",
            defaultextension=".json",
            filetypes=[("JSON文件", "*.json")],
            initialfilename="all_expressions.json"
        )
        
        if filepath:
            try:
                export_data = {
                    "version": "1.0",
                    "servo_config": SERVO_CONFIG,
                    "expressions": self.expressions
                }
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(export_data, f, ensure_ascii=False, indent=2)
                messagebox.showinfo("成功", f"所有表情已导出到: {filepath}")
            except Exception as e:
                messagebox.showerror("错误", f"导出失败: {e}")
    
    def import_expressions(self):
        """导入表情"""
        filepath = filedialog.askopenfilename(
            title="导入表情",
            filetypes=[("JSON文件", "*.json")]
        )
        
        if not filepath:
            return
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 判断是单个表情还是完整导出
            if "expressions" in data:
                # 完整导出格式
                imported = data["expressions"]
                if messagebox.askyesno("确认", f"发现 {len(imported)} 个表情，是否全部导入？"):
                    self.expressions.extend(imported)
            else:
                # 单个表情
                if "name" in data and "frames" in data:
                    self.expressions.append(data)
                else:
                    raise ValueError("无效的表情文件格式")
            
            self.save_expressions()
            self.refresh_expression_list()
            messagebox.showinfo("成功", "表情导入成功！")
        except Exception as e:
            messagebox.showerror("错误", f"导入失败: {e}")
    
    # ========== 数据持久化 ==========
    def save_expressions(self):
        """保存表情到文件"""
        try:
            with open(EXPRESSIONS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.expressions, f, ensure_ascii=False, indent=2)
            print(f"[保存] 表情已保存到 {EXPRESSIONS_FILE}")
        except Exception as e:
            print(f"[错误] 保存失败: {e}")
    
    def load_expressions(self):
        """从文件加载表情"""
        if os.path.exists(EXPRESSIONS_FILE):
            try:
                with open(EXPRESSIONS_FILE, 'r', encoding='utf-8') as f:
                    self.expressions = json.load(f)
                print(f"[加载] 已加载 {len(self.expressions)} 个表情")
            except Exception as e:
                print(f"[错误] 加载失败: {e}")
                self.expressions = []
        else:
            self.expressions = []


def main():
    root = tk.Tk()
    app = ServoUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()

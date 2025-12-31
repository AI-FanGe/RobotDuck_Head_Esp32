# app_main.py
# -*- coding: utf-8 -*-
import os, sys, time, json, asyncio, base64, audioop
from typing import Any, Dict, Optional, Tuple, List, Callable, Set, Deque
from collections import deque

from dataclasses import dataclass

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketState
import uvicorn
import cv2
import numpy as np
# import threading  # 已移除：不再需要音频初始化线程
# ---- Windows 事件循环策略 ----
if sys.platform.startswith("win"):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

# ---- .env ----
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ---- 新语音系统配置 ----
API_KEY = os.getenv("DASHSCOPE_API_KEY", "sk-3a6b1a3bd7124023a7ac7699d49c2caf")
if not API_KEY:
    raise RuntimeError("未设置 DASHSCOPE_API_KEY")

SAMPLE_RATE = 16000
CHUNK_MS = 20
BYTES_CHUNK = SAMPLE_RATE * CHUNK_MS // 1000 * 2
SILENCE_20MS = bytes(BYTES_CHUNK)

# ---- 引入新语音系统模块 ----
from voice_adapter import WebSocketASREngine, BroadcastTTSEngine
from robotduck_voice_assistant.dispatcher import IntentDispatcher
from robotduck_voice_assistant.workflows import Workflows
from robotduck_voice_assistant.state import ChatState

# 初始化新语音系统
def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()

BASE_URL = _env("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
WS_URL = _env("DASHSCOPE_WS_BASE_URL", "wss://dashscope.aliyuncs.com/api-ws/v1/inference")
ROUTER_MODEL = _env("ROUTER_MODEL", "qwen-turbo")
TEXT_MODEL = _env("TEXT_MODEL", "qwen-turbo")
VISION_MODEL = _env("VISION_MODEL", "qwen-vl-max")
TTS_MODEL = _env("TTS_MODEL", "cosyvoice-v3-plus")
DEFAULT_VOICE = _env("DEFAULT_VOICE", "longanhuan")

# 初始化状态和引擎（在应用启动时初始化）
chat_state: Optional[ChatState] = None
asr_engine: Optional[WebSocketASREngine] = None
tts_engine: Optional[BroadcastTTSEngine] = None
dispatcher: Optional[IntentDispatcher] = None
workflows: Optional[Workflows] = None

def init_voice_system():
    """初始化新语音系统"""
    global chat_state, asr_engine, tts_engine, dispatcher, workflows
    chat_state = ChatState(default_voice=DEFAULT_VOICE, current_voice=DEFAULT_VOICE, max_turns=8)
    asr_engine = WebSocketASREngine(api_key=API_KEY, sample_rate=SAMPLE_RATE, ws_url=WS_URL)
    tts_engine = BroadcastTTSEngine(api_key=API_KEY, tts_model=TTS_MODEL, default_voice=DEFAULT_VOICE, sample_rate=SAMPLE_RATE)
    dispatcher = IntentDispatcher(api_key=API_KEY, base_url=BASE_URL, router_model=ROUTER_MODEL, text_model=TEXT_MODEL)
    
    # 帧获取函数：从 ESP32 摄像头获取最新帧
    # 使用 lambda 延迟绑定，确保在运行时获取 last_frames
    def _get_esp32_frame():
        if not last_frames:
            return None
        try:
            _, jpeg_bytes = last_frames[-1]
            return jpeg_bytes
        except (IndexError, ValueError):
            return None
    
    workflows = Workflows(
        api_key=API_KEY, 
        base_url=BASE_URL, 
        vision_model=VISION_MODEL, 
        cosy=tts_engine, 
        dispatcher=dispatcher,
        frame_getter=_get_esp32_frame  # ESP32 帧获取函数
    )
    print("[VOICE] 新语音系统初始化完成（视觉问答使用ESP32摄像头）", flush=True)

# 情绪映射函数：将新系统情绪映射到ESP32表情
def map_emotion_to_esp32_expr(emotion: str) -> str:
    """
    将新系统的情绪类型映射到ESP32的表情名称
    不改新系统的情绪名称（因为要发送给大模型API）
    """
    emotion_lower = emotion.lower().strip()
    
    # 直接对应
    if emotion_lower == "angry":
        return "angry"
    elif emotion_lower == "sad":
        return "sad"
    elif emotion_lower == "happy":
        return "happy"
    
    # 映射规则
    elif emotion_lower == "neutral":
        return "idle"  # 中性 → 空闲
    elif emotion_lower == "surprised":
        return "wink"  # 惊讶 → 俏皮眨眼
    elif emotion_lower == "fearful":
        return "sad"  # 害怕 → 伤心（下垂的姿态）
    elif emotion_lower == "disgusted":
        return "speechless"  # 厌恶 → 无语（翻白眼）
    
    # 默认
    else:
        return "idle"

# ---- 唐老鸭变声器配置 ----
DONALD_DUCK_ENABLED   = False      # 启用唐老鸭变声效果
DONALD_PITCH_SHIFT    = 1.45      # 音调提升 1.65 倍（唐老鸭风格高音）
DONALD_TREMOLO_RATE   = 25.0      # 颤音频率 Hz（模拟嘎嘎声）
DONALD_TREMOLO_DEPTH  = 0      # 颤音深度 0-1
DONALD_GAIN           = 1.30      # 最终增益

# ---- 引入我们的模块 ----
from audio_stream import (
    register_stream_route,         # 挂 /stream.wav
    broadcast_pcm16_realtime,      # 实时向连接分发 16k PCM
    hard_reset_audio,              # 音频+AI 播放总闸
    BYTES_PER_20MS_16K,
    is_playing_now,
    current_ai_task,
    wait_for_stream_client,        # 等待音频客户端连接
    send_silence_prebuffer,        # 发送静音预缓冲
)
from audio_stream import STREAM_SR

# 保留旧的ASR管理接口（但内部会使用新系统）
_current_recognition = None
_rec_lock = asyncio.Lock()

async def set_current_recognition(r):
    global _current_recognition
    async with _rec_lock:
        _current_recognition = r

async def stop_current_recognition():
    global _current_recognition
    async with _rec_lock:
        r = _current_recognition
        _current_recognition = None
    if r:
        try:
            r.stop()
        except Exception:
            pass

# 表情控制现在完全由 ESP32 端执行
# Python 端只需发送 EXPR:xxx 指令到 WebSocket

# ==================== 元音分析器（嘴型控制）====================
class VowelAnalyzer:
    """基于 LPC 共振峰分析的元音识别器，用于驱动嘴巴动画"""
    
    def __init__(self, sample_rate=16000, lpc_order=12):
        self.sample_rate = sample_rate
        self.lpc_order = lpc_order
        
        # 元音 F1-F2 中心点定义（Hz）
        # F1 = 第一共振峰（嘴巴开合程度）
        # F2 = 第二共振峰（舌头前后位置）
        self.vowel_centers = {
            'A': (800, 1300),   # 啊 - 大张嘴
            'O': (450, 800),    # 哦 - 圆嘴
            'E': (500, 1800),   # 呃 - 半开
            'I': (300, 2400),   # 衣 - 扁嘴
            'U': (350, 700),    # 乌 - 嘟嘴
        }
        
        # 平滑状态
        self.last_vowel = 'E'
        self.vowel_confidence = 0
        self.smoothed_volume = 0
    
    def preemphasis(self, samples, coef=0.97):
        """预加重滤波器，增强高频"""
        return np.append(samples[0], samples[1:] - coef * samples[:-1])
    
    def levinson_durbin(self, r, order):
        """Levinson-Durbin 递归算法求 LPC 系数"""
        a = np.zeros(order + 1)
        a[0] = 1.0
        e = r[0]
        
        for i in range(1, order + 1):
            if e == 0:
                break
            lambda_val = sum(a[j] * r[i - j] for j in range(i))
            k = -lambda_val / e
            
            a_new = a.copy()
            for j in range(1, i):
                a_new[j] = a[j] + k * a[i - j]
            a_new[i] = k
            a = a_new
            
            e = e * (1 - k * k)
        
        return a
    
    def get_formants(self, samples):
        """使用 LPC 分析提取共振峰频率"""
        try:
            # 预加重
            samples = self.preemphasis(samples)
            
            # 加汉明窗
            windowed = samples * np.hamming(len(samples))
            
            # 自相关法计算 LPC 系数
            r = np.correlate(windowed, windowed, mode='full')
            r = r[len(r)//2:][:self.lpc_order + 1]
            
            # Levinson-Durbin 递归
            a = self.levinson_durbin(r, self.lpc_order)
            
            # 从 LPC 系数求根，找共振峰
            roots = np.roots(a)
            roots = roots[np.imag(roots) >= 0]  # 只取上半平面
            
            # 转换为频率
            angles = np.angle(roots)
            freqs = np.abs(angles) * self.sample_rate / (2 * np.pi)
            
            # 过滤有效频率范围并排序
            valid_freqs = freqs[(freqs > 90) & (freqs < 3500)]
            valid_freqs = np.sort(valid_freqs)
            
            if len(valid_freqs) >= 2:
                return valid_freqs[0], valid_freqs[1]  # F1, F2
            elif len(valid_freqs) == 1:
                return valid_freqs[0], 1500
            return 500, 1500  # 默认值
            
        except Exception:
            return 500, 1500
    
    def classify_vowel(self, f1, f2):
        """根据 F1-F2 分类元音"""
        min_dist = float('inf')
        best_vowel = 'E'
        
        for vowel, (c_f1, c_f2) in self.vowel_centers.items():
            # 欧几里得距离（F2 权重稍高因为区分度更大）
            dist = np.sqrt((f1 - c_f1)**2 + 1.5 * (f2 - c_f2)**2)
            if dist < min_dist:
                min_dist = dist
                best_vowel = vowel
        
        # 计算置信度
        confidence = max(0, 1 - min_dist / 800)
        return best_vowel, confidence
    
    def analyze(self, pcm_data: bytes) -> dict:
        """分析音频并返回元音和嘴型参数"""
        try:
            samples = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32)
            
            if len(samples) < 160:  # 至少 10ms
                return {'vowel': 'CLOSED', 'volume': 0, 'f1': 0, 'f2': 0, 'confidence': 0}
            
            # 计算音量 (RMS)
            rms = np.sqrt(np.mean(samples**2))
            volume = min(1.0, rms / 8000.0)  # 归一化到 0-1
            
            # 平滑音量
            self.smoothed_volume = self.smoothed_volume * 0.7 + volume * 0.3
            
            if self.smoothed_volume < 0.02:  # 静音阈值
                return {
                    'vowel': 'CLOSED',
                    'volume': self.smoothed_volume,
                    'f1': 0, 'f2': 0,
                    'confidence': 1.0
                }
            
            # 提取共振峰
            f1, f2 = self.get_formants(samples)
            
            # 分类元音
            vowel, confidence = self.classify_vowel(f1, f2)
            
            # 置信度过低时保持上一个元音
            if confidence < 0.3:
                vowel = self.last_vowel
            else:
                self.last_vowel = vowel
            
            return {
                'vowel': vowel,
                'volume': self.smoothed_volume,
                'f1': f1,
                'f2': f2,
                'confidence': confidence
            }
            
        except Exception as e:
            return {'vowel': 'CLOSED', 'volume': 0, 'f1': 0, 'f2': 0, 'confidence': 0}

# 全局元音分析器实例
vowel_analyzer = VowelAnalyzer(sample_rate=SAMPLE_RATE)

# ==================== 人脸追踪配置 ====================
FACE_TRACK_ENABLED = True           # 是否启用人脸追踪
FACE_DETECT_INTERVAL = 2            # 每隔多少帧检测一次人脸（降低CPU负载）
FACE_TRACK_SMOOTH = 0.85            # 眼球平滑系数 (0-1, 越大越快到位，0.85=几乎直接跳到目标)
FACE_TRACK_TIMEOUT_MS = 800         # 人脸丢失超时时间（毫秒）

# 眼球角度范围（与 ESP32 face_animation.h 保持一致）
EYE_LR_MIN = 30
EYE_LR_MAX = 140
EYE_LR_CENTER = 85   # 左右中心
EYE_UD_MIN = 60
EYE_UD_MAX = 120
EYE_UD_CENTER = 95   # 上下中心（ESP32是95，稍微偏上）

# YOLO 人脸检测器
yolo_face_model = None
face_track_state = {
    "frame_count": 0,
    "last_face_time": 0,
    "current_lr": EYE_LR_CENTER,
    "current_ud": EYE_UD_CENTER,
    "target_lr": EYE_LR_CENTER,
    "target_ud": EYE_UD_CENTER,
    "face_detected": False,
    "last_face_box": None,  # (x, y, w, h) 用于前端显示
    "last_log": "",         # 日志信息
}

# ==================== 手势追踪配置 ====================
HAND_TRACK_ENABLED = True           # 是否启用手势追踪
HAND_COVER_THRESHOLD = 0.5          # 手部遮挡阈值（占画面50%以上触发遮眼动画）
HAND_COVER_EXIT_THRESHOLD = 0.5     # 退出遮挡状态的阈值

# MediaPipe 手部检测器
hand_detector = None
hand_track_state = {
    "hand_detected": False,
    "hand_center_x": 0.5,           # 手部中心X（归一化 0-1）
    "hand_center_y": 0.5,           # 手部中心Y（归一化 0-1）
    "hand_area_ratio": 0.0,         # 手部面积占画面比例
    "last_hand_box": None,          # 手部边界框
    
    # 遮眼动画状态机
    "cover_state": "none",          # none / blink_start / eyes_closed / peek_open / peek_close
    "cover_state_start_ms": 0,      # 当前状态开始时间
    "peek_eye": "left",             # 睁开哪只眼 left/right
    "next_peek_ms": 0,              # 下次睁眼时间
    "peek_duration_ms": 0,          # 睁眼持续时间
}

def init_yolo_face_detector():
    """初始化 YOLO 人脸检测器"""
    global yolo_face_model
    if yolo_face_model is not None:
        return True
    try:
        # 尝试修复 DLL 加载问题
        import sys
        if sys.platform == 'win32':
            # 添加 anaconda 的 Library/bin 到 PATH
            anaconda_paths = [
                r"D:\software\anaconda3\Library\bin",
                r"D:\software\anaconda3\DLLs",
                r"D:\software\anaconda3\Lib\site-packages\torch\lib",
            ]
            for p in anaconda_paths:
                if os.path.exists(p) and p not in os.environ.get('PATH', ''):
                    os.environ['PATH'] = p + os.pathsep + os.environ.get('PATH', '')
            
            # 设置 DLL 搜索路径
            try:
                os.add_dll_directory(r"D:\software\anaconda3\Library\bin")
                os.add_dll_directory(r"D:\software\anaconda3\Lib\site-packages\torch\lib")
            except (AttributeError, OSError):
                pass
        
        from ultralytics import YOLO
        model_path = os.path.join(os.path.dirname(__file__), "model", "yolov11n-face.pt")
        if not os.path.exists(model_path):
            print(f"[FACE] YOLO模型不存在: {model_path}", flush=True)
            return False
        yolo_face_model = YOLO(model_path)
        print(f"[FACE] YOLO人脸检测器初始化成功: {model_path}", flush=True)
        return True
    except Exception as e:
        print(f"[FACE] YOLO人脸检测器初始化失败: {e}", flush=True)
        return False

def init_hand_detector():
    """初始化 MediaPipe 手部检测器"""
    global hand_detector
    if hand_detector is not None:
        return True
    try:
        import mediapipe as mp
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision
        
        model_path = os.path.join(os.path.dirname(__file__), "model", "hand_landmarker.task")
        if not os.path.exists(model_path):
            print(f"[HAND] 手部模型不存在: {model_path}", flush=True)
            return False
        
        base_options = python.BaseOptions(model_asset_path=model_path)
        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            num_hands=2,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5
        )
        hand_detector = vision.HandLandmarker.create_from_options(options)
        print(f"[HAND] 手部检测器初始化成功", flush=True)
        return True
    except Exception as e:
        print(f"[HAND] 手部检测器初始化失败: {e}", flush=True)
        return False

def detect_hand(frame_rgb) -> dict:
    """
    检测手部并返回手部信息
    返回: {detected, center_x, center_y, area_ratio, box}
    """
    global hand_detector
    
    if hand_detector is None:
        if not init_hand_detector():
            return {"detected": False, "center_x": 0.5, "center_y": 0.5, "area_ratio": 0, "box": None}
    
    try:
        import mediapipe as mp
        from mediapipe.tasks.python import vision
        
        h, w = frame_rgb.shape[:2]
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
        result = hand_detector.detect(mp_image)
        
        if not result.hand_landmarks or len(result.hand_landmarks) == 0:
            return {"detected": False, "center_x": 0.5, "center_y": 0.5, "area_ratio": 0, "box": None}
        
        # 合并所有手部的边界框
        all_x = []
        all_y = []
        for hand_landmarks in result.hand_landmarks:
            for lm in hand_landmarks:
                all_x.append(lm.x)
                all_y.append(lm.y)
        
        if not all_x:
            return {"detected": False, "center_x": 0.5, "center_y": 0.5, "area_ratio": 0, "box": None}
        
        # 计算边界框
        min_x, max_x = min(all_x), max(all_x)
        min_y, max_y = min(all_y), max(all_y)
        
        # 扩大边界框（手部关键点不包括手掌边缘）
        pad_x = (max_x - min_x) * 0.3
        pad_y = (max_y - min_y) * 0.3
        min_x = max(0, min_x - pad_x)
        max_x = min(1, max_x + pad_x)
        min_y = max(0, min_y - pad_y)
        max_y = min(1, max_y + pad_y)
        
        # 计算中心和面积
        center_x = (min_x + max_x) / 2
        center_y = (min_y + max_y) / 2
        area_ratio = (max_x - min_x) * (max_y - min_y)
        
        return {
            "detected": True,
            "center_x": center_x,
            "center_y": center_y,
            "area_ratio": area_ratio,
            "box": {"x": min_x, "y": min_y, "w": max_x - min_x, "h": max_y - min_y}
        }
        
    except Exception as e:
        # print(f"[HAND] 检测异常: {e}", flush=True)
        return {"detected": False, "center_x": 0.5, "center_y": 0.5, "area_ratio": 0, "box": None}

import random

async def process_hand_cover_animation(hand_area_ratio: float, audio_ws, now_ms: float):
    """
    处理手部遮挡时的眼皮动画状态机
    - 手部面积 > 50%: 触发遮眼动画
    - 快速眨几下 → 闭眼 → 间歇性睁一只眼
    """
    global hand_track_state
    
    state = hand_track_state["cover_state"]
    state_start = hand_track_state["cover_state_start_ms"]
    elapsed = now_ms - state_start
    
    # 状态机
    if hand_area_ratio >= HAND_COVER_THRESHOLD:
        # 手部遮挡中
        if state == "none":
            # 开始遮挡：快速眨眼
            hand_track_state["cover_state"] = "blink_start"
            hand_track_state["cover_state_start_ms"] = now_ms
            print(f"[HAND] 手部遮挡！开始眨眼动画 audio_ws={audio_ws is not None}", flush=True)
            # 发送快速眨眼命令
            if audio_ws:
                try:
                    await audio_ws.send_text("EYELID:BLINK_FAST")
                    print(f"[HAND] → ESP32: EYELID:BLINK_FAST", flush=True)
                except Exception as e:
                    print(f"[HAND] 发送失败: {e}", flush=True)
            else:
                print(f"[HAND] audio_ws 未连接，无法发送命令", flush=True)
                
        elif state == "blink_start":
            # 快速眨眼 500ms 后闭眼
            if elapsed > 500:
                hand_track_state["cover_state"] = "eyes_closed"
                hand_track_state["cover_state_start_ms"] = now_ms
                hand_track_state["next_peek_ms"] = now_ms + 1000  # 1秒后睁眼
                print(f"[HAND] 闭眼中...", flush=True)
                if audio_ws:
                    try:
                        await audio_ws.send_text("EYELID:CLOSE_BOTH")
                        print(f"[HAND] → ESP32: EYELID:CLOSE_BOTH", flush=True)
                    except Exception as e:
                        print(f"[HAND] 发送失败: {e}", flush=True)
                    
        elif state == "eyes_closed":
            # 闭眼状态，等待睁眼时机
            if now_ms >= hand_track_state["next_peek_ms"]:
                # 随机选择睁哪只眼
                hand_track_state["peek_eye"] = random.choice(["left", "right"])
                hand_track_state["cover_state"] = "peek_open"
                hand_track_state["cover_state_start_ms"] = now_ms
                hand_track_state["peek_duration_ms"] = random.randint(1000, 2000)  # 看1-2秒
                print(f"[HAND] 睁开{hand_track_state['peek_eye']}眼偷看", flush=True)
                if audio_ws:
                    try:
                        eye_cmd = "EYELID:PEEK_LEFT" if hand_track_state["peek_eye"] == "left" else "EYELID:PEEK_RIGHT"
                        await audio_ws.send_text(eye_cmd)
                    except: pass
                    
        elif state == "peek_open":
            # 睁一只眼偷看中
            if elapsed > hand_track_state["peek_duration_ms"]:
                hand_track_state["cover_state"] = "peek_close"
                hand_track_state["cover_state_start_ms"] = now_ms
                print(f"[HAND] 闭上偷看的眼睛", flush=True)
                if audio_ws:
                    try:
                        await audio_ws.send_text("EYELID:CLOSE_BOTH")
                    except: pass
                    
        elif state == "peek_close":
            # 闭眼后等待下次睁眼
            if elapsed > 500:  # 短暂闭眼后设置下次睁眼时间
                hand_track_state["cover_state"] = "eyes_closed"
                hand_track_state["cover_state_start_ms"] = now_ms
                # 2-4秒后再次睁眼
                hand_track_state["next_peek_ms"] = now_ms + random.randint(2000, 4000)
                
    else:
        # 手部离开
        if state != "none":
            hand_track_state["cover_state"] = "none"
            hand_track_state["cover_state_start_ms"] = now_ms
            print(f"[HAND] 手部离开，恢复正常", flush=True)
            if audio_ws:
                try:
                    await audio_ws.send_text("EYELID:NORMAL")
                except: pass

def nonlinear_eye_map(offset: float, total_range: float) -> int:
    """
    非线性眼球映射：小偏移→大转动
    - 人脸偏移 0~30% → 眼球转动 70% 角度范围
    - 人脸偏移 30%~100% → 眼球转动剩余 30% 角度范围
    
    offset: -1 到 1 的偏移值
    total_range: 眼球角度半范围（从中心到最大/最小的距离）
    返回: 相对于中心的角度偏移量
    """
    sign = 1 if offset >= 0 else -1
    abs_offset = abs(offset)
    
    # 分段映射
    THRESHOLD = 0.3  # 30% 的人脸偏移阈值
    FAST_RATIO = 0.7  # 前 30% 偏移占 70% 角度
    SLOW_RATIO = 0.3  # 后 70% 偏移占 30% 角度
    
    if abs_offset <= THRESHOLD:
        # 前 30% 偏移 → 70% 角度（快速响应区）
        normalized = abs_offset / THRESHOLD  # 0 到 1
        angle_ratio = normalized * FAST_RATIO
    else:
        # 后 70% 偏移 → 30% 角度（精细调节区）
        normalized = (abs_offset - THRESHOLD) / (1.0 - THRESHOLD)  # 0 到 1
        angle_ratio = FAST_RATIO + normalized * SLOW_RATIO
    
    return int(sign * angle_ratio * total_range)

def detect_face_yolo(jpeg_bytes: bytes) -> tuple:
    """
    使用 YOLO 检测人脸并计算眼球角度
    返回: (face_detected, lr_angle, ud_angle, face_box, log_msg)
    """
    global yolo_face_model, face_track_state
    
    if yolo_face_model is None:
        if not init_yolo_face_detector():
            return (False, EYE_LR_CENTER, EYE_UD_CENTER, None, "模型未加载")
    
    try:
        # 解码 JPEG
        nparr = np.frombuffer(jpeg_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if frame is None:
            return (False, EYE_LR_CENTER, EYE_UD_CENTER, None, "图像解码失败")
        
        h, w = frame.shape[:2]
        
        # YOLO 推理（静默模式）
        results = yolo_face_model(frame, verbose=False, conf=0.5)
        
        # 解析结果
        if len(results) == 0 or len(results[0].boxes) == 0:
            return (False, EYE_LR_CENTER, EYE_UD_CENTER, None, "未检测到人脸")
        
        # 取置信度最高的人脸
        boxes = results[0].boxes
        best_idx = boxes.conf.argmax().item()
        box = boxes.xyxy[best_idx].cpu().numpy()
        conf = boxes.conf[best_idx].item()
        
        x1, y1, x2, y2 = map(int, box)
        fw, fh = x2 - x1, y2 - y1
        
        # 计算人脸中心
        face_cx = (x1 + x2) // 2
        face_cy = (y1 + y2) // 2
        
        # 计算相对于图像中心的偏移（-1 到 1）
        offset_x = (face_cx - w / 2) / (w / 2)
        offset_y = (face_cy - h / 2) / (h / 2)
        
        # ★ 镜像左右：反转 offset_x
        offset_x = -offset_x
        
        # 眼球角度半范围
        lr_range = (EYE_LR_MAX - EYE_LR_MIN) / 2
        ud_range = (EYE_UD_MAX - EYE_UD_MIN) / 2
        
        # ★ 非线性映射：小偏移→大转动
        lr_offset = nonlinear_eye_map(offset_x, lr_range)
        ud_offset = nonlinear_eye_map(-offset_y, ud_range)  # 上下也反转
        
        lr_angle = EYE_LR_CENTER + lr_offset
        ud_angle = EYE_UD_CENTER + ud_offset
        
        # 限制在安全范围内
        lr_angle = max(EYE_LR_MIN, min(EYE_LR_MAX, lr_angle))
        ud_angle = max(EYE_UD_MIN, min(EYE_UD_MAX, ud_angle))
        
        # 生成详细日志（包含偏移量和角度变化）
        log_msg = f"偏移X={offset_x:+.2f} → LR偏移={lr_offset:+d} → 角度={lr_angle}° (范围{EYE_LR_MIN}-{EYE_LR_MAX})"
        
        # 返回人脸框（归一化坐标，用于前端绘制）
        face_box = {
            "x": x1 / w,
            "y": y1 / h,
            "w": fw / w,
            "h": fh / h,
            "conf": conf
        }
        
        return (True, lr_angle, ud_angle, face_box, log_msg)
        
    except Exception as e:
        return (False, EYE_LR_CENTER, EYE_UD_CENTER, None, f"检测异常: {e}")

async def process_face_tracking(jpeg_bytes: bytes, audio_ws):
    """
    处理人脸和手部追踪逻辑
    - 检测人脸/手部
    - 平滑眼球运动
    - 手部遮挡时触发眼皮动画
    - 发送命令到 ESP32
    - 广播状态到前端
    """
    global face_track_state, hand_track_state
    
    if not FACE_TRACK_ENABLED:
        return
    
    # 帧计数，降低检测频率
    face_track_state["frame_count"] += 1
    if face_track_state["frame_count"] % FACE_DETECT_INTERVAL != 0:
        return
    
    now = time.time() * 1000  # 毫秒
    
    # ========== 1. 解码图像（共用） ==========
    try:
        nparr = np.frombuffer(jpeg_bytes, np.uint8)
        frame_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if frame_bgr is None:
            return
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    except:
        return
    
    # ========== 2. 手部检测 ==========
    hand_info = {"detected": False, "area_ratio": 0}
    if HAND_TRACK_ENABLED:
        hand_info = detect_hand(frame_rgb)
        hand_track_state["hand_detected"] = hand_info["detected"]
        hand_track_state["hand_area_ratio"] = hand_info["area_ratio"]
        hand_track_state["last_hand_box"] = hand_info.get("box")
        
        if hand_info["detected"]:
            hand_track_state["hand_center_x"] = hand_info["center_x"]
            hand_track_state["hand_center_y"] = hand_info["center_y"]
        
        # 调试日志：每20帧打印一次手部检测状态
        if face_track_state["frame_count"] % 20 == 0:
            if hand_info["detected"]:
                print(f"[HAND DEBUG] 手部面积={hand_info['area_ratio']*100:.1f}% 阈值={HAND_COVER_THRESHOLD*100:.0f}% 状态={hand_track_state['cover_state']}", flush=True)
    
    # ========== 3. 手部遮挡动画处理 ==========
    if HAND_TRACK_ENABLED and hand_info["area_ratio"] >= HAND_COVER_THRESHOLD:
        # 手部遮挡时，处理眼皮动画状态机
        await process_hand_cover_animation(hand_info["area_ratio"], audio_ws, now)
        
        # 遮挡状态下也可以让眼球跟随手部（如果想要的话）
        # 但根据需求，遮挡时主要是眼皮动画，眼球可以不动
        await broadcast_face_track_state()
        return
    else:
        # 手部离开，确保恢复正常
        if hand_track_state["cover_state"] != "none":
            await process_hand_cover_animation(hand_info["area_ratio"], audio_ws, now)
    
    # ========== 4. 人脸/手部追踪 - 眼球跟随 ==========
    detected = False
    target_lr = EYE_LR_CENTER
    target_ud = EYE_UD_CENTER
    face_box = None
    log_msg = ""
    
    # 优先检测手部（如果手部检测到且面积 > 5%）
    if HAND_TRACK_ENABLED and hand_info["detected"] and hand_info["area_ratio"] > 0.05:
        # 手部追踪眼球
        offset_x = (hand_info["center_x"] - 0.5) * 2  # 转换为 -1 到 1
        offset_y = (hand_info["center_y"] - 0.5) * 2
        
        # 镜像左右
        offset_x = -offset_x
        
        lr_range = (EYE_LR_MAX - EYE_LR_MIN) / 2
        ud_range = (EYE_UD_MAX - EYE_UD_MIN) / 2
        
        lr_offset = nonlinear_eye_map(offset_x, lr_range)
        ud_offset = nonlinear_eye_map(-offset_y, ud_range)
        
        target_lr = EYE_LR_CENTER + lr_offset
        target_ud = EYE_UD_CENTER + ud_offset
        
        target_lr = max(EYE_LR_MIN, min(EYE_LR_MAX, target_lr))
        target_ud = max(EYE_UD_MIN, min(EYE_UD_MAX, target_ud))
        
        detected = True
        log_msg = f"[手] 面积={hand_info['area_ratio']*100:.0f}% → LR={target_lr} UD={target_ud}"
        face_box = hand_info.get("box")  # 用于前端显示
    else:
        # 人脸追踪
        face_detected, face_lr, face_ud, face_box_result, face_log = detect_face_yolo(jpeg_bytes)
        if face_detected:
            detected = True
            target_lr = face_lr
            target_ud = face_ud
            face_box = face_box_result
            log_msg = f"[脸] {face_log}"
        else:
            log_msg = face_log
    
    # 更新状态
    face_track_state["last_face_box"] = face_box
    face_track_state["last_log"] = log_msg
    
    # 调试日志：每30帧打印一次
    if face_track_state["frame_count"] % 30 == 0:
        audio_status = "已连接" if (audio_ws and audio_ws.client_state == WebSocketState.CONNECTED) else "未连接"
        hand_status = f"手:{hand_info['area_ratio']*100:.0f}%" if hand_info["detected"] else "手:无"
        print(f"[TRACK] 帧={face_track_state['frame_count']} {hand_status} ESP32={audio_status} {log_msg}", flush=True)
    
    if detected:
        face_track_state["last_face_time"] = now
        face_track_state["target_lr"] = target_lr
        face_track_state["target_ud"] = target_ud
        
        if not face_track_state["face_detected"]:
            face_track_state["face_detected"] = True
            print(f"[TRACK] ✓ 开始追踪 LR={target_lr} UD={target_ud}", flush=True)
    else:
        # 检查是否超时
        if now - face_track_state["last_face_time"] > FACE_TRACK_TIMEOUT_MS:
            if face_track_state["face_detected"]:
                face_track_state["face_detected"] = False
                face_track_state["last_face_box"] = None
                print(f"[TRACK] ✗ 目标丢失，恢复随机眼球运动", flush=True)
                if audio_ws is not None:
                    try:
                        if audio_ws.client_state == WebSocketState.CONNECTED:
                            await audio_ws.send_text("EYE:IDLE")
                    except Exception as e:
                        print(f"[TRACK] 发送 EYE:IDLE 失败: {e}", flush=True)
            await broadcast_face_track_state()
            return
    
    # 平滑插值
    face_track_state["current_lr"] += (face_track_state["target_lr"] - face_track_state["current_lr"]) * FACE_TRACK_SMOOTH
    face_track_state["current_ud"] += (face_track_state["target_ud"] - face_track_state["current_ud"]) * FACE_TRACK_SMOOTH
    
    lr = int(face_track_state["current_lr"])
    ud = int(face_track_state["current_ud"])
    
    # 发送眼球位置命令到 ESP32
    if audio_ws is not None:
        try:
            if audio_ws.client_state == WebSocketState.CONNECTED:
                cmd = f"EYE:{lr},{ud}"
                await audio_ws.send_text(cmd)
                if face_track_state["frame_count"] % 20 == 0:
                    print(f"[TRACK] → ESP32: {cmd}", flush=True)
        except Exception as e:
            print(f"[TRACK] 发送眼球命令失败: {e}", flush=True)
    
    # 广播状态到前端
    await broadcast_face_track_state()

# 人脸追踪状态广播
async def broadcast_face_track_state():
    """广播人脸追踪状态到所有 UI 客户端"""
    global face_track_state
    try:
        data = {
            "type": "face_track",
            "detected": face_track_state["face_detected"],
            "box": face_track_state["last_face_box"],
            "lr": int(face_track_state["current_lr"]),
            "ud": int(face_track_state["current_ud"]),
            "log": face_track_state["last_log"]
        }
        msg = "FACE:" + json.dumps(data)
        
        # 调试：每100帧打印一次广播状态
        #if face_track_state["frame_count"] % 100 == 0:
            #print(f"[FACE BROADCAST] 客户端数={len(ui_clients)} 数据={data}", flush=True)
        
        dead = []
        for k, ws in list(ui_clients.items()):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(k)
        for k in dead:
            ui_clients.pop(k, None)
    except Exception:
        pass

# ---- IMU UDP ---- (已移除：ESP32不再使用UDP发送IMU数据)
# UDP_IP   = "0.0.0.0"
# UDP_PORT = 12345

app = FastAPI()

# ====== 状态与容器 ======
app.mount("/static", StaticFiles(directory="static"), name="static")

ui_clients: Dict[int, WebSocket] = {}
current_partial: str = ""
recent_finals: List[str] = []
RECENT_MAX = 50
last_frames: Deque[Tuple[float, bytes]] = deque(maxlen=10)

camera_viewers: Set[WebSocket] = set()
esp32_camera_ws: Optional[WebSocket] = None
# imu_ws_clients: Set[WebSocket] = set()  # 已移除：ESP32不再使用UDP发送IMU数据
esp32_audio_ws: Optional[WebSocket] = None

# ========== 音色克隆相关变量 ==========
clone_recording = False  # 是否正在录制克隆音频
clone_audio_buffer: List[bytes] = []  # 克隆音频缓冲区
clone_start_time: float = 0.0  # 克隆开始时间
clone_duration: int = 7  # 克隆录音时长（秒）
clone_event: Optional[asyncio.Event] = None  # 克隆完成事件

def apply_donald_duck_effect(pcm_data: bytes, sample_rate: int, state_holder):
    """
    唐老鸭变声器 - 使用 scipy.signal.resample 实现真正的音调变换
    
    原理：
    1. 音调变换：将N个样本重采样为 N/pitch_shift 个样本，音调提高
    2. 颤音效果：振幅调制模拟嘎嘎声
    
    注意：由于音调提升会导致输出样本数减少，播放速度会更快
    """
    if (not DONALD_DUCK_ENABLED) or (not pcm_data) or len(pcm_data) < 4:
        return pcm_data

    try:
        import numpy as np
        from scipy import signal
        
        # 转换为 numpy 数组
        samples = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32)
        if len(samples) < 10:
            return pcm_data
        
        original_len = len(samples)
        
        # ===== 1. 音调变换（真正的 pitch shift）=====
        # 将 N 个样本重采样为 N/pitch 个样本
        # 当以原采样率播放时，音调会提高 pitch 倍
        new_len = int(original_len / DONALD_PITCH_SHIFT)
        if new_len < 10:
            return pcm_data
        
        # 使用 scipy 的 resample（基于 FFT，效果好）
        pitched = signal.resample(samples, new_len)
        
        # ===== 2. 颤音效果（振幅调制，模拟嘎嘎声）=====
        phase = state_holder.get("phase", 0.0)
        t = np.arange(len(pitched)) / sample_rate + phase
        
        # 正弦波 + 方波混合，模拟经典"嘎嘎"声
        tremolo = 1.0 - DONALD_TREMOLO_DEPTH * (
            0.6 * np.sin(2 * np.pi * DONALD_TREMOLO_RATE * t) +
            0.4 * np.sign(np.sin(2 * np.pi * DONALD_TREMOLO_RATE * 1.3 * t))
        )
        tremolo = np.clip(tremolo, 0.5, 1.4)
        pitched = pitched * tremolo
        
        # 更新相位（保持连续性）
        state_holder["phase"] = (phase + len(pitched) / sample_rate) % 100.0
        
        # ===== 3. 应用增益并转回字节 =====
        pitched = pitched * DONALD_GAIN
        pitched = np.clip(pitched, -32767, 32767).astype(np.int16)
        
        # 调试日志（每30次打印一次）
        if not hasattr(apply_donald_duck_effect, '_count'):
            apply_donald_duck_effect._count = 0
        apply_donald_duck_effect._count += 1
        if apply_donald_duck_effect._count % 30 == 1:
            print(f"[DONALD] 变声OK: {original_len}→{len(pitched)}样本, pitch={DONALD_PITCH_SHIFT}x", flush=True)
        
        return pitched.tobytes()
        
    except Exception as exc:
        import traceback
        print(f"[DONALD] effect failed: {exc}", flush=True)
        traceback.print_exc()
        return pcm_data

# ====== 高清抓拍（一次性）状态 ====== (已移除：直接使用视频流帧，避免卡顿)
# hq_snapshot_waiter: Optional[asyncio.Future] = None
# hq_snapshot_collecting: bool = False

# ============== 关键：系统级"硬重置"总闸 =================
interrupt_lock = asyncio.Lock()

# ============== 系统状态 =================

async def ui_broadcast_raw(msg: str):
    dead = []
    for k, ws in list(ui_clients.items()):
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(k)
    for k in dead:
        ui_clients.pop(k, None)


async def ui_broadcast_partial(text: str):
    global current_partial
    current_partial = text
    await ui_broadcast_raw("PARTIAL:" + text)

async def ui_broadcast_final(text: str):
    global current_partial, recent_finals
    current_partial = ""
    recent_finals.append(text)
    if len(recent_finals) > RECENT_MAX:
        recent_finals = recent_finals[-RECENT_MAX:]
    await ui_broadcast_raw("FINAL:" + text)
    print(f"[ASR/AI FINAL] {text}", flush=True)

async def full_system_reset(reason: str = ""):
    """
    回到刚启动后的状态：
    1) 停播 + 取消AI任务 + 切断所有/stream.wav（hard_reset_audio）
    2) 停止 ASR 实时识别流（关键）
    3) 清 UI 状态
    4) 清最近相机帧（避免把旧帧又拼进下一轮）
    5) 告知 ESP32：RESET（可选）
    """
    # 1) 音频&AI
    await hard_reset_audio(reason or "full_system_reset")

    # 2) ASR
    await stop_current_recognition()

    # 3) UI
    global current_partial, recent_finals
    current_partial = ""
    recent_finals = []

    # 4) 相机帧
    try:
        last_frames.clear()
    except Exception:
        pass

    # 5) 通知 ESP32
    try:
        if esp32_audio_ws and (esp32_audio_ws.client_state == WebSocketState.CONNECTED):
            await esp32_audio_ws.send_text("RESET")
    except Exception:
        pass

    print("[SYSTEM] full reset done.", flush=True)


# ========= 新语音系统播放启动 =========
async def start_ai_with_text(user_text: str):
    """硬重置后，开启新的 AI 语音输出（使用新语音系统）。"""
    if not chat_state or not dispatcher or not tts_engine or not workflows:
        print("[AI] 错误：语音系统未初始化", flush=True)
        return

    async def _runner():
        txt_buf: List[str] = []
        emotion_sent = False  # 是否已发送情绪到ESP32
        cartoon_states = {"down": None, "up": None}

        try:
            # 1. 意图路由：确定用户意图和情绪
            decision = dispatcher.route(user_text, chat_state)
            emotion = decision.emotion  # 直接从路由获取情绪（不需要额外LLM调用）
            esp32_expr = map_emotion_to_esp32_expr(emotion)

            # 2. 发送情绪到ESP32（只发送一次）
            if not emotion_sent and esp32_audio_ws and (esp32_audio_ws.client_state == WebSocketState.CONNECTED):
                emotion_sent = True
                try:
                    await esp32_audio_ws.send_text(f"EMO:{emotion}")  # 保留原情绪名称（用于LED颜色）
                    await esp32_audio_ws.send_text(f"EXPR:{esp32_expr}")  # 映射后的表情名称
                    print(f"[AI] 情绪: {emotion} -> ESP32表情: {esp32_expr}", flush=True)
                except Exception as e:
                    print(f"[AI] 发送情绪到ESP32失败: {e}", flush=True)

            # 3. 根据意图选择处理方式
            if decision.intent in ("default", "dialect", "role_scene"):
                # 流式处理：文本流 + TTS流
                # 更新状态（方言/角色/场景）
                if decision.intent == "dialect":
                    if decision.dialect:
                        chat_state.dialect = decision.dialect
                    if not (decision.query or "").strip():
                        # 只是设置方言，没有具体问题
                        ack = f"好的，接下来我会用{chat_state.dialect or '方言'}和你聊。"
                        instruction = chat_state.build_tts_instruction(emotion)
                        # 使用非流式speak（因为只有一句话）
                        reply_text = ack
                        await _speak_text_to_broadcast(reply_text, chat_state.current_voice, instruction, cartoon_states)
                        return

                if decision.intent == "role_scene":
                    if decision.role:
                        chat_state.role = decision.role
                    if decision.scene:
                        chat_state.scene = decision.scene
                    if decision.style_hint:
                        chat_state.style_hint = decision.style_hint
                    if not (decision.query or "").strip():
                        # 只是设置角色/场景，没有具体问题
                        ack = "好的，已进入角色/场景模式。你想让我怎么表演？"
                        instruction = chat_state.build_tts_instruction(emotion)
                        reply_text = ack
                        await _speak_text_to_broadcast(reply_text, chat_state.current_voice, instruction, cartoon_states)
                        return

                # 流式生成文本并TTS
                query = (decision.query or "").strip() or user_text
                instruction = chat_state.build_tts_instruction(emotion)
                
                # 生成流式文本
                text_stream = dispatcher.chat_answer_stream(query, chat_state, emotion)
                
                # 流式TTS并广播
                await _speak_stream_to_broadcast(text_stream, chat_state.current_voice, instruction, txt_buf, cartoon_states)

            elif decision.intent == "clone":
                # ★ 特殊处理：音色克隆（使用 ESP32 麦克风）
                global clone_recording, clone_audio_buffer, clone_start_time, clone_duration, clone_event
                
                # 解析录音时长
                seconds = 7
                try:
                    if decision.style_hint:
                        seconds = int(float(decision.style_hint))
                        seconds = max(5, min(30, seconds))  # 限制5-30秒
                except Exception:
                    seconds = 7
                
                clone_duration = seconds
                
                # 1. 先播放提示语
                prompt_text = f"这还不简单，我会录制{seconds}秒你的声音进行克隆。说点啥吧pPp。"
                instruction = chat_state.build_tts_instruction("neutral")
                await _speak_text_to_broadcast(prompt_text, chat_state.current_voice, instruction, cartoon_states)
                txt_buf.append(prompt_text)
                
                # 2. 等待提示语播放完成
                await asyncio.sleep(1.0)
                
                # 3. 开始收集 ESP32 音频
                clone_audio_buffer = []
                clone_start_time = time.time()
                clone_event = asyncio.Event()
                clone_recording = True
                
                print(f"[CLONE] 开始从 ESP32 录音 {seconds} 秒...", flush=True)
                
                # 通知 ESP32 开始发送音频（如果当前没有 ASR 在运行）
                if esp32_audio_ws and (esp32_audio_ws.client_state == WebSocketState.CONNECTED):
                    try:
                        await esp32_audio_ws.send_text("START")  # 确保 ESP32 发送音频
                    except Exception as e:
                        print(f"[CLONE] 通知 ESP32 失败: {e}", flush=True)
                
                # 4. 等待录音完成（超时保护）
                try:
                    await asyncio.wait_for(clone_event.wait(), timeout=seconds + 5)
                except asyncio.TimeoutError:
                    print(f"[CLONE] 录音超时，使用已收集的数据", flush=True)
                finally:
                    clone_recording = False
                
                # 5. 停止 ASR 流
                if esp32_audio_ws and (esp32_audio_ws.client_state == WebSocketState.CONNECTED):
                    try:
                        await esp32_audio_ws.send_text("STOP")
                    except Exception:
                        pass
                
                # 6. 合并收集到的音频
                if clone_audio_buffer:
                    pcm_data = b''.join(clone_audio_buffer)
                    print(f"[CLONE] 收集到 {len(pcm_data)} 字节音频 ({len(pcm_data)/32000:.1f}秒)", flush=True)
                    
                    # 7. 调用克隆服务
                    try:
                        new_voice = tts_engine.enroll_voice_from_pcm(pcm_data, prefix="myvoice")
                        chat_state.set_cloned_voice(new_voice)
                        
                        reply_text = "太好了！音色克隆成功，接下来我会用你的声音说话。你想聊点什么？"
                        print(f"[CLONE] 成功！新音色ID: {new_voice}", flush=True)
                    except Exception as e:
                        reply_text = f"音色克隆失败：{e}"
                        print(f"[CLONE] 失败: {e}", flush=True)
                else:
                    reply_text = "没有收到音频数据，请确保 ESP32 麦克风正常工作。"
                    print("[CLONE] 没有收集到音频数据", flush=True)
                
                clone_audio_buffer = []  # 清理缓冲区
                
                # 8. 播放结果
                instruction = chat_state.build_tts_instruction("neutral")
                await _speak_text_to_broadcast(reply_text, chat_state.current_voice, instruction, cartoon_states)
                txt_buf.append(reply_text)
                
            elif decision.intent == "vision":
                # ★ 流式视觉问答（优化版：base64直传 + 流式输出）
                question = (decision.query or "").strip() or user_text
                instruction = chat_state.build_tts_instruction(emotion)
                
                print(f"[AI] 流式视觉问答: {question}", flush=True)
                
                # 获取视觉流式回复生成器
                vision_stream = workflows.run_vision_stream(question)
                
                # 流式TTS并广播
                await _speak_stream_to_broadcast(vision_stream, chat_state.current_voice, instruction, txt_buf, cartoon_states)
                
            else:
                # 非流式处理：workflows（reset等）
                reply_text = workflows.run(decision, user_text, chat_state)
                instruction = chat_state.build_tts_instruction(emotion)
                
                # 非流式TTS并广播
                await _speak_text_to_broadcast(reply_text, chat_state.current_voice, instruction, cartoon_states)
                txt_buf.append(reply_text)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[AI] 错误: {e}", flush=True)
            import traceback
            traceback.print_exc()
            try:
                await ui_broadcast_final(f"[AI] 发生错误：{e}")
            except Exception:
                pass
        finally:
            # 自然结束时，给当前连接一个 "完结" 信号
            from audio_stream import stream_clients
            for sc in list(stream_clients):
                if not sc.abort_event.is_set():
                    try: sc.q.put_nowait(b"\x00"*BYTES_PER_20MS_16K)
                    except Exception: pass
                    try: sc.q.put_nowait(None)
                    except Exception: pass

            final_text = ("".join(txt_buf)).strip() or "（空响应）"
            try:
                await ui_broadcast_final("[AI] " + final_text)
            except Exception:
                pass
            
            # AI播放完成后，清空UI状态
            try:
                await ui_broadcast_partial("")
                print("[AI] 播放完成，已清空UI状态", flush=True)
            except Exception:
                pass
            
            # 短暂等待
            await asyncio.sleep(0.5)
            print("[AI] 等待完成，准备重启ASR", flush=True)
            
            # 通知ESP32重新启动ASR识别，并恢复 idle 表情
            try:
                if esp32_audio_ws and (esp32_audio_ws.client_state == WebSocketState.CONNECTED):
                    await esp32_audio_ws.send_text("START")
                    await esp32_audio_ws.send_text("EXPR:idle")
                    print("[AI] 已通知ESP32重启ASR + 恢复idle", flush=True)
            except Exception as e:
                print(f"[AI] 通知ESP32重启ASR失败：{e}", flush=True)

    # 真正启动前先硬重置（但保留音频连接，避免开头丢失）
    await hard_reset_audio("start_ai_with_text", keep_connections=True)
    
    # AI开始播放前，停止ASR识别
    await stop_current_recognition()
    
    # 清空UI状态
    global current_partial
    current_partial = ""
    await ui_broadcast_partial("")
    print("[AI] 已清空UI状态", flush=True)
    
    # 通知ESP32停止发送音频数据
    try:
        if esp32_audio_ws and (esp32_audio_ws.client_state == WebSocketState.CONNECTED):
            await esp32_audio_ws.send_text("STOP")
            print("[AI] 已通知ESP32停止ASR音频上行", flush=True)
    except Exception as e:
        print(f"[AI] 通知ESP32停止ASR失败：{e}", flush=True)
    
    print("[AI] 已停止ASR识别，开始AI播放", flush=True)
    
    # 等待音频客户端连接（最多2秒）
    if await wait_for_stream_client(timeout=2.0):
        # 发送短暂静音预缓冲，帮助ESP32同步
        await send_silence_prebuffer(duration_ms=60)
        print("[AI] 音频客户端已连接，预缓冲完成", flush=True)
    else:
        print("[AI] 警告：未检测到音频客户端连接", flush=True)
    
    loop = asyncio.get_running_loop()
    from audio_stream import current_ai_task as _task_holder
    from audio_stream import __dict__ as _as_dict
    task = loop.create_task(_runner())
    _as_dict["current_ai_task"] = task


async def _speak_text_to_broadcast(text: str, voice: str, instruction: Optional[str], cartoon_states: dict):
    """非流式TTS：将文本转为音频并广播"""
    if not text or not text.strip():
        return
    
    if not tts_engine:
        print("[AI] 错误：TTS引擎未初始化", flush=True)
        return
    
    # 使用cosyvoice的非流式方法生成WAV，然后转为PCM16广播
    from pathlib import Path
    import uuid
    
    # 临时保存WAV文件
    runtime_dir = Path("runtime")
    runtime_dir.mkdir(parents=True, exist_ok=True)
    wav_path = runtime_dir / f"tts_{uuid.uuid4().hex}.wav"
    
    try:
        # 生成WAV
        tts_engine.tts_to_wav(text=text, voice=voice, instruction=instruction, out_path=str(wav_path))
        
        # 读取WAV并转为PCM16
        import wave
        with wave.open(str(wav_path), "rb") as wf:
            sr = wf.getframerate()
            data = wf.readframes(wf.getnframes())
        
        pcm16 = np.frombuffer(data, dtype=np.int16)
        
        # 应用唐老鸭变声
        pcm16_bytes = apply_donald_duck_effect(pcm16.tobytes(), STREAM_SR, cartoon_states)
        
        # 广播
        await broadcast_pcm16_realtime(pcm16_bytes)
        
    finally:
        # 清理临时文件
        try:
            if wav_path.exists():
                wav_path.unlink()
        except Exception:
            pass


async def _speak_stream_to_broadcast(
    text_stream,
    voice: str,
    instruction: Optional[str],
    txt_buf: List[str],
    cartoon_states: dict,
):
    """流式TTS：边生成文本边TTS并广播"""
    from dashscope.audio.tts_v2 import AudioFormat, SpeechSynthesizer, ResultCallback
    import queue
    import threading
    
    # 创建队列用于接收音频数据
    audio_queue: queue.Queue[Optional[bytes]] = queue.Queue()
    tts_done = threading.Event()
    tts_error = [None]
    
    class StreamCallback(ResultCallback):
        def on_data(self, data: bytes):
            if data:
                audio_queue.put(data)
        
        def on_complete(self):
            audio_queue.put(None)
            tts_done.set()
        
        def on_error(self, msg):
            tts_error[0] = str(msg)
            audio_queue.put(None)
            tts_done.set()
    
    callback = StreamCallback()
    
    # 直接使用instruction参数（与旧代码保持一致）
    tts = SpeechSynthesizer(
        model=tts_engine.tts_model,
        voice=voice,
        format=AudioFormat.PCM_16000HZ_MONO_16BIT,
        instruction=instruction,
        callback=callback,
    )
    
    # 文本分块策略（优化首次延迟）
    MIN_CHARS = 12       # 降低首次发送门槛，更快开始TTS
    MAX_CHARS = 60       # 降低上限，更频繁发送
    MAX_WAIT = 0.5       # 降低等待时间
    PUNCT = set("。！？!?；;\n，,：:")
    
    buf = ""
    last_send = time.time()
    
    def flush_text():
        nonlocal buf, last_send
        if not buf:
            return
        from robotduck_voice_assistant.cosyvoice import _normalize_for_tts, _strip_emojis_for_tts
        to_send = _normalize_for_tts(_strip_emojis_for_tts(buf))
        if to_send:
            tts.streaming_call(to_send)
            buf = ""
            last_send = time.time()
    
    # 启动音频处理协程
    async def process_audio():
        while True:
            try:
                # 非阻塞获取音频数据
                try:
                    audio_data = audio_queue.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.01)
                    continue
                
                if audio_data is None:
                    break
                
                # 应用唐老鸭变声
                pcm16_bytes = apply_donald_duck_effect(audio_data, STREAM_SR, cartoon_states)
                
                # 广播
                if pcm16_bytes:
                    await broadcast_pcm16_realtime(pcm16_bytes)
                    
            except Exception as e:
                print(f"[AI] 音频处理错误: {e}", flush=True)
                break
    
    audio_task = asyncio.create_task(process_audio())
    
    try:
        # 处理文本流
        for delta in text_stream:
            txt_buf.append(delta)
            full_text = "".join(txt_buf)
            
            # UI更新
            try:
                await ui_broadcast_partial("[AI] " + full_text)
            except Exception:
                pass
            
            buf += delta
            now = time.time()
            
            # 分块发送逻辑
            if len(buf) >= MAX_CHARS:
                flush_text()
                await asyncio.sleep(0)  # 让出事件循环，让 audio_task 有机会执行
                continue
            
            if len(buf) >= MIN_CHARS and any(ch in PUNCT for ch in delta):
                flush_text()
                await asyncio.sleep(0)  # 让出事件循环
                continue
            
            if len(buf) >= MIN_CHARS and (now - last_send) >= MAX_WAIT:
                flush_text()
                await asyncio.sleep(0)  # 让出事件循环
                continue
            
            if (now - last_send) >= 6.0 and len(buf) > 0:
                flush_text()
            
            # 让出事件循环，让 audio_task 有机会处理音频
            await asyncio.sleep(0)

        # 收尾
        if buf.strip():
            flush_text()
        
        # 完成流式合成
        tts.streaming_complete()
        
        # 等待TTS完成
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: tts_done.wait(timeout=30.0))
        
        # 等待音频队列处理完毕
        while not audio_queue.empty():
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.2)  # 等待最后一段音频广播完
        
        if tts_error[0]:
            raise RuntimeError(tts_error[0])
            
    finally:
        audio_task.cancel()
        try:
            await audio_task
        except asyncio.CancelledError:
            pass

# ---------- 页面 / 健康 ----------
@app.get("/", response_class=HTMLResponse)
def root():
    with open(os.path.join("templates", "index.html"), "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.get("/api/health", response_class=PlainTextResponse)
def health():
    return "OK"

# 注册 /stream.wav
register_stream_route(app)

# ---------- WebSocket：WebUI 文本（ASR/AI 状态推送 + 表情控制） ----------
@app.websocket("/ws_ui")
async def ws_ui(ws: WebSocket):
    await ws.accept()
    ui_clients[id(ws)] = ws
    try:
        init = {"partial": current_partial, "finals": recent_finals[-10:]}
        await ws.send_text("INIT:" + json.dumps(init, ensure_ascii=False))
        while True:
            # 接收前端发来的命令（表情控制等）
            try:
                msg = await asyncio.wait_for(ws.receive_text(), timeout=60)
                # 处理表情命令：EXPR:xxx
                # 直接转发到 ESP32，由 ESP32 执行表情动画
                if msg.startswith("EXPR:"):
                    expr_name = msg[5:].strip().lower()
                    print(f"[UI] 收到表情命令: {expr_name}", flush=True)
                    
                    # 发送指令到 ESP32（LED颜色 + 表情动画）
                    if esp32_audio_ws and (esp32_audio_ws.client_state == WebSocketState.CONNECTED):
                        await esp32_audio_ws.send_text(f"EMO:{expr_name}")
                        await esp32_audio_ws.send_text(f"EXPR:{expr_name}")
                        print(f"[UI] 已发送 EMO+EXPR 指令到 ESP32: {expr_name}", flush=True)
                    else:
                        print("[UI] ESP32 未连接，无法发送表情命令", flush=True)
            except asyncio.TimeoutError:
                # 超时继续循环
                continue
    except WebSocketDisconnect:
        pass
    finally:
        ui_clients.pop(id(ws), None)

# ---------- WebSocket：ESP32 音频入口（ASR 上行） ----------
@app.websocket("/ws_audio")
async def ws_audio(ws: WebSocket):
    global esp32_audio_ws
    esp32_audio_ws = ws
    await ws.accept()
    print("\n[AUDIO] client connected")
    
    # ESP32 连接后自动开始执行 idle 动画（无需发送指令）
    # idle 动画在 ESP32 端自动执行
    print("[AUDIO] ESP32 已连接，idle 动画自动执行", flush=True)
    
    recognition = None
    streaming = False
    last_ts = time.monotonic()
    keepalive_task: Optional[asyncio.Task] = None

    async def stop_rec(send_notice: Optional[str] = None):
        nonlocal recognition, streaming, keepalive_task
        if keepalive_task and not keepalive_task.done():
            keepalive_task.cancel()
            try:
                await keepalive_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        keepalive_task = None
        if recognition:
            try: recognition.stop()
            except Exception: pass
            recognition = None
        await set_current_recognition(None)
        streaming = False
        if send_notice:
            try: await ws.send_text(send_notice)
            except Exception: pass

    async def on_sdk_error(_msg: str):
        await stop_rec(send_notice="RESTART")

    async def keepalive_loop():
        nonlocal last_ts, recognition, streaming
        try:
            while streaming and recognition is not None:
                idle = time.monotonic() - last_ts
                if idle > 0.35:
                    try:
                        for _ in range(30):  # ~600ms 静音
                            recognition.send_audio_frame(SILENCE_20MS)
                        last_ts = time.monotonic()
                    except Exception:
                        await on_sdk_error("keepalive send failed")
                        return
                await asyncio.sleep(0.10)
        except asyncio.CancelledError:
            return

    try:
        while True:
            if WebSocketState and ws.client_state != WebSocketState.CONNECTED:
                break
            try:
                msg = await ws.receive()
            except WebSocketDisconnect:
                break
            except RuntimeError as e:
                if "Cannot call \"receive\"" in str(e):
                    break
                raise

            if "text" in msg and msg["text"] is not None:
                raw = (msg["text"] or "").strip()
                cmd = raw.upper()

                if cmd == "START":
                    print("[AUDIO] START received")
                    await stop_rec()
                    
                    if not asr_engine:
                        print("[AUDIO] 错误：ASR引擎未初始化", flush=True)
                        await ws.send_text("ERR:ASR_NOT_INIT")
                        continue
                    
                    # 清空UI状态，防止旧识别结果残留导致自问自答
                    await ui_broadcast_partial("")
                    global current_partial
                    current_partial = ""
                    
                    # 短暂延迟（ESP32端已有500ms麦克风启用延迟）
                    await asyncio.sleep(0.3)
                    print("[AUDIO] UI状态已清空，准备启动全新的ASR会话", flush=True)
                    
                    # 冷却期状态（防止识别到AI残留音频）
                    session_start_time = time.time()
                    cooldown_seconds = 3.0
                    last_final_text = ""
                    
                    # 保存主事件循环引用（用于在回调线程中安全提交任务）
                    main_loop = asyncio.get_running_loop()
                    
                    # ASR回调函数（在后台线程中执行，需要用run_coroutine_threadsafe提交到主循环）
                    def on_partial_sync(text: str):
                        """同步包装的partial回调（在后台线程中执行）"""
                        async def _on_partial(text: str):
                            # 检查冷却期
                            if time.time() - session_start_time < cooldown_seconds:
                                return
                            
                            # AI播放时忽略
                            if is_playing_now():
                                return
                            
                            # UI更新
                            global current_partial
                            current_partial = text
                            await ui_broadcast_partial(text)
                        
                        # 使用run_coroutine_threadsafe安全地将任务提交到主事件循环
                        try:
                            asyncio.run_coroutine_threadsafe(_on_partial(text), main_loop)
                        except Exception as e:
                            print(f"[ASR] on_partial error: {e}", flush=True)
                    
                    def on_final_sync(text: str):
                        """同步包装的final回调（在后台线程中执行）"""
                        async def _on_final(text: str):
                            nonlocal last_final_text
                            
                            # 检查冷却期
                            if time.time() - session_start_time < cooldown_seconds:
                                print(f"[ASR] 冷却期内，忽略: {text}", flush=True)
                                return
                            
                            # AI播放时忽略
                            if is_playing_now():
                                print(f"[ASR] AI播放中，忽略: {text}", flush=True)
                                return
                            
                            # 避免重复处理
                            if text == last_final_text:
                                return
                            last_final_text = text
                            
                            if not text or not text.strip():
                                return
                            
                            # 热词检查（停下/别说了等）
                            text_lower = text.strip().lower()
                            hotwords = {"停下", "别说了", "停止"}
                            if any(hw in text_lower for hw in hotwords):
                                print(f"[ASR] 热词触发，全系统重置: {text}", flush=True)
                                await full_system_reset("Hotword interrupt")
                                return
                            
                            # 显示final结果
                            await ui_broadcast_final(text)
                            print(f"[ASR FINAL] {text}", flush=True)
                            
                            # 启动AI回复
                            async with interrupt_lock:
                                await start_ai_with_text(text)
                        
                        # 使用run_coroutine_threadsafe安全地将任务提交到主事件循环
                        try:
                            asyncio.run_coroutine_threadsafe(_on_final(text), main_loop)
                        except Exception as e:
                            print(f"[ASR] on_final error: {e}", flush=True)
                    
                    # 启动新ASR引擎
                    recognition = asr_engine.start(
                        on_partial=on_partial_sync,
                        on_final=on_final_sync,
                    )
                    await set_current_recognition(recognition)
                    streaming = True
                    last_ts = time.monotonic()
                    keepalive_task = asyncio.create_task(keepalive_loop())
                    await ui_broadcast_partial("（已开始接收音频…）")
                    await ws.send_text("OK:STARTED")

                elif cmd == "STOP":
                    if recognition:
                        for _ in range(15):  # ~300ms 静音
                            try: recognition.send_audio_frame(SILENCE_20MS)
                            except Exception: break
                    await stop_rec(send_notice="OK:STOPPED")

                elif raw.startswith("PROMPT:"):
                    # 设备端主动发起一轮：同样使用"先硬重置后播放"的强语义
                    text = raw[len("PROMPT:"):].strip()
                    if text:
                        async with interrupt_lock:
                            await start_ai_with_text(text)
                        await ws.send_text("OK:PROMPT_ACCEPTED")
                    else:
                        await ws.send_text("ERR:EMPTY_PROMPT")

            elif "bytes" in msg and msg["bytes"] is not None:
                audio_bytes = msg["bytes"]
                
                # ★ 音色克隆模式：收集音频到缓冲区
                if clone_recording:
                    clone_audio_buffer.append(audio_bytes)
                    elapsed = time.time() - clone_start_time
                    # 每秒打印一次进度
                    if int(elapsed) > int(elapsed - 0.1):
                        print(f"[CLONE] 录音中... {elapsed:.1f}s / {clone_duration}s", flush=True)
                    # 达到指定时长，触发完成事件
                    if elapsed >= clone_duration:
                        if clone_event:
                            clone_event.set()
                    continue  # 克隆模式下不进行 ASR
                
                # 双保险：如果当前正在播放 AI 语音，就直接丢弃上行音频
                if is_playing_now():
                    # 这里不打印日志，避免过于频繁；调试时可以打开
                    # print("[AUDIO] drop frame because AI is speaking", flush=True)
                    continue

                # ★ 元音识别已移到 ESP32 本地（零延迟）
                # Python 端不再发送 MOUTH 命令

                if streaming and recognition:
                    try:
                        # 使用新ASR引擎发送音频帧
                        asr_engine.send_audio_frame(audio_bytes)
                        last_ts = time.monotonic()
                    except Exception:
                        await on_sdk_error("send_audio_frame failed")

    except Exception as e:
        print(f"\n[WS ERROR] {e}")
    finally:
        await stop_rec()
        try:
            if WebSocketState is None or ws.client_state == WebSocketState.CONNECTED:
                await ws.close(code=1000)
        except Exception:
            pass
        if esp32_audio_ws is ws:
            esp32_audio_ws = None
        print("[WS] connection closed")

# ---------- WebSocket：ESP32 相机入口（JPEG 二进制） ----------
@app.websocket("/ws/camera")
async def ws_camera_esp(ws: WebSocket):
    global esp32_camera_ws
    if esp32_camera_ws is not None:
        await ws.close(code=1013)  # Try again later
        return
    esp32_camera_ws = ws
    await ws.accept()
    print("[CAMERA] ESP32 connected")
    try:
        while True:
            msg = await ws.receive()
            # 已移除高清抓拍相关的文本命令处理 (SNAP:BEGIN, SNAP:END)
            # 直接处理所有接收到的图像帧
            
            if "bytes" in msg and msg["bytes"] is not None:
                data = msg["bytes"]
                # 保存到最近帧缓存，供AI视觉交互使用
                try:
                    last_frames.append((time.time(), data))
                except Exception:
                    pass
                
                # 人脸追踪：检测人脸并控制眼球跟随
                try:
                    await process_face_tracking(data, esp32_audio_ws)
                except Exception:
                    pass
                
                # 直接广播原始画面给前端
                if camera_viewers:
                    async def _broadcast_raw():
                        try:
                            # 直接转发原始JPEG
                            jpeg_data = data
                            dead = []
                            for viewer_ws in list(camera_viewers):
                                try:
                                    await viewer_ws.send_bytes(jpeg_data)
                                except Exception:
                                    dead.append(viewer_ws)
                            for ws in dead:
                                camera_viewers.discard(ws)
                        except Exception as e:
                            print(f"[CAMERA] Broadcast error: {e}")
                    
                    await _broadcast_raw()

            elif "type" in msg and msg["type"] in ("websocket.close", "websocket.disconnect"):
                break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[CAMERA ERROR] {e}")
    finally:
        try:
            if WebSocketState is None or ws.client_state == WebSocketState.CONNECTED:
                await ws.close(code=1000)
        except Exception:
            pass
        esp32_camera_ws = None
        print("[CAMERA] ESP32 disconnected")

# ---------- 抓拍：保存 JPEG 到 photo/ 目录 ----------
def _save_photo_bytes(jpeg_bytes: bytes) -> str:
    base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "photo")
    try:
        os.makedirs(base_dir, exist_ok=True)
    except Exception:
        pass
    ts = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    ms = int((time.time() - int(time.time())) * 1000)
    fname = os.path.join(base_dir, f"{ts}_{ms:03d}.jpg")
    with open(fname, "wb") as f:
        f.write(jpeg_bytes)
    print(f"[PHOTO] saved: {fname} ({len(jpeg_bytes)} bytes)", flush=True)
    return fname

# ---------- 抓拍：向 ESP32 请求一张高清图 ---------- (已移除：直接使用视频流帧，避免卡顿)
# async def request_hq_snapshot(timeout: float = 1.8) -> Optional[bytes]:
#     """已废弃：不再使用高清抓拍，直接从last_frames获取视频流中的一帧"""
#     pass

# ---------- WebSocket：浏览器订阅相机帧 ----------
@app.websocket("/ws/viewer")
async def ws_viewer(ws: WebSocket):
    await ws.accept()
    camera_viewers.add(ws)
    print(f"[VIEWER] Browser connected. Total viewers: {len(camera_viewers)}", flush=True)
    try:
        while True:
            # 保持连接活跃
            await asyncio.sleep(60)
    except WebSocketDisconnect:
        print("[VIEWER] Browser disconnected", flush=True)
    finally:
        try: 
            camera_viewers.remove(ws)
        except Exception: 
            pass
        print(f"[VIEWER] Removed. Total viewers: {len(camera_viewers)}", flush=True)

# ---------- WebSocket：浏览器订阅 IMU ---------- (已移除：ESP32不再使用UDP发送IMU数据)
# @app.websocket("/ws")
# async def ws_imu(ws: WebSocket):
#     await ws.accept()
#     ...

# async def imu_broadcast(msg: str):
#     pass

# ---------- 服务端 IMU 估计 ---------- (已移除：ESP32不再使用UDP发送IMU数据)
# 所有IMU相关的处理逻辑已移除，包括：
# - IMU数据处理函数 (process_imu_and_maybe_store)
# - UDP协议类 (UDPProto)
# - IMU WebSocket端点 (/ws)
# 原因：ESP32代码中已移除IMU功能，不再通过UDP发送IMU数据




# 检测模型初始化
@app.on_event("startup")
async def on_startup_init_detectors():
    """启动时初始化检测模型和语音系统"""
    # 初始化新语音系统
    print("[STARTUP] 正在初始化新语音系统...", flush=True)
    try:
        init_voice_system()
        print("[STARTUP] 新语音系统初始化成功", flush=True)
    except Exception as e:
        print(f"[STARTUP] 新语音系统初始化失败: {e}", flush=True)
        import traceback
        traceback.print_exc()
    
    # YOLO 人脸检测
    print("[STARTUP] 正在初始化 YOLO 人脸检测模型...", flush=True)
    if init_yolo_face_detector():
        print("[STARTUP] YOLO 人脸检测模型初始化成功", flush=True)
    else:
        print("[STARTUP] YOLO 人脸检测模型初始化失败，将在首次检测时重试", flush=True)
    
    # MediaPipe 手部检测
    if HAND_TRACK_ENABLED:
        print("[STARTUP] 正在初始化 MediaPipe 手部检测模型...", flush=True)
        if init_hand_detector():
            print("[STARTUP] MediaPipe 手部检测模型初始化成功", flush=True)
        else:
            print("[STARTUP] MediaPipe 手部检测模型初始化失败，将在首次检测时重试", flush=True)

@app.on_event("shutdown")
async def on_shutdown():
    """应用关闭时的清理工作"""
    print("[SHUTDOWN] 开始清理资源...")
    
    # 停止音频和AI任务
    await hard_reset_audio("shutdown")
    
    print("[SHUTDOWN] 资源清理完成")


# --- 导出接口（可选） ---
def get_last_frames():
    return last_frames

def get_camera_ws():
    return esp32_camera_ws

def get_latest_esp32_frame() -> Optional[bytes]:
    """
    获取最新的 ESP32 摄像头帧 (JPEG bytes)。
    用于视觉问答功能。
    返回 None 如果没有可用帧。
    """
    if not last_frames:
        return None
    # 返回最新的帧（最后一个元素）
    try:
        _, jpeg_bytes = last_frames[-1]
        return jpeg_bytes
    except (IndexError, ValueError):
        return None

if __name__ == "__main__":
    uvicorn.run(
        app, host="0.0.0.0", port=8081,
        log_level="warning", access_log=False,
        loop="asyncio", workers=1, reload=False
    )

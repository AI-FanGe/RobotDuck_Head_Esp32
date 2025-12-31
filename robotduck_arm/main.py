# robotduck_arm/main.py
# -*- coding: utf-8 -*-
"""
机器鸭手臂控制主程序 - 集成语音和表情控制
- HAND 模式：检测到手靠近时躲避，同时播放生气/无语的语音和表情
- 语音通过 ESP32 播放（/stream.wav），嘴型自动同步
- 表情通过 WebSocket 发送 EXPR:xxx 命令到 ESP32

所有服务都在 8081 端口：
- /ws/camera - ESP32 相机上传
- /ws_audio - ESP32 音频命令通道（表情控制）
- /stream.wav - ESP32 获取 TTS 音频
"""
from __future__ import annotations

import os
import sys
import asyncio
import threading
import time
import random
import queue
from typing import Optional, List, Set
from dataclasses import dataclass

import cv2
import numpy as np
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import StreamingResponse
from starlette.websockets import WebSocketState

# 添加父目录到路径以导入公共模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from vision import VisionSystem
from control import Esp32Transport, InteractionController

# ==================== 环境配置 ====================
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

API_KEY = os.getenv("DASHSCOPE_API_KEY", "sk-3a6b1a3bd7124023a7ac7699d49c2caf")
if not API_KEY:
    raise RuntimeError("未设置 DASHSCOPE_API_KEY")

# TTS 配置
# cosyvoice-v3-plus + longanhuan（标准组合）
# 或 cosyvoice-v3-flash + longxiaochun_emo（情感组合，需要 instruction）
TTS_MODEL = os.getenv("TTS_MODEL", "cosyvoice-v3-plus").strip()
DEFAULT_VOICE = os.getenv("DEFAULT_VOICE", "longanhuan").strip()
SAMPLE_RATE = 16000

# 服务端口（ESP32 连接的端口）
SERVER_PORT = 8081

# ==================== 躲避时的语音短语 ====================
DODGE_PHRASES_ANGRY = [
    "你能不能不要摸我啊！",
    "别碰我！烦死了！",
    "走开啦，别摸！",
    "你干嘛一直摸我！",
    "讨厌！不要碰！",
    "再摸我就生气了！",
    "你手这么脏还敢摸我？",
    "够了够了，别摸了！",
]

DODGE_PHRASES_SPEECHLESS = [
    "无语，又来？",
    "呃，你能不能换个爱好？",
    "我真的服了你了",
    "你怎么老是这样啊",
    "我都躲成这样了你还摸？",
    "你是有多无聊啊",
    "我好累，能不能让我休息一下",
    "哎，你开心就好吧",
]

# 对应的表情
DODGE_EXPRESSIONS = ["angry", "speechless"]

# ==================== 音频流管理 ====================
STREAM_SR = 16000
STREAM_CH = 1
STREAM_SW = 2
STREAM_TICK_MS = 10
BYTES_PER_TICK = STREAM_SR * STREAM_SW * STREAM_TICK_MS // 1000

@dataclass(frozen=True)
class StreamClient:
    q: asyncio.Queue
    abort_event: asyncio.Event

stream_clients: Set[StreamClient] = set()
STREAM_QUEUE_MAX = 32

def _wav_header_unknown_size(sr=16000, ch=1, sw=2) -> bytes:
    import struct
    byte_rate = sr * ch * sw
    block_align = ch * sw
    data_size = 0x7FFFFFF0
    riff_size = 36 + data_size
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", riff_size, b"WAVE",
        b"fmt ", 16,
        1, ch, sr, byte_rate, block_align, sw * 8,
        b"data", data_size
    )

# ==================== 相机帧管理 ====================
class FrameHub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frame: Optional[np.ndarray] = None
        self._last_jpeg_len = 0
        self._last_ts = 0.0

    def update_from_jpeg(self, jpeg_bytes: bytes) -> None:
        arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return
        with self._lock:
            self._frame = img
            self._last_jpeg_len = len(jpeg_bytes)
            self._last_ts = time.time()

    def get(self) -> Optional[np.ndarray]:
        with self._lock:
            if self._frame is None:
                return None
            return self._frame.copy()

    def stats(self) -> tuple:
        with self._lock:
            return self._last_jpeg_len, self._last_ts


# 全局帧管理器
frame_hub = FrameHub()

# ==================== TTS 引擎 ====================
class SimpleTTSEngine:
    """简化的 TTS 引擎，用于生成躲避语音"""
    
    def __init__(self, api_key: str, tts_model: str, default_voice: str):
        import dashscope
        dashscope.api_key = api_key
        self.tts_model = tts_model
        self.default_voice = default_voice
        self._is_speaking = False
        self._lock = threading.Lock()
    
    def is_speaking(self) -> bool:
        with self._lock:
            return self._is_speaking
    
    def generate_and_broadcast(self, text: str, expression: str, esp32_ws: Optional[WebSocket], loop: asyncio.AbstractEventLoop):
        """
        生成语音并广播到 ESP32
        在后台线程中运行
        """
        from dashscope.audio.tts_v2 import AudioFormat, SpeechSynthesizer, ResultCallback
        
        with self._lock:
            if self._is_speaking:
                return
            self._is_speaking = True
        
        audio_chunks: List[bytes] = []
        done_event = threading.Event()
        error_msg = [None]
        
        class Callback(ResultCallback):
            def on_data(self, data: bytes):
                if data:
                    audio_chunks.append(data)
            
            def on_complete(self):
                done_event.set()
            
            def on_error(self, msg):
                error_msg[0] = str(msg)
                done_event.set()
        
        try:
            # 发送表情命令到 ESP32
            if esp32_ws:
                try:
                    asyncio.run_coroutine_threadsafe(
                        esp32_ws.send_text(f"EXPR:{expression}"),
                        loop
                    ).result(timeout=1.0)
                    print(f"[TTS] 发送表情: {expression}")
                except Exception as e:
                    print(f"[TTS] 发送表情失败: {e}")
            
            # 生成语音
            callback = Callback()
            tts = SpeechSynthesizer(
                model=self.tts_model,
                voice=self.default_voice,
                format=AudioFormat.PCM_16000HZ_MONO_16BIT,
                callback=callback,
            )
            
            # 一次性生成
            tts.call(text)
            done_event.wait(timeout=30.0)
            
            if error_msg[0]:
                print(f"[TTS] 错误: {error_msg[0]}")
                return
            
            # 合并所有音频块
            if audio_chunks:
                all_audio = b''.join(audio_chunks)
                print(f"[TTS] 生成音频: {len(all_audio)} 字节, 文本: {text}")
                
                # 广播音频
                asyncio.run_coroutine_threadsafe(
                    broadcast_pcm16_realtime(all_audio),
                    loop
                ).result(timeout=60.0)
                
                print(f"[TTS] 音频播放完成")
            
        except Exception as e:
            print(f"[TTS] 生成语音失败: {e}")
            import traceback
            traceback.print_exc()
        finally:
            with self._lock:
                self._is_speaking = False
            
            # 播放完成后恢复 idle 表情
            if esp32_ws:
                try:
                    asyncio.run_coroutine_threadsafe(
                        esp32_ws.send_text("EXPR:idle"),
                        loop
                    ).result(timeout=1.0)
                except Exception:
                    pass


async def broadcast_pcm16_realtime(pcm16: bytes):
    """将 PCM16 音频以 10ms 节拍发送给所有连接的客户端"""
    loop = asyncio.get_event_loop()
    next_tick = loop.time()
    off = 0
    tick_sec = STREAM_TICK_MS / 1000.0
    
    while off < len(pcm16):
        take = min(BYTES_PER_TICK, len(pcm16) - off)
        piece = pcm16[off:off + take]

        dead: List[StreamClient] = []
        for sc in list(stream_clients):
            if sc.abort_event.is_set():
                dead.append(sc)
                continue
            try:
                if sc.q.full():
                    try:
                        sc.q.get_nowait()
                    except Exception:
                        pass
                sc.q.put_nowait(piece)
            except Exception:
                dead.append(sc)
        for sc in dead:
            try:
                stream_clients.discard(sc)
            except Exception:
                pass

        next_tick += tick_sec
        now = loop.time()
        if now < next_tick:
            await asyncio.sleep(next_tick - now)
        else:
            next_tick = now
        off += take


# ==================== FastAPI 应用 ====================
app = FastAPI()

# ESP32 音频 WebSocket 连接（全局引用）
esp32_audio_ws: Optional[WebSocket] = None


# 静音心跳包（100ms 静音，防止 ESP32 超时断开）
SILENCE_HEARTBEAT = b'\x00' * (STREAM_SR * STREAM_SW * 100 // 1000)  # 100ms 静音

@app.get("/stream.wav")
async def stream_wav(_: Request):
    """ESP32 从这里获取 TTS 音频流"""
    # 强制单连接
    for sc in list(stream_clients):
        try:
            sc.abort_event.set()
        except Exception:
            pass
    stream_clients.clear()

    q: asyncio.Queue = asyncio.Queue(maxsize=STREAM_QUEUE_MAX)
    abort_event = asyncio.Event()
    sc = StreamClient(q=q, abort_event=abort_event)
    stream_clients.add(sc)
    
    print("[STREAM] ESP32 音频客户端已连接")

    async def gen():
        yield _wav_header_unknown_size(STREAM_SR, STREAM_CH, STREAM_SW)
        try:
            while True:
                if abort_event.is_set():
                    break
                try:
                    # 等待音频数据，超时 500ms
                    chunk = await asyncio.wait_for(q.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    # 超时时发送静音心跳包，防止 ESP32 断开连接
                    yield SILENCE_HEARTBEAT
                    continue
                if abort_event.is_set():
                    break
                if chunk is None:
                    break
                if chunk:
                    yield chunk
        finally:
            stream_clients.discard(sc)
            print("[STREAM] ESP32 音频客户端已断开")

    return StreamingResponse(gen(), media_type="audio/wav")


@app.websocket("/ws_audio")
async def ws_audio(ws: WebSocket):
    """ESP32 音频 WebSocket 连接（用于发送表情命令）"""
    global esp32_audio_ws
    esp32_audio_ws = ws
    await ws.accept()
    print("[WS_AUDIO] ESP32 已连接")
    
    try:
        while True:
            try:
                msg = await ws.receive()
                if "text" in msg and msg["text"]:
                    text = msg["text"].strip()
                    print(f"[WS_AUDIO] 收到: {text}")
                elif "bytes" in msg and msg["bytes"]:
                    # 忽略音频数据（本程序不需要 ASR）
                    pass
            except WebSocketDisconnect:
                break
            except Exception as e:
                print(f"[WS_AUDIO] 错误: {e}")
                break
    finally:
        if esp32_audio_ws is ws:
            esp32_audio_ws = None
        print("[WS_AUDIO] ESP32 已断开")


@app.websocket("/ws/camera")
async def ws_camera(ws: WebSocket):
    """ESP32 相机 WebSocket 连接"""
    await ws.accept()
    print("[WS_CAMERA] ESP32 相机已连接")
    
    try:
        while True:
            try:
                msg = await ws.receive()
                if "bytes" in msg and msg["bytes"]:
                    frame_hub.update_from_jpeg(msg["bytes"])
            except WebSocketDisconnect:
                break
            except Exception as e:
                print(f"[WS_CAMERA] 错误: {e}")
                break
    finally:
        print("[WS_CAMERA] ESP32 相机已断开")


@app.get("/health")
def health():
    return {"status": "ok"}


# ==================== 躲避语音控制器 ====================
class DodgeVoiceController:
    """控制躲避时的语音播放"""
    
    def __init__(self, tts_engine: SimpleTTSEngine):
        self.tts = tts_engine
        self.last_speak_time = 0.0
        self.speak_cooldown = 3.0  # 说话冷却时间（秒）
        self._speak_thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
    
    def set_event_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
    
    def try_speak_dodge(self) -> bool:
        """
        尝试播放躲避语音
        返回 True 如果开始播放，False 如果在冷却中或正在说话
        """
        global esp32_audio_ws
        
        now = time.time()
        
        # 检查冷却时间
        if now - self.last_speak_time < self.speak_cooldown:
            return False
        
        # 检查是否正在说话
        if self.tts.is_speaking():
            return False
        
        # 检查是否有音频客户端连接
        if len(stream_clients) == 0:
            print("[DODGE] 没有音频客户端连接，跳过语音")
            return False
        
        # 随机选择表情和短语
        expression = random.choice(DODGE_EXPRESSIONS)
        if expression == "angry":
            phrase = random.choice(DODGE_PHRASES_ANGRY)
        else:
            phrase = random.choice(DODGE_PHRASES_SPEECHLESS)
        
        print(f"[DODGE] 触发语音: {phrase} (表情: {expression})")
        
        self.last_speak_time = now
        
        # 在后台线程中生成并播放语音
        if self._loop:
            self._speak_thread = threading.Thread(
                target=self.tts.generate_and_broadcast,
                args=(phrase, expression, esp32_audio_ws, self._loop),
                daemon=True
            )
            self._speak_thread.start()
            return True
        
        return False


# ==================== HUD 绘制 ====================
def draw_hud(frame: np.ndarray, text: str, y: int) -> None:
    cv2.putText(frame, text, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)


# ==================== FastAPI 服务器线程 ====================
server_loop: Optional[asyncio.AbstractEventLoop] = None

def start_fastapi_server():
    """启动 FastAPI 服务器"""
    global server_loop
    
    # 创建新的事件循环
    server_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(server_loop)
    
    # 配置 uvicorn
    config_obj = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=SERVER_PORT,
        log_level="warning",
        access_log=False,
        loop="asyncio",
    )
    server = uvicorn.Server(config_obj)
    
    print(f"[SERVER] FastAPI 服务器启动在 0.0.0.0:{SERVER_PORT}")
    print(f"[SERVER] ESP32 需要连接:")
    print(f"  - ws://[IP]:{SERVER_PORT}/ws/camera - 相机上传")
    print(f"  - ws://[IP]:{SERVER_PORT}/ws_audio - 表情命令")
    print(f"  - http://[IP]:{SERVER_PORT}/stream.wav - 音频流")
    
    server_loop.run_until_complete(server.serve())


def start_server_thread() -> threading.Thread:
    """在后台线程中启动服务器"""
    t = threading.Thread(target=start_fastapi_server, daemon=True)
    t.start()
    # 等待服务器启动
    time.sleep(1.0)
    return t


# ==================== 主函数 ====================
def main():
    global server_loop
    
    # 启动 FastAPI 服务器（在后台线程）
    start_server_thread()
    
    # 等待事件循环准备好
    while server_loop is None:
        time.sleep(0.1)
    
    # 初始化 TTS 引擎
    tts_engine = SimpleTTSEngine(API_KEY, TTS_MODEL, DEFAULT_VOICE)
    
    # 初始化躲避语音控制器
    dodge_controller = DodgeVoiceController(tts_engine)
    dodge_controller.set_event_loop(server_loop)
    
    # 初始化视觉和控制系统
    vision = VisionSystem()
    transport = Esp32Transport()
    controller = InteractionController()

    scene_mode = "FACE"
    last_send = 0.0
    send_period = 1.0 / float(config.CONTROL_HZ)
    
    # 躲避状态追踪
    last_dodge_state = "NONE"

    print()
    print("[INFO] 按键说明:")
    print("  f=FACE模式  h=HAND模式  i=IDLE模式")
    print("  b=设置FACE基线  n=设置HAND基线  q=退出")
    print()
    print("[INFO] HAND模式下检测到手靠近会躲避并说话")
    print()

    while True:
        frame = frame_hub.get()
        if frame is None:
            blank = np.zeros((480, 640, 3), dtype=np.uint8)
            draw_hud(blank, "Waiting for ESP32 camera stream...", 30)
            draw_hud(blank, f"Server: 0.0.0.0:{SERVER_PORT}", 60)
            draw_hud(blank, "  /ws/camera  /ws_audio  /stream.wav", 90)
            
            # 显示连接状态
            audio_clients = len(stream_clients)
            ws_status = "Connected" if esp32_audio_ws else "Waiting..."
            draw_hud(blank, f"Audio clients: {audio_clients}  WS: {ws_status}", 120)
            
            cv2.imshow(config.WINDOW_NAME, blank)
            if cv2.waitKey(10) & 0xFF == ord('q'):
                break
            continue

        H, W = frame.shape[:2]

        # 检测
        face = None
        hand = None
        if scene_mode == "FACE":
            face = vision.detect_face(frame)
        elif scene_mode == "HAND":
            hand = vision.detect_hand(frame)

        cmd, dbg = controller.update(scene_mode, face, hand, W, H)

        # 下发舵机命令
        now = time.time()
        if now - last_send >= send_period:
            last_send = now
            ok = transport.send_batch(cmd, speed=config.SERVO_SPEED, acc=config.SERVO_ACC)
            dbg["send_ok"] = ok

        # ========== HAND 模式躲避语音触发 ==========
        if scene_mode == "HAND":
            current_state = dbg.get("hand_state", "NONE")
            
            # 当进入 AVOIDING 或 FLIPPING 状态时触发语音
            if current_state in ("AVOIDING", "FLIPPING") and last_dodge_state not in ("AVOIDING", "FLIPPING"):
                # 触发躲避语音
                dodge_controller.try_speak_dodge()
            
            last_dodge_state = current_state
        else:
            last_dodge_state = "NONE"

        # 可视化
        if config.DRAW_CENTER_CROSS:
            cv2.drawMarker(
                frame,
                (W // 2, H // 2),
                (255, 255, 255),
                markerType=cv2.MARKER_CROSS,
                markerSize=20,
                thickness=1,
            )

        if face is not None:
            vision.draw_target(frame, face, color=(0, 255, 0))
        if hand is not None:
            vision.draw_target(frame, hand, color=(0, 128, 255))

        # HUD
        draw_hud(frame, f"SCENE: {scene_mode}  (f=face, h=hand, i=idle)", 20)
        draw_hud(frame, f"MODE: {dbg.get('mode')}  hand_state={dbg.get('hand_state', '-')}", 45)
        draw_hud(frame, f"Servo p: {dbg.get('p')}", 70)

        if "ex" in dbg:
            draw_hud(
                frame,
                f"Face ex={dbg['ex']:.2f} ey={dbg['ey']:.2f} ea={dbg['ea']:.2f} A0={dbg['face_area0']:.3f}",
                95,
            )
        if "hx" in dbg:
            draw_hud(
                frame,
                f"Hand hx={dbg['hx']:.2f} area={dbg['hand_area']:.3f} A0={dbg.get('hand_area0', 0):.3f} err={dbg['err']:.2f}",
                95,
            )

        jpeg_len, last_ts = frame_hub.stats()
        dt = time.time() - last_ts if last_ts > 0 else 999
        draw_hud(frame, f"WS jpeg={jpeg_len} bytes, last={dt*1000:.0f}ms ago", 120)
        
        # 音频状态
        audio_status = f"Audio: {len(stream_clients)} client(s)"
        if tts_engine.is_speaking():
            audio_status += " [Speaking]"
        ws_status = "ESP32: OK" if esp32_audio_ws else "ESP32: --"
        draw_hud(frame, f"{audio_status}  {ws_status}", 145)
        
        draw_hud(frame, "Keys: f/h/i  b(FACE A0)  n(HAND A0)  q", 170)

        cv2.imshow(config.WINDOW_NAME, frame)

        k = cv2.waitKey(1) & 0xFF
        if k == ord('f'):
            scene_mode = "FACE"
            print("[MODE] FACE tracking enabled.")
        elif k == ord('h'):
            scene_mode = "HAND"
            print("[MODE] HAND interaction enabled.")
            print("       当手靠近时会躲避并说话！")
        elif k == ord('i'):
            scene_mode = "IDLE"
            print("[MODE] IDLE (no control) enabled.")
        elif k == ord('b'):
            if face is not None:
                controller.face_area0 = face.area_ratio
                print(f"[CALIB] Set face_area0 = {controller.face_area0:.4f}")
            else:
                controller.reset_face_area0()
                print("[CALIB] Face not found; cleared face_area0")
        elif k == ord('n'):
            if hand is not None:
                controller.hand_area0 = hand.area_ratio
                print(f"[CALIB] Set hand_area0 = {controller.hand_area0:.4f}")
            else:
                controller.reset_hand_area0()
                print("[CALIB] Hand not found; cleared hand_area0")
        elif k == ord('q'):
            break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

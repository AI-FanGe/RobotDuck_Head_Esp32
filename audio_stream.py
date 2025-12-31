# audio_stream.py
# -*- coding: utf-8 -*-
import asyncio
from dataclasses import dataclass
from typing import Optional, Set, List, Tuple, Any, Dict
from fastapi import Request
from fastapi.responses import StreamingResponse

# ===== 下行 WAV 流基础参数 =====
STREAM_SR = 16000  # 必须与ESP32的TTS_RATE保持一致
STREAM_CH = 1
STREAM_SW = 2

# ★ 优化实时性：10ms 节拍（原来是 20ms）
STREAM_TICK_MS = 10  # 发送节拍间隔（毫秒）
BYTES_PER_TICK = STREAM_SR * STREAM_SW * STREAM_TICK_MS // 1000  # 10ms@16k=320B

# 兼容旧代码
BYTES_PER_20MS_16K = STREAM_SR * STREAM_SW * 20 // 1000  # 16k=640B,12k=480B,8k=320B

# ===== AI 播放任务总闸 =====
current_ai_task: Optional[asyncio.Task] = None

async def cancel_current_ai():
    """取消当前大模型语音任务，并等待其退出。"""
    global current_ai_task
    task = current_ai_task
    current_ai_task = None
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

def is_playing_now() -> bool:
    t = current_ai_task
    return (t is not None) and (not t.done())

# ===== /stream.wav 连接管理 =====
@dataclass(frozen=True)
class StreamClient:
    q: asyncio.Queue
    abort_event: asyncio.Event

stream_clients: "Set[StreamClient]" = set()
# ★ 优化实时性：减小队列缓存（原来是 96）
STREAM_QUEUE_MAX = 32  # 更小的缓冲 = 更低延迟（约 320ms @10ms 节拍）

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

async def hard_reset_audio(reason: str = "", keep_connections: bool = False):
    """
    **一键清场**：取消当前AI任务，可选断开音频连接。
    keep_connections=True 时保留 ESP32 的音频连接（避免开头丢失）。
    """
    # 1) 可选：断开所有正在播放的 HTTP 连接
    if not keep_connections:
        for sc in list(stream_clients):
            try:
                sc.abort_event.set()
            except Exception:
                pass
        stream_clients.clear()

    # 2) 取消当前AI任务
    await cancel_current_ai()

    # 3) 日志
    if reason:
        print(f"[HARD-RESET] {reason}")


async def wait_for_stream_client(timeout: float = 2.0) -> bool:
    """等待至少一个 stream 客户端连接，返回是否成功"""
    import time
    start = time.time()
    while time.time() - start < timeout:
        if len(stream_clients) > 0:
            return True
        await asyncio.sleep(0.05)
    return False


async def send_silence_prebuffer(duration_ms: int = 40):
    """
    发送静音预缓冲，帮助 ESP32 同步。
    ★ 优化实时性：默认减少到 40ms（原来 100ms）
    """
    silence_bytes = BYTES_PER_TICK * (duration_ms // STREAM_TICK_MS)
    if silence_bytes > 0:
        silence = b'\x00' * silence_bytes
        await broadcast_pcm16_realtime(silence)

async def broadcast_pcm16_realtime(pcm16: bytes):
    """
    ★ 优化实时性：以 10ms 节拍（原来 20ms）把 pcm16 发送给所有仍存活的连接。
    队列满丢尾，保持实时。
    """
    loop = asyncio.get_event_loop()
    next_tick = loop.time()
    off = 0
    tick_sec = STREAM_TICK_MS / 1000.0  # 10ms = 0.01s
    
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
                    try: sc.q.get_nowait()
                    except Exception: pass
                sc.q.put_nowait(piece)
            except Exception:
                dead.append(sc)
        for sc in dead:
            try: stream_clients.discard(sc)
            except Exception: pass

        next_tick += tick_sec
        now = loop.time()
        if now < next_tick:
            await asyncio.sleep(next_tick - now)
        else:
            next_tick = now
        off += take

# ===== FastAPI 路由注册器 =====
def register_stream_route(app):
    @app.get("/stream.wav")
    async def stream_wav(_: Request):
        # —— 强制单连接（或少数连接），先拉闸所有旧连接 ——
        for sc in list(stream_clients):
            try: sc.abort_event.set()
            except Exception: pass
        stream_clients.clear()

        q: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=STREAM_QUEUE_MAX)
        abort_event = asyncio.Event()
        sc = StreamClient(q=q, abort_event=abort_event)
        stream_clients.add(sc)

        async def gen():
            yield _wav_header_unknown_size(STREAM_SR, STREAM_CH, STREAM_SW)
            try:
                while True:
                    if abort_event.is_set():
                        break
                    try:
                        chunk = await asyncio.wait_for(q.get(), timeout=0.5)
                    except asyncio.TimeoutError:
                        continue
                    if abort_event.is_set():
                        break
                    if chunk is None:
                        break
                    if chunk:
                        yield chunk
            finally:
                stream_clients.discard(sc)
        return StreamingResponse(gen(), media_type="audio/wav")
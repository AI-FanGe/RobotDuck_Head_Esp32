# audio_player.py
# 处理预录音频文件的播放，通过ESP32扬声器输出

import os
import wave
import asyncio
import threading
import queue
import time
from audio_stream import broadcast_pcm16_realtime
from audio_stream import STREAM_SR

# 音频文件路径
AUDIO_BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "music")

# 音频文件映射
AUDIO_MAP = {
    "检测到物体": os.path.join(AUDIO_BASE_DIR, "音频1.wav"),
    "向上": os.path.join(AUDIO_BASE_DIR, "音频2.wav"),
    "向下": os.path.join(AUDIO_BASE_DIR, "音频3.wav"),
    "向左": os.path.join(AUDIO_BASE_DIR, "音频4.wav"),
    "向右": os.path.join(AUDIO_BASE_DIR, "音频5.wav"),
    "OK": os.path.join(AUDIO_BASE_DIR, "音频6.wav"),
    "向前": os.path.join(AUDIO_BASE_DIR, "音频7.wav"),
    "后退": os.path.join(AUDIO_BASE_DIR, "音频8.wav"),
    "拿到物体": os.path.join(AUDIO_BASE_DIR, "音频9.wav"),
    # 红绿灯音频
    "现在是红灯": os.path.join(AUDIO_BASE_DIR, "红灯.wav"),
    "现在是黄灯": os.path.join(AUDIO_BASE_DIR, "黄灯.wav"),
    "现在是绿灯": os.path.join(AUDIO_BASE_DIR, "绿灯.wav"),
}

# 音频缓存，避免重复读取
_audio_cache = {}

# 音频播放队列和工作线程
_audio_queue = queue.Queue(maxsize=10)
_worker_thread = None
_worker_loop = None
_initialized = False
_last_play_ts = 0.0  # 记录上次播放结束时间，用于决定预热静音长度

def load_wav_file(filepath):
    """加载WAV文件并返回PCM数据"""
    if filepath in _audio_cache:
        return _audio_cache[filepath]
    
    try:
        with wave.open(filepath, 'rb') as wav:
            # 检查音频格式
            channels = wav.getnchannels()
            sampwidth = wav.getsampwidth()
            framerate = wav.getframerate()
            
            if channels != 1:
                print(f"[AUDIO] 警告: {filepath} 不是单声道，将只使用第一个声道")
            if sampwidth != 2:
                print(f"[AUDIO] 警告: {filepath} 不是16位音频")
            if framerate != STREAM_SR:
                print(f"[AUDIO] 警告: {filepath} 采样率不是{STREAM_SR}Hz，是{framerate}Hz")
            
            # 读取所有帧
            frames = wav.readframes(wav.getnframes())
            
            # 如果是立体声，只取左声道
            if channels == 2:
                import audioop
                frames = audioop.tomono(frames, sampwidth, 1, 0)
            
            # 如果采样率不等于当前下行采样率（例如12k），重采样
            if framerate != STREAM_SR:
                import audioop
                frames, _ = audioop.ratecv(frames, sampwidth, 1, framerate, STREAM_SR, None)
            
            _audio_cache[filepath] = frames
            return frames
            
    except Exception as e:
        print(f"[AUDIO] 加载音频文件失败 {filepath}: {e}")
        return None

def preload_all_audio():
    """预加载所有音频文件到内存"""
    print("[AUDIO] 开始预加载音频文件...")
    loaded_count = 0
    for audio_key, filepath in AUDIO_MAP.items():
        if os.path.exists(filepath):
            data = load_wav_file(filepath)
            if data:
                loaded_count += 1
                print(f"[AUDIO] 已加载: {audio_key} ({len(data)} bytes)")
        else:
            print(f"[AUDIO] 文件不存在: {filepath}")
    print(f"[AUDIO] 预加载完成，共加载 {loaded_count} 个音频文件")

def _audio_worker():
    """音频播放工作线程"""
    global _worker_loop
    _worker_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_worker_loop)
    
    async def process_queue():
        while True:
            try:
                audio_data = await asyncio.get_event_loop().run_in_executor(None, _audio_queue.get, True)
                if audio_data is None:
                    break
                await _broadcast_audio_optimized(audio_data)
            except Exception as e:
                print(f"[AUDIO] 工作线程错误: {e}")
    
    _worker_loop.run_until_complete(process_queue())

async def _broadcast_audio_optimized(pcm_data: bytes):
    """优化的音频广播：单次调用由底层按20ms节拍发送，移除重复节拍和Python层sleep"""
    global _last_play_ts
    try:
        now = time.monotonic()
        idle_sec = now - (_last_play_ts or now)
        # 首次或长时间空闲后，预热更长静音；否则小静音
        lead_ms = 160 if idle_sec > 3.0 else 60
        tail_ms = 40

        lead_silence = b'\x00' * (lead_ms * STREAM_SR * 2 // 1000)  # STREAM_SR * 2B
        tail_silence = b'\x00' * (tail_ms * STREAM_SR * 2 // 1000)

        # 单次调用交给底层 pacing（20ms节拍在 broadcast_pcm16_realtime 内部实现）
        await broadcast_pcm16_realtime(lead_silence + pcm_data + tail_silence)

        _last_play_ts = time.monotonic()
    except Exception as e:
        print(f"[AUDIO] 广播音频失败: {e}")

def initialize_audio_system():
    """初始化音频系统"""
    global _initialized, _worker_thread, _last_play_ts
    
    if _initialized:
        return
    
    preload_all_audio()
    
    _worker_thread = threading.Thread(target=_audio_worker, daemon=True)
    _worker_thread.start()
    _initialized = True
    _last_play_ts = 0.0
    print("[AUDIO] 音频系统初始化完成（预加载+工作线程）")

def play_audio_threadsafe(audio_key, clear_queue=False):
    """线程安全的音频播放函数
    
    参数:
        audio_key: 音频键值
        clear_queue: 是否清空播放队列（用于实时性要求高的场景）
    """
    if not _initialized:
        initialize_audio_system()
    
    if audio_key not in AUDIO_MAP:
        print(f"[AUDIO] 未知的音频键: {audio_key}")
        return
    
    filepath = AUDIO_MAP[audio_key]
    pcm_data = _audio_cache.get(filepath)
    if pcm_data is None:
        print(f"[AUDIO] 音频未在缓存中: {audio_key}")
        return
    
    # 如果要求清空队列，先清空所有待播放的音频
    if clear_queue:
        cleared_count = 0
        while not _audio_queue.empty():
            try:
                _audio_queue.get_nowait()
                cleared_count += 1
            except queue.Empty:
                break
        if cleared_count > 0:
            print(f"[AUDIO] 清空了 {cleared_count} 个待播放音频，保持实时性")
    
    try:
        _audio_queue.put_nowait(pcm_data)
    except queue.Full:
        print(f"[AUDIO] 播放队列已满，跳过: {audio_key}")

# 兼容旧接口
play_audio_on_esp32 = play_audio_threadsafe 
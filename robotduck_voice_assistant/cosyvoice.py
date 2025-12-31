from __future__ import annotations

import os
import re
import time
import uuid
import wave
import queue
import threading
from pathlib import Path
from typing import Optional, List, Iterable, Tuple

import numpy as np
import sounddevice as sd

import dashscope
import oss2  # type: ignore
from dashscope.audio.tts_v2 import (
    AudioFormat,
    SpeechSynthesizer,
    VoiceEnrollmentService,
    ResultCallback,
)

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    load_dotenv = None  # type: ignore

_THIS_DIR = Path(__file__).resolve().parent
_ENV_PATH = _THIS_DIR / ".env"
if load_dotenv is not None and _ENV_PATH.exists():
    load_dotenv(dotenv_path=_ENV_PATH, override=True)


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _missing_env(names: List[str]) -> List[str]:
    return [n for n in names if not _env(n)]


def _strip_emojis_for_tts(s: str) -> str:
    # 移除常见 emoji（避免 TTS 读“表情”或出现奇怪停顿）
    # 覆盖大多数非 BMP 字符
    return "".join(ch for ch in s if ord(ch) <= 0xFFFF)


def _normalize_for_tts(s: str) -> str:
    # 去掉部分 markdown 符号（可按需扩展）
    s = s.replace("**", "").replace("`", "")
    s = s.replace("#", "")
    s = re.sub(r"\s+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


class _PCMPlayer:
    """
    16kHz / mono / int16 的实时播放器：
    - 通过队列接收 PCM bytes（int16）
    - RawOutputStream 回调从缓冲区取音频
    - 预缓冲 gating：先攒够 prebuffer 才真正开始出声，减少 underflow 爆音
    - underflow 时做短淡出，减少“咔哒/噼啪”
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        prebuffer_ms: int = 80,
        fade_ms: int = 6,
        blocksize_frames: int = 512,
    ):
        self.sample_rate = sample_rate
        self.prebuffer_bytes = int(sample_rate * (prebuffer_ms / 1000.0) * 2)  # mono int16
        self.fade_samples = max(1, int(sample_rate * (fade_ms / 1000.0)))
        self.blocksize_frames = blocksize_frames

        self.q: "queue.Queue[bytes]" = queue.Queue()
        self.buf = bytearray()

        self._lock = threading.Lock()
        self._queued_bytes = 0

        self._started_audio = False
        self._closed = False
        self._last_sample = 0  # int16

        self.stream: Optional[sd.RawOutputStream] = None

    def start(self) -> None:
        def callback(outdata, frames, time_info, status):
            need = frames * 2  # bytes

            # 把队列数据尽量搬到 buf 里，直到够 need 或队列空
            while len(self.buf) < need:
                try:
                    chunk = self.q.get_nowait()
                except queue.Empty:
                    break
                if chunk:
                    self.buf.extend(chunk)
                    with self._lock:
                        self._queued_bytes -= len(chunk)
                        if self._queued_bytes < 0:
                            self._queued_bytes = 0

            # 预缓冲 gating：没开始出声前，先攒够一定量再输出，避免开头 underflow 咔哒
            if not self._started_audio:
                with self._lock:
                    available = len(self.buf) + self._queued_bytes
                if available < self.prebuffer_bytes:
                    outdata[:] = b"\x00" * need
                    return
                self._started_audio = True

            # 正常取音频
            take = min(need, len(self.buf))
            chunk = bytes(self.buf[:take])
            del self.buf[:take]

            # 不够则填充（underflow）
            if len(chunk) < need:
                pad = need - len(chunk)
                chunk = self._declick_pad(chunk, pad)
            else:
                # 更新 last_sample
                if len(chunk) >= 2:
                    self._last_sample = int(np.frombuffer(chunk[-2:], dtype=np.int16)[0])

            outdata[:] = chunk

        self.stream = sd.RawOutputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            callback=callback,
            blocksize=self.blocksize_frames,
        )
        self.stream.start()

    def _declick_pad(self, chunk: bytes, pad: int) -> bytes:
        """
        underflow 补齐时做淡出，减少“有波形→突然静音”带来的咔哒
        """
        if pad <= 0:
            return chunk

        # 先做一段淡出（从 last_sample 过渡到 0）
        fade_n = min(self.fade_samples, pad // 2)  # pad 是 bytes，sample 是 2 bytes
        out = bytearray(chunk)

        if fade_n > 0:
            start_val = self._last_sample
            # 生成 fade_n 个 sample，从 start_val 线性到 0
            ramp = np.linspace(start_val, 0, fade_n, endpoint=False, dtype=np.float32)
            ramp_i16 = ramp.astype(np.int16).tobytes()
            out.extend(ramp_i16)
            remain = pad - len(ramp_i16)
        else:
            remain = pad

        if remain > 0:
            out.extend(b"\x00" * remain)

        self._last_sample = 0
        return bytes(out)

    def push(self, data: bytes) -> None:
        if self._closed:
            return
        if not data:
            return
        with self._lock:
            self._queued_bytes += len(data)
        self.q.put(data)

    def stop(self) -> None:
        self._closed = True
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None

    def is_drained(self) -> bool:
        # 播放缓冲是否播空（队列空 + buf 空）
        if len(self.buf) > 0:
            return False
        if not self.q.empty():
            return False
        return True


class _TTSStreamCallback(ResultCallback):
    def __init__(self, player: _PCMPlayer):
        self.player = player
        self.done = threading.Event()
        self.err_msg: Optional[str] = None

    def on_open(self) -> None:
        pass

    def on_event(self, message: str) -> None:
        pass

    def on_data(self, data: bytes) -> None:
        # 服务器返回的是 PCM bytes
        self.player.push(data)

    def on_complete(self) -> None:
        self.done.set()

    def on_error(self, message) -> None:
        self.err_msg = str(message)
        self.done.set()

    def on_close(self) -> None:
        pass


class CosyVoiceEngine:
    def __init__(self, api_key: str, tts_model: str, default_voice: str, sample_rate: int = 16000) -> None:
        if not api_key:
            raise RuntimeError("CosyVoice: missing DASHSCOPE_API_KEY")
        dashscope.api_key = api_key

        self.tts_model = tts_model
        self.default_voice = default_voice
        self.sample_rate = sample_rate

    # ---------------------------
    # 非流式（保留，兼容你原来流程）
    # ---------------------------
    def tts_to_wav(self, text: str, voice: str, instruction: Optional[str], out_path: str) -> str:
        """
        固定输出 WAV 16k mono 16bit。
        遇到 instruction 不支持导致 428 时，自动降级 instruction=None 重试一次。
        """
        def _call(instr: Optional[str]) -> tuple[Optional[bytes], Optional[dict], Optional[str]]:
            tts = SpeechSynthesizer(
                model=self.tts_model,
                voice=voice,
                format=AudioFormat.WAV_16000HZ_MONO_16BIT,
                instruction=instr,
            )
            audio_bytes = tts.call(text)
            last = None
            rid = None
            get_resp = getattr(tts, "get_response", None)
            if callable(get_resp):
                last = get_resp()
            get_rid = getattr(tts, "get_last_request_id", None)
            if callable(get_rid):
                rid = get_rid()
            return audio_bytes, last, rid

        audio_bytes, last, rid = _call(instruction)

        if audio_bytes is None:
            err_msg = ""
            if isinstance(last, dict):
                err_msg = str(last.get("header", {}).get("error_message", ""))
            if "428" in err_msg:
                audio_bytes2, last2, rid2 = _call(None)
                if audio_bytes2 is not None:
                    print("[TTS] warning: instruction not supported for this voice, fallback to instruction=None")
                    audio_bytes, last, rid = audio_bytes2, last2, rid2

        if audio_bytes is None:
            raise RuntimeError(
                "TTS failed: SpeechSynthesizer.call() returned None.\n"
                f"- model={self.tts_model}\n"
                f"- voice={voice}\n"
                f"- instruction={instruction}\n"
                f"- request_id={rid}\n"
                f"- last_response={last}\n"
            )

        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(audio_bytes)
        return out_path

    def play_wav(self, wav_path: str) -> None:
        with wave.open(wav_path, "rb") as wf:
            sr = wf.getframerate()
            ch = wf.getnchannels()
            sw = wf.getsampwidth()
            if sw != 2:
                raise RuntimeError(f"Unsupported wav sample width: {sw}")
            data = wf.readframes(wf.getnframes())
        audio = np.frombuffer(data, dtype=np.int16)
        if ch > 1:
            audio = audio.reshape(-1, ch)
        sd.play(audio, sr)
        sd.wait()

    def speak(self, text: str, voice: str, instruction: Optional[str]) -> None:
        out_dir = Path("runtime")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"tts_{uuid.uuid4().hex}.wav"
        self.tts_to_wav(text=text, voice=voice, instruction=instruction, out_path=str(out_path))
        self.play_wav(str(out_path))

    # ---------------------------
    # 流式：解决“断续卡顿/句间噪音”的重点
    # ---------------------------
    def speak_stream(self, text_iter: "Iterable[str]", voice: str, instruction: Optional[str]) -> None:
        """
        流式 TTS：边收到文本增量，边分块送入 streaming_call，
        音频在 callback.on_data 中持续返回，实时播放（不落盘）。
        """

        # 播放器：预缓冲 + 淡出降噪 + 稳定 blocksize
        player = _PCMPlayer(
            sample_rate=self.sample_rate,
            prebuffer_ms=80,
            fade_ms=6,
            blocksize_frames=512,
        )
        player.start()
        cb = _TTSStreamCallback(player)

        # ✅PCM 流式最稳，不需要 wav 头，不需要解码
        tts = SpeechSynthesizer(
            model=self.tts_model,
            voice=voice,
            format=AudioFormat.PCM_16000HZ_MONO_16BIT,
            instruction=instruction,
            callback=cb,
        )

        # ——更平滑的文本分块策略——
        # 太碎会造成“生成间隙 → underflow → 咔哒”
        MIN_CHARS = 28     # 达到这个长度再优先发送
        MAX_CHARS = 90     # 太长会导致首句太慢，控制上限
        MAX_WAIT = 0.9     # 最长等待时间（秒），防止长时间不发送导致超时/延迟
        PUNCT = set("。！？!?；;\n")

        buf = ""
        last_send = time.time()

        def flush(force: bool = False) -> None:
            nonlocal buf, last_send
            if not buf:
                return

            # 清洗：去 emoji/部分 markdown
            to_send = _normalize_for_tts(_strip_emojis_for_tts(buf))

            if not to_send:
                buf = ""
                return

            tts.streaming_call(to_send)
            buf = ""
            last_send = time.time()

        try:
            for delta in text_iter:
                buf += delta
                now = time.time()

                # 1) 达到最大长度直接发
                if len(buf) >= MAX_CHARS:
                    flush(force=True)
                    continue

                # 2) 达到最小长度，并且最近出现句末标点，就发（但不是每个标点都立刻发）
                if len(buf) >= MIN_CHARS and any(ch in PUNCT for ch in delta):
                    flush(force=True)
                    continue

                # 3) 超过等待时间，也发一次（防止长句一直不出声）
                if len(buf) >= MIN_CHARS and (now - last_send) >= MAX_WAIT:
                    flush(force=True)
                    continue

                # 4) 如果 LLM 输出很慢，也别太久不发（保底）
                if (now - last_send) >= 6.0 and len(buf) > 0:
                    flush(force=True)

            # 收尾：把剩余内容发出去
            if buf.strip():
                flush(force=True)

            # ✅必须 complete，否则尾巴可能丢
            tts.streaming_complete()

            if cb.err_msg:
                raise RuntimeError(cb.err_msg)

        finally:
            # 1) 等服务端合成结束
            cb.done.wait()

            # 2) 等本地播放缓冲播空（防止下一轮 ASR 提前打断播放）
            t0 = time.time()
            while not player.is_drained():
                if time.time() - t0 > 20:
                    break
                time.sleep(0.05)

            player.stop()

    # ---------------------------
    # 克隆：录音→OSS→create_voice→poll OK
    # ---------------------------
    def _oss_upload(self, local_path: str, remote_prefix: str) -> str:
        required = ["OSS_ACCESS_KEY_ID", "OSS_ACCESS_KEY_SECRET", "OSS_ENDPOINT", "OSS_BUCKET", "OSS_PUBLIC_BASE"]
        miss = _missing_env(required)
        if miss:
            raise RuntimeError("OSS not configured. Missing env: " + ", ".join(miss))

        auth = oss2.Auth(_env("OSS_ACCESS_KEY_ID"), _env("OSS_ACCESS_KEY_SECRET"))
        bucket = oss2.Bucket(auth, _env("OSS_ENDPOINT"), _env("OSS_BUCKET"))

        p = Path(local_path)
        key = f"{remote_prefix}/{time.strftime('%Y%m%d')}/{uuid.uuid4().hex}{p.suffix.lower()}"
        bucket.put_object_from_file(key, str(p))
        return f"{_env('OSS_PUBLIC_BASE').rstrip('/')}/{key}"

    def _record_wav_16k(self, out_path: str, seconds: int = 7) -> str:
        """从本地麦克风录音（需要服务器有音频设备）"""
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        print(f"[CLONE] 录音 {seconds}s：请连续清晰朗读（尽量无噪音/无音乐/无他人声）")
        audio = sd.rec(int(seconds * self.sample_rate), samplerate=self.sample_rate, channels=1, dtype="float32")
        sd.wait()
        audio = np.squeeze(audio)
        audio = np.clip(audio, -1, 1)
        audio_i16 = (audio * 32767).astype(np.int16)

        with wave.open(out_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(audio_i16.tobytes())

        return out_path

    def _save_pcm_to_wav(self, pcm_data: bytes, out_path: str, sample_rate: int = 16000) -> str:
        """将 PCM 数据（int16）保存为 WAV 文件"""
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        with wave.open(out_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_data)
        return out_path

    def enroll_voice_from_mic(self, prefix: str = "myvoice", seconds: int = 7) -> str:
        """从本地麦克风录音进行音色克隆（需要服务器有音频设备）"""
        out_dir = Path("runtime")
        out_dir.mkdir(parents=True, exist_ok=True)
        wav_path = out_dir / f"enroll_{uuid.uuid4().hex}.wav"
        self._record_wav_16k(str(wav_path), seconds=seconds)

        url = self._oss_upload(str(wav_path), remote_prefix="robotduck/voice_samples")
        print(f"[CLONE] 样本URL: {url}")

        service = VoiceEnrollmentService()
        voice_id = service.create_voice(target_model=self.tts_model, prefix=prefix, url=url)
        print(f"[CLONE] create_voice 提交成功：{voice_id}")

        for i in range(30):
            info = service.query_voice(voice_id=voice_id)
            status = (info or {}).get("status")
            print(f"[CLONE] 状态({i+1}/30): {status}")
            if status == "OK":
                return voice_id
            if status == "UNDEPLOYED":
                raise RuntimeError("音色审核失败（UNDEPLOYED），请换更干净的朗读样本重试。")
            time.sleep(5)

        raise RuntimeError("音色创建超时，请稍后重试。")

    def enroll_voice_from_pcm(self, pcm_data: bytes, prefix: str = "myvoice") -> str:
        """
        ★ 从 PCM 数据进行音色克隆（用于 ESP32 麦克风录音）
        
        Args:
            pcm_data: int16 mono 16kHz 的 PCM 音频数据
            prefix: 音色名称前缀
        
        Returns:
            voice_id: 克隆成功的音色ID
        """
        if not pcm_data or len(pcm_data) < 16000:  # 至少 0.5 秒
            raise RuntimeError("录音数据太短，请确保 ESP32 麦克风正常工作")
        
        out_dir = Path("runtime")
        out_dir.mkdir(parents=True, exist_ok=True)
        wav_path = out_dir / f"enroll_{uuid.uuid4().hex}.wav"
        
        # 保存 PCM 为 WAV
        self._save_pcm_to_wav(pcm_data, str(wav_path), sample_rate=self.sample_rate)
        print(f"[CLONE] 已保存 ESP32 录音: {wav_path} ({len(pcm_data)} 字节)")

        # 上传到 OSS
        url = self._oss_upload(str(wav_path), remote_prefix="robotduck/voice_samples")
        print(f"[CLONE] 样本URL: {url}")

        # 调用音色克隆服务
        service = VoiceEnrollmentService()
        voice_id = service.create_voice(target_model=self.tts_model, prefix=prefix, url=url)
        print(f"[CLONE] create_voice 提交成功：{voice_id}")

        # 等待克隆完成
        for i in range(30):
            info = service.query_voice(voice_id=voice_id)
            status = (info or {}).get("status")
            print(f"[CLONE] 状态({i+1}/30): {status}")
            if status == "OK":
                return voice_id
            if status == "UNDEPLOYED":
                raise RuntimeError("音色审核失败（UNDEPLOYED），请换更干净的朗读样本重试。")
            time.sleep(5)

        raise RuntimeError("音色创建超时，请稍后重试。")

# voice_adapter.py
# -*- coding: utf-8 -*-
"""
语音系统适配器：将 robotduck_voice_assistant 适配到现有的 WebSocket 架构
- ASR适配：从WebSocket接收音频流（而不是从麦克风）
- TTS适配：输出到 broadcast_pcm16_realtime（而不是本地播放器）
"""
import os
import time
from typing import Optional, Callable, AsyncGenerator, Awaitable
import asyncio

import dashscope
from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult

from robotduck_voice_assistant.cosyvoice import CosyVoiceEngine
from robotduck_voice_assistant.dispatcher import IntentDispatcher
from robotduck_voice_assistant.workflows import Workflows
from robotduck_voice_assistant.state import ChatState

# ==================== ASR适配：从WebSocket接收 ====================

class WebSocketASRCallback(RecognitionCallback):
    """ASR回调：收集识别结果并通知外部"""
    def __init__(
        self,
        on_partial: Callable[[str], None],
        on_final: Callable[[str], None],
    ) -> None:
        super().__init__()
        self._last_partial: str = ""
        self._sentences: list[str] = []
        self.on_partial = on_partial
        self.on_final = on_final

    def on_event(self, result: RecognitionResult) -> None:
        sentence = result.get_sentence()
        if not isinstance(sentence, dict):
            return
        text = sentence.get("text")
        if not text:
            return
        
        self._last_partial = str(text).strip()
        if self._last_partial:
            # 通知外部partial结果
            try:
                self.on_partial(self._last_partial)
            except Exception as e:
                print(f"[ASR ADAPTER] on_partial error: {e}", flush=True)
        
        if RecognitionResult.is_sentence_end(sentence):
            final_text = self._last_partial
            self._sentences.append(final_text)
            self._last_partial = ""
            # 通知外部final结果
            try:
                self.on_final(final_text)
            except Exception as e:
                print(f"[ASR ADAPTER] on_final error: {e}", flush=True)

    def get_final_text(self) -> str:
        """获取所有识别到的句子"""
        if self._last_partial:
            self._sentences.append(self._last_partial)
            self._last_partial = ""
        final = " ".join([t.strip() for t in self._sentences if t and t.strip()]).strip()
        self._sentences.clear()
        return final


class WebSocketASREngine:
    """适配后的ASR引擎：从WebSocket接收音频数据"""
    def __init__(self, api_key: str, sample_rate: int = 16000, ws_url: str = None):
        if not api_key:
            raise RuntimeError("ASR: missing DASHSCOPE_API_KEY")
        dashscope.api_key = api_key
        if ws_url:
            dashscope.base_websocket_api_url = ws_url
        
        self.sample_rate = sample_rate
        self.recognition: Optional[Recognition] = None
        self.callback: Optional[WebSocketASRCallback] = None

    def start(
        self,
        on_partial: Callable[[str], None],
        on_final: Callable[[str], None],
    ) -> Recognition:
        """启动ASR识别"""
        self.callback = WebSocketASRCallback(on_partial, on_final)
        self.recognition = Recognition(
            model="fun-asr-realtime",
            format="pcm",
            sample_rate=self.sample_rate,
            semantic_punctuation_enabled=False,
            callback=self.callback,
        )
        self.recognition.start()
        return self.recognition

    def send_audio_frame(self, audio_bytes: bytes) -> None:
        """发送音频帧（从WebSocket接收的数据）"""
        if self.recognition:
            try:
                self.recognition.send_audio_frame(audio_bytes)
            except Exception as e:
                print(f"[ASR ADAPTER] send_audio_frame error: {e}", flush=True)

    def stop(self) -> None:
        """停止识别"""
        if self.recognition:
            try:
                self.recognition.stop()
            except Exception:
                pass
            self.recognition = None

# ==================== TTS适配：输出到 broadcast_pcm16_realtime ====================

class BroadcastTTSCallback:
    """TTS回调：将音频数据发送到 broadcast_pcm16_realtime"""
    def __init__(self, broadcast_fn: Callable[[bytes], None]) -> None:
        self.broadcast_fn = broadcast_fn
        self.done = asyncio.Event()
        self.err_msg: Optional[str] = None

    def on_open(self) -> None:
        pass

    def on_event(self, message: str) -> None:
        pass

    def on_data(self, data: bytes) -> None:
        """接收到PCM音频数据，放入队列（由外部异步处理）"""
        if data:
            # 注意：这里不能直接调用async函数，需要放入队列
            # 实际的广播会在app_main.py中处理
            pass

    def on_complete(self) -> None:
        self.done.set()

    def on_error(self, message) -> None:
        self.err_msg = str(message)
        self.done.set()

    def on_close(self) -> None:
        pass


class BroadcastTTSEngine(CosyVoiceEngine):
    """适配后的TTS引擎：输出到 broadcast_pcm16_realtime"""
    def __init__(self, api_key: str, tts_model: str, default_voice: str, sample_rate: int = 16000) -> None:
        super().__init__(api_key, tts_model, default_voice, sample_rate)

    async def speak_stream_to_broadcast(
        self,
        text_iter: "AsyncGenerator[str, None] | Iterable[str]",
        voice: str,
        instruction: Optional[str],
        broadcast_fn: Callable[[bytes], Awaitable[None]],
    ) -> None:
        """
        流式TTS：将文本转换为PCM16音频并广播给ESP32
        text_iter: 文本流（可以是async generator或普通iterable）
        broadcast_fn: 异步广播函数，接收bytes参数
        """
        from dashscope.audio.tts_v2 import (
            AudioFormat,
            SpeechSynthesizer,
        )

        callback = BroadcastTTSCallback(broadcast_fn)
        
        tts = SpeechSynthesizer(
            model=self.tts_model,
            voice=voice,
            format=AudioFormat.PCM_16000HZ_MONO_16BIT,
            instruction=instruction,
            callback=callback,
        )

        # 文本分块策略（与cosyvoice.py保持一致）
        MIN_CHARS = 28
        MAX_CHARS = 90
        MAX_WAIT = 0.9
        PUNCT = set("。！？!?；;\n")

        buf = ""
        last_send = time.time()

        def flush(force: bool = False) -> None:
            nonlocal buf, last_send
            if not buf:
                return

            # 清洗文本（复用cosyvoice的逻辑）
            from robotduck_voice_assistant.cosyvoice import _normalize_for_tts, _strip_emojis_for_tts
            to_send = _normalize_for_tts(_strip_emojis_for_tts(buf))

            if not to_send:
                buf = ""
                return

            tts.streaming_call(to_send)
            buf = ""
            last_send = time.time()

        try:
            # 处理文本流
            if hasattr(text_iter, "__aiter__"):
                # 异步生成器
                async for delta in text_iter:
                    buf += delta
                    now = time.time()

                    if len(buf) >= MAX_CHARS:
                        flush(force=True)
                        continue

                    if len(buf) >= MIN_CHARS and any(ch in PUNCT for ch in delta):
                        flush(force=True)
                        continue

                    if len(buf) >= MIN_CHARS and (now - last_send) >= MAX_WAIT:
                        flush(force=True)
                        continue

                    if (now - last_send) >= 6.0 and len(buf) > 0:
                        flush(force=True)
            else:
                # 普通iterable
                for delta in text_iter:
                    buf += delta
                    now = time.time()

                    if len(buf) >= MAX_CHARS:
                        flush(force=True)
                        continue

                    if len(buf) >= MIN_CHARS and any(ch in PUNCT for ch in delta):
                        flush(force=True)
                        continue

                    if len(buf) >= MIN_CHARS and (now - last_send) >= MAX_WAIT:
                        flush(force=True)
                        continue

                    if (now - last_send) >= 6.0 and len(buf) > 0:
                        flush(force=True)

            # 收尾
            if buf.strip():
                flush(force=True)

            # 完成流式合成
            tts.streaming_complete()

            if callback.err_msg:
                raise RuntimeError(callback.err_msg)

        finally:
            # 等待合成完成
            await asyncio.to_thread(callback.done.wait, timeout=30.0)


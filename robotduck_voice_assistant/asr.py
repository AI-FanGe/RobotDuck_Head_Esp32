from __future__ import annotations

import os
import time
from typing import List, Optional

import dashscope
import sounddevice as sd
from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult

# 默认参数（也会从环境变量读取）
DEFAULT_SR = int(os.getenv("AUDIO_SAMPLE_RATE", "16000"))
DEFAULT_WS_URL = os.getenv("DASHSCOPE_WS_BASE_URL", "wss://dashscope.aliyuncs.com/api-ws/v1/inference")


class _Collector(RecognitionCallback):
    """收集 sentence_end 的最终文本。"""
    def __init__(self) -> None:
        super().__init__()
        self._sentences: List[str] = []
        self._last_partial: str = ""

    def on_event(self, result: RecognitionResult) -> None:
        sentence = result.get_sentence()
        if not isinstance(sentence, dict):
            return
        text = sentence.get("text")
        if not text:
            return
        self._last_partial = str(text)
        if RecognitionResult.is_sentence_end(sentence):
            self._sentences.append(self._last_partial)
            self._last_partial = ""

    def get_text(self) -> str:
        if self._last_partial:
            self._sentences.append(self._last_partial)
            self._last_partial = ""
        final = " ".join([t.strip() for t in self._sentences if t and t.strip()]).strip()
        self._sentences.clear()
        return final


class AsrEngine:
    """
    Push-to-talk ASR:
    - 按回车开始说话
    - 再按回车结束
    """
    def __init__(self, api_key: str, sample_rate: int = DEFAULT_SR, ws_url: str = DEFAULT_WS_URL) -> None:
        if not api_key:
            raise RuntimeError("ASR: missing DASHSCOPE_API_KEY")
        dashscope.api_key = api_key
        dashscope.base_websocket_api_url = ws_url

        self.sample_rate = sample_rate

    def listen_once(self) -> str:
        # Windows 用 msvcrt；非 Windows fallback 到 input()
        try:
            import msvcrt  # type: ignore
            is_windows = True
        except Exception:
            msvcrt = None
            is_windows = False

        def wait_enter(prompt: str) -> None:
            print(prompt)
            if is_windows and msvcrt:
                while True:
                    if msvcrt.kbhit():
                        ch = msvcrt.getwch()
                        if ch == "\r":
                            break
                    time.sleep(0.02)
            else:
                input()

        wait_enter("\n[ASR] 按回车开始说话…")

        collector = _Collector()
        recog = Recognition(
            model="fun-asr-realtime",
            format="pcm",
            sample_rate=self.sample_rate,
            semantic_punctuation_enabled=False,
            callback=collector,
        )
        recog.start()

        stream = sd.RawInputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=1600,
        )
        stream.start()

        print("[ASR] 正在听…（再按回车结束）")
        try:
            if is_windows and msvcrt:
                while True:
                    if msvcrt.kbhit():
                        ch = msvcrt.getwch()
                        if ch == "\r":
                            break
                    data, _ = stream.read(1600)
                    recog.send_audio_frame(data)
            else:
                # 非 windows：按一次 enter 结束
                input()
        finally:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

        recog.stop()  # 等待收尾事件
        text = collector.get_text()
        print(f"[ASR] 识别结果: {text}")
        return text

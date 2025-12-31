from __future__ import annotations

import os
import time
import uuid
import base64
from pathlib import Path
from typing import Optional, Callable, Iterator

import cv2  # type: ignore
import numpy as np
import oss2  # type: ignore
from openai import OpenAI

from robotduck_voice_assistant.dispatcher import IntentDispatcher, RouteDecision
from robotduck_voice_assistant.cosyvoice import CosyVoiceEngine
from robotduck_voice_assistant.state import ChatState


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


class Workflows:
    def __init__(
        self, 
        api_key: str, 
        base_url: str, 
        vision_model: str, 
        cosy: CosyVoiceEngine, 
        dispatcher: IntentDispatcher,
        frame_getter: Optional[Callable[[], Optional[bytes]]] = None
    ) -> None:
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.vision_model = vision_model
        self.cosy = cosy
        self.dispatcher = dispatcher
        # ESP32 帧获取函数：返回最新的 JPEG bytes，或 None
        self._frame_getter = frame_getter

    def _oss_upload(self, local_path: str, remote_prefix: str) -> str:
        ak = _env("OSS_ACCESS_KEY_ID")
        sk = _env("OSS_ACCESS_KEY_SECRET")
        endpoint = _env("OSS_ENDPOINT")
        bucket_name = _env("OSS_BUCKET")
        public_base = _env("OSS_PUBLIC_BASE")
        if not (ak and sk and endpoint and bucket_name and public_base):
            raise RuntimeError("OSS not configured. vision/clone need OSS_* env.")

        auth = oss2.Auth(ak, sk)
        bucket = oss2.Bucket(auth, endpoint, bucket_name)

        p = Path(local_path)
        key = f"{remote_prefix}/{time.strftime('%Y%m%d')}/{uuid.uuid4().hex}{p.suffix.lower()}"
        bucket.put_object_from_file(key, str(p))
        return f"{public_base.rstrip('/')}/{key}"

    def run(self, decision: RouteDecision, raw_user_text: str, state: ChatState) -> str:
        if decision.intent == "reset":
            state.reset_to_default()
            return "好的，已恢复默认模式和默认音色。"

        if decision.intent == "dialect":
            if decision.dialect:
                state.dialect = decision.dialect
            if not decision.query:
                return f"好的，接下来我会用{state.dialect}和你聊。"
            return self.dispatcher.chat_answer(decision.query, state, decision.emotion)

        if decision.intent == "role_scene":
            if decision.role:
                state.role = decision.role
            if decision.scene:
                state.scene = decision.scene
            if decision.style_hint:
                state.style_hint = decision.style_hint
            if not decision.query:
                return "好的，收到。你想让我说点什么？"
            return self.dispatcher.chat_answer(decision.query, state, decision.emotion)

        if decision.intent == "clone":
            seconds = 7
            try:
                if decision.style_hint:
                    seconds = int(float(decision.style_hint))
            except Exception:
                seconds = 7

            try:
                new_voice = self.cosy.enroll_voice_from_mic(prefix="myvoice", seconds=seconds)
            except Exception as e:
                return f"当前无法进行音色克隆：{e}"

            state.set_cloned_voice(new_voice)

            if not decision.query:
                return "好的，已切换到新的克隆音色。你想聊点什么？"
            return self.dispatcher.chat_answer(decision.query, state, decision.emotion)

        if decision.intent == "vision":
            question = decision.query or raw_user_text
            try:
                img_url = self._capture_and_upload()
            except Exception as e:
                return f"当前无法进行视觉问答：{e}"

            try:
                ans = self._ask_vision(img_url, question)
                return ans or "我没看清楚，你能再说具体一点吗？"
            except Exception as e:
                return f"视觉模型调用失败：{e}"

        # default
        query = decision.query or raw_user_text
        return self.dispatcher.chat_answer(query, state, decision.emotion)

    def _capture_and_upload(self) -> str:
        """
        从 ESP32 摄像头获取最新帧并上传到 OSS。
        如果没有 ESP32 帧获取函数或没有帧，则回退到电脑摄像头。
        """
        jpeg_bytes: Optional[bytes] = None
        
        # 优先使用 ESP32 摄像头帧
        if self._frame_getter is not None:
            try:
                jpeg_bytes = self._frame_getter()
            except Exception as e:
                print(f"[VISION] ESP32 frame getter error: {e}")
                jpeg_bytes = None
        
        if jpeg_bytes is not None and len(jpeg_bytes) > 0:
            # 使用 ESP32 的 JPEG 帧
            out_dir = Path("runtime")
            out_dir.mkdir(parents=True, exist_ok=True)
            local = out_dir / f"frame_{uuid.uuid4().hex}.jpg"
            
            # 直接保存 JPEG 字节
            with open(str(local), "wb") as f:
                f.write(jpeg_bytes)
            
            print(f"[VISION] 使用 ESP32 摄像头帧: {len(jpeg_bytes)} bytes")
            return self._oss_upload(str(local), remote_prefix="robotduck/vision")
        
        # 回退：使用电脑摄像头
        print("[VISION] ESP32 帧不可用，尝试使用电脑摄像头")
        cam_idx = int(_env("CAMERA_INDEX", "0"))
        cap = cv2.VideoCapture(cam_idx)
        if not cap.isOpened():
            raise RuntimeError(f"ESP32 帧不可用，且无法打开电脑摄像头 (index {cam_idx})")

        ok, frame = cap.read()
        cap.release()
        if not ok or frame is None:
            raise RuntimeError("无法获取图像帧")

        out_dir = Path("runtime")
        out_dir.mkdir(parents=True, exist_ok=True)
        local = out_dir / f"frame_{uuid.uuid4().hex}.jpg"
        cv2.imwrite(str(local), frame)

        return self._oss_upload(str(local), remote_prefix="robotduck/vision")

    def _ask_vision(self, image_url: str, question: str) -> str:
        resp = self.client.chat.completions.create(
            model=self.vision_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_url}},
                        {"type": "text", "text": question},
                    ],
                }
            ],
            temperature=0.2,
        )
        return (resp.choices[0].message.content or "").strip()

    # ==================== 流式视觉问答（优化版） ====================
    
    def get_esp32_frame(self) -> Optional[bytes]:
        """获取 ESP32 摄像头的最新帧"""
        if self._frame_getter is None:
            return None
        try:
            return self._frame_getter()
        except Exception as e:
            print(f"[VISION] 获取ESP32帧失败: {e}")
            return None
    
    def run_vision_stream(self, question: str, jpeg_bytes: Optional[bytes] = None) -> Iterator[str]:
        """
        流式视觉问答（优化版）：
        1. 使用 base64 直接传图（不需要OSS上传，省1-2秒）
        2. 流式调用视觉模型（边生成边返回，首字延迟<1秒）
        3. 返回文本生成器，供流式TTS使用
        
        Args:
            question: 用户问题
            jpeg_bytes: JPEG 图片字节，如果为 None 则自动从 ESP32 获取
            
        Yields:
            文本片段
        """
        # 获取图片
        if jpeg_bytes is None:
            jpeg_bytes = self.get_esp32_frame()
        
        if jpeg_bytes is None or len(jpeg_bytes) == 0:
            yield "抱歉，摄像头没有画面，我看不到任何东西。"
            return
        
        # 转换为 base64（省去OSS上传）
        b64_data = base64.b64encode(jpeg_bytes).decode("utf-8")
        image_url = f"data:image/jpeg;base64,{b64_data}"
        
        print(f"[VISION-STREAM] 问题: {question}, 图片: {len(jpeg_bytes)} bytes")
        
        try:
            # 流式调用视觉模型
            stream = self.client.chat.completions.create(
                model=self.vision_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": image_url}},
                            {"type": "text", "text": question},
                        ],
                    }
                ],
                temperature=0.2,
                stream=True,  # 开启流式输出
            )
            
            has_content = False
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    has_content = True
                    yield content
            
            if not has_content:
                yield "我没看清楚，你能再说具体一点吗？"
                
        except Exception as e:
            print(f"[VISION-STREAM] 错误: {e}")
            yield f"视觉问答出错了：{e}"

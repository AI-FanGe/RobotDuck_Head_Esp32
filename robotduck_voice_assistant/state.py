from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

Emotion = str  # neutral|fearful|angry|sad|surprised|happy|disgusted


@dataclass
class ChatState:
    # ---- voice state ----
    default_voice: str = "longanhuan"
    current_voice: str = "longanhuan"
    is_cloned_voice: bool = False

    # ---- persistent “style modes” ----
    dialect: Optional[str] = None   # e.g. 四川话/广东话...
    scene: Optional[str] = None     # e.g. 闲聊对话/脱口秀表演...
    role: Optional[str] = None      # e.g. 温和客服
    style_hint: Optional[str] = None  # e.g. rap/押韵/脱口秀

    # ---- chat memory ----
    messages: List[Dict[str, Any]] = field(default_factory=list)
    max_turns: int = 8

    def reset_to_default(self) -> None:
        self.current_voice = self.default_voice
        self.is_cloned_voice = False
        self.dialect = None
        self.scene = None
        self.role = None
        self.style_hint = None

    def set_cloned_voice(self, voice_id: str) -> None:
        self.current_voice = voice_id
        self.is_cloned_voice = True

    def build_tts_instruction(self, emotion: Emotion) -> Optional[str]:
        """
        关键修复点：
        - 复刻音色（voice_id）不支持“情感/角色/场景”这类 Instruct，传了会 428。
        - 系统音色（如 longanhuan）支持“情感/场景/角色”（按音色能力），可继续用。
        - 复刻音色的方言/小语种 instruct 是允许的：例如“请用四川话表达。”（你后面方言模式要用它）
        """
        parts: List[str] = []

        if not self.is_cloned_voice:
            # 系统音色：可以用情感/场景/角色
            if self.role:
                parts.append(f"你说话的角色是{self.role}，你说话的情感是{emotion}。")
            elif self.scene:
                parts.append(f"你正在进行{self.scene}，你说话的情感是{emotion}。")
            else:
                parts.append(f"你说话的情感是{emotion}。")

            # 系统音色：不要加方言这句（官方限制方言句式主要给复刻音色用；系统音色容易 428）
            # 方言在未克隆阶段由 LLM 文本来实现（dispatcher.py里做）
            return " ".join(parts).strip() if parts else None

        # 复刻音色：只允许方言/小语种这类 instruction（情感等通过文本表达）
        if self.dialect:
            parts.append(f"请用{self.dialect}表达。")

        return " ".join(parts).strip() if parts else None

    # ---- memory helpers ----
    def ensure_system(self, system_prompt: str) -> None:
        if not self.messages or self.messages[0].get("role") != "system":
            self.messages.insert(0, {"role": "system", "content": system_prompt})
        else:
            self.messages[0]["content"] = system_prompt

    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})
        self._trim()

    def add_assistant(self, text: str) -> None:
        self.messages.append({"role": "assistant", "content": text})
        self._trim()

    def _trim(self) -> None:
        if not self.messages:
            return
        system = self.messages[:1] if self.messages[0].get("role") == "system" else []
        rest = self.messages[1:] if system else self.messages
        keep = self.max_turns * 2
        rest = rest[-keep:]
        self.messages = system + rest

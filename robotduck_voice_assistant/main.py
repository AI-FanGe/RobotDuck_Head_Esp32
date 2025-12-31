from __future__ import annotations

import os

# dotenv 可选
try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    load_dotenv = None  # type: ignore

from robotduck_voice_assistant.asr import AsrEngine
from robotduck_voice_assistant.cosyvoice import CosyVoiceEngine
from robotduck_voice_assistant.dispatcher import IntentDispatcher
from robotduck_voice_assistant.workflows import Workflows
from robotduck_voice_assistant.state import ChatState



def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def main() -> None:
    if load_dotenv is not None:
        load_dotenv()

    api_key = _env("DASHSCOPE_API_KEY")
    if not api_key:
        raise RuntimeError("请先在 .env 或系统环境变量中配置 DASHSCOPE_API_KEY")

    base_url = _env("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    ws_url = _env("DASHSCOPE_WS_BASE_URL", "wss://dashscope.aliyuncs.com/api-ws/v1/inference")

    router_model = _env("ROUTER_MODEL", "qwen-turbo")
    text_model = _env("TEXT_MODEL", "qwen-turbo")
    vision_model = _env("VISION_MODEL", "qwen-vl-max")

    tts_model = _env("TTS_MODEL", "cosyvoice-v3-flash")
    default_voice = _env("DEFAULT_VOICE", "longanhuan")
    sr = int(_env("AUDIO_SAMPLE_RATE", "16000"))

    state = ChatState(default_voice=default_voice, current_voice=default_voice, max_turns=8)

    asr = AsrEngine(api_key=api_key, sample_rate=sr, ws_url=ws_url)
    cosy = CosyVoiceEngine(api_key=api_key, tts_model=tts_model, default_voice=default_voice, sample_rate=sr)

    dispatcher = IntentDispatcher(api_key=api_key, base_url=base_url, router_model=router_model, text_model=text_model)
    workflows = Workflows(api_key=api_key, base_url=base_url, vision_model=vision_model, cosy=cosy, dispatcher=dispatcher)

    print("==============================================")
    print("RobotDuck Voice Assistant - Plan A (6 files)")
    print("操作：回车开始说话；再回车结束识别。")
    print("提示：")
    print("- 说“换回默认模式”恢复默认音色/清空模式。")
    print("- 说“模仿/学一下音色”触发克隆（需要 OSS 配置）。")
    print("- 说“帮我看一下/看一下”触发视觉问答（需要 OSS 配置 + 摄像头）。")
    print("- 说“用四川话跟我聊”触发方言模式。")
    print("- 说“你是温和客服/唱个rap”触发角色场景模式。")
    print("==============================================")

    while True:
        user_text = asr.listen_once().strip()
        if not user_text:
            continue

        if user_text in ["退出", "结束", "bye", "quit", "exit"]:
            print("Bye.")
            break

        decision = dispatcher.route(user_text, state)

        # ✅ 改动点：default / dialect / role_scene 都走“流式链路”
        if decision.intent in ("default", "dialect", "role_scene"):
            # 1) 先把模式参数写入 state（很关键：克隆后方言依赖 state.build_tts_instruction()）
            if decision.intent == "dialect":
                if decision.dialect:
                    state.dialect = decision.dialect

                # 如果用户只是在“设置方言模式”，没有继续问具体问题：直接确认一句（也用流式播出）
                if not (decision.query or "").strip():
                    ack = f"好的，接下来我会用{state.dialect or '方言'}和你聊。"
                    instruction = state.build_tts_instruction(decision.emotion)
                    cosy.speak_stream([ack], voice=state.current_voice, instruction=instruction)
                    continue

            if decision.intent == "role_scene":
                if decision.role:
                    state.role = decision.role
                if decision.scene:
                    state.scene = decision.scene
                if decision.style_hint:
                    state.style_hint = decision.style_hint

                # 同理：如果只是设置角色/场景，没有具体问题，也给个确认
                if not (decision.query or "").strip():
                    ack = "好的，已进入角色/场景模式。你想让我怎么表演？"
                    instruction = state.build_tts_instruction(decision.emotion)
                    cosy.speak_stream([ack], voice=state.current_voice, instruction=instruction)
                    continue

            # 2) LLM 文本流式
            query = (decision.query or "").strip() or user_text
            instruction = state.build_tts_instruction(decision.emotion)
            text_stream = dispatcher.chat_answer_stream(query, state, decision.emotion)

            # 3) TTS 语音流式（关键：克隆后第一次“方言聊天”也会立刻边说边播）
            cosy.speak_stream(text_stream, voice=state.current_voice, instruction=instruction)
            continue

        # 其它模式：保持你原来能跑通的逻辑（clone / vision / reset 仍走 workflows + 非流式 speak）
        reply_text = workflows.run(decision, user_text, state)
        instruction = state.build_tts_instruction(decision.emotion)

        try:
            cosy.speak(text=reply_text, voice=state.current_voice, instruction=instruction)
        except Exception as e:
            print("\n[TTS ERROR]")
            print(f"- voice={state.current_voice}")
            print(f"- instruction={instruction}")
            print(f"- reply_text={reply_text}")
            print(f"- error={e}\n")


if __name__ == "__main__":
    main()

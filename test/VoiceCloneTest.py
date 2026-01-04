# ============================================================
# 1. SECRET CONFIG（⚠️只在你自己电脑用，不要上传仓库）
# ============================================================

DASHSCOPE_API_KEY = "xxx"
OSS_ACCESS_KEY_ID = "xxx"
OSS_ACCESS_KEY_SECRET = "xxx"

# ============================================================
# 2. NORMAL CONFIG（安全，可长期写死）
# ============================================================

OSS_REGION = "cn-shanghai"
OSS_ENDPOINT = "https://oss-cn-shanghai.aliyuncs.com"
OSS_BUCKET = "xxx"
OSS_PUBLIC_BASE = "https://fancy.oss-cn-shanghai.aliyuncs.com"

OBJECT_PREFIX = "cosyvoice_inputs"
RECORD_SECONDS = 10
TARGET_SR = 16000

TARGET_MODEL = "cosyvoice-v3-plus"   # 或 cosyvoice-v3-flash
VOICE_PREFIX = "myvoice"             # <=10 字符
TEXT_TO_SYNTH = "你好，这是用来测试克隆音色的"

# ============================================================
# 3. IMPORTS
# ============================================================

import os
import time
import uuid
import wave
import numpy as np
import sounddevice as sd

import oss2
import dashscope
from dashscope.audio.tts_v2 import VoiceEnrollmentService, SpeechSynthesizer

# ============================================================
# 4. INIT
# ============================================================

if not DASHSCOPE_API_KEY:
    raise ValueError("DASHSCOPE_API_KEY 未填写")
if not OSS_ACCESS_KEY_ID or not OSS_ACCESS_KEY_SECRET:
    raise ValueError("OSS Key 未填写")

dashscope.api_key = DASHSCOPE_API_KEY

# ============================================================
# 5. AUDIO: record mic -> wav (16k mono 16bit)
# ============================================================

def record_wav(out_path, seconds=15, sr=16000):
    print(f"[1/6] 录音中（{seconds}s）...")
    audio = sd.rec(int(seconds * sr), samplerate=sr, channels=1, dtype="float32")
    sd.wait()

    audio = np.squeeze(audio)
    audio_int16 = np.clip(audio, -1, 1)
    audio_int16 = (audio_int16 * 32767).astype(np.int16)

    with wave.open(out_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(audio_int16.tobytes())

    print("录音完成:", out_path)

# ============================================================
# 6. OSS upload
# ============================================================

def upload_to_oss(local_path, object_key):
    print("[2/6] 上传 OSS...")
    auth = oss2.Auth(OSS_ACCESS_KEY_ID, OSS_ACCESS_KEY_SECRET)
    bucket = oss2.Bucket(auth, OSS_ENDPOINT, OSS_BUCKET)
    bucket.put_object_from_file(object_key, local_path)

    url = f"{OSS_PUBLIC_BASE}/{object_key}"
    print("OSS URL:", url)
    return url

# ============================================================
# 7. CosyVoice clone + poll
# ============================================================

def create_voice(audio_url):
    print("[3/6] 创建音色...")
    service = VoiceEnrollmentService()
    voice_id = service.create_voice(
        target_model=TARGET_MODEL,
        prefix=VOICE_PREFIX,
        url=audio_url
    )
    print("voice_id:", voice_id)

    print("[4/6] 等待音色就绪...")
    for i in range(30):
        info = service.query_voice(voice_id)
        status = info.get("status")
        print(f"  状态 {i+1}/30:", status)
        if status == "OK":
            return voice_id
        if status == "UNDEPLOYED":
            raise RuntimeError("音色审核失败")
        time.sleep(10)

    raise RuntimeError("音色创建超时")

# ============================================================
# 8. TTS
# ============================================================

def synthesize(voice_id, out_path):
    print("[5/6] 语音合成...")
    tts = SpeechSynthesizer(model=TARGET_MODEL, voice=voice_id)
    audio = tts.call(TEXT_TO_SYNTH)

    with open(out_path, "wb") as f:
        f.write(audio)

    print("[6/6] 合成完成:", out_path)

# ============================================================
# 9. MAIN
# ============================================================

def main():
    uid = uuid.uuid4().hex[:8]
    wav_name = f"record_{uid}.wav"

    record_wav(wav_name, RECORD_SECONDS, TARGET_SR)

    object_key = f"{OBJECT_PREFIX}/{time.strftime('%Y%m%d')}/{wav_name}"
    audio_url = upload_to_oss(wav_name, object_key)

    voice_id = create_voice(audio_url)

    out_audio = f"tts_{uid}.wav"
    synthesize(voice_id, out_audio)

    print("\n✅ 全流程完成")
    print("voice_id:", voice_id)
    print("audio_url:", audio_url)
    print("output:", out_audio)

if __name__ == "__main__":
    main()

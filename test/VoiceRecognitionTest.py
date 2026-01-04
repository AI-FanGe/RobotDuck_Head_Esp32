import os
import signal  
import sys

import dashscope
import sounddevice as sd
from dashscope.audio.asr import *

stream = None

sample_rate = 16000  # sampling rate (Hz)
channels = 1  # mono channel
dtype = 'int16'  # data type
format_pcm = 'pcm'  # the format of the audio data
block_size = 3200  # number of frames per buffer


class Callback(RecognitionCallback):
    def on_open(self) -> None:
        global stream
        print('RecognitionCallback open.')
        stream = sd.RawInputStream(
            samplerate=sample_rate,
            channels=channels,
            dtype=dtype,
            blocksize=block_size,
        )
        stream.start()

    def on_close(self) -> None:
        global stream
        print('RecognitionCallback close.')
        if stream:
            try:
                stream.stop()
            finally:
                stream.close()
            stream = None

    def on_complete(self) -> None:
        print('RecognitionCallback completed.')  

    def on_error(self, message) -> None:
        print('RecognitionCallback task_id: ', message.request_id)
        print('RecognitionCallback error: ', message.message)
        try:
            if 'stream' in globals() and stream:
                stream.stop()
                stream.close()
        finally:
            pass
        sys.exit(1)

    def on_event(self, result: RecognitionResult) -> None:
        sentence = result.get_sentence()
        if 'text' in sentence:
            print('RecognitionCallback text: ', sentence['text'])
            if RecognitionResult.is_sentence_end(sentence):
                print(
                    'RecognitionCallback sentence end, request_id:%s, usage:%s'
                    % (result.get_request_id(), result.get_usage(sentence)))


def signal_handler(sig, frame):
    print('Ctrl+C pressed, stop recognition ...')
    # Stop recognition
    recognition.stop()
    print('Recognition stopped.')
    print(
        '[Metric] requestId: {}, first package delay ms: {}, last package delay ms: {}'
        .format(
            recognition.get_last_request_id(),
            recognition.get_first_package_delay(),
            recognition.get_last_package_delay(),
        ))

    sys.exit(0)


# main function
if __name__ == '__main__':
    # 这里填上你自己的api key
    dashscope.api_key = "xxx"
    dashscope.base_websocket_api_url='wss://dashscope.aliyuncs.com/api-ws/v1/inference'

    callback = Callback()
    recognition = Recognition(
        model='fun-asr-realtime',
        format=format_pcm,
        sample_rate=sample_rate,
        semantic_punctuation_enabled=False,
        callback=callback)

    recognition.start()

    signal.signal(signal.SIGINT, signal_handler)
    print("Press 'Ctrl+C' to stop recording and recognition...")

    while True:
        if stream:
            data, overflowed = stream.read(block_size)
            recognition.send_audio_frame(data)
        else:
            break

    recognition.stop()
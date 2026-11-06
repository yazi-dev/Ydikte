"""The real app with one substitution: the microphone plays a WAV file. Used by e2e.py."""

import os
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ydikte import app, audio, config  # noqa: E402


class FakeStream:
    def __init__(self, pcm):
        self.pcm = pcm
        self.sent = False

    def wait(self, ms):
        time.sleep(ms / 1000)

    def read_ready(self):
        if self.sent:
            return [b"\x00\x08" * 400]  # keeps the meter moving
        self.sent = True
        return [self.pcm]

    def stop(self):
        return []

    def close(self):
        pass


class FakeRecorder(audio.Recorder):
    def _open_stream(self):
        with wave.open(os.environ["YDIKTE_E2E_WAV"], "rb") as wav:
            return FakeStream(wav.readframes(wav.getnframes()))


class E2EApp(app.App):
    recorder_class = FakeRecorder


if __name__ == "__main__":
    config.CONFIG_PATH = Path(os.environ["YDIKTE_E2E_CONFIG"])
    config.ENV_PATH = Path(os.environ["YDIKTE_E2E_CONFIG"] + ".env")
    config.LOG_PATH = Path(os.environ["YDIKTE_E2E_CONFIG"] + ".log")
    sys.exit(app.run_app(E2EApp))

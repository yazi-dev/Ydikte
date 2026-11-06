"""Microphone capture through the Windows waveIn API: 16 kHz, mono, 16-bit."""

import array
import ctypes as C
import logging
import queue
import threading
from concurrent.futures import Future
from ctypes import wintypes as W

from . import winapi as w

log = logging.getLogger("ydikte")

RATE = 16000
BUFFER_BYTES = 3200   # 100 ms
BUFFER_COUNT = 6
_HDR = C.sizeof(w.WAVEHDR)


class MicError(Exception):
    pass


def list_devices():
    names = []
    for index in range(w.winmm.waveInGetNumDevs()):
        caps = w.WAVEINCAPSW()
        if w.winmm.waveInGetDevCapsW(index, C.byref(caps), C.sizeof(caps)) == 0:
            names.append(caps.szPname)
    return names


def _find_device(name):
    if name:
        for index, device in enumerate(list_devices()):
            if name.lower() in device.lower():
                return index
        log.warning("microphone %r not found, using the default", name)
    return w.WAVE_MAPPER


class _Stream:
    def __init__(self, device_name):
        self.event = w.kernel32.CreateEventW(None, False, False, None)
        fmt = w.WAVEFORMATEX(w.WAVE_FORMAT_PCM, 1, RATE, RATE * 2, 2, 16, 0)
        self.handle = W.HANDLE()
        code = w.winmm.waveInOpen(C.byref(self.handle), _find_device(device_name), C.byref(fmt),
                                  self.event, 0, w.CALLBACK_EVENT)
        if code != 0:
            w.kernel32.CloseHandle(self.event)
            raise MicError(f"waveInOpen error {code}")
        self.buffers = [C.create_string_buffer(BUFFER_BYTES) for _ in range(BUFFER_COUNT)]
        self.headers = []
        for buffer in self.buffers:
            hdr = w.WAVEHDR()
            hdr.lpData = C.cast(buffer, C.c_void_p)
            hdr.dwBufferLength = BUFFER_BYTES
            w.winmm.waveInPrepareHeader(self.handle, C.byref(hdr), _HDR)
            w.winmm.waveInAddBuffer(self.handle, C.byref(hdr), _HDR)
            self.headers.append(hdr)
        code = w.winmm.waveInStart(self.handle)
        if code != 0:
            self.close()
            raise MicError(f"waveInStart error {code}")

    def read_ready(self, requeue=True):
        """Collect filled buffers in recording order."""
        chunks = []
        for _ in range(BUFFER_COUNT):
            ready = [(i, h) for i, h in enumerate(self.headers) if h.dwFlags & w.WHDR_DONE]
            if not ready:
                break
            index, hdr = ready[0]
            chunks.append(C.string_at(self.buffers[index], hdr.dwBytesRecorded))
            hdr.dwFlags &= ~w.WHDR_DONE
            if requeue:
                w.winmm.waveInAddBuffer(self.handle, C.byref(hdr), _HDR)
            self.headers.append(self.headers.pop(index))
            self.buffers.append(self.buffers.pop(index))
        return chunks

    def wait(self, ms):
        w.kernel32.WaitForSingleObject(self.event, ms)

    def stop(self):
        """Stops recording and returns what was still in the buffers."""
        w.winmm.waveInReset(self.handle)
        return self.read_ready(requeue=False)

    def close(self):
        w.winmm.waveInReset(self.handle)
        for hdr in self.headers:
            w.winmm.waveInUnprepareHeader(self.handle, C.byref(hdr), _HDR)
        w.winmm.waveInClose(self.handle)
        w.kernel32.CloseHandle(self.event)


class Recorder:
    """Owns the mic on its own thread. The mic is open only between start and stop."""

    def __init__(self, device_name=""):
        self.device_name = device_name
        self.level = 0.0      # 0..1, for the pill's meter
        self._commands = queue.SimpleQueue()
        threading.Thread(target=self._run, name="mic", daemon=True).start()

    def start(self, on_error):
        self._commands.put(("start", on_error))

    def discard(self):
        self._commands.put(("discard", None))

    def finish(self):
        """Stop and get the audio. Returns a Future of PCM bytes."""
        future = Future()
        self._commands.put(("finish", future))
        return future

    def _open_stream(self):
        return _Stream(self.device_name)

    def _run(self):
        pending = None
        while True:
            command, arg = pending or self._commands.get()
            pending = None
            if command == "finish":
                arg.set_result(b"")   # the mic failed or never opened
            elif command == "start":
                pending = self._capture(arg)

    def _capture(self, on_error):
        try:
            stream = self._open_stream()
        except MicError as exc:
            log.error("microphone: %s", exc)
            on_error(str(exc))
            return None
        chunks = []
        try:
            while True:
                try:
                    command = self._commands.get_nowait()
                except queue.Empty:
                    stream.wait(50)
                    for chunk in stream.read_ready():
                        chunks.append(chunk)
                        self._update_level(chunk)
                    continue
                name, arg = command
                if name == "finish":
                    chunks.extend(stream.stop())
                    arg.set_result(b"".join(chunks))
                    return None
                if name == "discard":
                    return None
                if name == "start":  # restart: the previous audio was not wanted
                    return command
        finally:
            stream.close()
            self.level = 0.0
            chunks.clear()

    def _update_level(self, chunk):
        samples = array.array("h")
        samples.frombytes(chunk[: len(chunk) - len(chunk) % 2])
        if samples:
            peak = max(map(abs, samples[::8])) / 32768.0
            # Speech peaks are often small; lift them so the meter visibly moves.
            target = min(1.0, peak * 4.0) ** 0.6
            self.level = max(target, self.level * 0.7)

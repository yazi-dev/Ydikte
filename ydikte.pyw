"""Start YDikte. Double-click, or run with pythonw to stay in the background.

Diagnostics (run with python.exe so they can print):
  python ydikte.pyw --settings            open the settings window
  python ydikte.pyw --keytest             show the code of each key you press
  python ydikte.pyw --mic-test [seconds]  list microphones and measure the level
  python ydikte.pyw --transcribe a.wav    run the pipeline on a file, print the text
"""

import sys


def keytest():
    import ctypes as C
    import time

    from ydikte import winapi as w

    print("Press keys to see their codes (20 seconds, keys still reach your apps).")
    print("Use the printed value in config.toml, e.g. hotkey = \"vk:0x7C\"\n")

    def proc(code, wparam, lparam):
        if code >= 0 and wparam in (w.WM_KEYDOWN, w.WM_SYSKEYDOWN):
            info = C.cast(lparam, C.POINTER(w.KBDLLHOOKSTRUCT)).contents
            print(f"vk:{info.vkCode:#04x}   sc:{info.scanCode:#04x}", flush=True)
        return w.user32.CallNextHookEx(None, code, wparam, lparam)

    callback = w.HOOKPROC(proc)
    w.user32.SetWindowsHookExW(w.WH_KEYBOARD_LL, callback, w.kernel32.GetModuleHandleW(None), 0)
    msg = w.W.MSG()
    w.user32.SetTimer(None, 0, 200, None)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and w.user32.GetMessageW(C.byref(msg), None, 0, 0) > 0:
        w.user32.DispatchMessageW(C.byref(msg))
    return 0


def mic_test(seconds):
    import time

    from ydikte import audio, config, pipeline

    print("Microphones:")
    for name in audio.list_devices():
        print("  " + name)
    recorder = audio.Recorder(config.load_config()["audio"]["input_device"])
    errors = []
    start = time.monotonic()
    recorder.start(errors.append)
    time.sleep(seconds)
    pcm = recorder.finish().result(timeout=5)
    if errors:
        print("FAILED:", errors[0])
        return 1
    print(f"Recorded {len(pcm) / 32000:.2f}s of audio in {time.monotonic() - start:.2f}s.")
    print("Heard speech-level sound." if pipeline.has_speech_energy(pcm)
          else "Nothing loud enough to count as speech. Talk during the test, or check the mic.")
    return 0


def transcribe(path):
    import wave

    from ydikte import config, net, pipeline

    with wave.open(path, "rb") as wav:
        if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (16000, 1, 2):
            print("Need a 16 kHz, mono, 16-bit WAV file.")
            return 2
        pcm = wav.readframes(wav.getnframes())
    result = pipeline.process(pcm, config.load_config(), config.load_keys(), net.CancelToken())
    for warning in result.warnings:
        print("warning:", warning, file=sys.stderr)
    print(f"[{result.backend}, cleaned={result.cleaned}, "
          f"{ {k: round(v, 2) for k, v in result.timings.items()} }]", file=sys.stderr)
    print(result.text or f"(nothing: {result.skipped})")
    return 0


def main(argv):
    if len(argv) >= 1 and argv[0] in ("--keytest", "--mic-test", "--transcribe"):
        sys.stdout.reconfigure(encoding="utf-8")
        if argv[0] == "--keytest":
            return keytest()
        if argv[0] == "--mic-test":
            return mic_test(float(argv[1]) if len(argv) > 1 else 3.0)
        if len(argv) < 2:
            print(__doc__)
            return 2
        return transcribe(argv[1])
    if argv == ["--settings"]:
        from ydikte.settings_ui import run_settings
        return run_settings()
    if argv and argv != ["--relaunched"]:
        print(__doc__)
        return 2
    from ydikte.app import run_app
    return run_app(relaunched=bool(argv))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

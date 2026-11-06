"""End-to-end test on the real desktop: real hook, real whisper, real paste, real pill.

It opens its own small text window and only sends keys while that window has focus.
The clipboard is saved first and restored at the end. Audio comes from a WAV, not the mic.

  python tests/e2e.py path\\to\\speech.wav [screenshot folder]
"""

import ctypes as C
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from ctypes import wintypes as W
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ydikte import insert  # noqa: E402
from ydikte import winapi as w  # noqa: E402

RCTRL, ESC, F13, KEY_C = 0xA3, 0x1B, 0x7C, 0x43
GWL_WNDPROC = -4
WM_GETTEXT, WM_GETTEXTLENGTH, WM_SETTEXT = 0x0D, 0x0E, 0x0C
ES_MULTILINE, WS_OVERLAPPEDWINDOW, WS_VISIBLE, WS_CHILD = 0x4, 0xCF0000, 0x10000000, 0x40000000
user32 = w.user32
user32.FindWindowW.restype = W.HWND
user32.FindWindowW.argtypes = [W.LPCWSTR, W.LPCWSTR]
user32.SendMessageW.restype = w.LRESULT
user32.SendMessageW.argtypes = [W.HWND, W.UINT, w.WPARAM, C.c_void_p]
user32.SetFocus.restype = W.HWND
user32.SetFocus.argtypes = [W.HWND]
user32.GetKeyboardState.argtypes = [C.c_void_p]

results = []
seen_keys = []        # keys that got past YDikte's hook (ours is installed first, so runs after)


def key(vk, up=False):
    item = w.INPUT()
    item.type = w.INPUT_KEYBOARD
    item.u.ki = w.KEYBDINPUT(vk, 0, w.KEYEVENTF_KEYUP if up else 0, 0, 0)
    return item


class Target:
    """A window with a text box, on its own thread with its own message loop."""

    def __init__(self):
        self.ready = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()
        self.ready.wait(5)

    def _run(self):
        instance = w.kernel32.GetModuleHandleW(None)
        self.proc = w.WNDPROC(lambda h, m, a, b: user32.DefWindowProcW(h, m, a, b))
        cls = w.WNDCLASSW()
        cls.lpfnWndProc = self.proc
        cls.hInstance = instance
        cls.lpszClassName = "YDikteE2E"
        user32.RegisterClassW(C.byref(cls))
        self.hwnd = user32.CreateWindowExW(
            0, "YDikteE2E", "YDikte test window", WS_OVERLAPPEDWINDOW | WS_VISIBLE,
            60, 60, 640, 200, None, None, instance, None)
        self.edit = user32.CreateWindowExW(
            0, "EDIT", "", WS_CHILD | WS_VISIBLE | ES_MULTILINE, 0, 0, 620, 160,
            self.hwnd, None, instance, None)
        user32.SetFocus(self.edit)
        self.thread_id = w.kernel32.GetCurrentThreadId()
        self.ready.set()
        msg = W.MSG()
        while user32.GetMessageW(C.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(C.byref(msg))
            user32.DispatchMessageW(C.byref(msg))

    def text(self):
        length = user32.SendMessageW(self.edit, WM_GETTEXTLENGTH, 0, None)
        buffer = C.create_unicode_buffer(length + 1)
        user32.SendMessageW(self.edit, WM_GETTEXT, length + 1, buffer)
        return buffer.value

    def clear(self):
        user32.SendMessageW(self.edit, WM_SETTEXT, 0, C.c_wchar_p(""))

    def focus(self):
        for _ in range(10):
            if user32.GetForegroundWindow() == self.hwnd:
                return True
            array = (w.INPUT * 2)(key(0xE8), key(0xE8, up=True))  # gets past the foreground lock
            user32.SendInput(2, array, C.sizeof(w.INPUT))
            user32.SetForegroundWindow(self.hwnd)
            time.sleep(0.1)
        return user32.GetForegroundWindow() == self.hwnd

    def press(self, vk, up=False):
        """Only ever presses keys in our own window. Releases always go through,
        otherwise a lost focus would leave the key stuck down for the whole desktop."""
        if not up and user32.GetForegroundWindow() != self.hwnd and not self.focus():
            raise RuntimeError("test window lost focus, stopping so no keys go elsewhere")
        array = (w.INPUT * 1)(key(vk, up))
        user32.SendInput(1, array, C.sizeof(w.INPUT))

    def tap(self, vk, hold=0.05):
        self.press(vk)
        time.sleep(hold)
        self.press(vk, up=True)


def install_watch_hook():
    def proc(code, wparam, lparam):
        if code >= 0 and wparam in (w.WM_KEYDOWN, w.WM_SYSKEYDOWN):
            info = C.cast(lparam, C.POINTER(w.KBDLLHOOKSTRUCT)).contents
            if info.dwExtraInfo != insert.INPUT_MARKER or info.vkCode == ESC:
                seen_keys.append(info.vkCode)   # Esc may be re-sent by YDikte without Ctrl
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def run():
        callback = w.HOOKPROC(proc)
        user32.SetWindowsHookExW(w.WH_KEYBOARD_LL, callback, w.kernel32.GetModuleHandleW(None), 0)
        msg = W.MSG()
        while user32.GetMessageW(C.byref(msg), None, 0, 0) > 0:
            pass
    threading.Thread(target=run, daemon=True).start()
    time.sleep(0.3)


class MockLLM(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        raw = body["messages"][1]["content"].removeprefix("<transcript>").removesuffix("</transcript>")
        data = json.dumps({"choices": [{"message": {"content": "CLEANED: " + raw}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def wait_for(predicate, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def check(name, passed, detail=""):
    results.append((name, passed))
    print(f"{'PASS' if passed else 'FAIL'}  {name}" + (f"   ({detail})" if detail else ""), flush=True)


def whisper_running():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq whisper-cli.exe", "/NH"],
                         capture_output=True, text=True).stdout
    return "whisper-cli" in out


def screenshot(folder, name):
    if not folder:
        return
    info = w.MONITORINFO()
    info.cbSize = C.sizeof(info)
    monitor = user32.MonitorFromWindow(user32.GetForegroundWindow(), w.MONITOR_DEFAULTTONEAREST)
    user32.GetMonitorInfoW(monitor, C.byref(info))
    work = info.rcWork
    width, height = 620, 110    # just the strip where the pill sits
    left = (work.left + work.right - width) // 2
    top = work.bottom - height
    path = os.path.join(folder, name + ".png")
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Add-Type -AssemblyName System.Drawing;"
                    f"$b=New-Object Drawing.Bitmap {width},{height};"
                    "$g=[Drawing.Graphics]::FromImage($b);"
                    f"$g.CopyFromScreen({left},{top},0,0,$b.Size,[Drawing.CopyPixelOperation]::SourceCopy);"
                    f"$b.Save('{path}')"], capture_output=True)


def config_text(hotkey="rctrl", restore=False, max_secs=300, mock_port=None):
    llm = (f'provider = "custom"\nbase_url = "http://127.0.0.1:{mock_port}/v1"\nmodel = "mock"\n'
           if mock_port else 'provider = "none"\n')
    return (f'hotkey = "{hotkey}"\n[timing]\nmax_recording_secs = {max_secs}\n'
            f'[transcription.local]\nexe = "{(ROOT / "whisper/bin/whisper-cli.exe").as_posix()}"\n'
            f'model = "{(ROOT / "whisper/models/ggml-small.bin").as_posix()}"\n'
            f'[insert]\nrestore_clipboard = {str(restore).lower()}\n[llm]\n{llm}')


def main():
    wav = sys.argv[1]
    shots = sys.argv[2] if len(sys.argv) > 2 else None
    install_watch_hook()
    saved_clipboard = insert.save_clipboard()
    workdir = tempfile.mkdtemp(prefix="yd-e2e-")   # not "ydikte-": the app sweeps those
    cfg = Path(workdir) / "config.toml"
    cfg.write_text(config_text(), encoding="utf-8")
    env = dict(os.environ, YDIKTE_E2E_WAV=wav, YDIKTE_E2E_CONFIG=str(cfg))
    app = subprocess.Popen([sys.executable, str(ROOT / "tests" / "e2e_app.py")], env=env)
    target = Target()
    try:
        time.sleep(2.0)
        check("app starts and stays running", app.poll() is None)
        check("test window has focus", target.focus())
        run_scenarios(target, cfg, shots)
    finally:
        for vk in (RCTRL, ESC, F13, KEY_C):
            if user32.GetAsyncKeyState(vk) & 0x8000:
                target.press(vk, up=True)
        app.terminate()
        user32.PostThreadMessageW(target.thread_id, 0x12, 0, 0)
        insert.restore_clipboard(saved_clipboard)
        log = cfg.with_name("config.toml.log")
        if log.exists():
            errors = [l for l in log.read_text(encoding="utf-8").splitlines() if " ERROR " in l or "Traceback" in l]
            check("no errors in the app log", not errors, "; ".join(errors)[:300])
            print("\n--- app log ---\n" + log.read_text(encoding="utf-8")[-1800:])
    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


def reload_config(cfg, **kw):
    cfg.write_text(config_text(**kw), encoding="utf-8")
    time.sleep(2.6)       # the app polls every 2 seconds


def run_scenarios(t, cfg, shots):
    words = "dictation"

    # Hold to talk
    t.press(RCTRL)
    time.sleep(0.7)
    screenshot(shots, "pill_hold")
    t.press(RCTRL, up=True)
    time.sleep(0.15)
    screenshot(shots, "pill_busy")
    start = time.monotonic()
    pasted = wait_for(lambda: words in t.text(), 200)
    check("hold-to-talk transcribes and pastes", pasted, f"{time.monotonic() - start:.1f}s: {t.text()[:70]!r}")
    check("transcript stays on the clipboard", words in (insert.get_clipboard_text() or ""))
    check("trailing space added", t.text().endswith(" "))
    screenshot(shots, "pill_after")

    # A single tap does nothing
    t.clear()
    t.tap(RCTRL)
    time.sleep(1.0)
    check("single tap does nothing", t.text() == "" and not whisper_running())

    # RightCtrl+C is a shortcut, not dictation, and it still reaches the app
    seen_keys.clear()
    t.press(RCTRL)
    time.sleep(0.03)
    t.tap(KEY_C)
    t.press(RCTRL, up=True)
    time.sleep(0.8)
    check("Ctrl+C with the hotkey is not dictated", t.text() == "" and not whisper_running())
    check("Ctrl+C still reaches the app", KEY_C in seen_keys and RCTRL in seen_keys)

    # Double-tap: hands-free, nothing held, a third tap stops
    time.sleep(0.5)
    t.tap(RCTRL)
    time.sleep(0.1)
    t.tap(RCTRL)
    time.sleep(1.4)
    screenshot(shots, "pill_hands_free")
    check("hands-free does not stop by itself", t.text() == "" and not whisper_running())
    t.tap(RCTRL)
    check("third tap stops and pastes", wait_for(lambda: words in t.text(), 200), repr(t.text()[:50]))

    # Esc during a held recording
    t.clear()
    time.sleep(0.5)
    seen_keys.clear()
    t.press(RCTRL)
    time.sleep(0.5)
    t.tap(ESC)
    time.sleep(0.05)
    screenshot(shots, "pill_cancelled")
    t.press(RCTRL, up=True)
    time.sleep(1.2)
    check("Esc drops a held recording", t.text() == "" and not whisper_running())
    check("Esc still reaches the focused app", ESC in seen_keys)
    check("Esc with the hotkey held does not open Start", user32.GetForegroundWindow() == t.hwnd)

    # Esc during hands-free
    t.tap(RCTRL)
    time.sleep(0.1)
    t.tap(RCTRL)
    time.sleep(0.6)
    t.tap(ESC)
    time.sleep(1.0)
    check("Esc drops a hands-free recording", t.text() == "" and not whisper_running())

    # Esc while whisper is running kills the process
    t.press(RCTRL)
    time.sleep(0.5)
    t.press(RCTRL, up=True)
    started = wait_for(whisper_running, 15)
    check("whisper-cli starts", started)
    time.sleep(0.3)
    t.tap(ESC)
    start = time.monotonic()
    gone = wait_for(lambda: not whisper_running(), 3)
    check("Esc kills a running transcription", gone, f"{time.monotonic() - start:.2f}s")
    time.sleep(1.5)
    check("a cancelled transcription pastes nothing", t.text() == "")

    # Settings hot reload, auto-stop
    reload_config(cfg, max_secs=2)
    t.tap(RCTRL)
    time.sleep(0.1)
    t.tap(RCTRL)
    check("auto-stop ends a forgotten session and pastes",
          wait_for(lambda: words in t.text(), 200), repr(t.text()[:50]))

    # Restore clipboard mode: the paste happens, the old clipboard comes back
    t.clear()
    reload_config(cfg, restore=True)
    insert.set_clipboard_text("my previous clipboard")
    t.press(RCTRL)
    time.sleep(0.5)
    t.press(RCTRL, up=True)
    check("restore mode still pastes", wait_for(lambda: words in t.text(), 200))
    back = wait_for(lambda: insert.get_clipboard_text() == "my previous clipboard", 3)
    check("restore mode brings the old clipboard back", back, repr(insert.get_clipboard_text()))

    # LLM cleanup goes through and is what gets pasted
    t.clear()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), MockLLM)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    reload_config(cfg, mock_port=server.server_port)
    t.press(RCTRL)
    time.sleep(0.5)
    t.press(RCTRL, up=True)
    check("LLM output is what gets pasted", wait_for(lambda: "CLEANED:" in t.text(), 200), repr(t.text()[:60]))

    # A non-modifier hotkey is swallowed, so the app never sees it
    t.clear()
    reload_config(cfg, hotkey="f13")
    seen_keys.clear()
    t.press(F13)
    time.sleep(0.5)
    t.press(F13, up=True)
    check("F13 hotkey works after reload", wait_for(lambda: words in t.text(), 200))
    check("F13 is swallowed", F13 not in seen_keys)

    terminal_scenario(t, cfg, words)


def terminal_scenario(t, cfg, words):
    """A raw-mode console app receives Ctrl+V as a control character, so text must be typed."""
    reload_config(cfg)
    out = str(cfg.with_name("raw.bin"))
    title = "YDIKTE E2E CONSOLE"
    console = subprocess.Popen(["node", str(ROOT / "tests" / "rawreader.js"), out, title],
                               creationflags=subprocess.CREATE_NEW_CONSOLE)
    try:
        time.sleep(2.0)
        hwnd = user32.FindWindowW(None, title)
        check("console window opens", bool(hwnd))
        t.hwnd, own = hwnd, t.hwnd     # press() now guards this window instead
        check("console window has focus", t.focus())
        insert.set_clipboard_text("marker")
        t.press(RCTRL)
        time.sleep(0.5)
        t.press(RCTRL, up=True)

        def received():
            return open(out, "rb").read().decode("utf-8", "replace") if os.path.exists(out) else ""

        check("text is typed into a raw console", wait_for(lambda: words in received() and received().endswith(" "), 200),
              repr(received()[:60]))
        check("no Ctrl+V control character reached it", "\x16" not in received())
        check("no Enter reached it", "\r" not in received() and "\n" not in received())
        check("transcript is still on the clipboard", words in (insert.get_clipboard_text() or ""))
        t.hwnd = own
    finally:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(console.pid)], capture_output=True)


if __name__ == "__main__":
    sys.exit(main())

"""The system-wide keyboard hook, on its own thread so nothing can delay the keyboard.

Every keystroke on the PC passes through this callback, so it must stay tiny. It
looks at key codes only, never stores what was typed, and passes Esc along.
"""

import ctypes as C
import threading
import time

from . import winapi as w
from .hotkey import VK_ESCAPE, Matcher
from .insert import INPUT_MARKER

_WM_REHOOK = w.WM_APP + 1


class KeyboardHook:
    def __init__(self, parts, on_events, on_esc_rewrite):
        """Both callbacks run on the hook thread and must not block.

        `on_events(list of events, time)` reports hotkey events.
        `on_esc_rewrite(held VKs)` means Esc was held back and must be re-sent.
        """
        self.on_events = on_events
        self.on_esc_rewrite = on_esc_rewrite
        self.enabled = True
        self._lock = threading.Lock()
        self._matcher = Matcher(parts)
        self._proc = w.HOOKPROC(self._callback)   # must outlive the hook
        self._handle = None
        self._thread_id = None
        self._ready = threading.Event()
        threading.Thread(target=self._run, name="keyboard-hook", daemon=True).start()
        self._ready.wait(5)

    def set_parts(self, parts):
        with self._lock:
            self._matcher = Matcher(parts)

    @property
    def only_modifiers(self):
        return self._matcher.only_modifiers

    @property
    def needs_mask(self):
        return self._matcher.needs_mask

    def set_enabled(self, enabled):
        with self._lock:
            self.enabled = enabled
            self._matcher.reset()

    def prune(self):
        """Catch a key-up the hook never saw. Call this periodically while recording."""
        with self._lock:
            events = self._matcher.prune(_physically_down)
        if events:
            self.on_events(events, time.monotonic())

    def rehook(self):
        """Windows silently drops a hook that was slow once, so renew it from time to time."""
        if self._thread_id:
            w.user32.PostThreadMessageW(self._thread_id, _WM_REHOOK, 0, 0)

    def _install(self):
        self._handle = w.user32.SetWindowsHookExW(
            w.WH_KEYBOARD_LL, self._proc, w.kernel32.GetModuleHandleW(None), 0)

    def _run(self):
        self._thread_id = w.kernel32.GetCurrentThreadId()
        self._install()
        self._ready.set()
        msg = w.W.MSG()
        while w.user32.GetMessageW(C.byref(msg), None, 0, 0) > 0:
            if msg.message == _WM_REHOOK:
                old = self._handle
                self._install()
                w.user32.UnhookWindowsHookEx(old)

    def _callback(self, code, wparam, lparam):
        swallow = False
        if code >= 0:
            try:
                swallow = self._handle_key(wparam, lparam)
            except Exception:
                swallow = False
        if swallow:
            return 1
        return w.user32.CallNextHookEx(None, code, wparam, lparam)

    def _handle_key(self, wparam, lparam):
        if not self.enabled:
            return False
        info = C.cast(lparam, C.POINTER(w.KBDLLHOOKSTRUCT)).contents
        if info.dwExtraInfo == INPUT_MARKER:
            return False
        is_down = wparam in (w.WM_KEYDOWN, w.WM_SYSKEYDOWN)
        vk, sc = info.vkCode, info.scanCode
        with self._lock:
            if is_down:
                self._matcher.prune(_physically_down, skip=vk)
            held = self._matcher.held_modifiers() if vk == VK_ESCAPE and is_down else []
            swallow, events = self._matcher.on_key(vk, sc, is_down)
        if events:
            self.on_events(events, time.monotonic())
        if held:
            # Passing Esc on now would make Ctrl+Esc and open Start. The app still
            # gets its Esc: the main thread re-sends it without the modifiers.
            self.on_esc_rewrite(held)
            return True
        return swallow


def _physically_down(vk):
    return bool(w.user32.GetAsyncKeyState(vk) & 0x8000)

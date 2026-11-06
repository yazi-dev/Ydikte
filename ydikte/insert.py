"""Put text on the clipboard and paste it into the focused app."""

import ctypes as C
import logging
import re
import time
from ctypes import wintypes as W

from . import winapi as w

log = logging.getLogger("ydikte")

# Our own synthetic keystrokes carry this mark so the hook ignores them.
INPUT_MARKER = 0x59444B54

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x2
VK_CONTROL, VK_V, VK_ESCAPE = 0x11, 0x56, 0x1B
VK_MASK = 0xE8     # unassigned key, stops a lone Win or Alt from opening Start or a menu
_MODIFIERS = (0x10, 0x11, 0x12, 0x5B, 0x5C)  # shift, ctrl, alt, lwin, rwin
# Handles that are not global memory. CF_DIB covers bitmaps when it is offered.
_SKIP_FORMATS = {2, 3, 9, 14, 0x80, 0x81, 0x82, 0x83, 0x8E}
_MAX_SAVE_BYTES = 64 * 1024 * 1024
KEYEVENTF_UNICODE = 0x4
TYPE_CHUNK = 48
TYPE_FAILED = "Metin yazılamadı."
# Windows Terminal, classic console, Git Bash's mintty, ConEmu, PuTTY, Alacritty, WezTerm.
TERMINAL_CLASSES = {
    "CASCADIA_HOSTING_WINDOW_CLASS", "ConsoleWindowClass", "PseudoConsoleWindow", "mintty",
    "VirtualConsoleClass", "PuTTY", "Alacritty", "org.wezfurlong.wezterm",
}
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x8
TokenElevation = 20


class _Clipboard:
    """Context manager: the clipboard is a shared lock, so retry while others hold it."""

    def __enter__(self):
        for _ in range(40):
            if w.user32.OpenClipboard(None):
                return self
            time.sleep(0.025)
        raise OSError("clipboard is busy")

    def __exit__(self, *exc):
        w.user32.CloseClipboard()


def _global_from(data):
    handle = w.kernel32.GlobalAlloc(GMEM_MOVEABLE, max(len(data), 1))
    if not handle:
        raise MemoryError("GlobalAlloc failed")
    pointer = w.kernel32.GlobalLock(handle)
    C.memmove(pointer, data, len(data))
    w.kernel32.GlobalUnlock(handle)
    return handle


def _set_format(fmt, data):
    handle = _global_from(data)
    if not w.user32.SetClipboardData(fmt, handle):
        w.kernel32.GlobalFree(handle)


def save_clipboard():
    """Snapshot every memory-backed format. Returns [(format, bytes)]."""
    saved = []
    total = 0
    with _Clipboard():
        fmt = w.user32.EnumClipboardFormats(0)
        while fmt:
            if fmt not in _SKIP_FORMATS and not (0x200 <= fmt <= 0x3FF):
                handle = w.user32.GetClipboardData(fmt)
                size = w.kernel32.GlobalSize(handle) if handle else 0
                pointer = w.kernel32.GlobalLock(handle) if size else None
                if pointer:
                    if total + size <= _MAX_SAVE_BYTES:
                        saved.append((fmt, C.string_at(pointer, size)))
                        total += size
                    w.kernel32.GlobalUnlock(handle)
            fmt = w.user32.EnumClipboardFormats(fmt)
    return saved


def restore_clipboard(saved):
    with _Clipboard():
        w.user32.EmptyClipboard()
        for fmt, data in saved:
            _set_format(fmt, data)


def set_clipboard_text(text, private=False):
    """`private` keeps the text out of Win+V history, for restore-clipboard mode."""
    data = text.encode("utf-16-le") + b"\0\0"
    with _Clipboard():
        w.user32.EmptyClipboard()
        _set_format(CF_UNICODETEXT, data)
        if private:
            exclude = w.user32.RegisterClipboardFormatW("CanIncludeInClipboardHistory")
            _set_format(exclude, b"\0\0\0\0")


def get_clipboard_text():
    with _Clipboard():
        handle = w.user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        pointer = w.kernel32.GlobalLock(handle)
        try:
            return C.wstring_at(pointer)
        finally:
            w.kernel32.GlobalUnlock(handle)


def _key(vk, up=False):
    item = w.INPUT()
    item.type = w.INPUT_KEYBOARD
    item.u.ki = w.KEYBDINPUT(vk, 0, w.KEYEVENTF_KEYUP if up else 0, 0, INPUT_MARKER)
    return item


def _send(*items):
    array = (w.INPUT * len(items))(*items)
    return w.user32.SendInput(len(items), array, C.sizeof(w.INPUT))


def send_mask_key():
    _send(_key(VK_MASK), _key(VK_MASK, up=True))


def send_plain_esc(held_modifiers):
    """Deliver Esc without the held hotkey modifiers, which would make it Ctrl+Esc (Start menu)."""
    _send(*(_key(vk, up=True) for vk in held_modifiers), _key(VK_ESCAPE))


def _wait_for_modifiers(cancel, timeout=1.5):
    """A held Shift or Alt would turn Ctrl+V into a different shortcut."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        cancel.check()
        if not any(w.user32.GetAsyncKeyState(vk) & 0x8000 for vk in _MODIFIERS):
            return
        time.sleep(0.02)


def foreground_blocks_input():
    """True if the focused window runs elevated. Windows drops our keystrokes to it silently."""
    hwnd = w.user32.GetForegroundWindow()
    if not hwnd:
        return False
    pid = W.DWORD()
    w.user32.GetWindowThreadProcessId(hwnd, C.byref(pid))
    process = w.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not process:
        return _self_is_elevated() is False
    try:
        token = W.HANDLE()
        if not w.advapi32.OpenProcessToken(process, TOKEN_QUERY, C.byref(token)):
            return _self_is_elevated() is False
        try:
            elevated = W.DWORD()
            size = W.DWORD()
            w.advapi32.GetTokenInformation(token, TokenElevation, C.byref(elevated), 4, C.byref(size))
            return bool(elevated.value) and _self_is_elevated() is False
        finally:
            w.kernel32.CloseHandle(token)
    finally:
        w.kernel32.CloseHandle(process)


def _self_is_elevated():
    token = W.HANDLE()
    if not w.advapi32.OpenProcessToken(w.kernel32.GetCurrentProcess(), TOKEN_QUERY, C.byref(token)):
        return False
    try:
        elevated = W.DWORD()
        size = W.DWORD()
        w.advapi32.GetTokenInformation(token, TokenElevation, C.byref(elevated), 4, C.byref(size))
        return bool(elevated.value)
    finally:
        w.kernel32.CloseHandle(token)


def foreground_is_terminal():
    hwnd = w.user32.GetForegroundWindow()
    if not hwnd:
        return False
    name = C.create_unicode_buffer(128)
    w.user32.GetClassNameW(hwnd, name, 128)
    return name.value in TERMINAL_CLASSES


def type_for_terminal(text):
    """Line breaks become spaces: a typed Enter would submit the line."""
    return re.sub(r"[\r\n]+", " ", text)


def type_text(text, cancel):
    """Send text as Unicode keystrokes, which any keyboard layout and console accepts."""
    data = text.encode("utf-16-le")
    units = [int.from_bytes(data[i:i + 2], "little") for i in range(0, len(data), 2)]
    for start in range(0, len(units), TYPE_CHUNK):
        cancel.check()
        items = []
        for unit in units[start:start + TYPE_CHUNK]:
            for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | w.KEYEVENTF_KEYUP):
                item = w.INPUT()
                item.type = w.INPUT_KEYBOARD
                item.u.ki = w.KEYBDINPUT(0, unit, flags, 0, INPUT_MARKER)
                items.append(item)
        if _send(*items) != len(items):
            return False
        time.sleep(0.004)   # lets a slow console keep up
    return True


def insert_text(text, restore, cancel, method="auto", settle=0.03, restore_delay=0.6):
    """Returns a warning for the user, or None."""
    cancel.check()
    _wait_for_modifiers(cancel)
    cancel.check()
    blocked = foreground_blocks_input()
    typing = not blocked and (method == "type" or (method == "auto" and foreground_is_terminal()))
    if typing and restore:
        # Typing needs no clipboard, so there is nothing to restore.
        return None if type_text(type_for_terminal(text), cancel) else TYPE_FAILED
    saved = None
    if restore and not blocked:
        try:
            saved = save_clipboard()
        except OSError as exc:
            log.warning("could not save the clipboard: %s", exc)
    set_clipboard_text(text, private=restore and not blocked)
    if blocked:
        return ("Bu pencere yönetici olarak çalışıyor, Windows yapıştırmayı engelledi. Metin panoda: Ctrl+V'ye bas. "
                "Kalıcı çözüm: Ayarlar > Yönetici pencerelerinde de çalış.")
    if typing:
        return None if type_text(type_for_terminal(text), cancel) else TYPE_FAILED
    our_copy = w.user32.GetClipboardSequenceNumber()
    time.sleep(settle)
    if _send(_key(VK_CONTROL), _key(VK_V), _key(VK_V, up=True), _key(VK_CONTROL, up=True)) != 4:
        return "Yapıştırma tuşu gönderilemedi. Metin panoda."
    if saved is not None:
        time.sleep(restore_delay)  # the target app reads the clipboard after it gets Ctrl+V
        if w.user32.GetClipboardSequenceNumber() == our_copy:  # not if the user copied since
            restore_clipboard(saved)
    return None

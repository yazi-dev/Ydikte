"""Tray icon, its menu, and the launch-at-login registry value."""

import ctypes as C
import sys
import winreg
from pathlib import Path

from . import winapi as w
from .config import ASSETS, HOME

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE = "YDikte"
WM_TRAY = w.WM_USER + 20


def login_command():
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else Path(sys.executable)
    return f'"{interpreter}" "{HOME / "ydikte.pyw"}"'


def login_enabled(value=_RUN_VALUE):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, value)
        return True
    except OSError:
        return False


def set_login(enabled, value=_RUN_VALUE):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, value, 0, winreg.REG_SZ, login_command())
        elif login_enabled(value):
            winreg.DeleteValue(key, value)


def load_icon(name):
    """Loads assets/<name>.ico at the exact size the tray uses on this display."""
    side = w.user32.GetSystemMetrics(49)    # SM_CXSMICON, scaled for DPI
    return w.user32.LoadImageW(None, str(ASSETS / f"{name}.ico"), 1, side, side, 0x10)  # LR_LOADFROMFILE


class Tray:
    def __init__(self, hwnd):
        self.hwnd = hwnd
        self._data = w.NOTIFYICONDATAW()
        self._data.cbSize = C.sizeof(self._data)
        self._data.hWnd = hwnd
        self._data.uID = 1
        self._data.uFlags = w.NIF_MESSAGE | w.NIF_ICON | w.NIF_TIP
        self._data.uCallbackMessage = WM_TRAY
        self.added = False

    def set(self, icon, tip):
        self._data.hIcon = icon
        self._data.szTip = tip[:127]
        self._data.uFlags = w.NIF_MESSAGE | w.NIF_ICON | w.NIF_TIP
        command = w.NIM_MODIFY if self.added else w.NIM_ADD
        self.added = bool(w.shell32.Shell_NotifyIconW(command, C.byref(self._data))) or self.added

    def readd(self):
        """Explorer restarted and forgot the icon."""
        self.added = False
        self.set(self._data.hIcon, self._data.szTip)

    def notify(self, title, message, warning=False):
        self._data.uFlags = w.NIF_INFO
        self._data.szInfoTitle = title[:63]
        self._data.szInfo = message[:255]
        self._data.dwInfoFlags = w.NIIF_WARNING if warning else w.NIIF_INFO
        w.shell32.Shell_NotifyIconW(w.NIM_MODIFY, C.byref(self._data))
        self._data.szInfo = ""

    def remove(self):
        if self.added:
            w.shell32.Shell_NotifyIconW(w.NIM_DELETE, C.byref(self._data))
            self.added = False

    def popup(self, items):
        """`items` are (id, label, flags), or None for a separator. Returns the chosen id or 0."""
        menu = w.user32.CreatePopupMenu()
        for item in items:
            if item is None:
                w.user32.AppendMenuW(menu, w.MF_SEPARATOR, 0, None)
            else:
                command, label, flags = item
                w.user32.AppendMenuW(menu, flags, command, label)
        point = w.W.POINT()
        w.user32.GetCursorPos(C.byref(point))
        # Without this the menu would not close when clicking elsewhere.
        w.user32.SetForegroundWindow(self.hwnd)
        chosen = w.user32.TrackPopupMenu(
            menu, w.TPM_RETURNCMD | w.TPM_NONOTIFY | w.TPM_RIGHTBUTTON,
            point.x, point.y, 0, self.hwnd, None)
        w.user32.PostMessageW(self.hwnd, w.WM_NULL, 0, 0)
        w.user32.DestroyMenu(menu)
        return chosen

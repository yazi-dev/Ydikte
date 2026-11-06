"""Running with administrator rights, so YDikte also works over elevated windows.

Windows does not let a normal process see keys in, or send keys to, an elevated
window. The only way over those windows is to be elevated too. This is opt-in and
Windows asks for consent (UAC) at every start: no scheduled task or other silent
elevation is created, because the code lives in a folder any normal program can write to.
"""

import ctypes as C
import logging
import subprocess
import sys
from ctypes import wintypes as W
from pathlib import Path

from . import winapi as w
from .config import HOME

log = logging.getLogger("ydikte")

w.shell32.ShellExecuteW.restype = W.HINSTANCE
w.shell32.ShellExecuteW.argtypes = [W.HWND, W.LPCWSTR, W.LPCWSTR, W.LPCWSTR, W.LPCWSTR, C.c_int]
SHORTCUT = HOME / "YDikte.lnk"


def pythonw():
    path = Path(sys.executable).with_name("pythonw.exe")
    return path if path.exists() else Path(sys.executable)


def is_elevated():
    token = W.HANDLE()
    if not w.advapi32.OpenProcessToken(w.kernel32.GetCurrentProcess(), 0x8, C.byref(token)):
        return False
    try:
        elevated = W.DWORD()
        size = W.DWORD()
        w.advapi32.GetTokenInformation(token, 20, C.byref(elevated), 4, C.byref(size))
        return bool(elevated.value)
    finally:
        w.kernel32.CloseHandle(token)


def relaunch_elevated():
    """Shows the UAC prompt. Returns True if the elevated copy was started."""
    params = f'"{HOME / "ydikte.pyw"}" --relaunched'
    result = w.shell32.ShellExecuteW(None, "runas", str(pythonw()), params, str(HOME), 1)
    started = (result or 0) > 32 if isinstance(result, int) or result is None else True
    log.info("elevation %s", "accepted" if started else "declined")
    return started


def relaunch_normal():
    """Go back to normal rights. Explorer runs what it opens at its own, normal, level.

    The one-second delay lets this process exit first, because the new copy would
    otherwise see it still running and step aside.
    """
    if not SHORTCUT.exists():
        return False
    subprocess.Popen(f'cmd /c ping -n 2 127.0.0.1 >nul & explorer.exe "{SHORTCUT}"',
                     creationflags=subprocess.CREATE_NO_WINDOW)
    return True

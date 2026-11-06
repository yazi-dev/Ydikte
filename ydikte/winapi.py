"""ctypes declarations for the Win32 functions YDikte uses."""

import ctypes as C
from ctypes import wintypes as W

LRESULT = C.c_ssize_t
WPARAM = C.c_size_t
LPARAM = C.c_ssize_t
ULONG_PTR = C.c_size_t
UINT_PTR = C.c_size_t

user32 = C.WinDLL("user32", use_last_error=True)
kernel32 = C.WinDLL("kernel32", use_last_error=True)
gdi32 = C.WinDLL("gdi32", use_last_error=True)
shell32 = C.WinDLL("shell32", use_last_error=True)
advapi32 = C.WinDLL("advapi32", use_last_error=True)
winmm = C.WinDLL("winmm", use_last_error=True)
gdiplus = C.WinDLL("gdiplus")
shcore = C.WinDLL("shcore")
wtsapi32 = C.WinDLL("wtsapi32", use_last_error=True)

# Keyboard hook
WH_KEYBOARD_LL = 13
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x100, 0x101, 0x104, 0x105
HOOKPROC = C.WINFUNCTYPE(LRESULT, C.c_int, WPARAM, LPARAM)


class KBDLLHOOKSTRUCT(C.Structure):
    _fields_ = [("vkCode", W.DWORD), ("scanCode", W.DWORD), ("flags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", ULONG_PTR)]


# SendInput
class KEYBDINPUT(C.Structure):
    _fields_ = [("wVk", W.WORD), ("wScan", W.WORD), ("dwFlags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(C.Structure):
    _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("mouseData", W.DWORD),
                ("dwFlags", W.DWORD), ("time", W.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _INPUTUNION(C.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(C.Structure):
    _fields_ = [("type", W.DWORD), ("u", _INPUTUNION)]


INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 2

# Windows
WNDPROC = C.WINFUNCTYPE(LRESULT, W.HWND, W.UINT, WPARAM, LPARAM)


class WNDCLASSW(C.Structure):
    _fields_ = [("style", W.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", C.c_int),
                ("cbWndExtra", C.c_int), ("hInstance", W.HINSTANCE), ("hIcon", W.HANDLE),
                ("hCursor", W.HANDLE), ("hbrBackground", W.HANDLE),
                ("lpszMenuName", W.LPCWSTR), ("lpszClassName", W.LPCWSTR)]


WM_DESTROY, WM_TIMER, WM_COMMAND, WM_NULL = 0x2, 0x113, 0x111, 0x0
WM_USER, WM_APP = 0x400, 0x8000
WM_RBUTTONUP, WM_LBUTTONUP = 0x205, 0x202
WM_WTSSESSION_CHANGE = 0x2B1
WTS_SESSION_LOCK, WTS_SESSION_UNLOCK = 7, 8
WS_POPUP = 0x80000000
WS_EX_TOPMOST, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW = 0x8, 0x20, 0x80
WS_EX_LAYERED, WS_EX_NOACTIVATE = 0x80000, 0x8000000
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
HWND_TOPMOST = W.HWND(-1)
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x1, 0x2, 0x10
ULW_ALPHA = 2
MONITOR_DEFAULTTONEAREST = 2
MB_ICONWARNING = 0x30


class BLENDFUNCTION(C.Structure):
    _fields_ = [("BlendOp", C.c_ubyte), ("BlendFlags", C.c_ubyte),
                ("SourceConstantAlpha", C.c_ubyte), ("AlphaFormat", C.c_ubyte)]


class MONITORINFO(C.Structure):
    _fields_ = [("cbSize", W.DWORD), ("rcMonitor", W.RECT),
                ("rcWork", W.RECT), ("dwFlags", W.DWORD)]


class BITMAPINFOHEADER(C.Structure):
    _fields_ = [("biSize", W.DWORD), ("biWidth", W.LONG), ("biHeight", W.LONG),
                ("biPlanes", W.WORD), ("biBitCount", W.WORD), ("biCompression", W.DWORD),
                ("biSizeImage", W.DWORD), ("biXPelsPerMeter", W.LONG),
                ("biYPelsPerMeter", W.LONG), ("biClrUsed", W.DWORD), ("biClrImportant", W.DWORD)]


def _sig(dll, name, res, *args):
    fn = getattr(dll, name)
    fn.restype = res
    fn.argtypes = args
    return fn


PV = C.c_void_p
_sig(user32, "SetWindowsHookExW", W.HHOOK, C.c_int, HOOKPROC, W.HINSTANCE, W.DWORD)
_sig(user32, "UnhookWindowsHookEx", W.BOOL, W.HHOOK)
_sig(user32, "CallNextHookEx", LRESULT, W.HHOOK, C.c_int, WPARAM, LPARAM)
_sig(user32, "GetMessageW", C.c_int, C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT)
_sig(user32, "TranslateMessage", W.BOOL, C.POINTER(W.MSG))
_sig(user32, "DispatchMessageW", LRESULT, C.POINTER(W.MSG))
_sig(user32, "PostMessageW", W.BOOL, W.HWND, W.UINT, WPARAM, LPARAM)
_sig(user32, "PostThreadMessageW", W.BOOL, W.DWORD, W.UINT, WPARAM, LPARAM)
_sig(user32, "PostQuitMessage", None, C.c_int)
_sig(user32, "GetAsyncKeyState", C.c_short, C.c_int)
_sig(user32, "SendInput", W.UINT, W.UINT, C.POINTER(INPUT), C.c_int)
_sig(user32, "RegisterClassW", W.ATOM, C.POINTER(WNDCLASSW))
_sig(user32, "CreateWindowExW", W.HWND, W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, C.c_int,
     C.c_int, C.c_int, C.c_int, W.HWND, W.HANDLE, W.HINSTANCE, PV)
_sig(user32, "DefWindowProcW", LRESULT, W.HWND, W.UINT, WPARAM, LPARAM)
_sig(user32, "DestroyWindow", W.BOOL, W.HWND)
_sig(user32, "ShowWindow", W.BOOL, W.HWND, C.c_int)
_sig(user32, "SetWindowPos", W.BOOL, W.HWND, W.HWND, C.c_int, C.c_int, C.c_int, C.c_int, W.UINT)
_sig(user32, "SetTimer", UINT_PTR, W.HWND, UINT_PTR, W.UINT, PV)
_sig(user32, "KillTimer", W.BOOL, W.HWND, UINT_PTR)
_sig(user32, "GetForegroundWindow", W.HWND)
_sig(user32, "SetForegroundWindow", W.BOOL, W.HWND)
_sig(user32, "GetClassNameW", C.c_int, W.HWND, W.LPWSTR, C.c_int)
_sig(user32, "FindWindowW", W.HWND, W.LPCWSTR, W.LPCWSTR)
_sig(user32, "LoadImageW", W.HANDLE, W.HINSTANCE, W.LPCWSTR, W.UINT, C.c_int, C.c_int, W.UINT)
_sig(user32, "ChangeWindowMessageFilterEx", W.BOOL, W.HWND, W.UINT, W.DWORD, C.c_void_p)
_sig(user32, "GetSystemMetrics", C.c_int, C.c_int)
_sig(user32, "GetWindowThreadProcessId", W.DWORD, W.HWND, C.POINTER(W.DWORD))
_sig(user32, "GetCursorPos", W.BOOL, C.POINTER(W.POINT))
_sig(user32, "MonitorFromWindow", W.HMONITOR, W.HWND, W.DWORD)
_sig(user32, "MonitorFromPoint", W.HMONITOR, W.POINT, W.DWORD)
_sig(user32, "GetMonitorInfoW", W.BOOL, W.HMONITOR, C.POINTER(MONITORINFO))
_sig(user32, "UpdateLayeredWindow", W.BOOL, W.HWND, W.HDC, C.POINTER(W.POINT), C.POINTER(W.SIZE),
     W.HDC, C.POINTER(W.POINT), W.DWORD, C.POINTER(BLENDFUNCTION), W.DWORD)
_sig(user32, "GetDC", W.HDC, W.HWND)
_sig(user32, "ReleaseDC", C.c_int, W.HWND, W.HDC)
_sig(user32, "CreatePopupMenu", W.HMENU)
_sig(user32, "AppendMenuW", W.BOOL, W.HMENU, W.UINT, UINT_PTR, W.LPCWSTR)
_sig(user32, "TrackPopupMenu", W.BOOL, W.HMENU, W.UINT, C.c_int, C.c_int, C.c_int, W.HWND, PV)
_sig(user32, "DestroyMenu", W.BOOL, W.HMENU)
_sig(user32, "DestroyIcon", W.BOOL, W.HICON)
_sig(user32, "RegisterWindowMessageW", W.UINT, W.LPCWSTR)
_sig(user32, "MessageBoxW", C.c_int, W.HWND, W.LPCWSTR, W.LPCWSTR, W.UINT)
_sig(user32, "SetProcessDpiAwarenessContext", W.BOOL, PV)
_sig(user32, "OpenClipboard", W.BOOL, W.HWND)
_sig(user32, "CloseClipboard", W.BOOL)
_sig(user32, "EmptyClipboard", W.BOOL)
_sig(user32, "SetClipboardData", W.HANDLE, W.UINT, W.HANDLE)
_sig(user32, "GetClipboardData", W.HANDLE, W.UINT)
_sig(user32, "EnumClipboardFormats", W.UINT, W.UINT)
_sig(user32, "GetClipboardSequenceNumber", W.DWORD)
_sig(user32, "RegisterClipboardFormatW", W.UINT, W.LPCWSTR)

_sig(kernel32, "GetModuleHandleW", W.HMODULE, W.LPCWSTR)
_sig(kernel32, "GetCurrentThreadId", W.DWORD)
_sig(kernel32, "CreateMutexW", W.HANDLE, PV, W.BOOL, W.LPCWSTR)
_sig(kernel32, "CreateEventW", W.HANDLE, PV, W.BOOL, W.BOOL, W.LPCWSTR)
_sig(kernel32, "WaitForSingleObject", W.DWORD, W.HANDLE, W.DWORD)
_sig(kernel32, "CloseHandle", W.BOOL, W.HANDLE)
_sig(kernel32, "GlobalAlloc", W.HGLOBAL, W.UINT, C.c_size_t)
_sig(kernel32, "GlobalLock", PV, W.HGLOBAL)
_sig(kernel32, "GlobalUnlock", W.BOOL, W.HGLOBAL)
_sig(kernel32, "GlobalFree", W.HGLOBAL, W.HGLOBAL)
_sig(kernel32, "GlobalSize", C.c_size_t, W.HGLOBAL)
_sig(kernel32, "OpenProcess", W.HANDLE, W.DWORD, W.BOOL, W.DWORD)
_sig(kernel32, "GetCurrentProcess", W.HANDLE)

_sig(advapi32, "OpenProcessToken", W.BOOL, W.HANDLE, W.DWORD, C.POINTER(W.HANDLE))
_sig(advapi32, "GetTokenInformation", W.BOOL, W.HANDLE, C.c_int, PV, W.DWORD, C.POINTER(W.DWORD))

_sig(gdi32, "CreateCompatibleDC", W.HDC, W.HDC)
_sig(gdi32, "DeleteDC", W.BOOL, W.HDC)
_sig(gdi32, "SelectObject", W.HGDIOBJ, W.HDC, W.HGDIOBJ)
_sig(gdi32, "DeleteObject", W.BOOL, W.HGDIOBJ)
_sig(gdi32, "CreateDIBSection", W.HBITMAP, W.HDC, PV, W.UINT, C.POINTER(PV), W.HANDLE, W.DWORD)

_sig(shcore, "GetDpiForMonitor", C.c_long, W.HMONITOR, C.c_int, C.POINTER(W.UINT), C.POINTER(W.UINT))
_sig(shell32, "SetCurrentProcessExplicitAppUserModelID", C.c_long, W.LPCWSTR)
_sig(wtsapi32, "WTSRegisterSessionNotification", W.BOOL, W.HWND, W.DWORD)
_sig(wtsapi32, "WTSUnRegisterSessionNotification", W.BOOL, W.HWND)


# Tray icon
class NOTIFYICONDATAW(C.Structure):
    _fields_ = [("cbSize", W.DWORD), ("hWnd", W.HWND), ("uID", W.UINT), ("uFlags", W.UINT),
                ("uCallbackMessage", W.UINT), ("hIcon", W.HICON), ("szTip", W.WCHAR * 128),
                ("dwState", W.DWORD), ("dwStateMask", W.DWORD), ("szInfo", W.WCHAR * 256),
                ("uVersion", W.UINT), ("szInfoTitle", W.WCHAR * 64), ("dwInfoFlags", W.DWORD),
                ("guidItem", C.c_byte * 16), ("hBalloonIcon", W.HICON)]


_sig(shell32, "Shell_NotifyIconW", W.BOOL, W.DWORD, C.POINTER(NOTIFYICONDATAW))
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 1, 2, 4, 0x10
NIIF_INFO, NIIF_WARNING = 1, 2
MF_STRING, MF_GRAYED, MF_CHECKED, MF_SEPARATOR = 0, 1, 8, 0x800
TPM_RETURNCMD, TPM_NONOTIFY, TPM_RIGHTBUTTON = 0x100, 0x80, 0x2


# waveIn
class WAVEFORMATEX(C.Structure):
    _fields_ = [("wFormatTag", W.WORD), ("nChannels", W.WORD), ("nSamplesPerSec", W.DWORD),
                ("nAvgBytesPerSec", W.DWORD), ("nBlockAlign", W.WORD),
                ("wBitsPerSample", W.WORD), ("cbSize", W.WORD)]


class WAVEHDR(C.Structure):
    pass


WAVEHDR._fields_ = [("lpData", PV), ("dwBufferLength", W.DWORD), ("dwBytesRecorded", W.DWORD),
                    ("dwUser", ULONG_PTR), ("dwFlags", W.DWORD), ("dwLoops", W.DWORD),
                    ("lpNext", C.POINTER(WAVEHDR)), ("reserved", ULONG_PTR)]


class WAVEINCAPSW(C.Structure):
    _fields_ = [("wMid", W.WORD), ("wPid", W.WORD), ("vDriverVersion", W.UINT),
                ("szPname", W.WCHAR * 32), ("dwFormats", W.DWORD),
                ("wChannels", W.WORD), ("wReserved1", W.WORD)]


WAVE_MAPPER = 0xFFFFFFFF
WAVE_FORMAT_PCM = 1
CALLBACK_EVENT = 0x50000
WHDR_DONE = 1
_sig(winmm, "waveInGetNumDevs", W.UINT)
_sig(winmm, "waveInGetDevCapsW", W.UINT, UINT_PTR, C.POINTER(WAVEINCAPSW), W.UINT)
_sig(winmm, "waveInOpen", W.UINT, C.POINTER(W.HANDLE), W.UINT, C.POINTER(WAVEFORMATEX),
     ULONG_PTR, ULONG_PTR, W.DWORD)
_sig(winmm, "waveInPrepareHeader", W.UINT, W.HANDLE, C.POINTER(WAVEHDR), W.UINT)
_sig(winmm, "waveInUnprepareHeader", W.UINT, W.HANDLE, C.POINTER(WAVEHDR), W.UINT)
_sig(winmm, "waveInAddBuffer", W.UINT, W.HANDLE, C.POINTER(WAVEHDR), W.UINT)
_sig(winmm, "waveInStart", W.UINT, W.HANDLE)
_sig(winmm, "waveInReset", W.UINT, W.HANDLE)
_sig(winmm, "waveInClose", W.UINT, W.HANDLE)

# GDI+ flat API
GP = C.c_void_p
F = C.c_float


class GdiplusStartupInput(C.Structure):
    _fields_ = [("GdiplusVersion", C.c_uint32), ("DebugEventCallback", PV),
                ("SuppressBackgroundThread", W.BOOL), ("SuppressExternalCodecs", W.BOOL)]


class RectF(C.Structure):
    _fields_ = [("X", F), ("Y", F), ("Width", F), ("Height", F)]


PixelFormat32bppPARGB = 0xE200B
_sig(gdiplus, "GdiplusStartup", C.c_int, C.POINTER(C.c_size_t), C.POINTER(GdiplusStartupInput), PV)
_sig(gdiplus, "GdipCreateBitmapFromScan0", C.c_int, C.c_int, C.c_int, C.c_int, C.c_int, PV, C.POINTER(GP))
_sig(gdiplus, "GdipGetImageGraphicsContext", C.c_int, GP, C.POINTER(GP))
_sig(gdiplus, "GdipDeleteGraphics", C.c_int, GP)
_sig(gdiplus, "GdipDisposeImage", C.c_int, GP)
_sig(gdiplus, "GdipSetSmoothingMode", C.c_int, GP, C.c_int)
_sig(gdiplus, "GdipSetTextRenderingHint", C.c_int, GP, C.c_int)
_sig(gdiplus, "GdipGraphicsClear", C.c_int, GP, C.c_uint32)
_sig(gdiplus, "GdipCreateSolidFill", C.c_int, C.c_uint32, C.POINTER(GP))
_sig(gdiplus, "GdipSetSolidFillColor", C.c_int, GP, C.c_uint32)
_sig(gdiplus, "GdipDeleteBrush", C.c_int, GP)
_sig(gdiplus, "GdipFillEllipse", C.c_int, GP, GP, F, F, F, F)
_sig(gdiplus, "GdipFillRectangle", C.c_int, GP, GP, F, F, F, F)
_sig(gdiplus, "GdipCreatePath", C.c_int, C.c_int, C.POINTER(GP))
_sig(gdiplus, "GdipDeletePath", C.c_int, GP)
_sig(gdiplus, "GdipAddPathArc", C.c_int, GP, F, F, F, F, F, F)
_sig(gdiplus, "GdipClosePathFigure", C.c_int, GP)
_sig(gdiplus, "GdipFillPath", C.c_int, GP, GP, GP)
_sig(gdiplus, "GdipCreateFontFamilyFromName", C.c_int, W.LPCWSTR, PV, C.POINTER(GP))
_sig(gdiplus, "GdipCreateFont", C.c_int, GP, F, C.c_int, C.c_int, C.POINTER(GP))
_sig(gdiplus, "GdipDeleteFont", C.c_int, GP)
_sig(gdiplus, "GdipDeleteFontFamily", C.c_int, GP)
_sig(gdiplus, "GdipCreateStringFormat", C.c_int, C.c_int, C.c_ushort, C.POINTER(GP))
_sig(gdiplus, "GdipSetStringFormatLineAlign", C.c_int, GP, C.c_int)
_sig(gdiplus, "GdipDrawString", C.c_int, GP, W.LPCWSTR, C.c_int, GP, C.POINTER(RectF), GP, GP)
_sig(gdiplus, "GdipMeasureString", C.c_int, GP, W.LPCWSTR, C.c_int, GP, C.POINTER(RectF), GP,
     C.POINTER(RectF), C.POINTER(C.c_int), C.POINTER(C.c_int))
_sig(gdiplus, "GdipCreateHICONFromBitmap", C.c_int, GP, C.POINTER(W.HICON))

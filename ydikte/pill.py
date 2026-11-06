"""The floating status pill: a click-through, never-focused layered window drawn with GDI+."""

import ctypes as C
import math
import time
from ctypes import wintypes as W

from . import winapi as w

BG = 0xF0171A21
TEXT = 0xFFF4F5F7
RED = 0xFFFF4D4F
GREEN = 0xFF2EE6A6
BLUE = 0xFF5B9DFF
AMBER = 0xFFFFB020

HEIGHT = 40
MARGIN_BOTTOM = 28
MAX_W, MAX_H = 560, 64     # canvas size at 100% scaling
BARS = 5

_gdip_token = None


def gdiplus_start():
    global _gdip_token
    if _gdip_token is None:
        token = C.c_size_t()
        start = w.GdiplusStartupInput(1, None, False, False)
        if w.gdiplus.GdiplusStartup(C.byref(token), C.byref(start), None) != 0:
            raise OSError("GDI+ failed to start")
        _gdip_token = token


def _gp(call, *args):
    out = C.c_void_p()
    status = call(*args, C.byref(out))
    if status != 0:
        raise OSError(f"GDI+ error {status} in {call.__name__}")
    return out


def _alpha(color, factor):
    return (int(((color >> 24) & 0xFF) * factor) << 24) | (color & 0xFFFFFF)


class _Canvas:
    """A premultiplied BGRA bitmap that GDI+ draws on and UpdateLayeredWindow shows."""

    def __init__(self, scale):
        self.scale = scale
        self.width = int(MAX_W * scale)
        self.height = int(MAX_H * scale)
        header = w.BITMAPINFOHEADER()
        header.biSize = C.sizeof(header)
        header.biWidth = self.width
        header.biHeight = -self.height   # top-down
        header.biPlanes = 1
        header.biBitCount = 32
        self.dc = w.gdi32.CreateCompatibleDC(None)
        bits = C.c_void_p()
        self.bitmap = w.gdi32.CreateDIBSection(self.dc, C.byref(header), 0, C.byref(bits), None, 0)
        self.old = w.gdi32.SelectObject(self.dc, self.bitmap)
        self.image = _gp(w.gdiplus.GdipCreateBitmapFromScan0, self.width, self.height,
                         self.width * 4, w.PixelFormat32bppPARGB, bits)
        self.g = _gp(w.gdiplus.GdipGetImageGraphicsContext, self.image)
        w.gdiplus.GdipSetSmoothingMode(self.g, 4)
        w.gdiplus.GdipSetTextRenderingHint(self.g, 4)
        self.brush = _gp(w.gdiplus.GdipCreateSolidFill, 0)
        family = _gp(w.gdiplus.GdipCreateFontFamilyFromName, "Segoe UI", None)
        self.font = _gp(w.gdiplus.GdipCreateFont, family, 14.0 * scale, 1, 2)  # bold, pixels
        w.gdiplus.GdipDeleteFontFamily(family)
        self.format = _gp(w.gdiplus.GdipCreateStringFormat, 0x1000, 0)  # no wrapping
        w.gdiplus.GdipSetStringFormatLineAlign(self.format, 1)

    def close(self):
        w.gdiplus.GdipDeleteBrush(self.brush)
        w.gdiplus.GdipDeleteFont(self.font)
        w.gdiplus.GdipDeleteGraphics(self.g)
        w.gdiplus.GdipDisposeImage(self.image)
        w.gdi32.SelectObject(self.dc, self.old)
        w.gdi32.DeleteObject(self.bitmap)
        w.gdi32.DeleteDC(self.dc)

    def clear(self):
        w.gdiplus.GdipGraphicsClear(self.g, 0)

    def color(self, argb):
        w.gdiplus.GdipSetSolidFillColor(self.brush, argb)

    def round_rect(self, x, y, width, height, radius):
        path = _gp(w.gdiplus.GdipCreatePath, 0)
        d = radius * 2
        w.gdiplus.GdipAddPathArc(path, x, y, d, d, 180, 90)
        w.gdiplus.GdipAddPathArc(path, x + width - d, y, d, d, 270, 90)
        w.gdiplus.GdipAddPathArc(path, x + width - d, y + height - d, d, d, 0, 90)
        w.gdiplus.GdipAddPathArc(path, x, y + height - d, d, d, 90, 90)
        w.gdiplus.GdipClosePathFigure(path)
        w.gdiplus.GdipFillPath(self.g, self.brush, path)
        w.gdiplus.GdipDeletePath(path)

    def circle(self, cx, cy, radius):
        w.gdiplus.GdipFillEllipse(self.g, self.brush, cx - radius, cy - radius, radius * 2, radius * 2)

    def text_width(self, text):
        box = w.RectF(0, 0, self.width, self.height)
        out = w.RectF()
        w.gdiplus.GdipMeasureString(self.g, text, -1, self.font, C.byref(box), self.format,
                                    C.byref(out), None, None)
        return out.Width

    def text(self, text, x, height):
        box = w.RectF(x, 0, self.width - x, height)
        w.gdiplus.GdipDrawString(self.g, text, -1, self.font, C.byref(box), self.format, self.brush)


class Pill:
    def __init__(self, level_source):
        gdiplus_start()
        self.level_source = level_source    # callable returning 0..1
        self.enabled = True
        self.mode = None       # None, "hold", "hands_free", "busy", "flash"
        self.label = ""
        self._color = RED
        self._started = 0.0
        self._flash_until = 0.0
        self._bars = [0.0] * BARS
        self._canvas = None
        self._pos = (0, 0)
        self._class = w.WNDCLASSW()
        self._class.lpfnWndProc = C.cast(w.user32.DefWindowProcW, w.WNDPROC)
        self._class.hInstance = w.kernel32.GetModuleHandleW(None)
        self._class.lpszClassName = "YDiktePill"
        w.user32.RegisterClassW(C.byref(self._class))
        style = (w.WS_EX_LAYERED | w.WS_EX_TOPMOST | w.WS_EX_TOOLWINDOW
                 | w.WS_EX_NOACTIVATE | w.WS_EX_TRANSPARENT)
        self.hwnd = w.user32.CreateWindowExW(
            style, "YDiktePill", "YDikte", w.WS_POPUP, 0, 0, 1, 1,
            None, None, self._class.hInstance, None)

    @property
    def animating(self):
        return self.mode is not None

    def show_hold(self):
        self._show("hold", "Dinliyor", RED)

    def show_hands_free(self):
        self._show("hands_free", "Eller serbest", GREEN)

    def show_busy(self, label="Yazıya dökülüyor"):
        self._show("busy", label, BLUE)

    def show_flash(self, message, color=AMBER, seconds=1.6):
        self._flash_until = time.monotonic() + seconds
        self._show("flash", message, color)

    def hide(self):
        self.mode = None
        w.user32.ShowWindow(self.hwnd, w.SW_HIDE)

    def _show(self, mode, label, color):
        if not self.enabled:
            return
        was_hidden = self.mode is None
        self.mode = mode
        self.label = label
        self._color = color
        if mode in ("hold", "hands_free"):
            self._started = time.monotonic()
        self._place()
        self.tick()
        if was_hidden:
            w.user32.ShowWindow(self.hwnd, w.SW_SHOWNOACTIVATE)
            w.user32.SetWindowPos(self.hwnd, w.HWND_TOPMOST, 0, 0, 0, 0,
                                  w.SWP_NOSIZE | w.SWP_NOMOVE | w.SWP_NOACTIVATE)

    def _place(self):
        """Bottom centre of the monitor being worked on, above the taskbar."""
        foreground = w.user32.GetForegroundWindow()
        if foreground:
            monitor = w.user32.MonitorFromWindow(foreground, w.MONITOR_DEFAULTTONEAREST)
        else:
            point = W.POINT()
            w.user32.GetCursorPos(C.byref(point))
            monitor = w.user32.MonitorFromPoint(point, w.MONITOR_DEFAULTTONEAREST)
        info = w.MONITORINFO()
        info.cbSize = C.sizeof(info)
        w.user32.GetMonitorInfoW(monitor, C.byref(info))
        dpi_x, dpi_y = W.UINT(96), W.UINT(96)
        w.shcore.GetDpiForMonitor(monitor, 0, C.byref(dpi_x), C.byref(dpi_y))
        scale = dpi_x.value / 96.0
        if self._canvas is None or self._canvas.scale != scale:
            if self._canvas:
                self._canvas.close()
            self._canvas = _Canvas(scale)
        self._work = info.rcWork

    def tick(self):
        """Redraw one frame. Returns False if the flash has ended and the pill hid itself."""
        if self.mode is None:
            return False
        if self.mode == "flash" and time.monotonic() > self._flash_until:
            self.hide()
            return False
        self._draw()
        return True

    def _draw(self):
        c = self._canvas
        s = c.scale
        now = time.monotonic()
        label = self.label
        if self.mode == "hands_free":
            secs = int(now - self._started)
            label = f"Eller serbest  {secs // 60}:{secs % 60:02d}"
        elif self.mode == "busy":
            label = f"{self.label}…"
        height = HEIGHT * s
        pad = 16 * s
        dot = 5 * s
        gap = 10 * s
        meter = (BARS * 3 + (BARS - 1) * 3) * s if self.mode in ("hold", "hands_free") else 0
        text_w = c.text_width(label)
        width = min(pad + dot * 2 + gap + (meter + gap if meter else 0) + text_w + pad, c.width)
        cy = height / 2

        c.clear()
        c.color(BG)
        c.round_rect(0, 0, width, height, height / 2)

        x = pad + dot
        if self.mode == "busy":
            for i in range(3):   # three dots chasing each other
                phase = (now * 2.2 - i * 0.28) % 1.0
                c.color(_alpha(self._color, 0.35 + 0.65 * max(0.0, math.sin(phase * math.pi))))
                c.circle(pad + i * 8 * s + 2 * s, cy, 2.4 * s)
            x = pad + 2 * 8 * s + 2 * s + 2.4 * s - dot
        elif self.mode == "flash":
            c.color(self._color)
            c.circle(x, cy, dot)
        else:
            c.color(_alpha(self._color, 0.72 + 0.28 * math.sin(now * 5)))
            c.circle(x, cy, dot)
        x += dot + gap

        if meter:
            level = self.level_source()
            c.color(self._color)
            for i in range(BARS):
                wobble = 0.65 + 0.35 * math.sin(now * 13 + i * 1.9)
                target = max(0.12, min(1.0, level * wobble * (1 - abs(i - 2) * 0.16)))
                self._bars[i] = max(target, self._bars[i] * 0.72)
                bar = (5 + 15 * self._bars[i]) * s
                c.round_rect(x + i * 6 * s, cy - bar / 2, 3 * s, bar, 1.5 * s)
            x += meter + gap

        c.color(TEXT)
        c.text(label, x, height)
        self._present(int(math.ceil(width)), int(height))

    def _present(self, width, height):
        work = self._work
        pos = W.POINT((work.left + work.right - width) // 2,
                      work.bottom - height - int(MARGIN_BOTTOM * self._canvas.scale))
        size = W.SIZE(width, height)
        origin = W.POINT(0, 0)
        blend = w.BLENDFUNCTION(0, 0, 255, 1)
        screen = w.user32.GetDC(None)
        w.user32.UpdateLayeredWindow(self.hwnd, screen, C.byref(pos), C.byref(size), self._canvas.dc,
                                     C.byref(origin), 0, C.byref(blend), w.ULW_ALPHA)
        w.user32.ReleaseDC(None, screen)



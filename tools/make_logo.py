"""Draws the YDikte logo and tray icons into assets/. Run it after changing the design.

The mark is a Y whose fork cradles a microphone capsule, so it reads as both the
letter and a mic on a stand.
"""

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ydikte.gfx import hex_rgb, ico_bytes, png_bytes  # noqa: E402

ASSETS = ROOT / "assets"
THEMES = {
    "logo": dict(top="#262B38", bottom="#0F1117", mark="#F6F7F9", capsule="#FF5A4F"),
    "off": dict(top="#3A3D44", bottom="#2A2C31", mark="#9A9EA6", capsule="#6E7178"),
    "live": dict(top="#FF6A5C", bottom="#E23D33", mark="#FFFFFF", capsule="#FFFFFF"),
}
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 256)
TRAY_SIZES = (16, 20, 24, 32, 40, 48)


def segment(px, py, ax, ay, bx, by):
    abx, aby = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * abx + (py - ay) * aby) / (abx * abx + aby * aby)))
    return math.hypot(px - ax - abx * t, py - ay - aby * t)


def inside_squircle(x, y):
    # Superellipse, the soft square Windows 11 app icons sit in.
    return abs((x - 0.5) / 0.5) ** 4.6 + abs((y - 0.5) / 0.5) ** 4.6 <= 1.0


def render(size, theme):
    top, bottom = hex_rgb(theme["top"]), hex_rgb(theme["bottom"])
    mark, capsule = hex_rgb(theme["mark"]), hex_rgb(theme["capsule"])
    # Small icons get heavier strokes or the shape dissolves at tray size.
    weight = 1.45 if size <= 24 else 1.2 if size <= 40 else 1.0
    stroke = 0.046 * weight
    cap_r = 0.074 * (1.18 if size <= 24 else 1.0)
    samples = 8 if size <= 64 else 3
    pixels = bytearray()
    for iy in range(size):
        for ix in range(size):
            r = g = b = a = 0.0
            for sy in range(samples):
                for sx in range(samples):
                    x = (ix + (sx + 0.5) / samples) / size
                    y = (iy + (sy + 0.5) / samples) / size
                    if not inside_squircle(x, y):
                        continue
                    d_y = min(segment(x, y, 0.235, 0.27, 0.5, 0.635),
                              segment(x, y, 0.765, 0.27, 0.5, 0.635),
                              segment(x, y, 0.5, 0.635, 0.5, 0.825))
                    if segment(x, y, 0.5, 0.215, 0.5, 0.375) <= cap_r:
                        color = capsule
                    elif d_y <= stroke:
                        color = mark
                    else:
                        color = tuple(t + (u - t) * y for t, u in zip(top, bottom))
                    r += color[0]
                    g += color[1]
                    b += color[2]
                    a += 1
            total = samples * samples
            if a:
                pixels += bytes((round(r / a), round(g / a), round(b / a), round(255 * a / total)))
            else:
                pixels += b"\0\0\0\0"
    return png_bytes(size, size, bytes(pixels))


def main():
    ASSETS.mkdir(exist_ok=True)
    images = {size: render(size, THEMES["logo"]) for size in ICON_SIZES}
    (ASSETS / "logo.ico").write_bytes(ico_bytes(list(images.items())))
    (ASSETS / "logo.png").write_bytes(images[256])
    (ASSETS / "logo_64.png").write_bytes(images[64])
    (ASSETS / "tray_ready.ico").write_bytes(
        ico_bytes([(s, images[s]) for s in TRAY_SIZES]))
    for name in ("off", "live"):
        (ASSETS / f"tray_{name}.ico").write_bytes(
            ico_bytes([(s, render(s, THEMES[name])) for s in TRAY_SIZES]))
    print("wrote", sorted(p.name for p in ASSETS.iterdir()))


if __name__ == "__main__":
    main()

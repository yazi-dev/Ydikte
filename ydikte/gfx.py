"""A tiny anti-aliased rasterizer that writes PNG and ICO. Standard library only."""

import struct
import zlib


def png_bytes(width, height, rgba):
    """`rgba` is width * height * 4 bytes."""
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    stride = width * 4
    raw = b"".join(b"\0" + rgba[y * stride:(y + 1) * stride] for y in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def ico_bytes(images):
    """`images` is [(size, png bytes)]. Windows accepts PNG payloads in ICO files."""
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries = b""
    body = b""
    for size, data in images:
        side = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(data), offset + len(body))
        body += data
    return header + entries + body


def hex_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def rounded_rect_png(width, height, radius, fill, background):
    """An opaque rounded rectangle. Only the corners cost per-pixel work, so big cards stay fast."""
    fill_rgb = hex_rgb(fill)
    back_rgb = hex_rgb(background)
    radius = min(radius, min(width, height) / 2)
    corner_px = int(radius + 0.999)
    samples = 4
    table = []
    for y in range(corner_px):
        row = []
        for x in range(corner_px):
            inside = 0
            for sy in range(samples):
                for sx in range(samples):
                    dx = radius - (x + (sx + 0.5) / samples)
                    dy = radius - (y + (sy + 0.5) / samples)
                    if dx * dx + dy * dy <= radius * radius:
                        inside += 1
            row.append(bytes(_mix(back_rgb, fill_rgb, inside / samples ** 2)) + b"\xff")
        table.append(row)
    solid = bytes(fill_rgb) + b"\xff"
    middle = width - 2 * corner_px
    rows = []
    for row in table:
        left = b"".join(row)
        rows.append(left + solid * middle + b"".join(reversed(row)))
    plain = solid * width
    pixels = b"".join(rows) + plain * (height - 2 * corner_px) + b"".join(reversed(rows))
    return png_bytes(width, height, pixels)


def toggle_png(width, height, on, on_color, off_color, knob_color, background):
    """A switch: a rounded track and a round knob, supersampled."""
    track = hex_rgb(on_color if on else off_color)
    knob = hex_rgb(knob_color)
    back = hex_rgb(background)
    samples = 3
    radius = height / 2
    knob_r = radius - height * 0.13
    knob_x = width - radius if on else radius
    out = bytearray()
    for y in range(height):
        for x in range(width):
            track_hits = knob_hits = 0
            for sy in range(samples):
                for sx in range(samples):
                    px = x + (sx + 0.5) / samples
                    py = y + (sy + 0.5) / samples
                    cx = min(max(px, radius), width - radius)
                    if (px - cx) ** 2 + (py - radius) ** 2 <= radius ** 2:
                        track_hits += 1
                    if (px - knob_x) ** 2 + (py - radius) ** 2 <= knob_r ** 2:
                        knob_hits += 1
            total = samples ** 2
            color = _mix(back, track, track_hits / total)
            color = _mix(color, knob, knob_hits / total)
            out += bytes(color) + b"\xff"
    return png_bytes(width, height, bytes(out))

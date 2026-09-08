#!/usr/bin/env python3
"""Render a CSS-style linear-gradient to a PNG (pure Python, no Pillow). Used for e-mail background
images because Outlook and Gmail Android do not render CSS gradients.

  python3 make_gradient.py assets/launch-coral.png 600 1600 160 "#fdbb8f 0%,#f86726 30%,#eabf7c 58%,#ffe2d8 82%,#d5ddda 100%"
"""
import math, struct, sys, zlib


def png_bytes(width, height, rows):
    raw = b"".join(b"\x00" + bytes(r) for r in rows)
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def parse_stops(spec):
    stops = []
    for part in spec.split(","):
        col, pos = part.strip().split()
        c = col.lstrip("#")
        stops.append((float(pos.rstrip("%")) / 100, tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))))
    return stops


def gradient_png(path, width, height, angle_deg, spec):
    stops = parse_stops(spec)
    a = math.radians(angle_deg)
    dx, dy = math.sin(a), -math.cos(a)                        # CSS: 0deg = to top, 90deg = to right
    length = abs(width * math.sin(a)) + abs(height * math.cos(a))
    cx, cy = width / 2, height / 2
    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            t = ((x - cx) * dx + (y - cy) * dy) / length + 0.5
            t = min(1.0, max(0.0, t))
            for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
                if t <= p1:
                    f = 0 if p1 == p0 else (t - p0) / (p1 - p0)
                    row += bytes(round(c0[i] + (c1[i] - c0[i]) * f) for i in range(3))
                    break
            else:
                row += bytes(stops[-1][1])
        rows.append(row)
    with open(path, "wb") as fh:
        fh.write(png_bytes(width, height, rows))


if __name__ == "__main__":
    out, w, h, ang, spec = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), float(sys.argv[4]), sys.argv[5]
    gradient_png(out, w, h, ang, spec)
    print(out)

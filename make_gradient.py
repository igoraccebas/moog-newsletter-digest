#!/usr/bin/env python3
"""Render a CSS-style linear-gradient to a PNG (pure Python, no Pillow). Used for e-mail background
images because Outlook and Gmail Android do not render CSS gradients.

  python3 make_gradient.py assets/launch-coral.png 600 1600 160 "#fdbb8f 0%,#f86726 30%,#eabf7c 58%,#ffe2d8 82%,#d5ddda 100%"
  python3 make_gradient.py mesh assets/launch-graphite.png 600 1600 160 "<stops>" "x,y,r,#hex,strength;..."
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


def parse_hex(col):
    c = col.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def mesh_png(path, width, height, angle_deg, spec, blobs):
    """Linear base gradient plus soft radial pools of colour (a 'mesh' look).
    blobs: "x,y,r,#hex,strength;..." with x/y/r relative to the width (y relative to the height),
    strength 0..1; each pool fades with a smoothstep falloff."""
    stops = parse_stops(spec)
    a = math.radians(angle_deg)
    dx, dy = math.sin(a), -math.cos(a)
    length = abs(width * math.sin(a)) + abs(height * math.cos(a))
    cx, cy = width / 2, height / 2
    pools = []
    for b in blobs.split(";"):
        bx, by, br, col, st = b.split(",")
        pools.append((float(bx) * width, float(by) * height, float(br) * width, parse_hex(col), float(st)))
    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            t = min(1.0, max(0.0, ((x - cx) * dx + (y - cy) * dy) / length + 0.5))
            for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
                if t <= p1:
                    f = 0 if p1 == p0 else (t - p0) / (p1 - p0)
                    r, g, bl = (c0[i] + (c1[i] - c0[i]) * f for i in range(3))
                    break
            else:
                r, g, bl = stops[-1][1]
            for px, py, pr, pc, ps in pools:
                d = math.hypot(x - px, y - py) / pr
                if d < 1.0:
                    w_ = (1 - d) * (1 - d) * (3 - 2 * (1 - d)) * ps      # smoothstep falloff
                    r, g, bl = r + (pc[0] - r) * w_, g + (pc[1] - g) * w_, bl + (pc[2] - bl) * w_
            row += bytes((round(r), round(g), round(bl)))
        rows.append(row)
    with open(path, "wb") as fh:
        fh.write(png_bytes(width, height, rows))


if __name__ == "__main__":
    if sys.argv[1] == "mesh":
        out, w, h, ang, spec, blobs = sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), float(sys.argv[5]), sys.argv[6], sys.argv[7]
        mesh_png(out, w, h, ang, spec, blobs)
    else:
        out, w, h, ang, spec = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), float(sys.argv[4]), sys.argv[5]
        gradient_png(out, w, h, ang, spec)
    print(out)

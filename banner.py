"""
Moog Audio - Deals banner renderer (design "Homepage Banner" 4B, claude.ai/design, Igor 2026-09-17).

Pure standard library, imported by digest.py (the entry point stays `python3 digest.py sale ...`). Everything
that touches pixels lives here so digest.py stays the pipeline:

  PNG codec (8-bit RGBA)      decode_png / encode_png
  compositing                 key_white / as_white_mask / bbox_alpha / crop / blit / fill_rect / draw_disc
  backgrounds                 linear_gradient / radial_wash / build_background
  text                        Font (TrueType: cmap 4, loca/glyf, hmtx) / draw_text / text_width
  the banner                  build_banner(card, headline, subline, background, fonts, logo_cache)

Pure Python is slow per pixel: the 900x675 background takes ~2 s and is built ONCE per run; each banner then
costs a few seconds (CDN fetches + PNG decode + text). Fonts: assets/fonts/Helvetica.ttf is required
(Igor's file; decision #15); --font-dir / MOOG_FONT_DIR point at another folder for local work (Arial).
There is deliberately NO automatic fallback so a cloud run can never render in the wrong face by accident.
"""
import json, math, os, re, struct, time, urllib.request, zlib
from collections import deque

W, H = 900, 675                      # design 4B frame
PAD_X, PAD_Y = 56, 48                # design padding: 48px 56px
LOGO_W, LOGO_H = 240, 56             # "Brand logo (white)" slot
DISC = 168                           # discount disc diameter
GAP = 18                             # bottom block gap
WHITE, BLACK, RED = (255, 255, 255), (0, 0, 0), (193, 39, 45)   # #c1272d = sale red
# Backdrops, one per banner in rotation (Igor, 2026-09-18: "each banner a different gradient colour"). Stops come
# from the design file's banners (indigo = 4B/2A/3A, coral = 1B, teal = 1C, lavender = 1A) and the launch e-mail
# palette (graphite). Each gets the same white wash / dots / sheen / hairline treatment as 4B; text stays white.
GRADIENTS = {
    "indigo":   {"angle": 112, "stops": [(0.0, "#2a2f6e"), (0.38, "#4b4fb0"), (0.68, "#7d7ae0"), (1.0, "#b7aef2")]},
    "coral":    {"angle": 135, "stops": [(0.0, "#f8a35e"), (1.0, "#fdc18f")],
                 "pools": [(0.18, 0.32, 0.42, "#fdbb8f"), (0.78, 0.22, 0.48, "#eabf7c"), (0.28, 0.78, 0.38, "#f86726"), (0.75, 0.78, 0.50, "#ffe2d8")]},
    "teal":     {"angle": 115, "stops": [(0.0, "#b8d6dd"), (0.40, "#8fbfd0"), (0.75, "#6f9fc4"), (1.0, "#9bb6dc")]},
    "lavender": {"angle": 115, "stops": [(0.0, "#d6cff2"), (0.45, "#b9b1ea"), (0.70, "#a297e6"), (1.0, "#c4b6f0")]},
    "graphite": {"angle": 112, "stops": [(0.0, "#8f96a2"), (0.32, "#6f7784"), (0.58, "#5f6774"), (0.82, "#7a828d"), (1.0, "#9aa1ab")]},
}
GRADIENT_ORDER = ["indigo", "coral", "teal", "lavender", "graphite"]
STORE = "https://moogaudio.com"
REQUIRED_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz$,.%-/&éèàçÉ"
FONT_REGULAR = ("Helvetica.ttf", "Arial.ttf")
FONT_BOLD = ("Helvetica Bold.ttf", "Helvetica-Bold.ttf", "Arial Bold.ttf", "Arial-Bold.ttf")
USER_AGENT = "MoogDigest/1.0"


# ------------------------------------------------------------------------------------------------ network ----
def fetch(url, timeout=40):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=timeout) as r:
        return r.read()


def cdn_png(src, width, height):
    """Shopify CDN: scale to fit inside width x height (no crop) and convert to PNG server-side."""
    return src + ("&" if "?" in src else "?") + f"width={width}&height={height}&format=png"


def vendor_handle(vendor):
    """Brand collection handle, same rule as the design's brands.js: lower, '&' -> space, non-alnum -> '-'."""
    return re.sub(r"[^a-z0-9]+", "-", vendor.lower().replace("&", " ")).strip("-")


# ---------------------------------------------------------------------------------------------- PNG codec ----
def decode_png(data):
    """8-bit non-interlaced PNG -> (w, h, rows of RGBA bytearrays). Colour types 0/2/3/4/6."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos, idat, plte, trns, hdr = 8, [], None, None, None
    while pos + 8 <= len(data):
        n, = struct.unpack(">I", data[pos:pos + 4])
        tag, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + n]
        pos += 12 + n
        if tag == b"IHDR":
            hdr = struct.unpack(">IIBBBBB", body)
        elif tag == b"IDAT":
            idat.append(body)
        elif tag == b"PLTE":
            plte = body
        elif tag == b"tRNS":
            trns = body
        elif tag == b"IEND":
            break
    w, h, depth, ctype, _, _, interlace = hdr
    if depth != 8 or interlace:
        raise ValueError(f"unsupported PNG (depth {depth}, interlace {interlace})")
    ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    raw = zlib.decompress(b"".join(idat))
    stride = w * ch
    prev = bytearray(stride)
    p, rows = 0, []
    for _ in range(h):
        f, line = raw[p], bytearray(raw[p + 1:p + 1 + stride])
        p += 1 + stride
        if f == 1:
            for i in range(ch, stride):
                line[i] = (line[i] + line[i - ch]) & 255
        elif f == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif f == 3:
            for i in range(stride):
                line[i] = (line[i] + (((line[i - ch] if i >= ch else 0) + prev[i]) >> 1)) & 255
        elif f == 4:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                b = prev[i]
                c = prev[i - ch] if i >= ch else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(line)
        prev = line
    out = []
    for line in rows:
        o = bytearray(w * 4)
        for x in range(w):
            if ctype == 2:
                r, g, b, a = line[3 * x], line[3 * x + 1], line[3 * x + 2], 255
            elif ctype == 6:
                r, g, b, a = line[4 * x:4 * x + 4]
            elif ctype == 0:
                r = g = b = line[x]
                a = 255
            elif ctype == 4:
                r = g = b = line[2 * x]
                a = line[2 * x + 1]
            else:
                v = line[x]
                r, g, b = plte[3 * v:3 * v + 3]
                a = trns[v] if trns and v < len(trns) else 255
            o[4 * x:4 * x + 4] = bytes((r, g, b, a))
        out.append(o)
    return w, h, out


def _paeth_row(cur, prev, bpp):
    """PNG filter type 4. Measured on a real banner: -20% file size for ~1 s of pure Python; the adaptive
    per-row choice gains almost nothing more, so every row is Paeth-filtered."""
    out = bytearray(len(cur))
    for i in range(len(cur)):
        a = cur[i - bpp] if i >= bpp else 0
        b = prev[i]
        c = prev[i - bpp] if i >= bpp else 0
        p = a + b - c
        pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
        out[i] = (cur[i] - (a if pa <= pb and pa <= pc else (b if pb <= pc else c))) & 255
    return bytes(out)


def encode_png(w, h, rows, opaque=True):
    """RGBA rows -> PNG bytes. opaque=True (the finished banner) drops the alpha channel and Paeth-filters
    every row; opaque=False keeps RGBA with no filter (intermediate images with transparency)."""
    def chunk(tag, payload):
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload) & 0xffffffff)
    if opaque:
        rgb = []
        for r in rows:
            b = bytearray(r)
            del b[3::4]
            rgb.append(bytes(b))
        prev = bytes(len(rgb[0]))
        parts = []
        for r in rgb:
            parts.append(b"\x04" + _paeth_row(r, prev, 3))
            prev = r
        body, ctype = b"".join(parts), 2
    else:
        body, ctype = b"".join(b"\x00" + bytes(r) for r in rows), 6
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, ctype, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(body, 9)) + chunk(b"IEND", b""))


# -------------------------------------------------------------------------------------------- compositing ----
def key_white(w, h, rows, lo=240, hi=252):
    """Remove a white studio background: near-white pixels that are CONNECTED to the image border become
    transparent (soft ramp between lo and hi, so PNGs converted from JPEG lose their off-white halo too).
    White areas enclosed by the product (a light front panel, a white knob) are left alone, unlike a plain
    chroma key that would eat them. Thresholds measured on Moog studio shots (2026-09-17): the backdrop is a
    pure 255, JPEG ringing sits at 245-254, light product panels at 200-240 -> lo=240 keeps panels solid."""
    seen = bytearray(w * h)
    q = deque()

    def light(x, y):
        i = 4 * x
        line = rows[y]
        return min(line[i], line[i + 1], line[i + 2]) >= lo

    for x in range(w):
        for y in (0, h - 1):
            if not seen[y * w + x] and light(x, y):
                seen[y * w + x] = 1
                q.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            if not seen[y * w + x] and light(x, y):
                seen[y * w + x] = 1
                q.append((x, y))
    while q:
        x, y = q.popleft()
        line = rows[y]
        m = min(line[4 * x], line[4 * x + 1], line[4 * x + 2])
        line[4 * x + 3] = 0 if m >= hi else int(line[4 * x + 3] * (hi - m) / (hi - lo))
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < w and 0 <= ny < h and not seen[ny * w + nx] and light(nx, ny):
                seen[ny * w + nx] = 1
                q.append((nx, ny))
    return rows


def as_white_mask(w, h, rows):
    """Keep only the alpha and paint every remaining pixel white: a black-on-white logo becomes a white logo.
    Flattens all inner detail — use logo_treatment() for real logos."""
    for line in rows:
        for x in range(w):
            if line[4 * x + 3]:
                line[4 * x:4 * x + 3] = b"\xff\xff\xff"
    return rows


def logo_treatment(w, h, rows, saturation_threshold=0.18):
    """Make a brand logo (already keyed off its white box) sit on a dark banner without losing its detail.
    Monochrome logos (black / grey on white, the usual collection image): alpha follows DARKNESS and the
    colour becomes white, so black strokes turn white and lighter inner details stay see-through — the same
    result as a designer's white cutout. Logos with real brand colours keep their colours; only the box is gone.
    Igor, 2026-09-18, after the first pass painted every logo solid white."""
    sat_sum, n = 0.0, 0
    for line in rows:
        for x in range(w):
            if line[4 * x + 3] > 32:
                r, g, b = line[4 * x], line[4 * x + 1], line[4 * x + 2]
                mx = max(r, g, b)
                sat_sum += (mx - min(r, g, b)) / mx if mx else 0
                n += 1
    if n and sat_sum / n > saturation_threshold:
        return rows                                        # coloured logo: keep as is
    for line in rows:
        for x in range(w):
            a = line[4 * x + 3]
            if not a:
                continue
            lum = (line[4 * x] * 299 + line[4 * x + 1] * 587 + line[4 * x + 2] * 114) // 1000
            line[4 * x:4 * x + 4] = bytes((255, 255, 255, a * (255 - lum) // 255))
    return rows


def bbox_alpha(w, h, rows, threshold=8):
    """Tight bounding box (x0, y0, x1, y1) of pixels with alpha > threshold, or None when fully transparent."""
    x0, y0, x1, y1 = w, h, -1, -1
    for y, line in enumerate(rows):
        for x in range(w):
            if line[4 * x + 3] > threshold:
                if x < x0:
                    x0 = x
                if x > x1:
                    x1 = x
                if y < y0:
                    y0 = y
                y1 = y
    return None if x1 < 0 else (x0, y0, x1 + 1, y1 + 1)


def crop(rows, box):
    x0, y0, x1, y1 = box
    return x1 - x0, y1 - y0, [bytearray(r[4 * x0:4 * x1]) for r in rows[y0:y1]]


def blit(dst, w, h, src_w, src_h, src, x0, y0):
    """Alpha-composite src onto dst at (x0, y0)."""
    for y in range(src_h):
        dy = y0 + y
        if not 0 <= dy < h:
            continue
        d, s = dst[dy], src[y]
        for x in range(src_w):
            dx = x0 + x
            if not 0 <= dx < w:
                continue
            a = s[4 * x + 3]
            if a == 0:
                continue
            if a == 255:
                d[4 * dx:4 * dx + 3] = s[4 * x:4 * x + 3]
                continue
            for c in range(3):
                d[4 * dx + c] = (s[4 * x + c] * a + d[4 * dx + c] * (255 - a)) // 255


def fill_rect(cv, w, h, x, y, rw, rh, rgb, alpha=255):
    for yy in range(max(0, y), min(h, y + rh)):
        row = cv[yy]
        for xx in range(max(0, x), min(w, x + rw)):
            if alpha == 255:
                row[4 * xx:4 * xx + 3] = bytes(rgb)
            else:
                for c in range(3):
                    row[4 * xx + c] = (rgb[c] * alpha + row[4 * xx + c] * (255 - alpha)) // 255


def draw_disc(cv, w, h, cx, cy, r, rgb):
    for yy in range(max(0, int(cy - r - 1)), min(h, int(cy + r + 2))):
        row = cv[yy]
        for xx in range(max(0, int(cx - r - 1)), min(w, int(cx + r + 2))):
            a = max(0.0, min(1.0, r - math.hypot(xx + 0.5 - cx, yy + 0.5 - cy) + 0.5))
            if a <= 0:
                continue
            a = int(a * 255)
            for c in range(3):
                row[4 * xx + c] = (rgb[c] * a + row[4 * xx + c] * (255 - a)) // 255


def hex_rgb(s):
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


# -------------------------------------------------------------------------------------------- backgrounds ----
def linear_gradient(w, h, angle_deg, stops):
    """CSS linear-gradient(angle, stops) as an RGBA canvas. stops: [(position 0..1, (r, g, b)), ...]."""
    a = math.radians(angle_deg)
    dx, dy = math.sin(a), -math.cos(a)
    length = abs(w * math.sin(a)) + abs(h * math.cos(a))
    cx, cy = w / 2, h / 2
    rows = []
    for y in range(h):
        row = bytearray(w * 4)
        for x in range(w):
            t = min(1.0, max(0.0, ((x - cx) * dx + (y - cy) * dy) / length + 0.5))
            for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
                if t <= p1:
                    f = 0 if p1 == p0 else (t - p0) / (p1 - p0)
                    row[4 * x:4 * x + 4] = bytes((round(c0[0] + (c1[0] - c0[0]) * f), round(c0[1] + (c1[1] - c0[1]) * f),
                                                  round(c0[2] + (c1[2] - c0[2]) * f), 255))
                    break
            else:
                row[4 * x:4 * x + 4] = bytes(stops[-1][1]) + b"\xff"
        rows.append(row)
    return rows


def radial_wash(cv, w, h, fx, fy, rx, ry, alpha0, rgb=WHITE):
    """Elliptical wash fading linearly from alpha0 at (fx, fy) to 0 at the ellipse edge."""
    for y in range(max(0, int(fy - ry)), min(h, int(fy + ry) + 1)):
        row = cv[y]
        for x in range(max(0, int(fx - rx)), min(w, int(fx + rx) + 1)):
            d = math.hypot((x - fx) / rx, (y - fy) / ry)
            if d >= 1:
                continue
            a = int(alpha0 * (1 - d) * 255)
            if a:
                for c in range(3):
                    row[4 * x + c] = (rgb[c] * a + row[4 * x + c] * (255 - a)) // 255


def build_background(name="indigo"):
    """Design 4B backdrop in one of the GRADIENTS colourways: gradient (+ colour pools for the coral mesh)
    + radial white wash + masked dot grid + skewed sheen + bottom hairline. The grain overlay of the design
    is left out on purpose: it makes the PNG ten times larger."""
    g = GRADIENTS[name]
    cv = linear_gradient(W, H, g["angle"], [(p, hex_rgb(c)) for p, c in g["stops"]])
    for fx, fy, r, colour in g.get("pools", []):             # radial-gradient(circle at fx fy, colour 0%, transparent r)
        radial_wash(cv, W, H, fx * W, fy * H, r * W, r * W, 1.0, hex_rgb(colour))
    radial_wash(cv, W, H, 0.70 * W, 0.62 * H, 0.55 * W, 0.55 * H, 0.22)
    # dot grid: 1px white dots every 14px at .55, masked by an ellipse 65% x 70% at 70%/60% (.9 -> .35 at 45% -> 0 at 75%), layer opacity .5
    mx, my, mrx, mry = 0.70 * W, 0.60 * H, 0.65 * W, 0.70 * H
    for y in range(7, H, 14):
        row = cv[y]
        for x in range(7, W, 14):
            md = math.hypot((x - mx) / mrx, (y - my) / mry)
            mask = 0.9 - 0.55 * md / 0.45 if md <= 0.45 else (0.35 * (1 - (md - 0.45) / 0.30) if md <= 0.75 else 0.0)
            a = int(0.55 * 0.5 * mask * 255)
            if a > 0:
                for c in range(3):
                    row[4 * x + c] = (255 * a + row[4 * x + c] * (255 - a)) // 255
    # skewed sheen: a soft diagonal band, white .10 at its centre line
    tan14 = math.tan(math.radians(14))
    for y in range(H):
        row = cv[y]
        for x in range(W):
            u = (x + (y - H / 2) * tan14 - W * 0.21) / (W * 0.70)
            if 0 <= u <= 1:
                a = int(0.10 * (1 - abs(u - 0.5) * 2) * 255)
                if a:
                    for c in range(3):
                        row[4 * x + c] = (255 * a + row[4 * x + c] * (255 - a)) // 255
    last = cv[-1]
    for x in range(W):
        for c in range(3):
            last[4 * x + c] = int(255 * 0.35 + last[4 * x + c] * 0.65)
    return cv


# --------------------------------------------------------------------------------------------------- fonts ----
class Font:
    """Minimal TrueType reader: cmap format 4, loca/glyf (simple + composite glyphs), hmtx. .ttc: first face."""

    def __init__(self, path):
        d = open(path, "rb").read()
        self.d, self.path, off = d, path, 0
        if d[:4] == b"ttcf":
            off, = struct.unpack(">I", d[12:16])
        num_tables, = struct.unpack(">H", d[off + 4:off + 6])
        self.tables = {}
        for i in range(num_tables):
            tag, _, o, l = struct.unpack(">4sIII", d[off + 12 + 16 * i:off + 28 + 16 * i])
            self.tables[tag.decode("latin1")] = (o, l)
        head = self.tables["head"][0]
        self.upem, = struct.unpack(">H", d[head + 18:head + 20])
        self.locfmt, = struct.unpack(">h", d[head + 50:head + 52])
        maxp = self.tables["maxp"][0]
        self.nglyphs, = struct.unpack(">H", d[maxp + 4:maxp + 6])
        hhea = self.tables["hhea"][0]
        self.ascent, self.descent = struct.unpack(">hh", d[hhea + 4:hhea + 8])
        self.nhm, = struct.unpack(">H", d[hhea + 34:hhea + 36])
        self.hmtx = self.tables["hmtx"][0]
        self.loca, self.glyf = self.tables["loca"][0], self.tables["glyf"][0]
        self.cmap = self._cmap()
        self._outlines = {}

    def _cmap(self):
        d = self.d
        base = self.tables["cmap"][0]
        n, = struct.unpack(">H", d[base + 2:base + 4])
        m = {}
        for i in range(n):
            pid, eid, o = struct.unpack(">HHI", d[base + 4 + 8 * i:base + 12 + 8 * i])
            t = base + o
            fmt, = struct.unpack(">H", d[t:t + 2])
            if fmt == 4 and (pid, eid) in ((3, 1), (0, 3), (0, 4), (0, 6)):
                segx2, = struct.unpack(">H", d[t + 6:t + 8])
                seg = segx2 // 2
                ends = struct.unpack(f">{seg}H", d[t + 14:t + 14 + segx2])
                starts = struct.unpack(f">{seg}H", d[t + 16 + segx2:t + 16 + 2 * segx2])
                deltas = struct.unpack(f">{seg}h", d[t + 16 + 2 * segx2:t + 16 + 3 * segx2])
                ro_base = t + 16 + 3 * segx2
                ros = struct.unpack(f">{seg}H", d[ro_base:ro_base + segx2])
                for s in range(seg):
                    for c in range(starts[s], min(ends[s], 0x2FF) + 1):
                        if ros[s] == 0:
                            g = (c + deltas[s]) & 0xFFFF
                        else:
                            gi = ro_base + 2 * s + ros[s] + 2 * (c - starts[s])
                            g, = struct.unpack(">H", d[gi:gi + 2])
                            if g:
                                g = (g + deltas[s]) & 0xFFFF
                        if g:
                            m[c] = g
                return m
        return m

    def advance(self, g):
        i = min(g, self.nhm - 1)
        return struct.unpack(">H", self.d[self.hmtx + 4 * i:self.hmtx + 4 * i + 2])[0]

    def _loc(self, g):
        if self.locfmt == 0:
            a, b = struct.unpack(">HH", self.d[self.loca + 2 * g:self.loca + 2 * g + 4])
            return 2 * a, 2 * b
        return struct.unpack(">II", self.d[self.loca + 4 * g:self.loca + 4 * g + 8])

    def outline(self, g, depth=0):
        """Contours as lists of (x, y, on_curve) in font units; cached per glyph."""
        if depth == 0 and g in self._outlines:
            return self._outlines[g]
        a, b = self._loc(g)
        if b <= a:
            return []
        d = self.d
        p = self.glyf + a
        nc, = struct.unpack(">h", d[p:p + 2])
        p += 10
        if nc >= 0:
            ends = struct.unpack(f">{nc}H", d[p:p + 2 * nc])
            p += 2 * nc
            npts = ends[-1] + 1 if nc else 0
            il, = struct.unpack(">H", d[p:p + 2])
            p += 2 + il
            flags = []
            while len(flags) < npts:
                f = d[p]
                p += 1
                flags.append(f)
                if f & 8:
                    r = d[p]
                    p += 1
                    flags += [f] * r
            xs, x = [], 0
            for f in flags:
                if f & 2:
                    dx = d[p]
                    p += 1
                    x += dx if f & 16 else -dx
                elif not f & 16:
                    dx, = struct.unpack(">h", d[p:p + 2])
                    p += 2
                    x += dx
                xs.append(x)
            ys, y = [], 0
            for f in flags:
                if f & 4:
                    dy = d[p]
                    p += 1
                    y += dy if f & 32 else -dy
                elif not f & 32:
                    dy, = struct.unpack(">h", d[p:p + 2])
                    p += 2
                    y += dy
                ys.append(y)
            contours, s = [], 0
            for e in ends:
                contours.append([(xs[i], ys[i], bool(flags[i] & 1)) for i in range(s, e + 1)])
                s = e + 1
        elif depth > 4:
            contours = []
        else:
            contours = []
            while True:                                          # composite glyph
                flags, gi = struct.unpack(">HH", d[p:p + 4])
                p += 4
                if flags & 1:
                    a1, a2 = struct.unpack(">hh", d[p:p + 4])
                    p += 4
                else:
                    a1, a2 = struct.unpack(">bb", d[p:p + 2])
                    p += 2
                sa = sd = 1.0
                sb = sc = 0.0

                def f2(o):
                    return struct.unpack(">h", d[o:o + 2])[0] / 16384
                if flags & 8:
                    sa = sd = f2(p)
                    p += 2
                elif flags & 0x40:
                    sa, sd = f2(p), f2(p + 2)
                    p += 4
                elif flags & 0x80:
                    sa, sb, sc, sd = f2(p), f2(p + 2), f2(p + 4), f2(p + 6)
                    p += 8
                dx, dy = (a1, a2) if flags & 2 else (0, 0)
                for c in self.outline(gi, depth + 1):
                    contours.append([(sa * x + sc * y + dx, sb * x + sd * y + dy, on) for x, y, on in c])
                if not flags & 0x20:
                    break
        if depth == 0:
            self._outlines[g] = contours
        return contours


def validate_font(font):
    """Loud failure for a truncated file or a face that cannot spell a price, a headline or a French title."""
    size = len(font.d)
    for t in ("head", "maxp", "hhea", "hmtx", "loca", "glyf", "cmap"):
        if t not in font.tables:
            raise SystemExit(f"ERROR: font {font.path} has no {t} table")
        o, l = font.tables[t]
        if o + l > size:
            raise SystemExit(f"ERROR: font {font.path} is truncated ({t} table ends past the end of the file)")
    missing = "".join(c for c in REQUIRED_CHARS if ord(c) not in font.cmap)
    if missing:
        raise SystemExit(f"ERROR: font {font.path} has no glyphs for: {missing}")


class Fonts:
    def __init__(self, regular, bold=None):
        self.regular, self.bold = regular, bold

    def face(self, bold):
        return (self.bold or self.regular) if bold else self.regular

    def embolden(self, bold):
        return 1 if (bold and not self.bold) else 0       # one Helvetica file: synthesise bold like the browser does


def load_fonts(font_dir, expected="assets/fonts/Helvetica.ttf"):
    """Regular face required (Helvetica.ttf, or Arial.ttf for local work), bold face optional."""
    regular = next((os.path.join(font_dir, n) for n in FONT_REGULAR if os.path.exists(os.path.join(font_dir, n))), None)
    if not regular:
        raise SystemExit(f"ERROR: Deals banners need a font. Put Igor's Helvetica.ttf at {expected}, or point --font-dir "
                         f"(or MOOG_FONT_DIR) at a folder holding Helvetica.ttf or Arial.ttf. Looked in: {font_dir}. Nothing rendered.")
    bold = next((os.path.join(font_dir, n) for n in FONT_BOLD if os.path.exists(os.path.join(font_dir, n))), None)
    fr = Font(regular)
    validate_font(fr)
    fb = None
    if bold:
        fb = Font(bold)
        validate_font(fb)
    return Fonts(fr, fb)


# ---------------------------------------------------------------------------------------------------- text ----
def _flatten(contours, tf, steps=8):
    """Quadratic TrueType contours -> closed polylines in pixel space through tf(x, y) -> (px, py)."""
    polys = []
    for c in contours:
        pts = list(c)
        if not pts:
            continue
        if not pts[0][2]:
            j = next((i for i, q in enumerate(pts) if q[2]), None)
            if j is None:
                mx, my = (pts[0][0] + pts[-1][0]) / 2, (pts[0][1] + pts[-1][1]) / 2
                pts = [(mx, my, True)] + pts
            else:
                pts = pts[j:] + pts[:j]
        poly = [tf(pts[0][0], pts[0][1])]
        n = len(pts)
        prev = pts[0]
        pts.append(pts[0])
        i = 1
        while i <= n:
            x, y, on = pts[i]
            if on:
                poly.append(tf(x, y))
                prev = (x, y, True)
                i += 1
            else:
                nx, ny, non = pts[i + 1] if i + 1 <= n else pts[0]
                if not non:
                    nx, ny = (x + nx) / 2, (y + ny) / 2
                x0, y0 = prev[0], prev[1]
                for s in range(1, steps + 1):
                    t = s / steps
                    poly.append(tf((1 - t) ** 2 * x0 + 2 * (1 - t) * t * x + t * t * nx,
                                   (1 - t) ** 2 * y0 + 2 * (1 - t) * t * y + t * t * ny))
                prev = (nx, ny, True)
                i += 1
                if not non:
                    pts[i] = (nx, ny, True)
        polys.append(poly)
    return polys


def _rasterize(polys, S=4):
    """Nonzero-winding scanline fill, S sub-rows, exact horizontal coverage -> (x0, y0, w, h, coverage rows 0..255)."""
    xs = [p[0] for poly in polys for p in poly]
    ys = [p[1] for poly in polys for p in poly]
    if not xs:
        return 0, 0, 0, 0, []
    x0, y0 = int(math.floor(min(xs))), int(math.floor(min(ys)))
    x1, y1 = int(math.ceil(max(xs))) + 1, int(math.ceil(max(ys))) + 1
    w, h = x1 - x0, y1 - y0
    cov = [[0.0] * w for _ in range(h)]
    edges = [(ax - x0, ay - y0, bx - x0, by - y0) for poly in polys
             for (ax, ay), (bx, by) in zip(poly, poly[1:] + poly[:1]) if ay != by]
    for sy in range(h * S):
        y = (sy + 0.5) / S
        xings = sorted((ax + (y - ay) * (bx - ax) / (by - ay), 1 if by > ay else -1)
                       for ax, ay, bx, by in edges if (ay <= y < by) or (by <= y < ay))
        wind, row = 0, cov[sy // S]
        for i in range(len(xings) - 1):
            wind += xings[i][1]
            if wind != 0:
                xa, xb = xings[i][0], xings[i + 1][0]
                ia, ib = int(xa), int(xb)
                if ia == ib:
                    row[ia] += xb - xa
                else:
                    row[ia] += ia + 1 - xa
                    for k in range(ia + 1, min(ib, w)):
                        row[k] += 1
                    if ib < w:
                        row[ib] += xb - ib
    return x0, y0, w, h, [[min(255, int(v / S * 255 + 0.5)) for v in r] for r in cov]


def text_width(font, text, size, tracking=0.0):
    scale = size / font.upem
    return sum(font.advance(font.cmap.get(ord(ch), 0)) * scale for ch in text) + tracking * size * max(0, len(text) - 1)


def draw_text(cv, w, h, font, text, size, x, y, rgb, tracking=0.0, angle=0.0, align="left", embolden=0, opacity=1.0):
    """Draw text with its baseline at (x, y). tracking in em, angle in degrees about (x, y),
    embolden = extra 1px passes (synthetic bold), opacity 0..1. Returns the advance width."""
    scale = size / font.upem
    pen, items = 0.0, []
    for ch in text:
        g = font.cmap.get(ord(ch), 0)
        items.append((g, pen))
        pen += font.advance(g) * scale + tracking * size
    width = pen - tracking * size
    ox = -width if align == "right" else -width / 2 if align == "center" else 0
    ca, sa = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    for g, px in items:
        outline = font.outline(g)
        if not outline:
            continue
        for pass_dx in range(embolden + 1):
            def tf(gx, gy, px=px, pass_dx=pass_dx):
                lx, ly = ox + px + gx * scale + pass_dx, -gy * scale
                return x + lx * ca - ly * sa, y + lx * sa + ly * ca
            bx, by, bw, bh, cov = _rasterize(_flatten(outline, tf))
            for j in range(bh):
                yy = by + j
                if not 0 <= yy < h:
                    continue
                row, crow = cv[yy], cov[j]
                for i in range(bw):
                    a = crow[i]
                    if not a:
                        continue
                    xx = bx + i
                    if not 0 <= xx < w:
                        continue
                    if opacity < 1:
                        a = int(a * opacity)
                    for c in range(3):
                        row[4 * xx + c] = (rgb[c] * a + row[4 * xx + c] * (255 - a)) // 255
    return width


def wrap_words(font, text, size, max_w, tracking):
    words, lines, cur = text.split(), [], ""
    for wd in words:
        cand = (cur + " " + wd).strip()
        if not cur or text_width(font, cand, size, tracking) <= max_w:
            cur = cand
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines


def fit_headline(fonts, text, max_w):
    """Design: 40px bold uppercase, at most two lines; 32px when a line would exceed the column; then trimmed."""
    face, tr = fonts.face(True), -0.025
    for size in (40, 32):
        lines = wrap_words(face, text, size, max_w, tr)
        if len(lines) <= 2 and all(text_width(face, l, size, tr) <= max_w for l in lines):
            return lines, size
    lines = wrap_words(face, text, 32, max_w, tr)[:2]
    while len(lines) == 2 and text_width(face, lines[1] + "…", 32, max_w and tr) > max_w and " " in lines[1]:
        lines[1] = lines[1].rsplit(" ", 1)[0]
    if len(lines) == 2:
        lines[1] = lines[1].rstrip(",;:") + "…"
    return lines, 32


# --------------------------------------------------------------------------------------------------- assets ----
def fetch_fit_trim(src, box_w, box_h, white_mask=False):
    """Fetch an image from the Shopify CDN fitted inside box_w x box_h, key its white background, trim the
    transparent margins. If the visible part fills less than 85% of the box (white margins in the source),
    fetch once more, larger, so it fills the box. white_mask=True paints the remaining pixels white (logos).
    Returns (w, h, rows) or None when nothing is left after keying."""
    def pass_(width, height):
        w, h, rows = decode_png(fetch(cdn_png(src, width, height)))
        key_white(w, h, rows)
        if white_mask:
            # a logo sits on a white box; if keying removed almost nothing the collection image is a photo or
            # a banner (Universal Audio's is a red product shot) — not usable as a logo
            opaque = sum(1 for line in rows for x in range(w) if line[4 * x + 3] > 32)
            if opaque > 0.85 * w * h:
                raise ValueError("collection image is not a logo on a white box")
            logo_treatment(w, h, rows)
        return w, h, rows, bbox_alpha(w, h, rows)

    w, h, rows, box = pass_(box_w, box_h)
    if not box:
        return None
    fill = max((box[2] - box[0]) / box_w, (box[3] - box[1]) / box_h)
    if fill < 0.85:
        scale = 0.98 / fill
        try:
            w, h, rows, box2 = pass_(int(w * scale), int(h * scale))
            box = box2 or box
        except Exception as e:
            print(f"  note: could not refetch the image larger ({type(e).__name__}); using the first pass")
    x0, y0, x1, y1 = box
    if x1 - x0 > box_w:                                   # never let the result exceed the box
        cx = (x0 + x1) // 2
        x0, x1 = cx - box_w // 2, cx - box_w // 2 + box_w
    if y1 - y0 > box_h:
        cy = (y0 + y1) // 2
        y0, y1 = cy - box_h // 2, cy - box_h // 2 + box_h
    return crop(rows, (max(0, x0), max(0, y0), min(w, x1), min(h, y1)))


def fetch_logo(vendor, cache):
    """White silhouette of the brand-collection logo (Shopify collection image, keyed and filled white),
    trimmed and fitted to the logo box. None when the brand has no collection or no image."""
    if vendor in cache:
        return cache[vendor]
    result = None
    try:
        data = json.loads(fetch(f"{STORE}/collections/{vendor_handle(vendor)}.json", timeout=20))
        src = ((data.get("collection") or {}).get("image") or {}).get("src")
        if src:
            result = fetch_fit_trim(src, LOGO_W, LOGO_H, white_mask=True)
    except Exception as e:                                # 404 for brands without a collection, photo instead of logo, network
        print(f"  note: no logo for {vendor} ({type(e).__name__}: {str(e)[:60]}); using the vendor name")
    cache[vendor] = result
    return result


def fetch_product_cutout(src, box_w, box_h):
    """Product photo fitted inside the box, keyed off its white background, trimmed (see fetch_fit_trim)."""
    return fetch_fit_trim(src, box_w, box_h)


# --------------------------------------------------------------------------------------------------- banner ----
def build_banner(card, headline, subline, background, fonts, logo_cache):
    """One design-4B banner for a deal card (digest.py card dict: vendor, title, image, price, compare, discount_pct).
    Returns (png_bytes, seconds)."""
    t0 = time.perf_counter()
    cv = [bytearray(r) for r in background]
    col_x, col_w = PAD_X, W - 2 * PAD_X
    cx = W / 2
    bold, regular = fonts.face(True), fonts.face(False)
    emb = fonts.embolden(True)

    # ---- bottom block, measured first so the middle area can take the rest
    lines, hsize = fit_headline(fonts, headline.upper(), col_w)
    line_h = hsize * 0.98
    sub_size, price_size, strike_size, btn_size = 17, 22, 14, 16
    btn_h = 13 + btn_size + 13
    block_h = len(lines) * line_h + 8 + sub_size * 1.3 + GAP + price_size + GAP + btn_h
    block_top = H - PAD_Y - block_h

    # ---- logo box (top centre)
    logo = fetch_logo(card["vendor"], logo_cache)
    if logo:
        lw, lh, lrows = logo
        blit(cv, W, H, lw, lh, lrows, int(cx - lw / 2), int(PAD_Y + (LOGO_H - lh) / 2))
    else:
        name, size = card["vendor"].upper(), 28
        while size > 16 and text_width(bold, name, size, 0.04) > LOGO_W:
            size -= 2
        draw_text(cv, W, H, bold, name, size, cx, PAD_Y + LOGO_H / 2 + size * 0.36, WHITE, tracking=0.04, align="center", embolden=emb)

    # ---- middle area: product cutout + discount disc
    mid_top, mid_bottom = PAD_Y + LOGO_H + 20, block_top - 20
    mid_h = int(mid_bottom - mid_top)
    box_x, box_w = int(col_x + 0.14 * col_w), int(0.72 * col_w)
    box_y, box_h = int(mid_top + 8), mid_h - 16
    try:
        cut = fetch_product_cutout(card["image"], box_w, box_h)
    except Exception as e:
        cut = None
        print(f"  note: product image skipped for {card['title'][:40]} ({type(e).__name__}: {e})")
    cut_x, cut_y = None, None
    if cut:
        pw, ph, prow = cut
        cut_x, cut_y = box_x + (box_w - pw) // 2, box_y + (box_h - ph) // 2
        blit(cv, W, H, pw, ph, prow, cut_x, cut_y)
    if card.get("discount_pct"):
        if cut_x is not None:
            # sticker on the product's top-left corner: mostly outside the photo, overlapping the corner a little
            # (Igor, 2026-09-18: the design's fixed position covered wide products)
            dcx, dcy = cut_x - 0.30 * DISC, cut_y - 0.10 * DISC
        else:
            dcx, dcy = col_x + 0.06 * col_w + DISC / 2, mid_top + 0.08 * mid_h + DISC / 2   # design 4B default
        dcx = max(PAD_X / 2 + DISC / 2, dcx)                     # never off the left edge
        dcy = max(PAD_Y + LOGO_H + 12 + DISC / 2, dcy)           # never up in the logo row
        draw_disc(cv, W, H, dcx, dcy, DISC / 2, RED)
        ang = -8
        ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))
        for text, size, dy, tr, is_bold in ((f"{card['discount_pct']}%", 60, 3, -0.03, True), ("OFF", 22, 39, 0.04, False)):
            ax, ay = dcx - dy * sa, dcy + dy * ca              # anchor rotated with the disc
            draw_text(cv, W, H, fonts.face(is_bold), text, size, ax, ay, WHITE, tracking=tr, angle=ang, align="center",
                      embolden=fonts.embolden(is_bold))

    # ---- bottom block
    y = block_top
    for line in lines:
        draw_text(cv, W, H, bold, line, hsize, cx, y + hsize * 0.78, WHITE, tracking=-0.025, align="center", embolden=emb)
        y += line_h
    y += 8
    draw_text(cv, W, H, regular, subline, sub_size, cx, y + sub_size * 0.95, WHITE, align="center")
    y += sub_size * 1.3 + GAP
    sale_w = text_width(bold, card["price"], price_size)
    if card.get("compare"):
        reg_w = text_width(regular, card["compare"], strike_size)
        start = cx - (sale_w + 10 + reg_w) / 2
        draw_text(cv, W, H, bold, card["price"], price_size, start, y + price_size * 0.8, WHITE, embolden=emb)
        draw_text(cv, W, H, regular, card["compare"], strike_size, start + sale_w + 10, y + price_size * 0.8, WHITE, opacity=0.75)
        fill_rect(cv, W, H, int(start + sale_w + 10), int(y + price_size * 0.8 - strike_size * 0.32), int(reg_w), 1, WHITE, alpha=190)
    else:
        draw_text(cv, W, H, bold, card["price"], price_size, cx, y + price_size * 0.8, WHITE, align="center", embolden=emb)
    y += price_size + GAP
    shop_w, here_w = text_width(bold, "SHOP", btn_size, 0.08), text_width(regular, "HERE", btn_size, 0.08)
    btn_w = 20 + shop_w + 6 + here_w + 20
    bx = int(cx - btn_w / 2)
    fill_rect(cv, W, H, bx, int(y), int(btn_w), btn_h, BLACK)
    base = y + 13 + btn_size * 0.8
    draw_text(cv, W, H, bold, "SHOP", btn_size, bx + 20, base, WHITE, tracking=0.08, embolden=emb)
    draw_text(cv, W, H, regular, "HERE", btn_size, bx + 20 + shop_w + 6, base, WHITE, tracking=0.08)

    return encode_png(W, H, cv), time.perf_counter() - t0

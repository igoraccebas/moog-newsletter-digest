#!/usr/bin/env python3
"""
Moog Audio - weekly "new products" digest builder.

Reads a department's "New" collection from the public storefront JSON,
figures out which products are actually new, and renders a Klaviyo-ready
HTML email plus a JSON manifest (subject, preview text, product list).

It never sends anything. Creating the Klaviyo draft is a separate step.

Usage:
  python3 digest.py dj                 # last 7 days, updates state
  python3 digest.py modular --days 14  # wider window
  python3 digest.py guitar --dry-run   # don't touch state/
"""
import argparse, datetime as dt, hashlib, html, json, os, re, struct, sys, urllib.error, urllib.request, zlib
from pathlib import Path

STORE = "https://moogaudio.com"
KL_IMG = "https://d3k81ch9hvuctc.cloudfront.net/company/R2MsVA/images/"
LOGO = KL_IMG + "7da9e136-1a23-4b1a-a7e4-cc813a440e95.jpeg"        # MOOG AUDIO wordmark, 600px
IMG_PAYMENTS = KL_IMG + "4a0085a2-ce1a-4e34-a1fe-43dc088a03b2.png"  # affirm | flexiti | paypLan
IMG_REWARDS = KL_IMG + "e4ded96b-c43b-473e-80d3-9bcca41a798a.jpeg"  # Patch Rewards block
SOCIAL = [("https://www.facebook.com/moogaudio", KL_IMG + "b5f1ea80-3801-42ca-80e4-4e7a3be7731c.jpeg", "Facebook"),
          ("https://www.instagram.com/moogaudio", KL_IMG + "4a51cdda-7fba-4c6e-8299-2041478da024.jpeg", "Instagram"),
          ("https://www.youtube.com/@moogaudio", KL_IMG + "a77aec37-0413-4700-babc-fbf569f14440.jpeg", "YouTube"),
          ("https://www.tiktok.com/@moogaudio", KL_IMG + "591f87da-ac88-4102-9a1d-387d14e2b82f.jpeg", "TikTok")]
NAV = [("NEW RELEASES", "/collections/newreleases"), ("OPEN BOX", "/collections/sales?q=open+box"),
       ("NOW IN STOCK", "/collections/new-in-stock"), ("BLOG", "/blogs/news")]
CATEGORY_LINKS = [("SHOP ALL", "/collections/all"), ("MODULARS", "/collections/modular-synthesizers"),
                  ("DJ & TURNTABLES", "/collections/dj-and-turntables"), ("SYNTHESIZERS", "/collections/synthesizers"),
                  ("PEDALS", "/collections/pedals")]
ADDRESS = "3828 St Laurent Blvd - Montreal QC H2W 1X6"
AFFIRM_LEGAL = ("*Payment options through Affirm Canada Holdings Ltd. (\u201cAffirm\u201d). Your rate will be 0\u201331.99% APR "
    "(where available and subject to provincial regulatory limitations). APR offered is based on creditworthiness and subject "
    "to an eligibility check. Not all customers will be eligible for 0% APR. Payment options depend on your purchase amount, "
    "may vary by merchant, and may not be available in all provinces/territories. Actual payment option terms will be shown "
    "at checkout. A down payment (or a payment due today) may be required. Affirm accepts debit cards and PAD as forms of "
    "repayment on payment options. Select payment options may be eligible for repayment in the form of credit cards. Please "
    "review the terms and conditions of your credit card when using it as a form of repayment. Sample payment options may be: "
    "a $800 purchase could be split into 12 monthly payments of $72.21 at 15% APR, or 4 interest-free payments of $200 every "
    "2 weeks. For more information, please see https://www.affirm.com/en-ca/how-it-works.")
PREVIEW_SUFFIX = "FREE SHIPPING on most orders over 199$"
# Klaviyo publish settings (drafts only — this script never creates a send job)
KLAVIYO_API = "https://a.klaviyo.com/api/"
KLAVIYO_REVISION = "2024-10-15"
AUDIENCES = ["R5ggT7", "RmQMN3"]          # Newsletter Moog Audio + Website Form Newsletter List
FROM_EMAIL, FROM_LABEL = "nouvelles@moogaudio.com", "Moog Audio"
# Brand tokens (Moog Audio design system)
BLACK, WHITE, GREY_TXT, HAIRLINE = "#000000", "#ffffff", "#6f6f6f", "#dcdcdc"
RED, GREEN, CORAL = "#c1272d", "#1f8a4c", "#f86726"
LIGHT_TXT, CAT_TXT = "#d9d9d9", "#9a9a9a"   # light text on the black hero panel / category links
# Gmail's dark mode recolours background-color and text but never touches background-images, so a
# white CSS gradient keeps an image-only cell white in every mode (only use on cells with NO text).
WHITE_LOCK = "background-image:linear-gradient(#ffffff,#ffffff);"
FONT = "Helvetica, Arial, sans-serif"

DEPARTMENTS = {
    # store-wide, tag-driven (Tuesday & Friday). Products are hand-tagged in Shopify.
    "store":   {"handle": "newreleases", "label": "This Week's Picks", "short": "new releases",
                "eyebrow": "New at Moog Audio", "tag": "newsletter", "weekday": "Tuesday & Friday",
                "title": "This Week's Picks", "subject_lead": "New at Moog Audio"},
    # single-product launch e-mail, hourly, tag-driven (newsletter-hot). One product per run.
    "hot":     {"handle": "newreleases", "label": "Product Launch", "short": "launch",
                "eyebrow": "It's finally here", "tag": "newsletter-hot", "weekday": "hourly",
                "title": "Product Launch", "subject_lead": "It's here"},
    # department collections (kept for reference / fallback)
    "dj":      {"handle": "dj-equipment-new",        "label": "DJ Equipment", "short": "DJ gear",     "weekday": "Monday"},
    "modular": {"handle": "new-modular-synthesizers", "label": "Modular",      "short": "modular gear","weekday": "Wednesday"},
    "guitar":  {"handle": "guitar-gear-new",          "label": "Guitar Gear",  "short": "guitar gear", "weekday": "Friday"},
}
TAG = "newsletter"        # queues a product for the "Also New This Week" list
TAG_HERO = "newsletter-hero"  # marks the single "Pick of the Week" hero
TAG_HOT = "newsletter-hot"    # queues ONE product for the Product Launch e-mail (hourly routine)
# Product Launch e-mail (design: claude.ai/design "Product Launch Email"). Whole body sits on a coral
# gradient; hosted PNG because CSS gradients do not render in Outlook / Gmail Android. Copy lines
# below are static marketing copy from the design — edit freely.
# Backdrops for the launch e-mail. Each is a 600x1600 PNG (assets/launch-<name>.png, made with
# make_gradient.py from `stops`, angle 160deg) hosted on Klaviyo; `solid` is the Outlook fallback,
# `accent` colours the small PRODUCT LAUNCH label. Pick one per product with the Shopify tag
# "launch:<name>" (e.g. launch:graphite) or --launch-style; default is the design's coral.
LAUNCH_STYLES = {
    "coral":    {"solid": "#f86726", "accent": "#eabf7c", "image": KL_IMG + "1810eefe-5c37-410a-a2fa-aa3d16ea803d.png",
                 "stops": "#fdbb8f 0%,#f86726 30%,#eabf7c 58%,#ffe2d8 82%,#d5ddda 100%"},
    "graphite": {"solid": "#6f7784", "accent": "#c9ced6", "image": KL_IMG + "baf4aebb-f15a-495b-9a53-8b36c529d9f7.png",
                 "stops": "#8f96a2 0%,#6f7784 32%,#5f6774 58%,#7a828d 82%,#9aa1ab 100%"},
    "slate":    {"solid": "#8aa4c8", "accent": "#b8c9df", "image": KL_IMG + "f601dc03-cb3f-4574-a063-0f7a6f16f4bb.png",
                 "stops": "#dbe4f0 0%,#8aa4c8 30%,#b8c9df 58%,#e6edf6 82%,#d5ddda 100%"},
    "sage":     {"solid": "#7fb59a", "accent": "#b7d6c6", "image": KL_IMG + "6e4223da-ad62-4408-b4cf-f0d7b3ebb0eb.png",
                 "stops": "#e3efe8 0%,#7fb59a 30%,#b7d6c6 58%,#eaf3ee 82%,#d5ddda 100%"},
    "gold":     {"solid": "#e0a526", "accent": "#f0d18a", "image": KL_IMG + "3128b897-5b35-4be9-b80c-73a2aef2e621.png",
                 "stops": "#fbe7b5 0%,#e0a526 30%,#f0d18a 58%,#fff3d6 82%,#e6e0cf 100%"},
    "blush":    {"solid": "#e8687a", "accent": "#f3b6bf", "image": KL_IMG + "bccb80bb-6eb1-4f50-b884-048d08c59c4e.png",
                 "stops": "#fbd7dd 0%,#e8687a 30%,#f3b6bf 58%,#fde9ec 82%,#e4d9dc 100%"},
}
LAUNCH_TAG_PREFIX = "launch:"


def launch_style(name=None, tags=()):
    """Resolve the launch backdrop: explicit name > 'launch:<name>' product tag > coral."""
    if not name:
        for t in tags or ():
            if t.lower().startswith(LAUNCH_TAG_PREFIX) and t.split(":", 1)[1].strip().lower() in LAUNCH_STYLES:
                name = t.split(":", 1)[1].strip().lower()
                break
    name = (name or "coral").lower()
    if name not in LAUNCH_STYLES:
        raise SystemExit(f"unknown launch style '{name}'; choose from {', '.join(LAUNCH_STYLES)}")
    s = dict(LAUNCH_STYLES[name])
    s["name"], s["gradient"] = name, f"linear-gradient(160deg,{s['stops']})"
    return s
LAUNCH_NOTE = "Limited first allocation — orders are filled in sequence."
LAUNCH_BAND = "Want to try it first? Come see it at the Boutique — 3828 St Laurent Blvd, Montreal."
BLOG_URL, EVENTS_URL = "/blogs/news", "/blogs/events"
# Every product that goes into the email is also added to this manual collection (Admin collectionAddProducts)
NEW_RELEASES_COLLECTION = {"handle": "newreleases", "id": "gid://shopify/Collection/306490671293"}
# Hero background rotation. Each variant: solid fallback (classic Outlook), a hosted PNG of the
# gradient (Klaviyo CDN; renders in Gmail/Apple Mail/Outlook.com/Android which ignore CSS gradients)
# and the CSS gradient itself. Source PNGs live in assets/. Black type on all.
HERO_GRADIENTS = [
    {"name": "peach-coral", "image": "https://d3k81ch9hvuctc.cloudfront.net/company/R2MsVA/images/0e501c8e-d710-4c87-b48b-96540da6fe8e.png", "solid": "#f86726", "gradient": "linear-gradient(115deg,#fdbb8f 0%,#f86726 38%,#eabf7c 68%,#ffe2d8 100%)"},
    {"name": "gold-amber", "image": "https://d3k81ch9hvuctc.cloudfront.net/company/R2MsVA/images/f7372c2a-403e-4a5b-b8e6-d3cbe698ec39.png",  "solid": "#e0a526", "gradient": "linear-gradient(115deg,#ffe08a 0%,#e0a526 40%,#f2c76b 70%,#fff1c9 100%)"},
    {"name": "blush-rose", "image": "https://d3k81ch9hvuctc.cloudfront.net/company/R2MsVA/images/5948a0b7-ce37-4abd-8a5e-6b552762552f.png",  "solid": "#e8687a", "gradient": "linear-gradient(115deg,#ffc4cf 0%,#e8687a 40%,#f4a0ad 70%,#ffe6ea 100%)"},
    {"name": "sage-mint", "image": "https://d3k81ch9hvuctc.cloudfront.net/company/R2MsVA/images/d9c1de40-a3a4-4d86-95fb-3996cd7f0402.png",   "solid": "#7fb59a", "gradient": "linear-gradient(115deg,#cfe9d9 0%,#7fb59a 40%,#a9d3bf 70%,#eaf6ef 100%)"},
    {"name": "slate-ice", "image": "https://d3k81ch9hvuctc.cloudfront.net/company/R2MsVA/images/44afa799-9a24-4bb7-b6c0-4dd91552a975.png",   "solid": "#8aa4c8", "gradient": "linear-gradient(115deg,#d6e2f5 0%,#8aa4c8 40%,#b3c6e3 70%,#eef3fb 100%)"},
]
HERO_EPOCH = dt.date(2026, 8, 31)   # a Monday; run slots are Tue (0) and Fri (1) of each week


def pick_hero_style(day=None, name=None):
    """Deterministic rotation: consecutive Tue/Fri runs walk through HERO_GRADIENTS in order."""
    if name:
        for g in HERO_GRADIENTS:
            if g["name"] == name:
                return g
        raise SystemExit(f"unknown hero style {name!r}; choose from {[g['name'] for g in HERO_GRADIENTS]}")
    day = day or dt.date.today()
    weeks = (day - HERO_EPOCH).days // 7
    slot = 0 if day.weekday() <= 3 else 1          # Mon-Thu -> Tuesday slot, Fri-Sun -> Friday slot
    return HERO_GRADIENTS[(weeks * 2 + slot) % len(HERO_GRADIENTS)]


# Keep the email light in dark mode where the client lets us:
#  Dark mode strategy (2026-09-08):
#  - Clients that honour a dark theme (Apple Mail, iOS Mail, Outlook apps via prefers-color-scheme;
#    Outlook.com / new Outlook via [data-ogsc]/[data-ogsb]) get the DESIGNED dark theme below:
#    dark page, white text, buttons inverted to white-on-black, hairlines dimmed. Things that must
#    keep their colour in every mode (hero text on the gradient image, white image tiles, nav band,
#    red sale flag) carry LOCK rules for Outlook, which otherwise recolours them on its own.
#  - Gmail (iOS/Android) ignores all of it and inverts by itself (iOS flips light AND dark blocks,
#    Android only light ones), so the layout is also built to survive inversion: live-text wordmark,
#    image-only cells locked white with WHITE_LOCK, black buttons with a white hairline border.
DARK_RULES = [
    (".bg-page", "background-color:#0f0f0f!important"),
    (".bg-body", "background-color:#1c1c1c!important"),
    (".txt-black,.txt-black a", "color:#ffffff!important"),
    (".txt-grey", "color:#b5b5b5!important"),
    (".txt-red", "color:#ff5c5c!important"),
    (".hl", "border-color:#3a3a3a!important"),
    (".btn", "background-color:#ffffff!important;color:#000000!important;border-color:#ffffff!important"),
    (".btn a", "color:#000000!important"),
]
LOCK_RULES = [   # same in light and dark; only needed because Outlook recolours on its own
    ("[data-ogsb] .bg-tile", "background-color:#ffffff!important"),
    ("[data-ogsb] .bg-launch", "background-color:#f86726!important"),
    ("[data-ogsc] .txt-sand", "color:#eabf7c!important"),
    ("[data-ogsb] .bg-nav,[data-ogsb] .bg-band,[data-ogsb] .btn-hero", "background-color:#000000!important"),
    ("[data-ogsb] .bg-red", "background-color:#c1272d!important"),
    ("[data-ogsc] .txt-hero,[data-ogsc] .txt-hero a", "color:#000000!important"),
    ("[data-ogsc] .txt-white,[data-ogsc] .txt-white a,[data-ogsc] .btn-hero a", "color:#ffffff!important"),
    ("[data-ogsc] .txt-coral", "color:#f86726!important"),
    ("[data-ogsc] a.txt-cat", "color:#9a9a9a!important"),
]


# "lock-light" (default, Igor 2026-09-08): the email stays light wherever the client lets us decide
# (Apple Mail, iOS Mail, Outlook.com / new Outlook). Only Gmail and Outlook mobile invert, and the
# layout survives that. "themed": serve the designed dark theme above to dark-mode users instead.
DARK_MODE = "lock-light"
LIGHT_LOCK_RULES = [   # Outlook.com / new Outlook re-assert the light design in their dark mode
    ("[data-ogsb] .bg-page", "background-color:#ececec!important"),
    ("[data-ogsb] .bg-launch", "background-color:#f86726!important"),
    ("[data-ogsc] .txt-sand", "color:#eabf7c!important"),
    ("[data-ogsb] .bg-body,[data-ogsb] .bg-tile", "background-color:#ffffff!important"),
    ("[data-ogsb] .bg-nav,[data-ogsb] .bg-band,[data-ogsb] .btn,[data-ogsb] .btn-hero", "background-color:#000000!important"),
    ("[data-ogsb] .bg-red", "background-color:#c1272d!important"),
    ("[data-ogsc] .txt-black,[data-ogsc] .txt-black a,[data-ogsc] .txt-hero,[data-ogsc] .txt-hero a", "color:#000000!important"),
    ("[data-ogsc] .txt-grey", "color:#6f6f6f!important"),
    ("[data-ogsc] .txt-white,[data-ogsc] .txt-white a,[data-ogsc] .btn,[data-ogsc] .btn a,[data-ogsc] .btn-hero a", "color:#ffffff!important"),
    ("[data-ogsc] .txt-red", "color:#c1272d!important"),
    ("[data-ogsc] .txt-coral", "color:#f86726!important"),
    ("[data-ogsc] a.txt-cat", "color:#9a9a9a!important"),
    ("[data-ogsc] .hl", "border-color:#dcdcdc!important"),
]


def color_scheme_meta():
    return "light" if DARK_MODE == "lock-light" else "light dark"


def dark_css():
    if DARK_MODE == "lock-light":
        return (":root{color-scheme:light only;supported-color-schemes:light;}"
                + "".join(f"{s}{{{d}}}" for s, d in LIGHT_LOCK_RULES))
    media = "@media (prefers-color-scheme: dark){" + "".join(f"{s}{{{d}}}" for s, d in DARK_RULES) + "}"
    outlook = "".join(",".join("[data-ogsc] " + part.strip() for part in s.split(",")) + f"{{{d}}}" for s, d in DARK_RULES)
    locks = "".join(f"{s}{{{d}}}" for s, d in LOCK_RULES)
    return ":root{color-scheme:light dark;supported-color-schemes:light dark;}" + media + outlook + locks

MOBILE_CSS = (
    "@media only screen and (max-width:480px){"
    " .stack{display:block!important;width:100%!important;padding-right:0!important;}"
    " .stack-img{padding-bottom:14px!important;}"
    " .stack-img img{width:100%!important;max-width:320px!important;margin:0 auto;}"
    " .m-h1{font-size:30px!important;line-height:36px!important;}"
    " .m-intro{font-size:17px!important;line-height:25px!important;}"
    " .m-label{font-size:13px!important;line-height:18px!important;}"
    " .m-nav a{font-size:13px!important;}"
    " .m-hero-title{font-size:24px!important;line-height:30px!important;}"
    " .m-title{font-size:19px!important;line-height:25px!important;}"
    " .m-body{font-size:16px!important;line-height:24px!important;}"
    " .m-price{font-size:17px!important;line-height:24px!important;}"
    " .m-btn{font-size:14px!important;padding:14px 22px!important;}"
    " .m-section{font-size:20px!important;}"
    " .m-small{font-size:14px!important;line-height:20px!important;}"
    " .m-legal{font-size:12px!important;line-height:17px!important;}"
    " .m-full{width:100%!important;max-width:100%!important;height:auto!important;}"
    " .m-logo{font-size:24px!important;line-height:30px!important;letter-spacing:4px!important;}"
    " .m-launch-h1{font-size:30px!important;line-height:34px!important;}"
    " .m-pad{padding-left:20px!important;padding-right:20px!important;}"
    " .m-pad2{padding-left:14px!important;padding-right:14px!important;}"
    "}")
# Noise rules (applied to every department). Tweak freely.
EXCLUDE_TYPES = {"Parts"}
EXCLUDE_TITLE_RE = re.compile(r"\((part|parts)\)", re.I)

STATUS_ORDER = ["in-stock", "arriving-soon", "pre-order", "order-now", "special-order"]
STATUS_LABEL = {"in-stock": "In Stock", "arriving-soon": "Arriving Soon", "pre-order": "Pre-Order",
                "order-now": "Order Now", "special-order": "Special Order"}

ROOT = Path(__file__).resolve().parent
OUT, STATE = ROOT / "out", ROOT / "state"


def fetch_collection(handle):
    items, page = [], 1
    while True:
        url = f"{STORE}/collections/{handle}/products.json?limit=250&page={page}"
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "MoogDigest/1.0"}), timeout=60) as r:
            batch = json.load(r)["products"]
        items += batch
        if len(batch) < 250:
            return items
        page += 1


def normalize_admin(node):
    """Shopify Admin GraphQL product node -> storefront-JSON-like dict used by the rest of the script."""
    variants = []
    for v in (node.get("variants") or {}).get("nodes", []):
        cmp_ = v.get("compareAtPrice")
        variants.append({"price": v["price"],
                         "compare_at_price": cmp_ if cmp_ and float(cmp_) > 0 else None,
                         "available": bool(v.get("availableForSale"))})
    img = (node.get("featuredImage") or {}).get("url")
    gallery = [n.get("url") for n in (node.get("images") or {}).get("nodes", []) if n.get("url")]
    ordered = ([img] if img else []) + [u for u in gallery if u != img]   # featured first, then the rest
    return {
        "id": int(str(node["id"]).rsplit("/", 1)[-1]), "admin_id": node["id"],
        "title": node["title"], "handle": node["handle"], "vendor": node.get("vendor") or "",
        "product_type": node.get("productType") or "", "tags": node.get("tags") or [],
        "published_at": node.get("publishedAt"), "status": node.get("status"),
        "body_html": node.get("descriptionHtml") or "",
        "images": [{"src": u} for u in ordered], "variants": variants,
    }


def load_products(path, allow_unpublished=False):
    """Accepts a raw Admin GraphQL response, a list of admin nodes, or a storefront-style list.
    allow_unpublished=True (launch mode) keeps DRAFT / not-yet-published products so an embargoed
    launch can be tagged ahead of time; the manifest then carries live=false."""
    data = json.loads(Path(path).read_text())
    if isinstance(data, dict):
        data = data.get("data", data).get("products", data)
        data = data.get("nodes", data) if isinstance(data, dict) else data
    out = []
    for item in data:
        p = normalize_admin(item) if "productType" in item else item
        if p.get("status") == "ARCHIVED":
            continue
        if not allow_unpublished:
            if p.get("status") and p["status"] != "ACTIVE":
                continue
            if not p.get("published_at"):
                continue
        out.append(p)
    return out


TAG_RE = re.compile(r"<[^>]+>")


WORD_RE = re.compile(r"[a-z0-9]+")


def _tokens(text):
    return set(WORD_RE.findall(text.lower().replace("–", "-").replace("-", " ")))


def excerpt(body_html, title, limit=170, min_len=40):
    """First real paragraph of the description. Skips short lines and anything that is mostly
    a restatement of the product title (e.g. 'Brand Model Descriptor.')."""
    paras = [html.unescape(TAG_RE.sub(" ", x)).replace("\xa0", " ") for x in re.split(r"</p>|<br\s*/?>|</li>|</h[1-6]>", body_html or "")]
    paras = [re.sub(r"\s+", " ", x).strip() for x in paras]
    tt = _tokens(title)
    for x in paras:
        if len(x) < min_len:
            continue
        xt = _tokens(x)
        if xt and len(xt & tt) / len(xt) >= 0.6:
            continue
        if len(x) <= limit:
            return x
        return x[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return ""


MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
MONTHS.update({"janv": 1, "fév": 2, "fev": 2, "mars": 3, "avr": 4, "mai": 5, "juin": 6, "juil": 7, "août": 8, "aout": 8,
               "sept": 9, "déc": 12, "dec": 12})
DATE_RE = re.compile(r"\b(?:(\d{1,2})(?:st|nd|rd|th)?\s+)?([A-Za-zéû]{3,9})\.?\s*(\d{1,2})?(?:st|nd|rd|th)?\b")
TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|h)\b", re.I)


META_DESC_RE = re.compile(r'<meta[^>]+(?:property="og:description"|name="description")[^>]+content="([^"]*)"', re.I)
_META_CACHE = {}


def img_url(src, **params):
    """Append Shopify CDN resize params (width, height, crop) to an image URL."""
    return src + ("&" if "?" in src else "?") + "&".join(f"{k}={v}" for k, v in params.items())


def flatten_png(data):
    """If `data` is a PNG with transparency, return an opaque PNG (RGB) composited onto white; else None.
    Pure Python: 8-bit, non-interlaced, colour types RGBA (6), grey+alpha (4) and palette+tRNS (3)."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
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
    if not hdr:
        return None
    w, h, depth, ctype, _, _, interlace = hdr
    if depth != 8 or interlace or ctype not in (3, 4, 6) or (ctype == 3 and not trns):
        return None                                   # no alpha channel (or unsupported): keep the original
    ch = {3: 1, 4: 2, 6: 4}[ctype]
    raw = zlib.decompress(b"".join(idat))
    stride = w * ch
    prev = bytearray(stride)
    p = 0
    rows = []
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
    if ctype == 3:                                    # palette + tRNS -> RGBA
        alpha = trns + b"\xff" * 256
        rows = [bytearray(b"".join(plte[3 * v:3 * v + 3] + bytes([alpha[v]]) for v in line)) for line in rows]
        ch = 4
    out_rows = []
    has_alpha = False
    for line in rows:
        o = bytearray(w * 3)
        for x in range(w):
            if ch == 4:
                r, g, b, a = line[4 * x:4 * x + 4]
            else:
                r = g = b = line[2 * x]
                a = line[2 * x + 1]
            if a != 255:
                has_alpha = True
                inv = 255 - a
                r, g, b = (r * a + 255 * inv) // 255, (g * a + 255 * inv) // 255, (b * a + 255 * inv) // 255
            o[3 * x], o[3 * x + 1], o[3 * x + 2] = r, g, b
        out_rows.append(bytes(o))
    if not has_alpha:
        return None
    body = b"".join(b"\x00" + r for r in out_rows)
    def chunk(tag, payload):
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(body, 9)) + chunk(b"IEND", b""))


def klaviyo_upload_image(png_bytes, name, api_key):
    """POST /api/image-upload/ (multipart). Returns the hosted image URL."""
    boundary = "----moog-digest-" + hashlib.sha1(png_bytes).hexdigest()[:16]
    parts = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"name\"\r\n\r\n{name}\r\n"
             f"--{boundary}\r\nContent-Disposition: form-data; name=\"hidden\"\r\n\r\nfalse\r\n"
             f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}.png\"\r\n"
             f"Content-Type: image/png\r\n\r\n").encode() + png_bytes + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(KLAVIYO_API + "image-upload", data=parts, method="POST", headers={
        "Authorization": f"Klaviyo-API-Key {api_key}", "revision": KLAVIYO_REVISION, "accept": "application/json",
        "content-type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read())["data"]["attributes"]["image_url"]


_OPAQUE_CACHE = {}


def product_img(src, **params):
    """Shopify CDN URL with resize params. A PNG with a transparent background is downloaded, composited
    onto white and re-hosted on Klaviyo (needs KLAVIYO_API_KEY), because mail clients that invert
    colours in dark mode would otherwise show a dark box behind the product. Falls back to the plain
    CDN URL whenever that is not possible."""
    url = img_url(src, **params)
    if not src.split("?")[0].lower().endswith(".png"):
        return url
    if url in _OPAQUE_CACHE:
        return _OPAQUE_CACHE[url]
    result, short = url, src.split("/")[-1].split("?")[0]
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as r:
            flat = flatten_png(r.read())
        if flat:
            key = os.environ.get("KLAVIYO_API_KEY")
            if key:
                result = klaviyo_upload_image(flat, "flat-" + hashlib.sha1(url.encode()).hexdigest()[:12], key)
                print(f"  note: {short} had a transparent background; hosted a flattened copy on Klaviyo")
            else:
                print(f"  note: {short} has a transparent background (dark box in inverting clients); "
                      f"set KLAVIYO_API_KEY to host a flattened copy")
    except Exception as e:                            # network blocked, odd PNG, upload refused: keep the CDN URL
        print(f"  note: could not flatten {short}: {e}")
    _OPAQUE_CACHE[url] = result
    return result


def split_title(title, vendor="", product_type=""):
    """Headline / sub-line for the launch e-mail.
    'Morphor Echon 6 Analog Polyphonic BBD Synthesizer' -> ('Morphor Echon 6', 'Analog Polyphonic BBD Synthesizer')
    Rules: split on ' - ' first; else right after the first model-number token (contains a digit);
    else the whole title, with the product type as sub-line."""
    parts = re.split(r"\s+[-–]\s+", title, maxsplit=1)
    if len(parts) == 2 and 3 <= len(parts[0]) <= 40 and parts[1].strip():
        return parts[0].strip(), parts[1].strip()
    toks = title.split()
    for i, t in enumerate(toks):
        if 1 <= i <= 4 and re.search(r"\d", t):
            head, tail = " ".join(toks[:i + 1]), " ".join(toks[i + 1:])
            if tail:
                return head, tail
            break
    return title, (product_type or "")


def long_blurb(body_html, title, limit=480, min_len=120):
    """Two-ish paragraphs of the product description (no bullet lists, no headings, no title line),
    cut at a sentence boundary near `limit`."""
    body = re.sub(r"<(ul|ol|table)[^>]*>.*?</\1>", " ", body_html or "", flags=re.S | re.I)
    body = re.sub(r"<h\d[^>]*>.*?</h\d>", " ", body, flags=re.S | re.I)
    title_t = _tokens(title)
    paras = []
    for raw in re.split(r"</p>|<br\s*/?>|</div>", body, flags=re.I):
        t = html.unescape(re.sub(r"\s+", " ", TAG_RE.sub(" ", raw))).strip()
        if len(t) < 40:
            continue
        toks = _tokens(t)
        if toks and len(toks & title_t) / len(toks) > 0.6:          # the title repeated as a line
            continue
        if re.match(r"^(key\s+)?(features?|specifications?|specs|highlights?)\b", t, re.I):
            continue
        letters = [c for c in t if c.isalpha()]
        if letters and sum(c.isupper() for c in letters) / len(letters) > 0.8 and len(t) < 120:
            continue                                                 # ALL-CAPS label line ("8-CHANNEL AUDIO & CV ...")
        paras.append(t)
    text = ""
    for p in paras:
        if not text:
            text = p
        elif len(text) + 1 + len(p) <= limit:
            text += " " + p
        else:
            break
    if len(text) > limit:
        cut = text[:limit]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        text = cut[:end + 1] if end >= min_len else cut.rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return text


def spec_rows(body_html, limit=6):
    """Rows for the SPECIFICATIONS box, from the first bullet list in the description.
    'Voices: 6-voice analog' -> ('Voices', '6-voice analog'); a bullet without 'Label: value'
    shape becomes ('', bullet) and is rendered full-width."""
    body = body_html or ""
    heads = [(m.start(), html.unescape(TAG_RE.sub(" ", m.group(1))).strip())
             for m in re.finditer(r"<h\d[^>]*>(.*?)</h\d>", body, flags=re.S | re.I)]
    lists = []          # (heading just above the list, items)
    for m in re.finditer(r"<(?:ul|ol)[^>]*>(.*?)</(?:ul|ol)>", body, flags=re.S | re.I):
        head = next((h for pos, h in reversed(heads) if pos < m.start()), "")
        items = []
        for li in re.findall(r"<li[^>]*>(.*?)</li>", m.group(1), flags=re.S | re.I):
            t = html.unescape(re.sub(r"\s+", " ", TAG_RE.sub(" ", li))).strip(" .;•·-–")
            if 3 <= len(t) <= 160:
                items.append(t)
        if items:
            lists.append((head, items))
    if not lists:
        return []
    # prefer a list under a "Specifications"-style heading, else the first list (usually Features)
    _, items = next(((h, it) for h, it in lists if re.search(r"spec", h, re.I)), lists[0])
    rows = []
    for t in items[:limit]:
        m = re.match(r"^([^:–—]{2,28}?)\s*[:–—]\s+(.+)$", t)
        rows.append((m.group(1).strip(), m.group(2).strip()) if m else ("", t))
    return rows


def fetch_meta_description(url):
    """Teaser from the public article page (<meta og:description>). Fails soft to ''."""
    if url in _META_CACHE:
        return _META_CACHE[url]
    text = ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MoogDigest/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            head = r.read(200_000).decode("utf-8", errors="replace")
        m = META_DESC_RE.search(head)
        text = html.unescape(m.group(1)).strip() if m else ""
    except Exception:
        text = ""
    _META_CACHE[url] = text
    return text


def article_teaser(node, limit=110):
    text = (node.get("summary") or "").strip() or excerpt(node.get("body") or "", node["title"], limit=limit, min_len=80)
    if not text:
        text = fetch_meta_description(article_url(node))
        # Shopify's page description = title + headings + first words; keep just the prose part.
        t = node["title"].strip()
        if text.lower().startswith(t.lower()):
            text = text[len(t):].strip(" :-–|")
        if "Introduction" in text:
            text = text.split("Introduction", 1)[1].strip()
        elif "?" in text[:120]:
            text = text.split("?", 1)[1].strip()
    text = re.sub(r"\s+", " ", TAG_RE.sub(" ", html.unescape(text))).strip()
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def article_url(node):
    return f"{STORE}/blogs/{(node.get('blog') or {}).get('handle', 'news')}/{node['handle']}"


FULL_DATE_RE = re.compile(
    r"\b(?:(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day,?\s+)?"
    r"(January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d{2})\b")


def event_date(node):
    """First full date ('Saturday, April 25, 2026') found in title+body, as a date; None if absent."""
    text = html.unescape(TAG_RE.sub(" ", f"{node['title']} {node.get('body') or ''}"))
    m = FULL_DATE_RE.search(text)
    if not m:
        return None
    mon = MONTHS.get(m.group(1).lower()[:4]) or MONTHS.get(m.group(1).lower()[:3])
    try:
        return dt.date(int(m.group(3)), mon, int(m.group(2)))
    except (TypeError, ValueError):
        return None


def event_when(node):
    """('SEP 12', '7 PM') for the email; time is the first clock time after the date, if any."""
    d = event_date(node)
    if not d:
        return None, None
    text = html.unescape(TAG_RE.sub(" ", node.get("body") or ""))
    m = FULL_DATE_RE.search(text)
    tail = text[m.end():m.end() + 200] if m else text
    t = TIME_RE.search(tail)
    time_label = None
    if t:
        hh, mm, ap = int(t.group(1)), t.group(2), t.group(3).lower()
        if ap == "h":
            ap = "pm" if hh >= 12 else "am"; hh = hh - 12 if hh > 12 else hh
        time_label = f"{hh}{':' + mm if mm and mm != '00' else ''} {ap.upper()}"
    return d.strftime("%b %-d").upper(), time_label


def upcoming(events, today=None):
    today = today or dt.date.today()
    keep = [(event_date(e), e) for e in events]
    keep = [(d, e) for d, e in keep if d and d >= today]
    return [e for d, e in sorted(keep, key=lambda x: x[0])]


def load_extras(path):
    """extras.json: {"blog": [<article nodes>], "events": [<article nodes>]} (raw Admin GraphQL article nodes)."""
    if not path:
        return {"blog": [], "events": []}
    data = json.loads(Path(path).read_text())
    def nodes(x):
        if isinstance(x, dict):
            x = x.get("data", x).get("articles", x)
            x = x.get("nodes", x) if isinstance(x, dict) else x
        return [n for n in (x or []) if n.get("publishedAt")]
    return {"blog": nodes(data.get("blog")), "events": upcoming(nodes(data.get("events")))}


def status_of(tags):
    found = set()
    for t in tags:
        if t.startswith("status:"):
            found.add(t.split(":", 1)[1])
        elif t == "Pre-Orders":
            found.add("pre-order")
    for s in STATUS_ORDER:
        if s in found:
            return s
    return None


def is_purchasable(p):
    """False when the storefront shows 'Sold out' (no variant can be added to cart)."""
    return any(v.get("available") for v in p.get("variants", []))


def is_noise(p):
    return p.get("product_type") in EXCLUDE_TYPES or bool(EXCLUDE_TITLE_RE.search(p["title"])) or not p.get("images")


MODEL_TOKEN = re.compile(r"^[A-Z0-9][A-Z0-9/-]{3,}$")  # e.g. SL-1200M7GL, AT-VM95EBK


def stem_of(title):
    """Title with a trailing ' - variant' suffix and model codes removed. Used only to group siblings."""
    base = re.split(r"\s+[-–]\s+", title)[0]
    toks = [t for t in base.split() if not (MODEL_TOKEN.match(t) and re.search(r"\d", t) and re.search(r"[A-Z]", t))]
    return " ".join(toks).lower()


def variant_suffix(title):
    parts = re.split(r"\s+[-–]\s+", title)
    return parts[-1].strip() if len(parts) > 1 else None


def money(v):
    return f"${float(v):,.2f} CAD"


def group(products):
    """Collapse colour/finish siblings into one card. Only groups when every sibling has a
    distinct ' - variant' suffix (or identical titles); anything else stays a separate card."""
    buckets = {}
    for p in products:
        key = (p["vendor"], p.get("product_type"), stem_of(p["title"]))
        buckets.setdefault(key, []).append(p)

    def first_avail(p):
        return next((v for v in p["variants"] if v.get("available")), p["variants"][0])

    def make_card(ps, variants):
        ps.sort(key=lambda p: p["published_at"], reverse=True)
        lead = ps[0]
        prices = sorted({float(first_avail(p)["price"]) for p in ps})
        compares = [float(first_avail(p)["compare_at_price"]) for p in ps
                    if first_avail(p).get("compare_at_price") and float(first_avail(p)["compare_at_price"]) > float(first_avail(p)["price"])]
        compare = max(compares) if (compares and len(prices) == 1) else None
        title = re.split(r"\s+[-–]\s+", lead["title"])[0] if variants else lead["title"]
        statuses = [status_of(p["tags"]) for p in ps]
        return {
            "title": title, "vendor": lead["vendor"], "type": lead.get("product_type"),
            "url": f"{STORE}/products/{lead['handle']}", "image": lead["images"][0]["src"],
            "price": (("From " if len(prices) > 1 else "") + money(prices[0])),
            "compare": money(compare) if compare else None,
            "save": money(compare - prices[0]) if compare else None,
            "status": next((s for s in STATUS_ORDER if s in statuses), None),
            "variants": variants,
            "published_at": lead["published_at"], "ids": [p["id"] for p in ps],
            "admin_ids": [p.get("admin_id") for p in ps if p.get("admin_id")],
            "excerpt": excerpt(lead.get("body_html", ""), lead["title"]), "_price_num": prices[-1],
        }

    cards = []
    for _, ps in buckets.items():
        if len(ps) == 1:
            cards.append(make_card(ps, []))
            continue
        suffixes = [variant_suffix(p["title"]) for p in ps]
        titles = {p["title"] for p in ps}
        if all(suffixes) and len(set(suffixes)) == len(suffixes):
            cards.append(make_card(ps, suffixes))          # colour/finish family
        elif len(titles) == 1:
            cards.append(make_card(ps, []))                # duplicate listings of one product
        else:
            cards.extend(make_card([p], []) for p in ps)   # unrelated, keep separate
    cards.sort(key=lambda c: (c["published_at"][:10], c["_price_num"]), reverse=True)
    return cards


def render(dept, cards, week_label):
    d = DEPARTMENTS[dept]
    utm = f"?utm_source=klaviyo&utm_medium=email&utm_campaign=new-{dept}-digest"
    amp = "&" if "?" in utm else "?"
    def link(path):  # store link with utm
        return f"{STORE}{path}" + ("&" if "?" in path else "?") + utm[1:]
    coll_url = link(f"/collections/{d['handle']}")
    n = len(cards)
    esc = html.escape
    eyebrow = d.get("eyebrow", "New Arrivals")
    if dept == "store":
        heading = d["title"]
        intro = f"{n} new {'pick' if n == 1 else 'picks'} from across the store, chosen by the team. Here's what's worth a look this week."
        cta = "Shop All New Releases"
    else:
        heading = f"New in {d['label']}"
        intro = f"{n} new {'arrival' if n == 1 else 'arrivals'} just landed in {d['label']}. Here's what's new this week."
        cta = f"View All New {d['short']}"
    btn = (f"display:inline-block;background:{BLACK};color:{WHITE};font-family:{FONT};font-size:12px;font-weight:700;"
           f"letter-spacing:1px;text-transform:uppercase;text-decoration:none;border-radius:0;")

    def row_html(c, last):
        url = c["url"] + utm
        if c["compare"]:
            price = (f'<span style="color:{RED};font-weight:700;">{esc(c["price"])}</span> '
                     f'<span style="color:{GREY_TXT};text-decoration:line-through;font-size:12px;">{esc(c["compare"])}</span> '
                     f'<span style="display:inline-block;background:{RED};color:{WHITE};font-size:10px;font-weight:700;'
                     f'letter-spacing:1px;text-transform:uppercase;padding:3px 6px;margin-left:6px;">Save {esc(c["save"])}</span>')
        else:
            price = f'<span style="color:{BLACK};">{esc(c["price"])}</span>'
        # Stock status is deliberately NOT shown: emails are static and availability changes.
        variants = ""
        if c["variants"]:
            variants = (f'<div style="font-size:12px;color:{GREY_TXT};margin-top:4px;">'
                        f'{len(c["variants"])} options: {esc(", ".join(c["variants"]))}</div>')
        blurb = f'<div style="font-size:13px;line-height:19px;color:{BLACK};margin-top:8px;">{esc(c["excerpt"])}</div>' if c.get("excerpt") else ""
        border = "" if last else f"border-bottom:1px solid {HAIRLINE};"
        return f"""
      <tr><td style="padding:22px 0;{border}">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
          <td class="stack stack-img" width="200" valign="top" style="width:200px;padding-right:20px;">
            <a href="{url}"><img src="{c['image']}&width=400" width="200" alt="{esc(c['title'])}"
               style="display:block;width:200px;max-width:100%;height:auto;border:0;background:{WHITE};"></a>
          </td>
          <td class="stack" valign="top" style="font-family:{FONT};">
            <div style="font-size:11px;letter-spacing:1px;text-transform:uppercase;color:{GREY_TXT};">{esc(c['vendor'])}</div>
            <div style="font-size:16px;line-height:21px;font-weight:700;color:{BLACK};margin-top:4px;">
              <a href="{url}" style="color:{BLACK};text-decoration:none;">{esc(c['title'])}</a>
            </div>
            {variants}
            {blurb}
            <div style="font-size:14px;margin-top:10px;">{price}</div>
            <div style="margin-top:14px;"><a href="{url}" style="{btn}padding:10px 16px;">View Product</a></div>
          </td>
        </tr></table>
      </td></tr>"""

    grid = "\n".join(row_html(c, i == n - 1) for i, c in enumerate(cards))

    nav_cells = "".join(
        f'<td align="center" style="padding:11px 6px;"><a href="{link(p)}" style="color:{WHITE};font-family:{FONT};font-size:12px;'
        f'letter-spacing:1px;text-decoration:none;">{t}</a></td>' for t, p in NAV)
    cat_rows = "".join(
        f'<tr><td align="center" style="padding:9px 0;border-bottom:1px solid {HAIRLINE};"><a href="{link(p)}" style="color:#c1c1c1;'
        f'font-family:{FONT};font-size:14px;font-weight:700;letter-spacing:2px;text-decoration:none;">{t}</a></td></tr>'
        for t, p in CATEGORY_LINKS)
    social = "".join(
        f'<a href="{u}" style="display:inline-block;margin:0 7px;"><img src="{img}" width="25" height="25" alt="{a}" style="display:block;border:0;"></a>'
        for u, img, a in SOCIAL)
    gradient = "linear-gradient(90deg,#fdbb8f 0%,#f86726 35%,#eabf7c 65%,#ffe2d8 85%,#d5ddda 100%)"

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(heading)}</title>
<style>@media only screen and (max-width:480px){{ .stack{{display:block!important;width:100%!important;padding-right:0!important;}} .stack-img{{padding-bottom:14px!important;}} .stack-img img{{width:100%!important;max-width:320px!important;margin:0 auto;}} }}</style></head>
<body style="margin:0;padding:0;background:{WHITE};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{WHITE};">
<tr><td align="center">
  <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:{WHITE};">
    <tr><td align="center" style="padding:10px 0 4px 0;font-family:{FONT};font-size:10px;color:{GREY_TXT};">
      Can't see this email? {{% web_view 'View in Your Browser' %}}
    </td></tr>
    <tr><td align="center" style="padding:6px 0 14px 0;">
      <a href="{link('/')}"><img src="{LOGO}" width="600" alt="Moog Audio" style="display:block;width:100%;max-width:600px;height:auto;border:0;"></a>
    </td></tr>
    <tr><td style="background:{BLACK};"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>{nav_cells}</tr></table></td></tr>
    <tr><td style="height:3px;line-height:3px;font-size:0;background:{CORAL};background-image:{gradient};">&nbsp;</td></tr>
    <tr><td align="center" style="padding:14px 20px;font-family:{FONT};font-size:12px;color:{BLACK};border-bottom:1px solid {HAIRLINE};">
      <strong>FREE SHIPPING</strong> on most orders over 199$ | <strong>FLEXITI</strong> financing available at checkout
    </td></tr>

    <tr><td align="center" style="padding:36px 24px 8px 24px;font-family:{FONT};">
      <div style="font-size:11px;letter-spacing:2px;text-transform:uppercase;color:{GREY_TXT};">{esc(eyebrow)} &middot; {esc(week_label)}</div>
      <h1 style="margin:10px 0 0 0;font-family:{FONT};font-size:28px;line-height:34px;font-weight:700;letter-spacing:-0.3px;color:{BLACK};">{esc(heading)}</h1>
      <p style="margin:10px 0 0 0;font-size:14px;line-height:21px;color:{BLACK};">{esc(intro)}</p>
    </td></tr>
    <tr><td style="padding:10px 24px 0 24px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{grid}</table>
    </td></tr>
    <tr><td align="center" style="padding:28px 24px 40px 24px;">
      <a href="{coll_url}" style="{btn}padding:14px 26px;">{esc(cta)}</a>
    </td></tr>

    <tr><td style="padding:0 24px;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid {HAIRLINE};">{cat_rows}</table></td></tr>
    <tr><td align="center" style="padding:28px 0 6px 0;">
      <img src="{IMG_PAYMENTS}" width="600" alt="Affirm, Flexiti and PayPlan by RBC financing" style="display:block;width:100%;max-width:600px;height:auto;border:0;">
    </td></tr>
    <tr><td align="center" style="padding:6px 0 10px 0;">
      <a href="{link('/pages/reward')}"><img src="{IMG_REWARDS}" width="600" alt="Patch Rewards: earn points every time you shop, connect and review" style="display:block;width:100%;max-width:600px;height:auto;border:0;"></a>
    </td></tr>
    <tr><td align="center" style="padding:10px 0 22px 0;">{social}</td></tr>
    <tr><td align="center" style="padding:0 24px 12px 24px;font-family:{FONT};font-size:12px;line-height:18px;color:{BLACK};">
      <a href="{link('/')}" style="color:{BLACK};font-weight:700;text-decoration:underline;">moogaudio.com</a><br>
      <a href="https://maps.google.com/?q=3828+St+Laurent+Blvd+Montreal+QC+H2W+1X6" style="color:{BLACK};text-decoration:underline;">{ADDRESS}</a>
    </td></tr>
    <tr><td style="padding:8px 24px 16px 24px;font-family:{FONT};font-size:10px;line-height:15px;color:{GREY_TXT};text-align:justify;">
      {esc(AFFIRM_LEGAL)}
    </td></tr>
    <tr><td align="center" style="padding:6px 24px 32px 24px;font-family:{FONT};font-size:11px;line-height:17px;color:{BLACK};">
      No longer want to receive these emails?
      <a href="{{% manage_preferences_link %}}" style="color:{BLACK};text-decoration:underline;">Manage Preferences</a> |
      <a href="{{% unsubscribe_link %}}" style="color:{BLACK};text-decoration:underline;">Unsubscribe</a>
    </td></tr>
  </table>
</td></tr></table>
</body></html>"""


def render_picks(cards, hero, extras, week_label, style=None):
    style = style or HERO_GRADIENTS[0]
    d = DEPARTMENTS["store"]
    utm = "utm_source=klaviyo&utm_medium=email&utm_campaign=new-store-digest"
    def link(path):
        return f"{STORE}{path}" + ("&" if "?" in path else "?") + utm
    esc = html.escape
    n = len(cards) + (1 if hero else 0)
    names = ([hero["title"]] if hero else []) + [c["title"] for c in cards]
    preheader = "This week's picks: " + ", ".join(short_name(t, 30) for t in names[:4]) + " — free shipping over 199$."
    btn = (f"display:block;font-size:12px;font-weight:700;letter-spacing:1px;text-transform:uppercase;"
           f"color:{WHITE};text-decoration:none;")

    def price_html(c, size=14, dark=False):
        # dark=True is for the black hero panel: coral sale price and light strike-through
        if c["compare"]:
            return (f'<span class="{"txt-coral" if dark else "txt-red"}" style="color:{CORAL if dark else RED};font-weight:700;">{esc(c["price"])}</span> '
                    f'<span class="{"txt-light" if dark else "txt-grey"}" style="color:{LIGHT_TXT if dark else GREY_TXT};text-decoration:line-through;font-size:12px;">{esc(c["compare"])}</span> '
                    f'<span class="bg-red txt-white" style="display:inline-block;background:{RED};color:{WHITE};font-size:10px;font-weight:700;'
                    f'letter-spacing:1px;text-transform:uppercase;padding:3px 6px;margin-left:6px;">Save {esc(c["save"])}</span>')
        return esc(c["price"])

    hero_html = ""
    if hero:
        url = hero["url"] + "?" + utm
        blurb = excerpt_long = hero.get("excerpt_long") or hero.get("excerpt") or ""
        hero_html = f"""
  <tr><td bgcolor="{style['solid']}" background="{style['image']}" valign="top" style="background-color:{style['solid']};background-image:url({style['image']});background-repeat:no-repeat;background-size:cover;background-position:center top;padding:28px 24px 32px 24px">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%">
      <tr><td class="m-label txt-hero" style="font-size:11px;font-weight:bold;letter-spacing:2px;color:{BLACK};padding-bottom:12px">PICK OF THE WEEK</td></tr>
      <tr><td align="center" bgcolor="{WHITE}" class="bg-tile" style="background-color:{WHITE};{WHITE_LOCK}border:1px solid {BLACK};padding:18px 0">
        <a href="{url}" style="display:block"><img src="{product_img(hero['image'], width=800)}" width="400" alt="{esc(hero['title'])}" style="display:block;width:100%;max-width:400px;height:auto;border:0;margin:0 auto"></a>
      </td></tr>
      <tr><td class="m-label txt-hero" style="padding-top:18px;font-size:11px;letter-spacing:1px;text-transform:uppercase;color:{BLACK}">{esc(hero['vendor'])}</td></tr>
      <tr><td class="m-hero-title txt-hero" style="padding-top:4px;font-size:22px;line-height:27px;font-weight:bold;color:{BLACK}"><a href="{url}" style="color:{BLACK};text-decoration:none">{esc(hero['title'])}</a></td></tr>
      {f'<tr><td class="m-body txt-hero" style="padding-top:8px;font-size:14px;line-height:21px;color:{BLACK}">{esc(blurb)}</td></tr>' if blurb else ''}
      <tr><td class="m-price txt-hero" style="padding-top:10px;font-size:16px;color:{BLACK}">{price_html(hero, 15)}</td></tr>
      <tr><td style="padding-top:16px">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
          <td bgcolor="{BLACK}" class="btn-hero" style="background:{BLACK}"><a href="{url}" class="m-btn txt-white" style="{btn}padding:12px 28px;">Shop Now</a></td>
        </tr></table>
      </td></tr>
    </table>
  </td></tr>"""

    def row_html(c, last):
        url = c["url"] + "?" + utm
        border = "" if last else f";border-bottom:1px solid {HAIRLINE}"
        blurb = f'<div class="m-body txt-black" style="font-size:14px;line-height:21px;color:{BLACK};margin-top:8px">{esc(c["excerpt"])}</div>' if c.get("excerpt") else ""
        variants = (f'<div class="m-small txt-grey" style="font-size:12px;color:{GREY_TXT};margin-top:4px">{len(c["variants"])} options: {esc(", ".join(c["variants"]))}</div>'
                    if c["variants"] else "")
        return f"""
      <tr><td class="hl" style="padding:22px 0{border}">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%"><tr>
          <td class="stack stack-img" width="200" valign="top" style="width:200px;padding-right:20px">
            <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%"><tr>
              <td align="center" bgcolor="{WHITE}" class="bg-tile" style="background-color:{WHITE};{WHITE_LOCK}border:1px solid {HAIRLINE};padding:8px">
                <a href="{url}" style="display:block"><img src="{product_img(c['image'], width=400)}" width="182" alt="{esc(c['title'])}" style="display:block;width:100%;max-width:182px;height:auto;border:0;margin:0 auto"></a>
              </td>
            </tr></table>
          </td>
          <td class="stack" valign="top">
            <div class="m-label txt-grey" style="font-size:11px;letter-spacing:1px;text-transform:uppercase;color:{GREY_TXT}">{esc(c['vendor'])}</div>
            <div class="m-title txt-black" style="font-size:17px;line-height:22px;font-weight:700;color:{BLACK};margin-top:4px"><a href="{url}" style="color:{BLACK};text-decoration:none">{esc(c['title'])}</a></div>
            {variants}{blurb}
            <div class="m-price txt-black" style="font-size:15px;margin-top:10px;color:{BLACK}">{price_html(c)}</div>
            <div style="margin-top:14px"><a href="{url}" class="m-btn btn" style="display:inline-block;background:{BLACK};color:{WHITE};border:1px solid {WHITE};font-size:12px;font-weight:700;letter-spacing:1px;text-transform:uppercase;text-decoration:none;padding:10px 16px">View Product</a></div>
          </td>
        </tr></table>
      </td></tr>"""

    list_html = ""
    if cards:
        list_title = "Also New This Week" if hero else "New This Week"
        rows = "".join(row_html(c, i == len(cards) - 1) for i, c in enumerate(cards))
        list_html = f"""
  <tr><td style="padding:30px 24px 0 24px">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%"><tr>
      <td class="m-section txt-black" style="font-size:18px;font-weight:bold;color:{BLACK}">{list_title}</td>
      <td align="right" class="m-label txt-black" style="font-size:11px;font-weight:bold;letter-spacing:1px"><a href="{link('/collections/newreleases')}" style="color:{BLACK};text-decoration:underline">VIEW ALL</a></td>
    </tr></table>
  </td></tr>
  <tr><td style="padding:0 24px">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%">{rows}
    </table>
  </td></tr>"""

    def section_head(title, link_text, href, pad_top=32):
        return f"""
  <tr><td style="padding:{pad_top}px 24px 8px 24px">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%"><tr>
      <td class="m-section txt-black" style="font-size:18px;font-weight:bold;color:{BLACK}">{title}</td>
      <td align="right" class="m-label txt-black" style="font-size:11px;font-weight:bold;letter-spacing:1px"><a href="{href}" style="color:{BLACK};text-decoration:underline">{link_text}</a></td>
    </tr></table>
  </td></tr>"""

    blog_html = ""
    posts = extras.get("blog", [])[:2]
    if posts:
        def post_cell(a, last):
            img = (a.get("image") or {}).get("url")
            url = article_url(a) + "?" + utm
            pic = (f'<a href="{url}"><img src="{img}&width=536" width="268" alt="{esc(a["title"])}" class="m-full" style="display:block;width:100%;max-width:268px;height:auto;border:0"></a>'
                   if img else f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="268"><tr><td height="140" bgcolor="#f4f4f4" style="background:#f4f4f4"></td></tr></table>')
            pad = "" if last else "padding-right:16px;"
            return f"""
      <td class="stack stack-img" width="268" valign="top" style="width:268px;{pad}">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="268" style="width:100%">
          <tr><td>{pic}</td></tr>
          <tr><td class="m-title txt-black" style="padding:12px 0 4px 0;font-size:15px;line-height:20px;font-weight:bold;color:{BLACK}"><a href="{url}" style="color:{BLACK};text-decoration:none">{esc(a['title'])}</a></td></tr>
          <tr><td class="m-small txt-grey" style="font-size:13px;line-height:18px;color:{GREY_TXT}">{esc(article_teaser(a))}</td></tr>
        </table>
      </td>"""
        cells = "".join(post_cell(a, i == len(posts) - 1) for i, a in enumerate(posts))
        blog_html = section_head("From the Blog", "ALL POSTS", link(BLOG_URL)) + f"""
  <tr><td style="padding:16px 24px 12px 24px">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%"><tr>{cells}
    </tr></table>
  </td></tr>"""

    events_html = ""
    events = extras.get("events", [])[:3]
    if events:
        def event_row(a, first):
            url = article_url(a) + "?" + utm
            date_label, time_label = event_when(a)
            when = (f'{esc(date_label)}' + (f'<br><span class="txt-grey" style="font-weight:normal;color:{GREY_TXT}">{esc(time_label)}</span>' if time_label else "")) if date_label else ""
            when_cell = (f'<td width="90" valign="top" class="txt-coral" style="width:90px;font-size:12px;line-height:17px;font-weight:bold;color:{CORAL};letter-spacing:1px;padding-right:16px">{when}</td>'
                         if when else "")
            top = f"border-top:1px solid {HAIRLINE};" if first else ""
            return f"""
      <tr><td class="hl" style="padding:14px 0;{top}border-bottom:1px solid {HAIRLINE}">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%"><tr>
          {when_cell}
          <td valign="top">
            <div class="m-title txt-black" style="font-size:15px;line-height:20px;font-weight:bold;color:{BLACK}"><a href="{url}" style="color:{BLACK};text-decoration:none">{esc(a['title'])}</a></div>
            <div class="m-small txt-grey" style="font-size:13px;line-height:18px;color:{GREY_TXT};margin-top:4px">{esc(article_teaser(a))}</div>
          </td>
          <td align="right" valign="middle" width="80"><a href="{url}" class="txt-black" style="font-size:11px;font-weight:bold;letter-spacing:1px;color:{BLACK};text-decoration:underline">DETAILS</a></td>
        </tr></table>
      </td></tr>"""
        rows = "".join(event_row(a, i == 0) for i, a in enumerate(events))
        events_html = section_head("Upcoming Events", "ALL EVENTS", link(EVENTS_URL), pad_top=24) + f"""
  <tr><td style="padding:16px 24px 12px 24px">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%">{rows}
    </table>
  </td></tr>"""

    nav_cells = "".join(
        f'<td align="center" style="padding:11px 6px"><a href="{link(p)}" class="txt-white" style="color:{WHITE};font-size:12px;letter-spacing:1px;text-decoration:none">{t}</a></td>'
        for t, p in NAV)
    cat_rows = "".join(
        f'<tr><td align="center" class="m-body hl" style="padding:9px 0;border-bottom:1px solid {HAIRLINE}"><a href="{link(p)}" class="txt-cat" style="color:{CAT_TXT};font-size:14px;font-weight:700;letter-spacing:2px;text-decoration:none">{t}</a></td></tr>'
        for t, p in CATEGORY_LINKS)
    social = ('<table role="presentation" cellpadding="0" cellspacing="0" border="0" align="center"><tr>'
              + "".join(f'<td align="center" valign="middle" style="padding:0 7px;line-height:0;font-size:0"><a href="{u}" style="text-decoration:none;display:block;line-height:0">'
                        f'<img src="{img}" width="25" height="25" alt="{a}" style="display:block;border:0;width:25px;height:25px"></a></td>'
                        for u, img, a in SOCIAL)
              + '</tr></table>')
    intro = f"{n} new {'pick' if n == 1 else 'picks'} from across the store, chosen by the team. Here's what's worth a look this week."

    return f"""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="{color_scheme_meta()}">
<meta name="supported-color-schemes" content="{color_scheme_meta()}">
<title>{esc(d['title'])}</title>
<style>{MOBILE_CSS}{dark_css()}</style>
<!--[if mso]><noscript><xml><o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml></noscript><![endif]-->
</head>
<body class="bg-page" style="margin:0;padding:0;background:#ececec;-webkit-text-size-adjust:100%;">
<div class="bg-page" style="background:#ececec;padding:24px 0;font-family:Helvetica,Arial,sans-serif">
<span style="display:none;font-size:1px;color:#ececec;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden">{esc(preheader)}</span>
<table role="presentation" class="bg-body" cellpadding="0" cellspacing="0" border="0" width="100%" align="center" style="width:100%;max-width:600px;margin:0 auto;background:{WHITE}">
  <tr><td align="center" class="txt-grey" style="padding:10px 0 4px 0;font-size:10px;color:{GREY_TXT}">Can't see this email? {{% web_view 'View in Your Browser' %}}</td></tr>
  <tr><td align="center" class="m-logo txt-black" style="padding:18px 0 16px 0;font-size:28px;line-height:34px;letter-spacing:5px;font-weight:400;color:{BLACK}"><a href="{link('/')}" style="color:{BLACK};text-decoration:none">MOOG&nbsp;AUDIO</a></td></tr>
  <tr><td bgcolor="{BLACK}" class="bg-nav" style="background:{BLACK}">
    <table role="presentation" class="m-nav" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%"><tr>{nav_cells}</tr></table>
  </td></tr>
  <tr><td height="3" style="height:3px;line-height:3px;font-size:0;background:{CORAL};background-image:linear-gradient(90deg,#fdbb8f 0%,#f86726 35%,#eabf7c 65%,#ffe2d8 85%,#d5ddda 100%)">&nbsp;</td></tr>
  <tr><td align="center" class="m-small txt-black hl" style="padding:14px 20px;font-size:12px;color:{BLACK};border-bottom:1px solid {HAIRLINE}"><strong>FREE SHIPPING</strong> on most orders over 199$ | <strong>FLEXITI</strong> financing available at checkout</td></tr>
  <tr><td align="center" style="padding:36px 24px 26px 24px">
    <div class="m-label txt-grey" style="font-size:11px;letter-spacing:2px;text-transform:uppercase;color:{GREY_TXT}">{esc(d['eyebrow'])} &middot; {esc(week_label)}</div>
    <h1 class="m-h1 txt-black" style="margin:10px 0 0 0;font-size:28px;line-height:34px;font-weight:700;letter-spacing:-0.3px;color:{BLACK}">{esc(d['title'])}</h1>
    <p class="m-intro txt-black" style="margin:10px 0 0 0;font-size:15px;line-height:22px;color:{BLACK}">{esc(intro)}</p>
  </td></tr>{hero_html}{list_html}
  <tr><td align="center" style="padding:28px 24px 40px 24px">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" align="center"><tr>
      <td bgcolor="{BLACK}" class="btn" style="background:{BLACK};border:1px solid {WHITE}"><a href="{link('/collections/newreleases')}" class="m-btn" style="{btn}padding:14px 26px;">Shop All New Releases</a></td>
    </tr></table>
  </td></tr>
  <tr><td style="padding:0 24px">
    <table role="presentation" class="hl" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%;border-top:1px solid {HAIRLINE}">{cat_rows}
    </table>
  </td></tr>{blog_html}{events_html}
  <tr><td style="padding:12px 24px 8px 24px">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%"><tr>
      <td bgcolor="{BLACK}" class="bg-band" style="background:{BLACK};padding:24px">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%"><tr>
          <td class="stack stack-img m-body txt-white" style="font-size:14px;line-height:20px;color:{WHITE};padding-right:16px"><span style="font-weight:bold">Visit the Boutique.</span> Try the gear in person &mdash; 3828 St Laurent Blvd, Montreal.</td>
          <td align="right" width="140" class="stack" style="padding-top:0">
            <table role="presentation" cellpadding="0" cellspacing="0" border="0" align="right" class="stack"><tr>
              <td style="border:1px solid {WHITE}"><a href="https://maps.google.com/?q=3828+St+Laurent+Blvd+Montreal+QC+H2W+1X6" class="m-label txt-white" style="display:block;padding:10px 20px;font-size:11px;font-weight:bold;letter-spacing:1px;color:{WHITE};text-decoration:none;text-align:center">GET DIRECTIONS</a></td>
            </tr></table>
          </td>
        </tr></table>
      </td>
    </tr></table>
  </td></tr>
  <tr><td class="hl" style="padding:16px 24px 0 24px;border-bottom:1px solid {HAIRLINE}">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%"><tr>
      <td class="stack m-small txt-black" width="268" valign="top" style="font-size:13px;line-height:18px;color:{BLACK};padding-right:16px;padding-bottom:16px"><span style="font-weight:bold">Free shipping.</span> We offer Free Shipping on most orders over 199$. Conditions may apply.</td>
      <td class="stack m-small txt-black" width="268" valign="top" style="font-size:13px;line-height:18px;color:{BLACK};padding-bottom:16px"><span style="font-weight:bold">Rewards.</span> For each dollar spent, earn one reward point which you can use as a discount for your future purchases.</td>
    </tr></table>
  </td></tr>
  <tr><td align="center" bgcolor="{WHITE}" class="bg-tile" style="background-color:{WHITE};{WHITE_LOCK}padding:28px 0 6px 0"><img src="{IMG_PAYMENTS}" width="600" alt="Affirm, Flexiti and PayPlan by RBC financing" style="display:block;width:100%;max-width:600px;height:auto;border:0"></td></tr>
  <tr><td align="center" bgcolor="{WHITE}" class="bg-tile" style="background-color:{WHITE};{WHITE_LOCK}padding:6px 0 10px 0"><a href="{link('/pages/reward')}"><img src="{IMG_REWARDS}" width="600" alt="Patch Rewards: earn points every time you shop, connect and review" style="display:block;width:100%;max-width:600px;height:auto;border:0"></a></td></tr>
  <tr><td align="center" bgcolor="{WHITE}" class="bg-tile" style="background-color:{WHITE};{WHITE_LOCK}padding:10px 0 22px 0;line-height:0;font-size:0">{social}</td></tr>
  <tr><td align="center" class="m-small txt-black" style="padding:0 24px 12px 24px;font-size:13px;line-height:19px;color:{BLACK}">
    <a href="{link('/')}" style="color:{BLACK};font-weight:700;text-decoration:underline">moogaudio.com</a><br>
    <a href="https://maps.google.com/?q=3828+St+Laurent+Blvd+Montreal+QC+H2W+1X6" style="color:{BLACK};text-decoration:underline">{ADDRESS}</a>
  </td></tr>
  <tr><td class="m-legal txt-grey" style="padding:8px 24px 16px 24px;font-size:11px;line-height:16px;color:{GREY_TXT};text-align:justify">{esc(AFFIRM_LEGAL)}</td></tr>
  <tr><td align="center" class="m-small txt-black" style="padding:6px 24px 32px 24px;font-size:12px;line-height:18px;color:{BLACK}">No longer want to receive these emails? <a href="{{% manage_preferences_link %}}" style="color:{BLACK};text-decoration:underline">Manage Preferences</a> | <a href="{{% unsubscribe_link %}}" style="color:{BLACK};text-decoration:underline">Unsubscribe</a></td></tr>
</table>
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" align="center" style="width:100%;max-width:600px;margin:0 auto"><tr><td height="24" style="font-size:1px;line-height:1px">&nbsp;</td></tr></table>
</div>
</body>
</html>"""


def render_launch(card, product, extras, style=None):
    """Single-product 'Product Launch' e-mail (claude.ai/design 'Product Launch Email').
    Coral gradient backdrop; black header bar; eyebrow/headline/sub-line on the gradient; then a WHITE
    SHEET holding everything with body text — main image card, up to three gallery thumbnails (row
    omitted when the product has only one image), description, SPECIFICATIONS box from the
    description's bullet list, price + CTA + note — so Gmail's dark-mode inversion turns the sheet
    dark with white text instead of leaving white text on a light image. Then the boutique band and
    the standard white footer (blog, events, value props, payments, rewards, socials, legal)."""
    utm = "utm_source=klaviyo&utm_medium=email&utm_campaign=product-launch"
    def link(path):
        return f"{STORE}{path}" + ("&" if "?" in path else "?") + utm
    esc = html.escape
    url = card["url"] + "?" + utm
    h1, sub = split_title(card["title"], card["vendor"], card.get("type") or "")
    h1_size = 40 if len(h1) <= 22 else (32 if len(h1) <= 34 else 26)
    body_html = product.get("body_html", "")
    images = [i["src"] for i in product.get("images", []) if i.get("src")] or [card["image"]]
    main_img, thumbs = images[0], images[1:4]
    blurb = long_blurb(body_html, card["title"])
    rows = spec_rows(body_html)
    labeled = sum(1 for lbl, _ in rows if lbl)
    spec_title = "SPECIFICATIONS" if rows and labeled * 2 >= len(rows) else "KEY FEATURES"
    perks = "Financing available at checkout" + (" &middot; Free shipping" if card["_price_num"] >= 199 else "")
    price_line = esc(card["price"]) + (f' <span class="txt-grey" style="color:{GREY_TXT};text-decoration:line-through;font-size:14px;font-weight:normal">{esc(card["compare"])}</span>'
                                       if card.get("compare") else "")
    first_sentence = re.split(r"(?<=[.!?])\s", blurb, maxsplit=1)[0] if blurb else ""
    preheader = f"It's here: the {h1}. {first_sentence}".strip()
    bg = style or launch_style()
    bg_attr = f' background="{bg["image"]}"' if bg["image"] else ""
    bg_css = (f"background-image:url({bg['image']});background-size:cover;background-position:center top;background-repeat:no-repeat;"
              if bg["image"] else f"background-image:{bg['gradient']};")
    btn = f"display:block;font-size:13px;font-weight:bold;letter-spacing:2px;text-transform:uppercase;color:{WHITE};text-decoration:none;"

    thumbs_html = ""
    if thumbs:
        n = len(thumbs)
        tw = {1: 300, 2: 236, 3: 158}[n]
        th = round(tw * 0.65)
        cells = []
        for i, t in enumerate(thumbs):
            if i:
                cells.append('<td width="11" style="width:11px;font-size:1px;line-height:1px">&nbsp;</td>')
            # no inner padding: if a client inverts the tile background, there is no white ring to turn dark
            cells.append(f'<td class="thumb bg-tile" bgcolor="{WHITE}" align="center" valign="middle" style="background-color:{WHITE};{WHITE_LOCK}border:1px solid {BLACK};padding:0;line-height:0;font-size:0">'
                         f'<a href="{url}" style="display:block;line-height:0"><img src="{product_img(t, width=tw * 2, height=th * 2, crop="center")}" width="{tw}" alt="{esc(card["title"])} — view {i + 2}" '
                         f'style="display:block;width:100%;height:auto;border:0"></a></td>')
        thumbs_html = f"""
  <tr><td align="center" class="m-pad" style="padding:12px 32px 0 32px">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%"><tr>{"".join(cells)}</tr></table>
  </td></tr>"""

    spec_html = ""
    if rows:
        trs = []
        for i, (label, value) in enumerate(rows):
            border = "" if i == len(rows) - 1 else f"border-bottom:1px solid {HAIRLINE};"
            if label:
                trs.append(f'<tr><td width="170" valign="top" class="m-small txt-black hl" style="width:170px;padding:12px 0 12px 20px;font-size:12px;line-height:18px;font-weight:bold;color:{BLACK};{border}">{esc(label)}</td>'
                           f'<td valign="top" class="m-small txt-black hl" style="padding:12px 20px;font-size:12px;line-height:18px;color:{BLACK};{border}">{esc(value)}</td></tr>')
            else:
                trs.append(f'<tr><td colspan="2" valign="top" class="m-small txt-black hl" style="padding:12px 20px;font-size:12px;line-height:18px;color:{BLACK};{border}">{esc(value)}</td></tr>')
        spec_html = f"""
  <tr><td class="m-pad" style="padding:28px 32px 0 32px">
    <table role="presentation" class="bg-body" cellpadding="0" cellspacing="0" border="0" width="100%" bgcolor="{WHITE}" style="width:100%;background-color:{WHITE};border:1px solid {BLACK}">
      <tr><td colspan="2" bgcolor="{BLACK}" class="bg-nav txt-white" style="background:{BLACK};padding:12px 20px;font-size:11px;font-weight:bold;letter-spacing:2px;color:{WHITE}">{spec_title}</td></tr>
      {"".join(trs)}
    </table>
  </td></tr>"""

    blurb_html = (f"""
  <tr><td class="m-pad" style="padding:30px 32px 0 32px">
    <div class="m-body txt-hero" style="font-size:15px;line-height:23px;color:{BLACK}">{esc(blurb)}</div>
  </td></tr>""" if blurb else "")

    def section_head(title, link_text, href, pad_top=32):
        return f"""
  <tr><td style="padding:{pad_top}px 24px 8px 24px">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%"><tr>
      <td class="m-section txt-black" style="font-size:18px;font-weight:bold;color:{BLACK}">{title}</td>
      <td align="right" class="m-label txt-black" style="font-size:11px;font-weight:bold;letter-spacing:1px"><a href="{href}" style="color:{BLACK};text-decoration:underline">{link_text}</a></td>
    </tr></table>
  </td></tr>"""

    blog_html = ""
    posts = extras.get("blog", [])[:2]
    if posts:
        def post_cell(a, last):
            img = (a.get("image") or {}).get("url")
            purl = article_url(a) + "?" + utm
            pic = (f'<a href="{purl}"><img src="{img}&width=536" width="268" alt="{esc(a["title"])}" class="m-full" style="display:block;width:100%;max-width:268px;height:auto;border:0"></a>'
                   if img else f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="268"><tr><td height="140" bgcolor="#f4f4f4" style="background:#f4f4f4"></td></tr></table>')
            pad = "" if last else "padding-right:16px;"
            return f"""
      <td class="stack stack-img" width="268" valign="top" style="width:268px;{pad}">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="268" style="width:100%">
          <tr><td>{pic}</td></tr>
          <tr><td class="m-title txt-black" style="padding:12px 0 4px 0;font-size:15px;line-height:20px;font-weight:bold;color:{BLACK}"><a href="{purl}" style="color:{BLACK};text-decoration:none">{esc(a['title'])}</a></td></tr>
          <tr><td class="m-small txt-grey" style="font-size:13px;line-height:18px;color:{GREY_TXT}">{esc(article_teaser(a))}</td></tr>
        </table>
      </td>"""
        cells = "".join(post_cell(a, i == len(posts) - 1) for i, a in enumerate(posts))
        blog_html = section_head("From the Blog", "ALL POSTS", link(BLOG_URL)) + f"""
  <tr><td style="padding:16px 24px 12px 24px">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%"><tr>{cells}
    </tr></table>
  </td></tr>"""

    events_html = ""
    events = extras.get("events", [])[:3]
    if events:
        def event_row(a, first):
            eurl = article_url(a) + "?" + utm
            date_label, time_label = event_when(a)
            when = (f'{esc(date_label)}' + (f'<br><span class="txt-grey" style="font-weight:normal;color:{GREY_TXT}">{esc(time_label)}</span>' if time_label else "")) if date_label else ""
            when_cell = (f'<td width="90" valign="top" class="txt-coral" style="width:90px;font-size:12px;line-height:17px;font-weight:bold;color:{CORAL};letter-spacing:1px;padding-right:16px">{when}</td>'
                         if when else "")
            top = f"border-top:1px solid {HAIRLINE};" if first else ""
            return f"""
      <tr><td class="hl" style="padding:14px 0;{top}border-bottom:1px solid {HAIRLINE}">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%"><tr>
          {when_cell}
          <td valign="top">
            <div class="m-title txt-black" style="font-size:15px;line-height:20px;font-weight:bold;color:{BLACK}"><a href="{eurl}" style="color:{BLACK};text-decoration:none">{esc(a['title'])}</a></div>
            <div class="m-small txt-grey" style="font-size:13px;line-height:18px;color:{GREY_TXT};margin-top:4px">{esc(article_teaser(a))}</div>
          </td>
          <td align="right" valign="middle" width="80"><a href="{eurl}" class="txt-black" style="font-size:11px;font-weight:bold;letter-spacing:1px;color:{BLACK};text-decoration:underline">RSVP</a></td>
        </tr></table>
      </td></tr>"""
        erows = "".join(event_row(a, i == 0) for i, a in enumerate(events))
        events_html = section_head("Upcoming Events", "ALL EVENTS", link(EVENTS_URL), pad_top=24) + f"""
  <tr><td style="padding:16px 24px 12px 24px">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%">{erows}
    </table>
  </td></tr>"""

    social = ('<table role="presentation" cellpadding="0" cellspacing="0" border="0" align="center"><tr>'
              + "".join(f'<td align="center" valign="middle" style="padding:0 7px;line-height:0;font-size:0"><a href="{u}" style="text-decoration:none;display:block;line-height:0">'
                        f'<img src="{img}" width="25" height="25" alt="{alt}" style="display:block;border:0;width:25px;height:25px"></a></td>'
                        for u, img, alt in SOCIAL)
              + '</tr></table>')

    return f"""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="{color_scheme_meta()}">
<meta name="supported-color-schemes" content="{color_scheme_meta()}">
<title>{esc(h1)}</title>
<style>{MOBILE_CSS}{dark_css()}</style>
<!--[if mso]><noscript><xml><o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml></noscript><![endif]-->
</head>
<body class="bg-page" style="margin:0;padding:0;background:#ececec;-webkit-text-size-adjust:100%;">
<div class="bg-page" style="background:#ececec;padding:24px 0;font-family:Helvetica,Arial,sans-serif">
<span style="display:none;font-size:1px;color:#ececec;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden">{esc(preheader)}</span>
<table role="presentation" class="bg-launch" cellpadding="0" cellspacing="0" border="0" width="100%" align="center" bgcolor="{bg['solid']}"{bg_attr} style="width:100%;max-width:600px;margin:0 auto;background-color:{bg['solid']};{bg_css}">
  <tr><td align="center" class="txt-hero" style="padding:10px 0 4px 0;font-size:10px;color:{BLACK}">Can't see this email? {{% web_view 'View in Your Browser' %}}</td></tr>
  <tr><td bgcolor="{BLACK}" class="bg-nav m-pad" style="background:{BLACK};padding:16px 32px">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%"><tr>
      <td class="txt-white" style="font-size:18px;font-weight:bold;color:{WHITE};letter-spacing:2px"><a href="{link('/')}" style="color:{WHITE};text-decoration:none">MOOG&nbsp;AUDIO</a></td>
      <td align="right" class="m-label txt-sand" style="font-size:11px;font-weight:bold;letter-spacing:1px;color:{bg['accent']}">PRODUCT LAUNCH</td>
    </tr></table>
  </td></tr>
  <tr><td align="center" class="m-pad" style="padding:44px 32px 10px 32px">
    <div class="m-label txt-hero" style="font-size:11px;font-weight:bold;letter-spacing:3px;text-transform:uppercase;color:{BLACK}">{esc(DEPARTMENTS['hot']['eyebrow'])}</div>
    <h1 class="m-launch-h1 txt-hero" style="margin:12px 0 0 0;font-size:{h1_size}px;line-height:{h1_size + 4}px;font-weight:bold;letter-spacing:-0.5px;color:{BLACK}">{esc(h1)}</h1>
    {f'<div class="m-intro txt-hero" style="margin-top:10px;font-size:15px;line-height:22px;color:{BLACK}">{esc(sub)}</div>' if sub else ''}
  </td></tr>
  <tr><td align="center" class="m-pad" style="padding:26px 32px 0 32px">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%"><tr>
      <td bgcolor="{WHITE}" class="bg-tile" align="center" valign="middle" style="background-color:{WHITE};{WHITE_LOCK}border:1px solid {BLACK};padding:0;line-height:0;font-size:0">
        <a href="{url}" style="display:block;line-height:0"><img src="{product_img(main_img, width=1000)}" width="534" alt="{esc(card['title'])}" style="display:block;width:100%;height:auto;border:0"></a>
      </td>
    </tr></table>
  </td></tr>{thumbs_html}{blurb_html}{spec_html}
  <tr><td align="center" class="m-pad" style="padding:30px 32px 8px 32px">
    <div class="m-hero-title txt-hero" style="font-size:22px;font-weight:bold;color:{BLACK}">{price_line}</div>
    <div class="m-small txt-hero" style="margin-top:4px;font-size:12px;color:{BLACK}">{perks}</div>
  </td></tr>
  <tr><td align="center" style="padding:12px 32px 8px 32px">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" align="center"><tr>
      <td bgcolor="{BLACK}" class="btn-hero" style="background:{BLACK}"><a href="{url}" class="m-btn txt-white" style="{btn}padding:16px 40px;">Shop Now</a></td>
    </tr></table>
  </td></tr>
  <tr><td align="center" class="m-small txt-hero m-pad" style="padding:4px 32px 40px 32px;font-size:12px;color:{BLACK}">{esc(LAUNCH_NOTE)}</td></tr>
  <tr><td bgcolor="{BLACK}" class="bg-band m-pad" style="background:{BLACK};padding:26px 32px">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%"><tr>
      <td class="stack stack-img m-body txt-white" style="font-size:13px;line-height:19px;color:{WHITE};padding-right:16px">{esc(LAUNCH_BAND)}</td>
      <td align="right" width="140" class="stack" style="padding-top:0">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" align="right" class="stack"><tr>
          <td style="border:1px solid {WHITE}"><a href="https://maps.google.com/?q=3828+St+Laurent+Blvd+Montreal+QC+H2W+1X6" class="m-label txt-white" style="display:block;padding:10px 20px;font-size:11px;font-weight:bold;letter-spacing:1px;color:{WHITE};text-decoration:none;text-align:center">GET DIRECTIONS</a></td>
        </tr></table>
      </td>
    </tr></table>
  </td></tr>
  <tr><td bgcolor="{WHITE}" class="bg-body" style="background:{WHITE}">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%">{blog_html}{events_html}
  <tr><td class="hl" style="padding:16px 24px 0 24px;border-bottom:1px solid {HAIRLINE}">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%"><tr>
      <td class="stack m-small txt-black" width="268" valign="top" style="font-size:13px;line-height:18px;color:{BLACK};padding-right:16px;padding-bottom:16px"><span style="font-weight:bold">Free shipping.</span> We offer Free Shipping on most orders over 199$. Conditions may apply.</td>
      <td class="stack m-small txt-black" width="268" valign="top" style="font-size:13px;line-height:18px;color:{BLACK};padding-bottom:16px"><span style="font-weight:bold">Rewards.</span> For each dollar spent, earn one reward point which you can use as a discount for your future purchases.</td>
    </tr></table>
  </td></tr>
  <tr><td align="center" bgcolor="{WHITE}" class="bg-tile" style="background-color:{WHITE};{WHITE_LOCK}padding:28px 0 6px 0"><img src="{IMG_PAYMENTS}" width="600" alt="Affirm, Flexiti and PayPlan by RBC financing" style="display:block;width:100%;max-width:600px;height:auto;border:0"></td></tr>
  <tr><td align="center" bgcolor="{WHITE}" class="bg-tile" style="background-color:{WHITE};{WHITE_LOCK}padding:6px 0 10px 0"><a href="{link('/pages/reward')}"><img src="{IMG_REWARDS}" width="600" alt="Patch Rewards: earn points every time you shop, connect and review" style="display:block;width:100%;max-width:600px;height:auto;border:0"></a></td></tr>
  <tr><td align="center" bgcolor="{WHITE}" class="bg-tile" style="background-color:{WHITE};{WHITE_LOCK}padding:10px 0 22px 0;line-height:0;font-size:0">{social}</td></tr>
  <tr><td align="center" class="m-small txt-black" style="padding:0 24px 12px 24px;font-size:13px;line-height:19px;color:{BLACK}">
    <a href="{link('/')}" style="color:{BLACK};font-weight:700;text-decoration:underline">moogaudio.com</a><br>
    <a href="https://maps.google.com/?q=3828+St+Laurent+Blvd+Montreal+QC+H2W+1X6" style="color:{BLACK};text-decoration:underline">{ADDRESS}</a>
  </td></tr>
  <tr><td class="m-legal txt-grey" style="padding:8px 24px 16px 24px;font-size:11px;line-height:16px;color:{GREY_TXT};text-align:justify">{esc(AFFIRM_LEGAL)}</td></tr>
  <tr><td align="center" class="m-small txt-black" style="padding:6px 24px 32px 24px;font-size:12px;line-height:18px;color:{BLACK}">No longer want to receive these emails? <a href="{{% manage_preferences_link %}}" style="color:{BLACK};text-decoration:underline">Manage Preferences</a> | <a href="{{% unsubscribe_link %}}" style="color:{BLACK};text-decoration:underline">Unsubscribe</a></td></tr>
    </table>
  </td></tr>
</table>
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" align="center" style="width:100%;max-width:600px;margin:0 auto"><tr><td height="24" style="font-size:1px;line-height:1px">&nbsp;</td></tr></table>
</div>
</body>
</html>"""


def short_name(title, limit=34):
    head = re.split(r"\s+[-–]\s+", title)[0].strip()
    if len(head) <= limit:
        return head
    return head[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def subject_for(dept, cards):
    d = DEPARTMENTS[dept]
    by_price = sorted(cards, key=lambda c: c["_price_num"], reverse=True)
    names = [short_name(c["title"]) for c in by_price]
    lead = d.get("subject_lead") or f"New {d['short']}"
    if len(cards) == 1:
        return f"{lead}: {names[0]}"
    rest = len(cards) - 2
    return f"{lead}: {', '.join(names[:2])}" + (f" + {rest} more" if rest > 0 else "")


def publish_klaviyo(manifest, html_str, api_key):
    """Create template + DRAFT campaign + attach template (Klaviyo revision 2024-10-15 shapes).
    Returns dict with ids/url. Never sends. If the campaign step fails, the just-created
    template is deleted so no orphan is left behind."""
    headers = {"Authorization": f"Klaviyo-API-Key {api_key}", "revision": KLAVIYO_REVISION,
               "accept": "application/json", "content-type": "application/json"}

    def call(method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(KLAVIYO_API + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Klaviyo {method} {path} -> HTTP {e.code}: {e.read().decode(errors='replace')[:800]}")

    t = call("POST", "templates", {"data": {"type": "template", "attributes": {
        "name": f"{manifest['campaign_name']} (auto-digest)", "editor_type": "CODE", "html": html_str}}})
    template_id = t["data"]["id"]
    try:
        c = call("POST", "campaigns", {"data": {"type": "campaign", "attributes": {
            "name": f"{manifest['campaign_name']} (auto-digest DRAFT)",
            "audiences": {"included": AUDIENCES, "excluded": []},
            "send_strategy": {"method": "immediate"},
            "send_options": {"use_smart_sending": True},
            # tracking_options omitted on purpose: optional, and the account defaults apply
            "campaign-messages": {"data": [{"type": "campaign-message", "attributes": {
                "channel": "email", "label": manifest["label"],
                "content": {"subject": manifest["subject"], "preview_text": manifest["preview_text"],
                            "from_email": FROM_EMAIL, "from_label": FROM_LABEL}}}]}}}})
        campaign_id = c["data"]["id"]
        message_id = c["data"]["relationships"]["campaign-messages"]["data"][0]["id"]
        call("POST", "campaign-message-assign-template", {"data": {"type": "campaign-message", "id": message_id,
             "relationships": {"template": {"data": {"type": "template", "id": template_id}}}}})
    except Exception:
        try:
            call("DELETE", f"templates/{template_id}")
        except Exception:
            pass
        raise
    return {"template_id": template_id, "campaign_id": campaign_id, "message_id": message_id,
            "status": c["data"]["attributes"].get("status", "Draft"),
            "campaign_url": f"https://www.klaviyo.com/campaign/{campaign_id}/wizard"}


def replace_campaign_template(campaign_id, name, html_str, api_key):
    """Swap the template on an EXISTING Klaviyo campaign that is still a Draft: creates a fresh CODE
    template from html_str and assigns it to every e-mail message of the campaign. Subject, preview,
    audiences and status are untouched. Refuses anything that is not a Draft. Never sends."""
    headers = {"Authorization": f"Klaviyo-API-Key {api_key}", "revision": KLAVIYO_REVISION,
               "accept": "application/json", "content-type": "application/json"}

    def call(method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(KLAVIYO_API + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Klaviyo {method} {path} -> HTTP {e.code}: {e.read().decode(errors='replace')[:800]}")

    camp = call("GET", f"campaigns/{campaign_id}")
    status = camp["data"]["attributes"].get("status", "")
    if status.lower() != "draft":
        raise RuntimeError(f"campaign {campaign_id} is '{status}', not Draft — refusing to touch it")
    msgs = call("GET", f"campaigns/{campaign_id}/campaign-messages")
    message_ids = [m["id"] for m in msgs.get("data", []) if m.get("attributes", {}).get("channel", "email") == "email"]
    if not message_ids:
        raise RuntimeError(f"campaign {campaign_id} has no e-mail message")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M")
    t = call("POST", "templates", {"data": {"type": "template", "attributes": {
        "name": f"{name} (auto-digest, updated {stamp} UTC)", "editor_type": "CODE", "html": html_str}}})
    template_id = t["data"]["id"]
    try:
        for mid in message_ids:
            call("POST", "campaign-message-assign-template", {"data": {"type": "campaign-message", "id": mid,
                 "relationships": {"template": {"data": {"type": "template", "id": template_id}}}}})
    except Exception:
        try:
            call("DELETE", f"templates/{template_id}")
        except Exception:
            pass
        raise
    return {"template_id": template_id, "campaign_id": campaign_id, "message_ids": message_ids,
            "status": status, "campaign_url": f"https://www.klaviyo.com/campaign/{campaign_id}/wizard"}


def klaviyo_step(a, json_path, html_path):
    """--publish / --update-campaign for an already rendered e-mail. Returns a non-zero exit code on error."""
    if not (a.publish or a.update_campaign):
        return 0
    key = os.environ.get("KLAVIYO_API_KEY")
    if not key:
        print("ERROR: --publish/--update-campaign given but KLAVIYO_API_KEY is not set. Files were written; nothing published.")
        return 2
    manifest = json.loads(json_path.read_text())
    if a.publish:
        result = publish_klaviyo(manifest, html_path.read_text(), key)
        print(f"\nKlaviyo : {result['status']} campaign {result['campaign_id']} -> {result['campaign_url']}")
    else:
        result = replace_campaign_template(a.update_campaign, manifest["campaign_name"], html_path.read_text(), key)
        print(f"\nKlaviyo : new template {result['template_id']} assigned to Draft campaign {result['campaign_id']} -> {result['campaign_url']}")
    manifest["klaviyo"] = result
    json_path.write_text(json.dumps(manifest, indent=2))
    return 0


def run_hot(a, d, keep, sold_out, noise, now):
    """Product Launch e-mail: exactly one product per run (the most recently published one tagged
    newsletter-hot); any others stay tagged and go out on the following runs."""
    if not a.from_json:
        print("ERROR: 'hot' needs --from-json (Admin GraphQL response of products tagged newsletter-hot).")
        return 2
    if not keep:
        print(f"Product Launch: nothing purchasable tagged {TAG_HOT}. No file written.")
        for p in sold_out:
            print(f"  sold out: {p['title']}")
        for p in noise:
            print(f"  noise:    {p['title']}  [{p.get('product_type')}]")
        return 0
    # newest first; a not-yet-published (embargoed) product counts as the newest of all
    keep = sorted(keep, key=lambda p: p.get("published_at") or "9999", reverse=True)
    product, queued = keep[0], keep[1:]
    live = bool(product.get("published_at")) and (product.get("status") or "ACTIVE") == "ACTIVE"
    if not product.get("published_at"):
        product["published_at"] = now.isoformat()            # group() sorts on it; None would crash
    card = group([product])[0]
    extras = load_extras(a.extras)
    style = launch_style(a.launch_style, product.get("tags", []))
    style_tags = [t for t in product.get("tags", []) if t.lower().startswith(LAUNCH_TAG_PREFIX)]
    h1, sub = split_title(card["title"], card["vendor"], card.get("type") or "")
    blurb = long_blurb(product.get("body_html", ""), card["title"])
    first_sentence = re.split(r"(?<=[.!?])\s", blurb, maxsplit=1)[0] if blurb else ""
    subject = f"{d['subject_lead']}: {h1}" + (f" — {sub}" if sub and len(h1) + len(sub) <= 58 else "")
    preview = f"{h1} has landed at Moog Audio. {first_sentence}".strip()
    if len(preview) > 140:
        preview = preview[:137].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    stamp = now.strftime("%Y-%m-%d")
    slug = re.sub(r"[^a-z0-9]+", "-", h1.lower()).strip("-")[:40]
    html_path, json_path = OUT / f"hot-{stamp}-{slug}.html", OUT / f"hot-{stamp}-{slug}.json"
    html_path.write_text(render_launch(card, product, extras, style))
    day_label = now.astimezone(dt.timezone(dt.timedelta(hours=-4))).strftime("%b %-d")
    images = [i["src"] for i in product.get("images", []) if i.get("src")]
    json_path.write_text(json.dumps({
        "dept": "hot", "label": d["label"], "generated_at": now.isoformat(),
        "subject": subject, "preview_text": preview, "campaign_name": f"Product Launch · {h1} · {day_label}",
        "tags": [TAG_HOT], "launch_style": style["name"],
        "untag": [{"id": i, "tags": [TAG_HOT] + style_tags} for i in card.get("admin_ids", [])],
        "add_to_collection": {**NEW_RELEASES_COLLECTION, "product_ids": list(card.get("admin_ids", []))},
        "product": {"headline": h1, "subline": sub, "vendor": card["vendor"], "title": card["title"],
                    "live": live, "status": product.get("status"),
                    "price": card["price"], "compare": card["compare"], "url": card["url"],
                    "images": images, "thumbnails": len(images[1:4]), "specs": spec_rows(product.get("body_html", "")),
                    "blurb": blurb},
        "queued_for_next_run": [{"id": p.get("admin_id"), "title": p["title"]} for p in queued],
        "blog": [{"title": x["title"], "url": article_url(x)} for x in extras["blog"][:2]],
        "events": [{"title": x["title"], "url": article_url(x), "when": event_when(x)} for x in extras["events"][:3]],
    }, indent=2))
    rc = klaviyo_step(a, json_path, html_path)
    if rc:
        return rc
    print(f"Product Launch: {len(keep)} tagged {TAG_HOT}, featuring the most recent; {len(queued)} left for later runs")
    if not live:
        print(f"WARNING: product is NOT LIVE yet (status {product.get('status')}, not published to the Online Store). "
              f"The draft links to {card['url']} — publish the product before the campaign's send time.")
    print(f"\nSubject : {subject}\nPreview : {preview}\nHTML    : {html_path}\nManifest: {json_path}")
    print(f"  PRODUCT {card['vendor']} | {h1} | {sub} | {card['price']} | {len(images)} image(s) | {len(spec_rows(product.get('body_html', '')))} spec rows  [backdrop: {style['name']}]")
    for p in queued:
        print(f"  queued: {p['title']}")
    if extras["blog"]:
        print("  blog:   " + " / ".join(x["title"] for x in extras["blog"][:2]))
    if extras["events"]:
        print("  events: " + " / ".join(f"{x['title']} [{event_when(x)[0] or 'no date'}]" for x in extras["events"][:3]))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dept", choices=DEPARTMENTS)
    ap.add_argument("--days", type=int, default=7, help="publish window for 'new' (default 7)")
    ap.add_argument("--dry-run", action="store_true", help="do not read/write state/")
    ap.add_argument("--from-json", metavar="FILE", help="render from a saved Shopify Admin GraphQL response (tag mode)")
    ap.add_argument("--extras", metavar="FILE", help='store mode: {"blog": [...articles], "events": [...articles]}')
    ap.add_argument("--publish", action="store_true", help="create the Klaviyo DRAFT campaign (needs KLAVIYO_API_KEY env var)")
    ap.add_argument("--launch-style", metavar="NAME", choices=sorted(LAUNCH_STYLES),
                    help="hot mode: backdrop colour (default: the product's 'launch:<name>' tag, else coral)")
    ap.add_argument("--update-campaign", metavar="CAMPAIGN_ID",
                    help="instead of a new campaign, put the freshly rendered HTML on this existing DRAFT campaign (needs KLAVIYO_API_KEY)")
    ap.add_argument("--hero-style", metavar="NAME", help="force a hero background (default: rotate by date): "
                    + ", ".join(g["name"] for g in HERO_GRADIENTS))
    a = ap.parse_args()
    d = DEPARTMENTS[a.dept]
    now = dt.datetime.now(dt.timezone.utc)
    OUT.mkdir(exist_ok=True); STATE.mkdir(exist_ok=True)
    state_file = STATE / f"{a.dept}.json"
    state = json.loads(state_file.read_text()) if (state_file.exists() and not a.dry_run) else {"announced": {}, "members": []}

    if a.from_json:
        members = load_products(a.from_json, allow_unpublished=(a.dept == "hot"))   # every tagged product is a candidate
        fresh = list(members)
    else:
        members = fetch_collection(d["handle"])
        seen_before = set(state.get("members", []))
        fresh = []
        for p in members:
            if not p.get("published_at"):
                continue
            age = (now - dt.datetime.fromisoformat(p["published_at"].replace("Z", "+00:00"))).days
            newly_added = bool(seen_before) and p["id"] not in seen_before and age <= 30
            if (age <= a.days or newly_added) and str(p["id"]) not in state["announced"]:
                fresh.append(p)

    def sellable(p):   # launch mode: an embargoed (unpublished) product is kept even if its variants
        return is_purchasable(p) or (a.dept == "hot" and not p.get("published_at"))   # are not sellable yet
    sold_out = [p for p in fresh if not sellable(p)]
    noise = [p for p in fresh if sellable(p) and is_noise(p)]
    keep = [p for p in fresh if sellable(p) and not is_noise(p)]
    if a.dept == "hot":
        return run_hot(a, d, keep, sold_out, noise, now)
    hero = None
    if a.dept == "store":
        heroes = [p for p in keep if TAG_HERO in p.get("tags", [])]
        if len(heroes) > 1:
            heroes.sort(key=lambda p: float(p["variants"][0]["price"]), reverse=True)
            print(f"  note: {len(heroes)} products tagged {TAG_HERO}; using the highest-priced as hero, others go to the list")
        if heroes:
            hero_p = heroes[0]
            keep = [p for p in keep if p["id"] != hero_p["id"]]
            hero = group([hero_p])[0]
            hero["excerpt_long"] = excerpt(hero_p.get("body_html", ""), hero_p["title"], limit=200)
    cards = group(keep)
    if a.from_json:
        cards.sort(key=lambda c: c["_price_num"], reverse=True)   # hero items first

    print(f"{d['label']}: {len(members)} candidates, {len(fresh)} in scope, "
          f"{len(sold_out)} sold out, {len(noise)} dropped as noise, {len(cards)} cards after grouping")
    for p in sold_out:
        print(f"  sold out: {p['title']}")
    for p in noise:
        print(f"  noise:    {p['title']}  [{p.get('product_type')}]")
    if not cards and not hero:
        print("Nothing to announce. No file written.")
        return 0
    extras = load_extras(a.extras) if a.dept == "store" else {"blog": [], "events": []}
    hero_style = pick_hero_style(now.date(), a.hero_style)

    week_label = now.astimezone(dt.timezone(dt.timedelta(hours=-4))).strftime("Week of %b %-d")
    subject = subject_for(a.dept, ([hero] if hero else []) + cards) if a.dept != "store" or not hero else \
        f"{d['subject_lead']}: {short_name(hero['title'])}" + (f" + {len(cards)} more {'pick' if len(cards)==1 else 'picks'}" if cards else "")
    if a.dept == "store":
        total = len(cards) + (1 if hero else 0)
        preview = f"{total} hand-picked {'product' if total==1 else 'products'} new at Moog Audio this week. {PREVIEW_SUFFIX}"
    else:
        preview = f"{len(cards)} new {'arrival' if len(cards)==1 else 'arrivals'} in {d['label']} this week. {PREVIEW_SUFFIX}"
    stamp = now.strftime("%Y-%m-%d")
    html_path = OUT / f"{a.dept}-{stamp}.html"
    json_path = OUT / f"{a.dept}-{stamp}.json"
    html_path.write_text(render_picks(cards, hero, extras, week_label, hero_style) if a.dept == "store" else render(a.dept, cards, week_label))
    json_path.write_text(json.dumps({
        "dept": a.dept, "label": d["label"], "generated_at": now.isoformat(), "window_days": a.days,
        "subject": subject, "preview_text": preview, "label": d.get("title") or f"New in {d['label']}",
        "campaign_name": (f"{d['title']} · {week_label}" if a.dept == "store" else f"New Arrivals · {d['label']} · {week_label}"),
        "tags": [TAG, TAG_HERO] if a.dept == "store" else None,
        "untag": ([{"id": i, "tags": [TAG_HERO]} for i in hero.get("admin_ids", [])] if hero else [])
                 + [{"id": i, "tags": [TAG]} for c in cards for i in c.get("admin_ids", [])],
        "add_to_collection": {**NEW_RELEASES_COLLECTION,
                              "product_ids": ([i for i in hero.get("admin_ids", [])] if hero else [])
                                             + [i for c in cards for i in c.get("admin_ids", [])]} if a.dept == "store" else None,
        "hero_style": hero_style["name"], "hero": hero, "cards": cards,
        "blog": [{"title": x["title"], "url": article_url(x)} for x in extras["blog"][:2]],
        "events": [{"title": x["title"], "url": article_url(x), "when": event_when(x)} for x in extras["events"][:3]],
    }, indent=2))

    if not a.dry_run:
        for c in cards:
            for pid in c["ids"]:
                state["announced"][str(pid)] = stamp
        state["members"] = [p["id"] for p in members]
        state["last_run"] = now.isoformat()
        state_file.write_text(json.dumps(state, indent=2))

    rc = klaviyo_step(a, json_path, html_path)
    if rc:
        return rc

    print(f"\nSubject : {subject}\nPreview : {preview}\nHTML    : {html_path}\nManifest: {json_path}")
    if hero:
        print(f"  HERO {hero['vendor']} | {hero['title']} | {hero['price']}  [background: {hero_style['name']}]")
    for c in cards:
        print(f"  - {c['vendor']} | {c['title']} | {c['price']}" + (f" | {len(c['variants'])} options" if c['variants'] else ""))
    if extras["blog"]:
        print("  blog:   " + " / ".join(x["title"] for x in extras["blog"][:2]))
    if extras["events"]:
        print("  events: " + " / ".join(f"{x['title']} [{event_when(x)[0] or 'no date'}]" for x in extras["events"][:3]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

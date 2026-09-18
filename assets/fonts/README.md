# Fonts for the Deals banners

`digest.py sale` renders every banner's text itself (see `banner.py`) and needs a TrueType file here:

- `Helvetica.ttf` — **required**. The file the Moog Audio design system was built with (Igor's copy; licence risk
  accepted by the owner on 2026-09-17). Without it the run stops with an explicit error and writes nothing.
- `Helvetica Bold.ttf` (or `Helvetica-Bold.ttf`) — optional. When absent, bold is synthesised from the regular face,
  the same way a browser does for the design's single-file `@font-face`.

Local work without the file: `python3 digest.py sale ... --font-dir "/System/Library/Fonts/Supplemental"` (macOS Arial)
or `export MOOG_FONT_DIR=...`. That override is never used by the cloud routine, on purpose.

"""Product cut-out with rembg (model isnet-general-use), run by banner.py in its own venv (.cache/rembg-venv).

    python rembg_cut.py IN_IMAGE OUT_PNG [IN_IMAGE OUT_PNG ...]

Writes an RGBA PNG per input. Kept out of banner.py so the banner code itself stays standard-library only; banner.py
creates the venv on first use (pip install rembg[cpu]) and falls back to its own white key if this fails.
"""
import sys

from rembg import new_session, remove


def main(args):
    if not args or len(args) % 2:
        sys.exit("usage: rembg_cut.py IN OUT [IN OUT ...]")
    session = new_session("isnet-general-use")
    for src, dst in zip(args[::2], args[1::2]):
        with open(src, "rb") as f:
            data = remove(f.read(), session=session, post_process_mask=True)
        with open(dst, "wb") as f:
            f.write(data)


if __name__ == "__main__":
    main(sys.argv[1:])

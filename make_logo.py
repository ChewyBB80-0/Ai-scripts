"""
make_logo.py
Generates a circular profile picture / logo for a channel.

Design constraints that drive everything here: a pfp is displayed at ~40-60px
in a comments list and ~150px on a profile. So the mark must survive being
tiny -- that means ONE strong shape, heavy weight, high contrast, and no fine
detail or long words. Everything below is built for legibility first.

    python make_logo.py --name "THE CAR VETERAN" --short CV --style gauge
    python make_logo.py --name "OLD ENGINE" --short OE --style piston --preview
"""

import argparse
import math
from pathlib import Path

ROOT = Path(__file__).parent
OUT_DIR = ROOT / "branding"
SIZE = 1024          # square; platforms crop to a circle themselves

PALETTES = {
    # deep automotive tones: oil-dark grounds, hot metal accents
    "rust": ((18, 16, 15), (214, 92, 39), (247, 233, 216)),
    "steel": ((16, 19, 26), (108, 152, 195), (238, 243, 250)),
    "ember": ((20, 14, 13), (206, 62, 46), (250, 236, 226)),
    "brass": ((22, 19, 13), (198, 154, 63), (250, 243, 226)),
}


def _font(size: int, bold: bool = True):
    from hook_card import _font as f
    return f(size, bold)


def _ring(d, cx, cy, r, width, color):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=width)


def build(name: str, short: str, style: str = "gauge", palette: str = "rust",
          out: Path | None = None) -> Path:
    from PIL import Image, ImageDraw, ImageFilter

    bg, accent, ink = PALETTES.get(palette, PALETTES["rust"])
    img = Image.new("RGB", (SIZE, SIZE), bg)
    d = ImageDraw.Draw(img)
    c = SIZE // 2

    # soft radial warmth so the ground isn't flat
    glow = Image.new("RGB", (SIZE, SIZE), bg)
    ImageDraw.Draw(glow).ellipse([c - 380, c - 460, c + 380, c + 300],
                                 fill=tuple(min(255, v + 34) for v in accent))
    img = Image.blend(img, glow.filter(ImageFilter.GaussianBlur(190)), 0.55)
    d = ImageDraw.Draw(img)

    if style == "gauge":
        # a tachometer sweep -- reads instantly as "car" even at 40px
        r = 350
        d.arc([c - r, c - r, c + r, c + r], start=145, end=395,
              fill=accent, width=30)
        for i in range(11):                      # tick marks
            a = math.radians(145 + i * 25)
            x1, y1 = c + math.cos(a) * (r - 46), c + math.sin(a) * (r - 46)
            x2, y2 = c + math.cos(a) * (r - 92), c + math.sin(a) * (r - 92)
            hot = i >= 8                         # redline
            d.line([x1, y1, x2, y2], fill=accent if hot else ink,
                   width=16 if hot else 9)
        # needle swept into the redline
        a = math.radians(355)
        d.line([c, c, c + math.cos(a) * (r - 120), c + math.sin(a) * (r - 120)],
               fill=accent, width=22)
        d.ellipse([c - 26, c - 26, c + 26, c + 26], fill=ink)

    elif style == "piston":
        w, h = 210, 250
        d.rounded_rectangle([c - w, c - 330, c + w, c - 330 + h], radius=34,
                            fill=accent)                       # crown
        d.rectangle([c - 70, c - 330 + h, c + 70, c + 120], fill=ink)  # rod
        d.ellipse([c - 150, c + 60, c + 150, c + 360], outline=ink, width=42)

    else:  # "badge" -- pure typographic mark
        _ring(d, c, c, 350, 26, accent)

    # monogram
    f = _font(300 if len(short) <= 2 else 220)
    tw = d.textlength(short.upper(), font=f)
    ty = c - (150 if style == "gauge" else 120)
    if style == "gauge":
        d.text((c - tw / 2, ty), short.upper(), font=f, fill=ink)

    # name around the lower edge, small and wide-tracked
    nf = _font(74)
    label = name.upper()
    lw = d.textlength(label, font=nf)
    if lw > SIZE - 150:                     # too long -> drop to the short form
        label = short.upper()
        lw = d.textlength(label, font=nf)
    d.text((c - lw / 2, SIZE - 200), label, font=nf, fill=ink)

    _ring(d, c, c, SIZE // 2 - 12, 14, accent)   # outer rim

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = out or OUT_DIR / f"logo_{style}_{palette}.png"
    img.save(out)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--short", required=True, help="1-3 char monogram")
    ap.add_argument("--style", default="gauge", choices=["gauge", "piston", "badge"])
    ap.add_argument("--palette", default="rust", choices=list(PALETTES))
    ap.add_argument("--all", action="store_true", help="render every combination")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    if a.all:
        for st in ("gauge", "piston", "badge"):
            for pal in PALETTES:
                p = build(a.name, a.short, st, pal)
                print(f"  {p}")
    else:
        print(build(a.name, a.short, a.style, a.palette,
                    Path(a.out) if a.out else None))

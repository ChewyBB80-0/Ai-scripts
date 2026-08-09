"""
thumbnail.py
Generates a bold 1280x720 thumbnail for long-form compilations and sets it on
the uploaded video.

Why: YouTube otherwise picks a random frame -- for a compilation that means a
blurred piece of gameplay as the video's face. On long-form the thumbnail is
the single biggest click-through lever, and a consistent one is how a channel
becomes recognisable in a feed (the identity problem behind 800 views, 0 subs).

Design rules, kept deliberately simple so every thumbnail looks like the same
channel: one bold phrase in a heavy face, a hard drop shadow for legibility at
tiny sizes, a fixed accent colour per theme, and the channel logo bottom-right.
No faces, no clutter -- text has to survive being shown 200px wide on a phone.

    python thumbnail.py --text "LANDLORDS WHO PICKED THE WRONG TENANT"
    python thumbnail.py --video-id ABC123 --text "..." --set
"""

import argparse
from pathlib import Path

import config

ROOT = Path(__file__).parent
OUT_DIR = ROOT / "output" / "thumbnails"
W, H = 1280, 720

# One accent per theme so a returning viewer recognises the series at a glance.
THEME_COLORS = {
    "landlord": (240, 85, 61),      # red
    "hoa": (240, 180, 41),          # amber
    "wedding": (232, 93, 155),      # pink
    "work": (124, 140, 255),        # indigo
    "family": (94, 230, 185),       # mint
    "creepy": (150, 110, 255),      # violet
    None: (124, 140, 255),
}


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], []
    for w in words:
        cur.append(w)
        if draw.textlength(" ".join(cur), font=font) > max_w:
            cur.pop()
            if cur:
                lines.append(" ".join(cur))
            cur = [w]
    if cur:
        lines.append(" ".join(cur))
    return lines


_PHRASE_CACHE = ROOT / "output" / "thumb_phrases.json"


def hook_phrase(title: str, api_key: str | None = None) -> str:
    """A short, punchy thumbnail phrase written for the title.

    Mechanically truncating a long title breaks mid-thought ("...FINED ME $500
    FOR 'EXCESSIVE"), which reads as broken rather than as a teaser. Asking for
    a purpose-written phrase costs a fraction of a cent and is cached per title,
    so a re-run never pays twice. Falls back to the title on any failure.
    """
    import json as _json
    try:
        cache = _json.loads(_PHRASE_CACHE.read_text(encoding="utf-8"))
    except Exception:
        cache = {}
    if title in cache:
        return cache[title]

    try:
        import anthropic
        import os
        c = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        r = c.messages.create(
            model="claude-sonnet-5", max_tokens=60, thinking={"type": "disabled"},
            messages=[{"role": "user", "content":
                       f"""Write a YouTube thumbnail phrase for this story title:
"{title}"

Rules:
- 3 to 6 words. It is read at 200px wide on a phone, so short wins.
- Keep the single most intriguing concrete detail (a dollar amount, the object,
  the relationship). Specifics beat vague drama.
- Must read as a complete thought -- never end on a preposition or article.
- Do NOT reveal the outcome; the thumbnail teases, the video pays off.
- No quotes, no emoji, no trailing punctuation.
Return ONLY the phrase."""}])
        phrase = next(b.text for b in r.content if b.type == "text").strip()
        phrase = phrase.strip('"“”').rstrip(".!,")
        if not (2 <= len(phrase.split()) <= 9):
            raise ValueError(f"bad length: {phrase!r}")
        cache[title] = phrase
        _PHRASE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _PHRASE_CACHE.write_text(_json.dumps(cache, indent=1), encoding="utf-8")
        return phrase
    except Exception as e:
        print(f"  (hook_phrase fell back for {title[:34]!r}: {e})")
        return title


def _fit(draw, text: str, max_w: int, max_h: int, start: int = 150):
    """Largest size where the text fits BOTH the width and the available
    height. Checking width alone (the obvious version) lets a long phrase wrap
    to five lines and run off the bottom of the frame."""
    from hook_card import _font
    size = start
    while size > 44:
        f = _font(size)
        lines = _wrap(draw, text, f, max_w)
        longest_ok = all(draw.textlength(w, font=f) <= max_w for w in text.split())
        if longest_ok and len(lines) * int(size * 1.12) <= max_h and len(lines) <= 3:
            return f, lines
        size -= 6
    f = _font(44)
    return f, _wrap(draw, text, f, max_w)[:3]


def build(text: str, theme: str | None = None, out: Path | None = None,
          subtitle: str = "", background: str | Path | None = None) -> Path:
    """Compose a 16:9 thumbnail.

    background: optional image to sit behind the text. The flat wash below
    reads as a template at a glance, which is the look the compilations are
    trying to get away from. A photographic background fixes that, but only
    if the title stays readable over it -- hence the darkening scrim rather
    than dropping the art in raw.
    """
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
    from hook_card import _font

    accent = THEME_COLORS.get(theme, THEME_COLORS[None])
    img = None
    if background and Path(background).exists():
        try:
            bg = Image.open(background).convert("RGB")
            # cover-fit: fill the frame, crop the overflow, never letterbox
            scale = max(W / bg.width, H / bg.height)
            bg = bg.resize((round(bg.width * scale), round(bg.height * scale)),
                           Image.LANCZOS)
            img = bg.crop(((bg.width - W) // 2, (bg.height - H) // 2,
                           (bg.width - W) // 2 + W, (bg.height - H) // 2 + H))
            # Knock the art back so white text wins, but only just. Checked by
            # downsampling to 320px -- roughly a phone impression, which is
            # where almost all of them happen. A harder grade (0.55 + 0.28)
            # kept the text perfectly legible and flattened the image to a
            # black rectangle at that size, losing the thing worth looking at.
            img = ImageEnhance.Brightness(img).enhance(0.72)
            scrim = Image.new("RGB", (W, H), (0, 0, 0))
            img = Image.blend(img, scrim, 0.16)
        except Exception as e:
            print(f"(thumbnail background unusable, falling back: {e})")
            img = None

    if img is None:
        img = Image.new("RGB", (W, H), (11, 13, 20))
        # subtle vignette-ish wash so flat text doesn't look pasted on
        wash = Image.new("RGB", (W, H), (0, 0, 0))
        wd = ImageDraw.Draw(wash)
        wd.ellipse([-260, -420, W + 260, H], fill=(accent[0] // 5, accent[1] // 5,
                                                   accent[2] // 5))
        img = Image.blend(img, wash.filter(ImageFilter.GaussianBlur(90)), 0.85)
    d = ImageDraw.Draw(img)

    # accent bar -- a fixed, recognisable channel element
    d.rectangle([0, 0, 22, H], fill=accent)

    pad = 74
    text = text.upper()
    # leave room for the subtitle and the logo so nothing runs off the frame
    avail_h = H - pad * 2 - (90 if subtitle else 0)
    font, lines = _fit(d, text, W - pad * 2 - 190, avail_h)

    lh = int(font.size * 1.12)
    total = lh * len(lines)
    y = (H - total) // 2 - (18 if subtitle else 0)
    for ln in lines:
        # hard shadow first -- this is what keeps it legible at 200px wide
        d.text((pad + 6, y + 6), ln, font=font, fill=(0, 0, 0))
        d.text((pad, y), ln, font=font, fill=(255, 255, 255))
        y += lh

    if subtitle:
        sf = _font(46, bold=False)
        d.text((pad + 4, y + 16), subtitle.upper(), font=sf, fill=accent)

    logo = ROOT / config.HOOK_CARD_AVATAR
    if logo.exists():
        try:
            lg = Image.open(logo).convert("RGBA").resize((132, 132))
            mask = Image.new("L", (132, 132), 0)
            ImageDraw.Draw(mask).ellipse([0, 0, 132, 132], fill=255)
            img.paste(lg, (W - 132 - 44, H - 132 - 40), mask)
        except Exception:
            pass

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = out or OUT_DIR / "thumb.jpg"
    img.save(out, quality=92)
    return out


def set_on_video(video_id: str, path: Path):
    """Attach the thumbnail to an uploaded video (needs force-ssl scope)."""
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    from set_privacy import get_service
    from googleapiclient.http import MediaFileUpload
    get_service().thumbnails().set(
        videoId=video_id,
        media_body=MediaFileUpload(str(path), mimetype="image/jpeg")).execute()
    print(f"Thumbnail set on https://youtube.com/watch?v={video_id}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", required=True)
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--theme", default=None)
    ap.add_argument("--video-id", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--set", action="store_true", help="upload it to the video")
    a = ap.parse_args()
    p = build(a.text, a.theme, Path(a.out) if a.out else None, a.subtitle)
    print(f"Thumbnail -> {p}")
    if a.set:
        if not a.video_id:
            raise SystemExit("--set needs --video-id")
        set_on_video(a.video_id, p)

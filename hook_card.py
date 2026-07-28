"""
hook_card.py
Renders the "social post" hook card overlay (ZoroTales-style): white rounded
card with channel avatar, handle + verified badge, the story hook in bold
with 1-2 keywords color-highlighted, and an engagement row (99+ likes etc.).

Output is a transparent PNG sized for a 1080-wide vertical video; assemble.py
overlays it near the top of the frame.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

CARD_WIDTH = 940
PAD = 44
AVATAR_SIZE = 92
HANDLE_COLOR = (17, 17, 17)
TEXT_COLOR = (17, 17, 17)
HIGHLIGHT_COLORS = [(224, 49, 49), (47, 158, 68)]  # red, green like the reference
GRAY = (100, 100, 100)
AVATAR_BG = (47, 158, 68)
VERIFIED_BLUE = (29, 155, 240)

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "for", "with", "from", "that",
    "this", "your", "my", "his", "her", "their", "our", "was", "were",
    "did", "have", "has", "had", "you", "not", "are", "is", "it", "its",
    "when", "what", "who", "how", "why", "which", "of", "in", "on", "to",
}


_FONT_DIR = Path(__file__).parent / "fonts"


def _font(size: int, bold: bool = True):
    """Load a display font, preferring the BUNDLED one.

    Bundled-first matters for portability: on Linux the Windows font names
    below don't exist, and PIL's silent fallback is a tiny bitmap face that
    wrecks the card layout without raising an error -- so the failure looks
    like a rendering bug rather than a missing font.
    """
    candidates = [
        _FONT_DIR / "Rubik-Black.ttf",                    # travels with the repo
        # Linux/DejaVu (present on essentially every Ubuntu install)
        Path("/usr/share/fonts/truetype/dejavu") /
        ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),
    ]
    for p in candidates:
        try:
            return ImageFont.truetype(str(p), size)
        except OSError:
            continue
    # Windows system fonts, by name (resolved via the system font path)
    for name in (["arialbd.ttf", "segoeuib.ttf"] if bold else ["arial.ttf", "segoeui.ttf"]):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    print("WARNING: no TrueType font found -- cards will render with PIL's "
          "bitmap default and look wrong. Check the fonts/ directory.")
    return ImageFont.load_default()


def format_hook_for_display(hook: str) -> str:
    """
    Written surfaces (card, video title) show 'r/AITAH' so the story reads as
    a real subreddit post; narration keeps plain 'AITAH' so TTS says it
    naturally instead of 'r slash...'.
    """
    if "r/AITAH" in hook:
        return hook
    return hook.replace("AITAH", "r/AITAH", 1)


def _pick_highlights(words: list[str]) -> dict[int, tuple]:
    """Pick up to 2 emphatic words (longest non-stopwords) to color."""
    candidates = [
        (len(w.strip(".,?!'\"")), i) for i, w in enumerate(words)
        if len(w.strip(".,?!'\"")) >= 5 and w.strip(".,?!'\"").lower() not in STOPWORDS
    ]
    chosen = sorted(candidates, reverse=True)[:2]
    idxs = sorted(i for _, i in chosen)
    return {i: HIGHLIGHT_COLORS[n] for n, i in enumerate(idxs)}


# which subreddit each genre "comes from" (shown on the card for authenticity)
GENRE_SUBREDDIT = {"aitah": "r/AITAH", "revenge": "r/pettyrevenge",
                   "confession": "r/TrueOffMyChest", "creepy": "r/nosleep"}


def build_hook_card(hook_text: str, out_path: str | Path,
                    handle: str = "@ParkourFlux",
                    avatar_path: str | Path | None = None,
                    part_label: str | None = None,
                    subreddit: str | None = None) -> Path:
    hook_font = _font(56)
    handle_font = _font(42)
    eng_font = _font(36, bold=False)

    words = hook_text.split()
    highlights = _pick_highlights(words)

    # --- wrap words to lines ---
    tmp = Image.new("RGBA", (10, 10))
    meas = ImageDraw.Draw(tmp)
    space_w = meas.textlength(" ", font=hook_font)
    max_w = CARD_WIDTH - 2 * PAD
    lines, cur, cur_w = [], [], 0.0
    for i, w in enumerate(words):
        ww = meas.textlength(w, font=hook_font)
        if cur and cur_w + space_w + ww > max_w:
            lines.append(cur)
            cur, cur_w = [(i, w)], ww
        else:
            cur.append((i, w))
            cur_w += (space_w if cur[:-1] else 0) + ww
    if cur:
        lines.append(cur)

    line_h = 70
    sub_h = 46 if subreddit else 0          # "posted in r/X" line above the hook
    hook_top = PAD + AVATAR_SIZE + 28 + sub_h
    hook_h = len(lines) * line_h
    eng_top = hook_top + hook_h + 26
    card_h = eng_top + 52 + PAD

    # --- canvas with drop shadow ---
    margin = 30
    img = Image.new("RGBA", (CARD_WIDTH + 2 * margin, card_h + 2 * margin), (0, 0, 0, 0))
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [margin + 6, margin + 10, margin + CARD_WIDTH + 6, margin + card_h + 10],
        radius=44, fill=(0, 0, 0, 110))
    shadow = shadow.filter(ImageFilter.GaussianBlur(12))
    img.alpha_composite(shadow)

    d = ImageDraw.Draw(img)
    ox, oy = margin, margin  # card origin
    d.rounded_rectangle([ox, oy, ox + CARD_WIDTH, oy + card_h], radius=44,
                        fill=(255, 255, 255, 255))

    # --- avatar: channel logo (circle-cropped) or colored circle + initial ---
    ax, ay = ox + PAD, oy + PAD
    if avatar_path and Path(avatar_path).exists():
        logo = Image.open(avatar_path).convert("RGBA").resize(
            (AVATAR_SIZE * 2, AVATAR_SIZE * 2), Image.LANCZOS)
        mask = Image.new("L", logo.size, 0)
        ImageDraw.Draw(mask).ellipse([0, 0, logo.size[0], logo.size[1]], fill=255)
        logo.putalpha(mask)
        logo = logo.resize((AVATAR_SIZE, AVATAR_SIZE), Image.LANCZOS)
        img.alpha_composite(logo, (ax, ay))
    else:
        d.ellipse([ax, ay, ax + AVATAR_SIZE, ay + AVATAR_SIZE], fill=AVATAR_BG)
        initial = handle.lstrip("@")[:1].upper()
        ifont = _font(52)
        iw = d.textlength(initial, font=ifont)
        d.text((ax + AVATAR_SIZE / 2 - iw / 2, ay + AVATAR_SIZE / 2 - 30), initial,
               font=ifont, fill=(255, 255, 255))

    # --- handle + verified badge ---
    hx = ax + AVATAR_SIZE + 26
    hy = ay + AVATAR_SIZE / 2 - 26
    d.text((hx, hy), handle, font=handle_font, fill=HANDLE_COLOR)
    bx = hx + d.textlength(handle, font=handle_font) + 16
    bcy, br = hy + 26, 19
    d.ellipse([bx, bcy - br, bx + 2 * br, bcy + br], fill=VERIFIED_BLUE)
    d.line([(bx + 10, bcy + 1), (bx + 17, bcy + 8), (bx + 29, bcy - 8)],
           fill=(255, 255, 255), width=5)

    # --- part badge (multi-part series), top-right on the avatar row ---
    if part_label:
        pfont = _font(34)
        pw = d.textlength(part_label, font=pfont)
        px2 = ox + CARD_WIDTH - PAD
        px1 = px2 - pw - 36
        pcy = ay + AVATAR_SIZE / 2
        d.rounded_rectangle([px1, pcy - 28, px2, pcy + 28], radius=28,
                            fill=(124, 140, 255))
        d.text((px1 + 18, pcy - 22), part_label, font=pfont, fill=(255, 255, 255))

    # --- "posted in r/X" subreddit line (authenticity) ---
    if subreddit:
        sfont = _font(36)
        d.text((ox + PAD, oy + PAD + AVATAR_SIZE + 18),
               f"posted in {subreddit}", font=sfont, fill=(100, 100, 100))

    # --- hook text with highlighted words ---
    ty = oy + hook_top
    for line in lines:
        tx = ox + PAD
        for i, w in line:
            d.text((tx, ty), w, font=hook_font, fill=highlights.get(i, TEXT_COLOR))
            tx += meas.textlength(w, font=hook_font) + space_w
        ty += line_h

    # --- engagement row: heart 99+, bubble 99+, share ---
    ey = oy + eng_top
    ex = ox + PAD
    # heart
    d.ellipse([ex, ey + 8, ex + 20, ey + 28], outline=GRAY, width=4)
    d.ellipse([ex + 16, ey + 8, ex + 36, ey + 28], outline=GRAY, width=4)
    d.polygon([(ex + 3, ey + 24), (ex + 18, ey + 42), (ex + 33, ey + 24)], fill=(255, 255, 255))
    d.line([(ex + 4, ey + 23), (ex + 18, ey + 40), (ex + 32, ey + 23)], fill=GRAY, width=4)
    d.text((ex + 48, ey), "99+", font=eng_font, fill=GRAY)
    # comment bubble
    cx = ex + 170
    d.rounded_rectangle([cx, ey + 2, cx + 40, ey + 34], radius=12, outline=GRAY, width=4)
    d.polygon([(cx + 8, ey + 32), (cx + 8, ey + 44), (cx + 20, ey + 32)], fill=GRAY)
    d.text((cx + 54, ey), "99+", font=eng_font, fill=GRAY)
    # share (right-aligned)
    share_w = d.textlength("Share", font=eng_font)
    sx = ox + CARD_WIDTH - PAD - share_w
    d.text((sx, ey), "Share", font=eng_font, fill=GRAY)
    d.line([(sx - 34, ey + 14), (sx - 34, ey + 36)], fill=GRAY, width=4)
    d.polygon([(sx - 42, ey + 16), (sx - 26, ey + 16), (sx - 34, ey + 2)], fill=GRAY)

    out_path = Path(out_path)
    img.save(out_path)
    return out_path


if __name__ == "__main__":
    p = build_hook_card(
        "Which officer's incompetence did your NCO corps quietly fix for months?",
        "output/_card_test.png",
    )
    print(f"Card rendered -> {p}")


def build_end_card(out_path: str | Path,
                   handle: str = "@ParkourFlux",
                   avatar_path: str | Path | None = None,
                   line: str = "Follow for a new Reddit story every day",
                   sub_line: str = "New stories daily") -> Path:
    """The closing call-to-action card, overlaid over the last few seconds.

    The spoken CTA alone converts poorly -- it lands while the footage keeps
    scrolling and is easy to miss. A held visual card with the handle is what
    actually turns a viewer into a follower, which is the channel's real gap.
    Centered (not top-anchored like the hook card) so it reads as an ending.
    """
    W = CARD_WIDTH
    pad = PAD
    big = _font(60)
    small = _font(38, bold=False)
    handle_font = _font(48)

    tmp = Image.new("RGBA", (10, 10))
    meas = ImageDraw.Draw(tmp)

    # wrap the CTA line
    words, lines, cur, cur_w = line.split(), [], [], 0.0
    space_w = meas.textlength(" ", font=big)
    for w in words:
        ww = meas.textlength(w, font=big)
        if cur and cur_w + space_w + ww > W - 2 * pad:
            lines.append(cur); cur, cur_w = [w], ww
        else:
            cur_w += (space_w + ww) if cur else ww
            cur.append(w)
    if cur:
        lines.append(cur)

    line_h = 78
    body_h = len(lines) * line_h
    card_h = pad + AVATAR_SIZE + 28 + body_h + 20 + 46 + pad

    img = Image.new("RGBA", (W + 40, card_h + 40), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ox, oy = 20, 20
    # soft shadow, then the card
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [ox + 6, oy + 10, ox + W + 6, oy + card_h + 10], radius=44, fill=(0, 0, 0, 120))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(12)))
    d.rounded_rectangle([ox, oy, ox + W, oy + card_h], radius=44, fill=(255, 255, 255, 250))

    # avatar centered at the top
    ax = ox + (W - AVATAR_SIZE) // 2
    ay = oy + pad
    if avatar_path and Path(avatar_path).exists():
        logo = Image.open(avatar_path).convert("RGBA").resize((AVATAR_SIZE, AVATAR_SIZE))
        mask = Image.new("L", (AVATAR_SIZE, AVATAR_SIZE), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, AVATAR_SIZE, AVATAR_SIZE], fill=255)
        img.paste(logo, (ax, ay), mask)
    else:
        d.ellipse([ax, ay, ax + AVATAR_SIZE, ay + AVATAR_SIZE], fill=AVATAR_BG)
        d.text((ax + 30, ay + 18), handle[1:2].upper(), font=big, fill=(255, 255, 255))

    y = ay + AVATAR_SIZE + 28
    for ln in lines:
        txt = " ".join(ln)
        tw = d.textlength(txt, font=big)
        d.text((ox + (W - tw) / 2, y), txt, font=big, fill=TEXT_COLOR)
        y += line_h

    y += 8
    hw = d.textlength(handle, font=handle_font)
    d.text((ox + (W - hw) / 2, y), handle, font=handle_font, fill=HIGHLIGHT_COLORS[0])

    out_path = Path(out_path)
    img.save(out_path)
    return out_path

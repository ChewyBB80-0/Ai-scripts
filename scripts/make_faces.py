"""
make_faces.py
Cut the two 2x2 expression grids into the 8 transparent character PNGs the
dialogue renderer overlays, and give each one a drop shadow.

Always regenerates from the grids, so it is safe to re-run -- the shadow is
never applied twice to an already-shadowed file.

    python scripts/make_faces.py
"""

from collections import deque
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "branding" / "carveteran"
OUT = SRC / "faces"

GRIDS = {
    "rusty": ("rusty_grid.png", ["deadpan", "smug", "eyeroll", "explaining"]),
    "sparky": ("sparky_grid.png", ["happy", "question", "shocked", "delighted"]),
}

TOL = 42              # colour distance treated as "same as the background"
SHADOW_BLUR = 14
SHADOW_ALPHA = 150    # 0-255
SHADOW_OFFSET = (10, 12)


def strip_bg(im: Image.Image) -> Image.Image:
    """Flood-fill transparency inward from the edges. Only clears background
    CONNECTED to the border, so flat colours enclosed inside the car survive."""
    im = im.convert("RGBA")
    w, h = im.size
    px = im.load()
    ref = [px[s][:3] for s in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]]
    seen = [[False] * h for _ in range(w)]
    q = deque()
    for x in range(w):
        q.extend(((x, 0), (x, h - 1)))
    for y in range(h):
        q.extend(((0, y), (w - 1, y)))
    while q:
        x, y = q.popleft()
        if x < 0 or y < 0 or x >= w or y >= h or seen[x][y]:
            continue
        r, g, b, _ = px[x, y]
        if not any(abs(r - c[0]) + abs(g - c[1]) + abs(b - c[2]) < TOL for c in ref):
            continue
        seen[x][y] = True
        px[x, y] = (r, g, b, 0)
        q.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
    return im


def add_shadow(im: Image.Image) -> Image.Image:
    """Soft dark shadow behind the character.

    Without it a character disappears into a background of the same colour --
    orange Rusty over an orange car was the case that prompted this. The shadow
    separates them from ANY background, which an outline colour cannot do.

    The canvas grows by the blur plus the offset so the shadow is never clipped;
    the render scales on width, so a slightly wider PNG just means the character
    sits fractionally smaller, not shifted.
    """
    pad = SHADOW_BLUR * 2
    w, h = im.size
    canvas = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))

    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    alpha = im.getchannel("A").point(lambda a: SHADOW_ALPHA if a > 8 else 0)
    solid = Image.new("RGBA", im.size, (0, 0, 0, 255))
    solid.putalpha(alpha)
    shadow.paste(solid, (pad + SHADOW_OFFSET[0], pad + SHADOW_OFFSET[1]))
    shadow = shadow.filter(ImageFilter.GaussianBlur(SHADOW_BLUR))

    canvas = Image.alpha_composite(canvas, shadow)
    canvas.paste(im, (pad, pad), im)
    return canvas


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for who, (grid_name, names) in GRIDS.items():
        grid_path = SRC / grid_name
        if not grid_path.exists():
            print(f"  missing {grid_path} -- skipping {who}")
            continue
        grid = Image.open(grid_path).convert("RGBA")
        W, H = grid.size
        inset = int(W * 0.012)          # skip the white gutter between cells
        for i, name in enumerate(names):
            cx, cy = i % 2, i // 2
            cell = grid.crop((cx * W // 2 + inset, cy * H // 2 + inset,
                              (cx + 1) * W // 2 - inset, (cy + 1) * H // 2 - inset))
            cut = strip_bg(cell)
            if bbox := cut.getbbox():   # trim dead margin before the shadow
                cut = cut.crop(bbox)
            cut.thumbnail((700, 700), Image.LANCZOS)
            cut = add_shadow(cut)
            p = OUT / f"{who}_{name}.png"
            cut.save(p)
            print(f"  {p.name:26} {cut.size}")


if __name__ == "__main__":
    main()

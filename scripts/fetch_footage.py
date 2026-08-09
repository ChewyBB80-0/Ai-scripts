"""
fetch_footage.py
Pull background clips from Pexels, which licenses everything for commercial use
with no attribution required.

Why this exists: the car channel's original clips were a 640x360 rip of someone
else's GTA stream, and the race map had a Twitch billboard built into it -- in
frame in nearly every shot, so no crop removed it. Scraped gameplay is a rights
problem AND a quality problem, and both go away if the footage is licensed and
downloaded at source resolution.

Needs a free key from https://www.pexels.com/api/ in PEXELS_API_KEY.

    python scripts/fetch_footage.py --preset road
    python scripts/fetch_footage.py --query "aerial forest" --out footage/forest
"""

import argparse
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import env_file  # noqa: E402

API = "https://api.pexels.com/videos/search"
# Pexels sits behind Cloudflare, which rejects the default urllib agent with
# 403 "error code: 1010" -- a client-signature block, not an auth failure, so
# it looks exactly like a bad key until you read the body.
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36")

# Sets of searches per channel. Several narrow queries beat one broad one --
# "driving" alone returns a lot of parked cars and steering-wheel close-ups.
PRESETS = {
    "road": {
        "out": "footage/road",
        "queries": ["driving highway", "car driving road", "dashcam driving",
                    "highway aerial", "night driving city", "country road driving",
                    "car pov driving", "traffic timelapse"],
    },
}

# The pipeline centre-crops to 1080x1920, so anything under 1080 tall gets
# upscaled and looks soft. Full HD landscape is what the Minecraft footage is.
MIN_W, MIN_H = 1920, 1080
# Background clips are held 8-13s on the dialogue channel, so anything shorter
# than that has to loop within a single hold, which is visible.
MIN_SECONDS = 12


def _get(url: str, key: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": key,
                                               "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def _best_file(video: dict) -> dict | None:
    """SMALLEST mp4 that still clears the minimum.

    Not the largest: the render is 1080 wide, so a 4K rendition is several
    times the download and the disk for pixels that get scaled away. Anything
    at or above Full HD already has more detail than the output can show.
    """
    ok = [f for f in video.get("video_files", [])
          if f.get("file_type") == "video/mp4"
          and (f.get("width") or 0) >= MIN_W and (f.get("height") or 0) >= MIN_H]
    return min(ok, key=lambda f: f["width"] * f["height"]) if ok else None


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def fetch(queries: list[str], out_dir: Path, want: int, key: str) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    # Pexels ids are in the filenames, so a re-run tops up instead of
    # re-downloading, and the same clip never arrives twice under two queries.
    have = {m.group(1) for p in out_dir.glob("*.mp4")
            if (m := re.search(r"_(\d+)\.mp4$", p.name))}
    got = []

    # Cap what any ONE query contributes. Without this the first query fills the
    # whole quota and the other seven never run -- which is the opposite of why
    # there are several narrow queries. Fourteen clips of "driving highway" all
    # look like each other.
    per_q = max(2, -(-want // max(1, len(queries))))

    for q in queries:
        if len(got) >= want:
            break
        from_q = 0
        url = f"{API}?" + urllib.parse.urlencode(
            {"query": q, "orientation": "landscape", "size": "medium",
             "per_page": 40})
        try:
            data = _get(url, key)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                sys.exit("  PEXELS_API_KEY rejected -- check the key at "
                         "https://www.pexels.com/api/")
            print(f"  {q}: HTTP {e.code}, skipping")
            continue

        for v in data.get("videos", []):
            if len(got) >= want or from_q >= per_q:
                break
            vid = str(v["id"])
            if vid in have or v.get("duration", 0) < MIN_SECONDS:
                continue
            f = _best_file(v)
            if not f:
                continue
            name = f"{_slug(q)}_{vid}.mp4"
            dest = out_dir / name
            try:
                dreq = urllib.request.Request(f["link"], headers={"User-Agent": UA})
                with urllib.request.urlopen(dreq, timeout=180) as src:
                    with open(dest, "wb") as fh:
                        shutil.copyfileobj(src, fh)
            except Exception as e:
                print(f"  {name}: download failed ({e})")
                dest.unlink(missing_ok=True)
                continue
            have.add(vid)
            from_q += 1
            got.append({"file": name, "id": vid, "query": q,
                        "size": f"{f['width']}x{f['height']}",
                        "seconds": v.get("duration"),
                        "author": v.get("user", {}).get("name", ""),
                        "url": v.get("url", "")})
            print(f"  {name:44} {f['width']}x{f['height']}  {v.get('duration')}s")

    return got


def write_credits(out_dir: Path, got: list[dict]):
    """Pexels does not require attribution, but recording where each clip came
    from is how we prove provenance later -- which is the whole point of the
    switch away from ripped gameplay."""
    p = out_dir / "CREDITS.md"
    lines = []
    if p.exists():
        lines = [l for l in p.read_text(encoding="utf-8").splitlines()
                 if l.startswith("- ")]
    for g in got:
        lines.append(f"- `{g['file']}` — {g['author'] or 'Pexels'} — {g['url']}")
    p.write_text(
        "Footage from [Pexels](https://www.pexels.com), free for commercial "
        "use.\nEvery clip below was downloaded through the Pexels API by "
        "`scripts/fetch_footage.py`.\n\n" + "\n".join(sorted(set(lines))) + "\n",
        encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", choices=sorted(PRESETS))
    ap.add_argument("--query", action="append", help="repeatable")
    ap.add_argument("--out")
    ap.add_argument("--count", type=int, default=10)
    a = ap.parse_args()

    env_file.load()
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        sys.exit("  PEXELS_API_KEY is not set.\n"
                 "  Get one free in about a minute at https://www.pexels.com/api/\n"
                 "  then add it to .env as  PEXELS_API_KEY=...")

    if a.preset:
        cfg = PRESETS[a.preset]
        queries, out = cfg["queries"], Path(a.out or cfg["out"])
    elif a.query and a.out:
        queries, out = a.query, Path(a.out)
    else:
        sys.exit("  need --preset, or both --query and --out")

    out = out if out.is_absolute() else ROOT / out
    print(f"  -> {out}")
    got = fetch(queries, out, a.count, key)
    if got:
        write_credits(out, got)
    print(f"\n  {len(got)} new clip(s); {len(list(out.glob('*.mp4')))} total")


if __name__ == "__main__":
    main()

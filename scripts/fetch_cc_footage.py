"""Fetch Creative Commons gameplay footage into a background set.

    python scripts/fetch_cc_footage.py [limit]

LICENCE FILTERING IS THE POINT. The source list is built from the YouTube API
filtered on status.license == "creativeCommon" -- NOT on the words "Free To
Use" in a title, which are a claim rather than a grant. The playlist this was
built for had 93 entries of which 3 carried the standard licence and 61 were
unique; titles alone would have caught neither problem.

CC BY requires attribution, so the folder carries a CREDIT.txt that bot.py
reads and appends to the description of any video cut from it, and an
ATTRIBUTION.json recording every clip's source video.

Note the uploader licenses THEIR recording. The underlying game footage belongs
to its publisher; the CC tag covers their layer, not that one.
"""
import json, os, subprocess, sys, time
from pathlib import Path

OUT = Path("footage/carveteran/gameplay_cc")
OUT.mkdir(parents=True, exist_ok=True)
MANIFEST = OUT / "ATTRIBUTION.json"
LOCK = OUT / ".fetch.lock"
START, LENGTH = 90, 60

if LOCK.exists():
    age = time.time() - LOCK.stat().st_mtime
    if age < 1800:
        raise SystemExit(f"another fetch is running (lock {age:.0f}s old)")
    LOCK.unlink()
LOCK.write_text(str(os.getpid()))

try:
    cc = {c["id"]: c for c in json.load(open("/tmp/cc_list.json"))}
    # Rebuild from disk: one row per file actually present, no duplicates.
    on_disk = sorted(p.name for p in OUT.glob("cc_*.mp4"))
    done = []
    for name in on_disk:
        vid = name[3:-4]
        c = cc.get(vid, {})
        done.append({"id": vid, "title": c.get("title", ""),
                     "channel": c.get("channel", "No Copyright Gameplay"),
                     "url": f"https://www.youtube.com/watch?v={vid}",
                     "license": "CC-BY (YouTube: creativeCommon)", "file": name})
    MANIFEST.write_text(json.dumps(done, indent=1), encoding="utf-8")
    print(f"manifest rebuilt from disk: {len(done)} clip(s)", flush=True)

    have = {d["id"] for d in done}
    todo = [c for c in cc.values() if c["id"] not in have]
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else len(todo)
    todo = todo[:limit]
    print(f"retrying/fetching {len(todo)}", flush=True)

    ok = fail = 0
    for n, c in enumerate(todo, 1):
        dest = OUT / f"cc_{c['id']}.mp4"
        cmd = ["yt-dlp", "--no-warnings", "--no-playlist", "--quiet",
               "--retries", "3", "--fragment-retries", "3",
               "-f", "bestvideo[height<=1080][ext=mp4]/best[height<=1080]",
               "--download-sections", f"*{START}-{START+LENGTH}",
               "--merge-output-format", "mp4", "-o", str(dest),
               f"https://www.youtube.com/watch?v={c['id']}"]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=420)
        except subprocess.TimeoutExpired:
            print(f"  [{n}/{len(todo)}] TIMEOUT {c['id']}", flush=True); fail += 1; continue
        if r.returncode != 0 or not dest.exists() or dest.stat().st_size < 200_000:
            print(f"  [{n}/{len(todo)}] FAIL {c['id']}: {(r.stderr or '').strip()[-70:]}", flush=True)
            dest.unlink(missing_ok=True); fail += 1
            time.sleep(4)          # back off; most failures look like throttling
            continue
        ok += 1
        done.append({"id": c["id"], "title": c["title"], "channel": c["channel"],
                     "url": f"https://www.youtube.com/watch?v={c['id']}",
                     "license": "CC-BY (YouTube: creativeCommon)", "file": dest.name})
        MANIFEST.write_text(json.dumps(done, indent=1), encoding="utf-8")
        print(f"  [{n}/{len(todo)}] {dest.name} {dest.stat().st_size/1e6:.0f}MB", flush=True)
        time.sleep(2)
    print(f"\ndone: +{ok} fetched, {fail} failed, {len(done)} total", flush=True)
finally:
    LOCK.unlink(missing_ok=True)

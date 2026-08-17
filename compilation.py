"""
compilation.py
Stitches already-rendered Shorts into ONE long-form video for YouTube.

Why this exists: a vertical video <=3 minutes is classified as a Short, and
Shorts earn ZERO "valid public watch hours" toward the Partner Program -- they
feed a separate 10M-views/90-day track instead. Combining two 55s saga parts
still lands under 3 minutes, so it stays a Short and still earns nothing. The
only way this content generates watch hours is a compilation LONG enough to be
treated as a normal video (we target 10+ minutes, well clear of the line).

It also attacks the subscriber half of the problem: someone who watches eight
minutes is a far likelier subscriber than someone who scrolls past a Short,
which is the gap behind 800+ views and 0 subs.

Design notes:
  * Best-performing stories go FIRST (strongest hook up top = retention).
  * Saga parts are kept TOGETHER and IN ORDER -- ranking purely by views would
    scatter a pt2 away from its pt1 and break the story.
  * Vertical is padded into 16:9 over a blurred copy of itself, so it doesn't
    sit in ugly pillarboxes on desktop.
  * A numbered title card announces each story, so the result is a structured
    video rather than a raw dump.
  * Used stories are recorded, so the next compilation picks fresh ones.

    python compilation.py --minutes 12          # build (does not upload)
    python compilation.py --minutes 12 --upload # build + upload as long-form
    python compilation.py --list                # what's available/used
"""

import argparse
import csv
import json
import os
import re
import subprocess
from pathlib import Path

import config
from ffmpeg_setup import ensure_ffmpeg

ROOT = Path(__file__).parent
# All of these follow the account. use_account() repoints them; the defaults
# are the first account's, so existing callers behave exactly as before.
OUT = ROOT / "output"
OUT_DIR = OUT / "compilations"
USED_FILE = OUT / "compilation_used.json"
POST_LOG = OUT / "post_log.csv"
STATS = OUT / "channel_stats.json"
ACCOUNT = None


def use_account(acc_id: str = ""):
    """Point this module at ONE channel's rendered videos and history."""
    global OUT, OUT_DIR, USED_FILE, POST_LOG, STATS, ACCOUNT
    import sys as _sys
    _sys.path.insert(0, str(ROOT))
    from accounts import all_accounts, get_account, paths
    acc = get_account(acc_id) if acc_id else all_accounts()[0]
    p = paths(acc)
    OUT = p["out_dir"]
    OUT_DIR = OUT / "compilations"
    USED_FILE = OUT / "compilation_used.json"
    POST_LOG = p["post_log"]
    STATS = p["channel_stats"]
    ACCOUNT = acc
    return acc
# Long-form copy per content type. Everything format-specific lives here, so a
# new channel format is a dict entry rather than an edit to upload(). Tags are
# NOT here -- they come off the account, which already carries the right ones.
COMPILATION_COPY = {
    "story": {
        "title": "Stories To Fall Asleep To (Story Compilation)",
        "unit": "original short stories",
        "jump": "Jump to any story using the chapters below.",
        "tail": "New stories every day — subscribe so you don't miss them.",
    },
    "dialogue": {
        "title": "Car Repairs You're Being Overcharged For (Compilation)",
        "unit": "quick car-maintenance breakdowns",
        "jump": "Jump to any topic using the chapters below.",
        "tail": "New car tips every day — subscribe so you don't miss them.",
    },
}

W, H = 1920, 1080          # 16:9 long-form, NOT vertical (must not be a Short)
CARD_SECONDS = 2.0

# Weekly build settings (--weekly, run hourly from run_all.py).
COMPILATION_WEEKDAY = 6    # 6 = Sunday; a week's Shorts are done by then
TARGET_MINUTES = 12
MIN_MINUTES = 8            # below this, wait rather than ship a thin one

# THEMES -- modelled on how the big Reddit-compilation channels actually work
# (e.g. a 2-hour upload where every story is about one subject). A theme is a
# promise: it gives a viewer a reason to keep watching past the story they
# clicked for, which a random grab-bag never does. Mixed compilations are the
# fallback, not the goal.
THEMES = {
    "landlord": (("landlord", "lease", "tenant", "rent", "deposit", "apartment",
                  "eviction", "security deposit"),
                 "Landlords Who Picked The Wrong Tenant"),
    "hoa": (("hoa", "homeowners association", "neighbor", "mailbox", "fence", "yard"),
            "HOA Presidents Who Went Too Far"),
    "wedding": (("wedding", "bride", "groom", "maid of honor", "bridesmaid",
                 "rehearsal", "engagement"),
                "Weddings That Fell Apart"),
    "work": (("boss", "manager", "coworker", "fired", "shift", "badge",
              "register", "write-up", "hr "),
             "Bosses Who Regretted It"),
    "family": (("sister", "brother", "mom", "dad", "mother", "father",
                "in-law", "cousin", "aunt", "uncle"),
               "Family Drama That Went Nuclear"),
    "creepy": (("baby monitor", "3am", "night shift", "footsteps", "attic",
                "basement", "vanished", "no one", "alone"),
               "Stories That'll Keep You Up Tonight"),
}
# A themed compilation needs enough of one subject to justify the promise.
MIN_THEME_MINUTES = 15


def theme_of(group: dict) -> str | None:
    t = (group["title"] + " " + group["base"]).lower()
    for name, (keys, _title) in THEMES.items():
        if any(k in t for k in keys):
            return name
    return None


def themed_inventory(include_used: bool = False) -> dict:
    """{theme: {'groups': [...], 'minutes': float, 'title': str}} sorted by size."""
    out: dict[str, dict] = {}
    for g in rank_stories(include_used=include_used):
        name = theme_of(g)
        if not name:
            continue
        d = out.setdefault(name, {"groups": [], "minutes": 0.0,
                                  "title": THEMES[name][1]})
        d["groups"].append(g)
        d["minutes"] += g["seconds"] / 60
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["minutes"]))


def _used() -> set[str]:
    try:
        return set(json.loads(USED_FILE.read_text(encoding="utf-8")))
    except Exception:
        return set()


def _mark_used(stems: list[str]):
    USED_FILE.parent.mkdir(parents=True, exist_ok=True)
    USED_FILE.write_text(json.dumps(sorted(_used() | set(stems)), indent=1),
                         encoding="utf-8")


def _base(stem: str) -> str:
    return re.sub(r"_pt\d+$", "", stem)


def _part_no(stem: str) -> int:
    m = re.search(r"_pt(\d+)$", stem)
    return int(m.group(1)) if m else 1


def _duration(path: Path) -> float:
    try:
        r = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries",
                            "format=duration", "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True, timeout=30)
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def _title_for(stem: str) -> str:
    """The story's own hook, from its caption file; falls back to the stem."""
    cap = OUT / f"{stem}_caption.txt"
    if cap.exists():
        for line in cap.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if len(line) > 15:
                return line
    return stem.replace("_", " ").title()


def _deleted_stems() -> set[str]:
    """Stems whose YouTube upload no longer exists.

    A deleted upload leaves its 'posted' row in the log and its mp4 on disk, so
    without this a compilation would republish content the owner deliberately
    pulled. Fails OPEN (returns nothing) only on an API error -- but prints a
    warning, since silently including everything is the risky direction here.
    """
    import sys
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from set_privacy import get_service
        yt = get_service()
    except Exception as e:
        print(f"WARNING: couldn't verify deleted videos ({e}) -- "
              "review the list before uploading.")
        return set()

    # ALL of a stem's uploads, not just the last one. This was
    # `stem2id[stem] = vid`, so a stem uploaded twice kept only the later id --
    # and deleting EITHER copy then condemned the episode. That is exactly what
    # happened to car_brake_squeal_diagnosis: it went up twice (oZKDEIWNkv8 and
    # Jw2VXueR-vQ), the duplicate was deleted, and the still-public original was
    # judged deleted with it, quietly barring a good episode from every future
    # compilation. A stem is gone only when nothing it produced survives.
    stem2ids: dict[str, set] = {}
    for r in csv.reader(open(POST_LOG, encoding="utf-8")):
        if len(r) >= 4 and r[2] and r[3] in ("posted", "posted_manual", "scheduled"):
            stem2ids.setdefault(r[1].replace(".mp4", ""), set()).add(r[2])
    ids = sorted({v for s in stem2ids.values() for v in s})
    alive = set()
    try:
        for i in range(0, len(ids), 50):
            alive |= {v["id"] for v in yt.videos().list(
                part="id", id=",".join(ids[i:i + 50])).execute().get("items", [])}
    except Exception as e:
        print(f"WARNING: YouTube check failed ({e}) -- review before uploading.")
        return set()
    # Deleted only if NONE of its uploads survive.
    return {s for s, vids in stem2ids.items() if not (vids & alive)}


def rank_stories(include_used: bool = False) -> list[dict]:
    """Stories on disk, best-performing first, saga parts grouped in order.

    A saga is ranked by its BEST part's views, then its parts play in sequence
    -- otherwise a pt2 could appear pages away from its pt1.
    """
    stats = json.loads(STATS.read_text())
    views_by_id = {v["videoId"]: v["views"] for v in stats.get("videos", [])}
    stem2views: dict[str, int] = {}
    for r in csv.reader(open(POST_LOG, encoding="utf-8")):
        if len(r) >= 4 and r[2] and r[3] in ("posted", "posted_manual"):
            stem = r[1].replace(".mp4", "")
            stem2views[stem] = max(stem2views.get(stem, 0),
                                   views_by_id.get(r[2], 0))

    # Only material that actually went out. A render sitting in out_dir was
    # never vetted -- it may predate a quality fix, or have been rejected -- and
    # a compilation is the one place an unposted file could reach the public
    # without anyone having decided it should. The car channel has 7 such
    # renders, several from during the pitch/shadow/caption iteration; the only
    # thing keeping them out was that compilations were refused for it at all.
    # Instagram-only counts: it shipped, and it is still new to a YouTube
    # audience.
    published = set()
    if POST_LOG.exists():
        for r in csv.reader(open(POST_LOG, encoding="utf-8")):
            if len(r) >= 4 and r[3] in ("posted", "posted_manual", "scheduled",
                                        "posted_instagram"):
                published.add(r[1].replace(".mp4", ""))

    used = set() if include_used else _used()
    # Never reuse something the owner deleted -- see _deleted_stems().
    skip = used | _deleted_stems()
    groups: dict[str, list[Path]] = {}
    for p in sorted(OUT.glob("*.mp4")):
        if p.stem.startswith("_") or p.stem in skip or p.stem not in published:
            continue
        groups.setdefault(_base(p.stem), []).append(p)

    out = []
    for base, files in groups.items():
        files.sort(key=lambda f: _part_no(f.stem))
        score = max(stem2views.get(f.stem, 0) for f in files)
        secs = sum(_duration(f) for f in files)
        if secs <= 0:
            continue
        out.append({"base": base, "files": files, "views": score,
                    "seconds": secs, "title": _title_for(files[0].stem)})
    out.sort(key=lambda g: -g["views"])
    return out


def _make_card(text: str, index: int, path: Path):
    """A numbered title card so the compilation reads as structured chapters."""
    from PIL import Image, ImageDraw
    from hook_card import _font

    img = Image.new("RGB", (W, H), (13, 16, 23))
    d = ImageDraw.Draw(img)
    num_font, body = _font(120), _font(58)
    d.text((W // 2, H // 2 - 150), f"STORY {index}", font=num_font,
           fill=(124, 140, 255), anchor="mm")

    words, lines, cur = text.split(), [], []
    for w in words:
        cur.append(w)
        if d.textlength(" ".join(cur), font=body) > W - 320:
            cur.pop()
            lines.append(" ".join(cur))
            cur = [w]
        if len(lines) == 3:
            break
    if cur and len(lines) < 3:
        lines.append(" ".join(cur))
    y = H // 2 + 10
    for ln in lines:
        d.text((W // 2, y), ln, font=body, fill=(233, 234, 238), anchor="mm")
        y += 78
    img.save(path)


# Domain groupings. Purely lexical overlap catches "check engine light" twice
# but NOT a dealership-loan episode sitting next to an extended-warranty one --
# same pitch to a viewer, no words in common. These are deliberately coarse and
# best-effort; an episode matching nothing is simply never called similar.
_TOPIC_CLUSTERS = {
    "engine_light": ("check engine", "engine light", "obd", "code read", "diagnostic"),
    "finance":      ("dealership", "loan", "warranty", "finance", "upsell",
                     "add-on", "add on", "f&i"),
    "tires":        ("tire", "psi", "pressure", "wheel", "nitrogen", "alignment",
                     "lug", "rotate"),
    "brakes":       ("brake", "rotor", "pad", "squeal"),
    "fluids":       ("oil change", "coolant", "washer fluid", "transmission",
                     "gas tank", "fuel", "gas station", "octane", "premium gas"),
    "battery":      ("battery", "terminal", "alternator", "jump start"),
    "filters":      ("air filter", "cabin filter", "engine filter"),
    "cosmetic":     ("wash", "wax", "paint", "headlight", "detail", "ceramic"),
}
_STOP = {"the", "a", "an", "your", "you", "youre", "is", "are", "to", "for",
         "of", "and", "at", "in", "on", "it", "its", "that", "this", "my",
         "why", "what", "how", "not", "be", "was", "with", "from", "quietly",
         "might", "mean", "costs", "cost", "free", "every", "just"}


def _content_words(title: str) -> set:
    return {w for w in re.findall(r"[a-z]+", (title or "").lower())
            if len(w) > 2 and w not in _STOP}


def _topic_cluster(title: str):
    low = (title or "").lower()
    for name, keys in _TOPIC_CLUSTERS.items():
        if any(k in low for k in keys):
            return name
    return None


def _similar(a: dict, b: dict) -> bool:
    """Two episodes a viewer would experience as the same subject."""
    ca, cb = _topic_cluster(a.get("title")), _topic_cluster(b.get("title"))
    if ca and ca == cb:
        return True
    return len(_content_words(a.get("title")) & _content_words(b.get("title"))) >= 2


def _space_topics(groups: list) -> list:
    """Reorder so near-duplicate subjects never sit adjacent.

    Ranking is purely by views, which happily lands two check-engine-light
    episodes back to back -- and in a twelve-minute video that reads as
    repetition exactly where a viewer decides whether to stay.

    Interleaved, not greedy. A greedy scan from the front fixes clashes near
    the top and then strands the rest: two dealership-finance episodes ranked
    last stayed adjacent because by the time the scan reached them nothing else
    remained to separate them. Similar items sinking to the tail always collide
    that way.

    So: bucket by subject, then repeatedly take from whichever subject has the
    MOST left, never the one just used. Emptying the crowded subjects first is
    what guarantees they can be separated -- the same argument as rearranging a
    string so no two equal characters touch. Rank order is preserved inside
    each subject, so the best episode of a subject still comes first.
    """
    from collections import defaultdict
    buckets, order = defaultdict(list), []
    for i, g in enumerate(groups):
        # Unclustered episodes each get their own bucket: nothing is "similar"
        # to them by cluster, so they are free separators.
        key = _topic_cluster(g.get("title")) or f"__solo_{i}"
        if key not in buckets:
            order.append(key)
        buckets[key].append(g)

    out, prev = [], None
    while any(buckets.values()):
        live = [k for k in order if buckets[k]]
        cands = [k for k in live if k != prev] or live
        # Most-remaining first; ties broken by original rank so the higher-viewed
        # subject leads.
        key = max(cands, key=lambda k: (len(buckets[k]), -order.index(k)))
        out.append(buckets[key].pop(0))
        prev = key

    # Content-word overlap can still pair two episodes the cluster map does not
    # know about. One cheap pass swaps such a neighbour forward if anywhere
    # later in the list is safe.
    for i in range(len(out) - 1):
        if not _similar(out[i], out[i + 1]):
            continue
        for j in range(i + 2, len(out)):
            if (not _similar(out[i], out[j])
                    and (i + 2 >= len(out) or not _similar(out[j], out[i + 2]))):
                out[i + 1], out[j] = out[j], out[i + 1]
                break
    return out


def _build_lock():
    """Refuse to start a second build for this account.

    PID-scoped temp dirs stop concurrent builds destroying each other, but two
    builds still race for the same compilation_YYYYMMDD.mp4 and burn twenty
    minutes of CPU rendering the same video twice. The hourly --weekly job and
    a manual run are the pair that actually collided.
    """
    lock = OUT_DIR / ".build.lock"
    if lock.exists():
        import time
        age = time.time() - lock.stat().st_mtime
        if age < 3600:
            print(f"another build is running (lock {age/60:.0f} min old) — "
                  "skipping. Delete .build.lock if that is stale.")
            return None
        lock.unlink(missing_ok=True)
    lock.write_text(str(os.getpid()))
    return lock


def build(minutes: int = 12, dry_run: bool = False,
          theme: str | None = None) -> Path | None:
    ensure_ffmpeg()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lock = _build_lock()
    if lock is None:
        return None
    try:
        return _build_inner(minutes, dry_run, theme)
    finally:
        lock.unlink(missing_ok=True)


def _build_inner(minutes: int = 12, dry_run: bool = False,
                 theme: str | None = None) -> Path | None:
    target = minutes * 60

    if theme == "auto":
        # Prefer the biggest theme that clears the bar; fall back to mixed
        # rather than shipping a themed video that can't keep its promise.
        inv = themed_inventory()
        theme = next((n for n, d in inv.items()
                      if d["minutes"] >= MIN_THEME_MINUTES), None)
        if theme:
            print(f"Theme: {theme} ({inv[theme]['minutes']:.1f} min available)")
        else:
            best = next(iter(inv.items()), None)
            print("No theme has enough material yet"
                  + (f" (biggest: {best[0]} at {best[1]['minutes']:.1f} min, "
                     f"need {MIN_THEME_MINUTES})" if best else "")
                  + " -- building a mixed compilation.")

    if theme:
        inv = themed_inventory()
        if theme not in inv:
            print(f"No stories match theme '{theme}'. Available: "
                  + ", ".join(f"{n} ({d['minutes']:.1f}m)" for n, d in inv.items()))
            return None
        ranked = inv[theme]["groups"]
    else:
        ranked = rank_stories()
    if not ranked:
        print("No unused rendered stories available.")
        return None

    picked, total = [], 0.0
    for g in ranked:
        if total >= target:
            break
        picked.append(g)
        total += g["seconds"] + CARD_SECONDS

    # Selection is by views; ORDER is by variety. Done after picking so the
    # spacing never changes which episodes make the cut, only where they sit.
    picked = _space_topics(picked)

    if total < 240:
        print(f"Only {total/60:.1f} min available -- too short to clear the "
              "3-minute Shorts threshold safely. Render more stories first.")
        return None

    print(f"Building a {total/60:.1f} min compilation from {len(picked)} stories:")
    for i, g in enumerate(picked, 1):
        print(f"  {i:2}. [{g['views']:>4} views] {g['title'][:56]}")
    if dry_run:
        return None

    # PID-scoped, because this directory is WIPED at the end of a build. It was
    # a fixed "_tmp", so two builds running at once deleted each other's
    # in-flight segments: on 2026-08-16 a manual build and the hourly --weekly
    # job overlapped, one crashed on a card PNG the other had just removed, and
    # the survivor produced 4.4 minutes of an intended 12.1 while reporting
    # success. assemble.py already scopes its temp dir by PID for exactly this
    # reason; this module never got the same treatment.
    tmp = OUT_DIR / f"_tmp_{os.getpid()}"
    tmp.mkdir(exist_ok=True)
    segments: list[Path] = []
    dropped: list[tuple] = []
    # Vertical source over a blurred, zoomed copy of itself -> fills 16:9
    # without the black pillarbox that makes desktop playback look broken.
    vf = (f"split[bg][fg];"
          f"[bg]scale={W}:{H}:force_original_aspect_ratio=increase,"
          f"crop={W}:{H},boxblur=28:3[bgb];"
          f"[fg]scale=-1:{H}[fgs];[bgb][fgs]overlay=(W-w)/2:0")

    for i, g in enumerate(picked, 1):
        card_png = tmp / f"card_{i:02d}.png"
        _make_card(g["title"], i, card_png)
        card_mp4 = tmp / f"card_{i:02d}.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1",
                        "-i", str(card_png), "-f", "lavfi",
                        "-i", "anullsrc=r=44100:cl=stereo",
                        "-t", str(CARD_SECONDS), "-c:v", "libx264",
                        "-preset", config.FFMPEG_PRESET, "-crf", config.FFMPEG_CRF,
                        "-pix_fmt", "yuv420p", "-r", "30",
                        "-c:a", "aac", "-shortest", str(card_mp4)],
                       capture_output=True, timeout=180)
        segments.append(card_mp4)

        for f in g["files"]:
            seg = tmp / f"seg_{i:02d}_{f.stem[:20]}.mp4"
            r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(f),
                            "-filter_complex", vf, "-c:v", "libx264",
                            "-preset", config.FFMPEG_PRESET, "-crf", config.FFMPEG_CRF,
                            "-pix_fmt", "yuv420p", "-r", "30",
                            "-c:a", "aac", "-ar", "44100", "-ac", "2",
                            str(seg)], capture_output=True, text=True, timeout=900)
            if seg.exists() and r.returncode == 0:
                segments.append(seg)
            else:
                # Was `if seg.exists()` with the result discarded, so a failed
                # encode dropped the story and the build still reported success.
                dropped.append((f.name, (r.stderr or "").strip()[-160:]))

    lst = tmp / "concat.txt"
    lst.write_text("".join(f"file '{s.as_posix()}'\n" for s in segments),
                   encoding="utf-8")
    from datetime import date
    out = OUT_DIR / f"compilation_{date.today():%Y%m%d}.mp4"
    if dropped:
        print(f"WARNING: {len(dropped)} story segment(s) failed to encode and "
              "were left out:")
        for name, err in dropped:
            print(f"   {name}: {err or '(no stderr)'}")

    expected = sum(_duration(s) for s in segments)
    cj = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                         "-i", str(lst), "-c", "copy", str(out)],
                        capture_output=True, text=True, timeout=900)
    if cj.returncode != 0 or (cj.stderr or "").strip():
        print(f"concat reported: {(cj.stderr or '').strip()[:300]}")
    got = _duration(out) if out.exists() else 0.0
    for f in tmp.iterdir():
        f.unlink(missing_ok=True)
    tmp.rmdir()

    if not out.exists():
        print("ffmpeg failed to produce the compilation.")
        return None

    # A build that quietly loses most of its runtime is the failure that
    # actually happened: 14 stories were selected, the log said "Built ...",
    # and the file was 4.4 minutes of an intended 12.1. Never hand back a
    # truncated compilation as if it succeeded.
    if expected and got < expected * 0.95:
        print(f"ABORTING: the joined file is {got/60:.1f} min but its parts "
              f"total {expected/60:.1f} min — {expected - got:.0f}s went missing "
              "in the concat. Not returning a truncated compilation.")
        out.unlink(missing_ok=True)
        return None
    dur = got
    print(f"\nBuilt {out.name} — {dur/60:.1f} min, "
          f"{out.stat().st_size/1e6:.0f} MB, {W}x{H}")
    if dur < 185:
        print("WARNING: under ~3 minutes; YouTube may still class this a Short.")
    _mark_used([f.stem for g in picked for f in g["files"]])
    # stash the line-up so upload() can build chapters from it
    (OUT_DIR / (out.stem + "_lineup.json")).write_text(
        json.dumps([{"title": g["title"], "seconds": g["seconds"]}
                    for g in picked], indent=1), encoding="utf-8")
    return out


def _chapters(picked: list[dict]) -> str:
    """YouTube chapter timestamps. These become clickable chapters, which
    matter a lot on a compilation -- a viewer who can jump to a story that
    interests them stays instead of bouncing. YouTube requires the first to be
    0:00 and at least three in total."""
    lines, t = [], 0.0
    for i, g in enumerate(picked, 1):
        m, s = divmod(int(t), 60)
        h, m = divmod(m, 60)
        stamp = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
        # Trim at the first sentence end, but NOT at commas -- "$4,200" would
        # be cut to "$4". Fall back to a clean word-boundary truncation.
        title = re.split(r"(?<=[a-z])\.\s", g["title"])[0].strip().rstrip(".")
        if len(title) > 75:
            title = title[:75].rsplit(" ", 1)[0] + "…"
        lines.append(f"{stamp} — {title}")
        t += CARD_SECONDS + g["seconds"]
    return "\n".join(lines)


def upload(path: Path, picked: list[dict] | None = None,
           privacy: str | None = None, theme: str | None = None):
    """Upload as standard long-form (16:9, >3min, no #shorts tag).

    Costs no Anthropic tokens -- title/description are templates, not generated.
    YouTube's API is free; an upload just consumes ~1600 of the 10k daily quota.
    """
    from youtube_upload import upload_video
    from accounts import load_accounts
    # Upload to whichever channel this run is scoped to -- ACCOUNT is set by
    # use_account(). Falling back to the first account here would upload one
    # channel's compilation onto the other's channel.
    acc = ACCOUNT or load_accounts()[0]
    from datetime import date
    n = len(picked) if picked else 0
    # Title as an EVENT, not an inventory: name the theme ("...Who Went Too
    # Far"), because a count like "14 Stories" reads as a listing and converts
    # worse. "(Story Compilation)" keeps the format signal people search for.
    #
    # It used to say "(Reddit Compilation)", and the description "Reddit-style
    # stories". Same problem as the r/ badge on the Shorts cards -- these are
    # our own fiction, and claiming a Reddit origin is the thing YouTube's
    # inauthentic-content rules look for. It matters more here than on a Short:
    # long-form is what carries watch hours toward monetization review.
    kind = getattr(acc, "content_type", "story")
    copy = COMPILATION_COPY.get(kind, COMPILATION_COPY["story"])
    # THEMES are story concepts (landlord, wedding, HOA), so a themed title
    # only applies where a theme was actually matched.
    if theme and theme in THEMES:
        title = f"{THEMES[theme][1]} (Story Compilation)"
    else:
        title = copy["title"]
    desc = (f"{n} {copy['unit']} back to back. {copy['jump']}\n\n"
            + (_chapters(picked) if picked else "")
            + f"\n\n{copy['tail']}\n\n"
            + getattr(config, "ORIGINALITY_NOTE", "").strip()
            + "\n\n" + getattr(acc, "yt_hashtags", "").replace("#shorts ", ""))
    # Tags off the ACCOUNT. The hardcoded list said "short fiction" and
    # "original story" for every channel, which on the car channel would tell
    # YouTube the wrong audience -- the same failure per-account yt_tags fixed
    # for Shorts. "shorts" itself is dropped: this is deliberately not one.
    tags = [t for t in getattr(acc, "yt_tags", ()) if t != "shorts"]
    vid = upload_video(str(path), title=title, description=desc,
                       tags=(tags + ["compilation"])[:15],
                       privacy_status=privacy or config.PRIVACY_STATUS,
                       token_file=acc.yt_token)
    print(f"Uploaded: https://youtube.com/watch?v={vid}")

    # Custom thumbnail -- without one YouTube picks a random frame, which on a
    # compilation means a blurred piece of gameplay as the video's face. Needs
    # a phone-verified channel (done 2026-07-26). Never fails the upload.
    try:
        import thumbnail
        mins = int(_duration(path) // 60)
        sub = f"{n} stories · {mins} minutes" if n else f"{mins} minutes"
        # Strip the parenthetical: it earns its place in a search result, but
        # on a thumbnail it just steals size from the words that stop a scroll.
        th = thumbnail.build(re.sub(r"\s*\([^)]*Compilation\)\s*$", "", title),
                             theme=theme,
                             out=OUT_DIR / f"{path.stem}_thumb.jpg",
                             subtitle=sub)
        thumbnail.set_on_video(vid, th)
    except Exception as e:
        print(f"Thumbnail step skipped (video is fine): {e}")
    return vid


def _weekly_build(acc) -> None:
    """One channel's weekly build. Never raises -- a channel that cannot build
    must not stop the next one, and this runs from the hourly job."""
    from datetime import date, datetime
    try:
        marker = OUT_DIR / ".last_weekly"
        week = f"{date.today().isocalendar().year}-W{date.today().isocalendar().week}"
        if marker.exists() and marker.read_text().strip() == week:
            print(f"[{acc.id}] weekly compilation already built this week")
            return
        if date.today().weekday() != COMPILATION_WEEKDAY or datetime.now().hour < 9:
            return
        # Published material only -- see rank_stories. A young channel sits
        # under this floor and waits, which is how the car channel turns itself
        # on once it has actually shipped enough episodes.
        avail = sum(g["seconds"] for g in rank_stories()) / 60
        if avail < MIN_MINUTES:
            print(f"[{acc.id}] only {avail:.1f} min published and unused -- "
                  "waiting for more material")
            return
        out = build(TARGET_MINUTES, theme='auto')
        if out:
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            marker.write_text(week)
            try:
                import sys as _s
                _s.path.insert(0, str(ROOT / "scripts"))
                from discord_notify import send_dm
                send_dm(f"🎬 **Weekly compilation ready** — {acc.name}: "
                        f"`{out.name}` ({_duration(out)/60:.0f} min).\n"
                        f"Review it, then upload with:\n"
                        f"`python compilation.py --upload --account {acc.id}`")
            except Exception:
                pass
    except Exception as e:
        print(f"[{acc.id}] weekly compilation skipped (non-fatal): {e}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, default=12)
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--theme", default=None,
                    help="theme name, or 'auto' to pick the biggest one that qualifies")
    ap.add_argument("--themes", action="store_true", help="show themed inventory")
    ap.add_argument("--weekly", action="store_true",
                    help="build only if it's the chosen weekday and there's "
                         "enough unused material; never fails the run")
    ap.add_argument("--account", default="",
                    help="channel id (default: the first account)")
    a = ap.parse_args()
    _acc = use_account(a.account)
    # --weekly loops every channel below, so naming one here would imply the
    # others were not considered.
    if not a.weekly:
        print(f"channel: {_acc.name}")

    if a.weekly:
        # Called hourly by run_all.py, so it must be a cheap no-op almost every
        # time. Deliberately BUILDS but never uploads: long-form lives or dies
        # on its title and thumbnail, so the owner reviews before publishing.
        #
        # EVERY enabled channel, not just the first. run_all invokes this with
        # no --account, so a second channel was never even considered. Each one
        # gates itself on having MIN_MINUTES of PUBLISHED material, so a young
        # channel simply waits and switches itself on once it has shipped
        # enough -- no separate enable step to remember.
        from accounts import load_accounts
        # use_account() resolves the id and repoints every path this module
        # reads, so route through it rather than holding an Account here.
        _ids = [a.account] if a.account else [x.id for x in load_accounts()]
        for _id in _ids:
            _weekly_build(use_account(_id))
        raise SystemExit(0)

    if a.themes:
        inv = themed_inventory()
        print(f"Themed inventory (need {MIN_THEME_MINUTES} min for a themed build):")
        for name, d in inv.items():
            ok = "READY" if d["minutes"] >= MIN_THEME_MINUTES else "building"
            print(f'  {name:10} {d["minutes"]:5.1f} min  {len(d["groups"]):2} stories  [{ok}]  "{d["title"]}"')
    elif a.list:
        used = _used()
        av = rank_stories()
        print(f"{len(av)} unused stories on disk ({len(used)} already used):")
        tot = 0
        for g in av:
            tot += g["seconds"]
            print(f"  [{g['views']:>4} views] {g['seconds']:5.1f}s  {g['title'][:52]}")
        print(f"\n  total available: {tot/60:.1f} min")
    else:
        p = build(a.minutes, dry_run=a.dry_run, theme=a.theme)
        if p and a.upload:
            lu = OUT_DIR / (p.stem + "_lineup.json")
            picked = json.loads(lu.read_text(encoding="utf-8")) if lu.exists() else None
            upload(p, picked, theme=a.theme)

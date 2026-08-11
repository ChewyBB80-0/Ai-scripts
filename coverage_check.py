"""
coverage_check.py
Flags videos that only made it to some of the platforms they should be on.

Why this exists: YouTube and Instagram are posted independently so a failure on
one never blocks the other (see bot._post_video). That's the right behaviour,
but it means a video can quietly end up half-posted -- which is exactly what
happened on 2026-07-22, when one story went to Instagram only and another to
YouTube only, and nothing surfaced it.

TikTok is deliberately NOT treated as a gap: it's approval-gated, so "not on
TikTok" is a normal state, not an error. It's reported for information only.

    python coverage_check.py            # report
    python coverage_check.py --fix      # also post the missing side
    python coverage_check.py --days 3   # only look at the last 3 days
"""

import csv
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent
# The account's log, not "the" log. Defaults to the first account so existing
# callers and the bare CLI behave exactly as before; use_account() repoints it.
LOG = ROOT / "output" / "post_log.csv"
OUT = ROOT / "output"


def use_account(acc_id: str = "") -> str:
    """Point this module at ONE channel's post log. Returns the account name.

    Coverage is per channel: a video half-posted on the car channel is invisible
    while this reads the story channel's log, which is the exact failure the
    checker exists to catch.
    """
    global LOG, OUT
    import sys as _sys
    _sys.path.insert(0, str(ROOT))
    from accounts import all_accounts, get_account, paths
    acc = get_account(acc_id) if acc_id else all_accounts()[0]
    LOG = paths(acc)["post_log"]
    OUT = paths(acc)["out_dir"]
    return acc.name

# statuses that mean "this story is on YouTube" -- scheduled counts, the upload
# already exists and will auto-release
YT_OK = {"posted", "posted_manual", "scheduled"}
IG_OK = {"posted_instagram"}


def _rows(days: int | None = None) -> list:
    if not LOG.exists():
        return []
    out = []
    cutoff = datetime.now().astimezone() - timedelta(days=days) if days else None
    for r in csv.reader(open(LOG, encoding="utf-8")):
        if len(r) < 4 or r[3] == "status":
            continue
        if cutoff:
            try:
                when = datetime.fromisoformat(r[0])
                # early rows were logged without a timezone offset; treat those
                # as local time so they can be compared with the newer ones
                if when.tzinfo is None:
                    when = when.astimezone()
                if when < cutoff:
                    continue
            except ValueError:
                continue
        out.append(r)
    return out


def _stem(title: str) -> str:
    """Older log rows stored the filename with its extension, newer ones the
    bare stem -- normalise so the same video isn't counted as two."""
    return title[:-4] if title.lower().endswith(".mp4") else title


def coverage(days: int | None = None) -> dict:
    """stem -> {'youtube': bool, 'instagram': bool, 'when': first, 'last': latest}.

    Coverage is ALWAYS computed over the whole log. `days` only decides which
    videos are worth reporting on, never which platform rows count.

    That distinction is the whole correctness of this file. Reading rows through
    the window instead made the two sides of a video invisible to each other
    whenever they landed more than `days` apart -- and that is the normal shape
    of a recovered failure, not an edge case. brother_in_law_uploaded_my_run
    reached Instagram on Jul 30, failed YouTube three times, and only succeeded
    there on Aug 7; the Instagram row fell outside the 7-day window, so it was
    reported as a gap and --fix tried to post a second copy. Only the dedup
    inside _post_video stopped a duplicate going out.
    """
    cov: dict[str, dict] = {}
    for ts, title, _vid, status in _rows(None):          # full history, always
        c = cov.setdefault(_stem(title),
                           {"youtube": False, "instagram": False,
                            "when": ts, "last": ts})
        if status in YT_OK:
            c["youtube"] = True
        if status in IG_OK:
            c["instagram"] = True
        c["when"] = min(c["when"], ts)
        c["last"] = max(c["last"], ts)
    if days is None:
        return cov
    # In scope = touched recently. Judged on everything.
    # Compared as ISO strings, matching platform_start() and the rest of this
    # file -- _rows() hands back raw CSV fields, so these are text, and mixing
    # in a datetime here would raise on the first comparison.
    cutoff = (datetime.now().astimezone() - timedelta(days=days)).isoformat()
    return {s: c for s, c in cov.items() if c["last"] >= cutoff}


def platform_start() -> dict:
    """When each platform actually came online, read out of the log itself.
    A video posted before Instagram was wired up (2026-07-18) isn't 'missing'
    from Instagram -- there was nowhere to post it. Deriving this instead of
    hardcoding a date means it stays correct if a platform is added later."""
    first = {"youtube": None, "instagram": None}
    for ts, _title, _vid, status in _rows(None):
        key = "youtube" if status in YT_OK else ("instagram" if status in IG_OK else None)
        if key and (first[key] is None or ts < first[key]):
            first[key] = ts
    return first


def _deleted_from_youtube(stems: list[str]) -> set[str]:
    """Stems whose YouTube upload no longer exists.

    A deleted upload still leaves its 'posted' row in the log, so without this
    the checker reports "missing from Instagram" for videos that were pulled on
    purpose -- and --fix would then republish content the owner deliberately
    removed. Fails open (returns nothing) so a YouTube API problem can't cause
    real gaps to be silently hidden.
    """
    ids = {}
    for _ts, title, vid, status in _rows(None):
        if vid and status in YT_OK:
            ids[_stem(title)] = vid
    wanted = {s: ids[s] for s in stems if s in ids}
    if not wanted:
        return set()
    try:
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        from set_privacy import get_service
        yt = get_service()
        alive = set()
        vals = list(wanted.values())
        for i in range(0, len(vals), 50):
            alive |= {v["id"] for v in yt.videos().list(
                part="id", id=",".join(vals[i:i + 50])).execute().get("items", [])}
        return {s for s, v in wanted.items() if v not in alive}
    except Exception as e:
        print(f"(couldn't verify YouTube videos, assuming all live: {e})")
        return set()


def gaps(days: int | None = None, check_deleted: bool = True) -> list[tuple[str, str]]:
    """[(stem, missing_platform)] for anything that reached exactly one side,
    excluding videos that predate the missing platform going live and videos
    whose YouTube upload has since been deleted."""
    start = platform_start()
    out = []
    for stem, c in coverage(days).items():
        missing = None
        if c["youtube"] and not c["instagram"]:
            missing = "instagram"
        elif c["instagram"] and not c["youtube"]:
            missing = "youtube"
        if not missing:
            continue
        began = start.get(missing)
        if began and c["when"] < began:
            continue          # platform didn't exist yet -- not a real gap
        out.append((stem, missing))
    # Drop anything whose YouTube upload was deleted: the owner pulled it, so
    # cross-posting it now would republish removed content.
    if check_deleted and out:
        dead = _deleted_from_youtube([s for s, _ in out])
        if dead:
            print(f"(ignoring {len(dead)} deleted video(s): {', '.join(sorted(dead))})")
            out = [(s, p) for s, p in out if s not in dead]
    return out


def _tiktok_state() -> dict:
    try:
        import tiktok_queue
        return {Path(r["video"]).stem: r["status"] for r in tiktok_queue._load()}
    except Exception:
        return {}


def report(days: int | None = None) -> str:
    cov = coverage(days)
    if not cov:
        return "No posts logged yet."
    tt = _tiktok_state()
    holes = dict(gaps(days))
    lines = []
    for stem, c in sorted(cov.items(), key=lambda kv: kv[1]["when"]):
        both = c["youtube"] and c["instagram"]
        neither = not c["youtube"] and not c["instagram"]
        # "neither" is its own state. The old two-way split fell through to
        # "IG only" for a video that reached NO platform -- a row logged
        # pending_review and never posted was reported as live on Instagram and
        # merely missing YouTube, which is the opposite of what needs doing.
        # It also printed GAP while gaps() correctly ignored it, so the rows and
        # the summary disagreed.
        mark = "OK  " if both else ("--  " if neither else "GAP ")
        where = ("YT+IG" if both else "not posted" if neither
                 else "YT only" if c["youtube"] else "IG only")
        lines.append(f"{mark} {where:10} tiktok:{tt.get(stem, '-'):8} {stem[:48]}")
    body = "\n".join(lines)
    if holes:
        body += f"\n\n{len(holes)} gap(s): " + ", ".join(
            f"{s} (missing {p})" for s, p in holes.items())
        body += "\nRun `python coverage_check.py --fix` to post the missing side."
    else:
        body += "\n\nNo gaps -- every story reached both YouTube and Instagram."
    return body


def _title_for(stem: str) -> str:
    """A real display title for a re-post. The caption file's first line is the
    story's own hook -- using the bare stem instead put a raw filename
    ("sisters wedding ring pt1") on a public YouTube video on 2026-07-23."""
    import re
    cap = OUT / f"{stem}_caption.txt"
    if cap.exists():
        for line in cap.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if len(line) > 15:                       # skip blanks/short tag lines
                m = re.search(r"_pt(\d+)$", stem)
                part = f" (Part {m.group(1)})" if m else ""
                return line[:95] + part
    return stem.replace("_", " ")


def fix(days: int | None = None, dry_run: bool = False) -> str:
    """Post the missing side of any half-posted video."""
    holes = gaps(days)
    if not holes:
        return "Nothing to fix."
    if dry_run:
        return "Would post: " + ", ".join(f"{s} -> {p}" for s, p in holes)
    import bot
    done, failed = [], []
    for stem, missing in holes:
        video = OUT / f"{stem}.mp4"
        if not video.exists():
            failed.append(f"{stem} (render cleaned up)")
            continue
        try:
            # Believe what it DID, not what we asked for. _post_video skips
            # silently when a config flag, account setting or its own dedup
            # says no -- this used to be counted as a success and reported
            # "Fixed", for videos that were never touched.
            posted = bot._post_video(video, _title_for(stem), platforms=missing)
            if missing in (posted or set()):
                done.append(f"{stem} -> {missing}")
            else:
                failed.append(f"{stem} (skipped -- already posted there, or "
                              f"{missing} posting is disabled)")
        except Exception as e:
            failed.append(f"{stem} ({e})")
    msg = f"Fixed {len(done)}: " + ", ".join(done) if done else "Nothing posted."
    if failed:
        msg += f" | Skipped {len(failed)}: " + ", ".join(failed)
    return msg


DEFAULT_DAYS = 7   # anything older is history we can't meaningfully act on:
                   # the earliest videos predate Instagram being wired up at
                   # all, and their renders are long since cleaned up.


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if "--account" in args:
        try:
            who = use_account(args[args.index("--account") + 1])
        except (IndexError, KeyError) as e:
            raise SystemExit(f"--account needs a known channel id ({e})")
    else:
        who = use_account()
    days = None if "--all" in args else DEFAULT_DAYS
    if "--days" in args:
        days = int(args[args.index("--days") + 1])
    scope = "all time" if days is None else f"last {days} days"
    print(f"Platform coverage for {who} ({scope}):\n")
    print(report(days))
    if "--fix" in args:
        print("\n" + fix(days, dry_run="--dry-run" in args))

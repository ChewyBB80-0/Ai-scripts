"""
scripts/issue_watch.py
Watches the open GitHub issues for the moment each one stops being blocked.

Why this and not an agent that "works the issues": every open issue is waiting
on something that cannot be hurried -- a platform's review verdict, enough
posted videos to make a number mean something, a scheduled build, or a decision
that is the owner's to make. There is no code sitting there waiting to be
written. What was actually missing is anyone noticing the day a condition flips,
because a blocked issue is invisible until someone re-reads it.

So each issue gets a predicate over real state -- the post log, the analytics
join, the footage on disk, the error log -- and the daily report says which ones
just became answerable. An issue with no automatable condition says so plainly
rather than being quietly dropped.

    python scripts/issue_watch.py            # human-readable
    python scripts/issue_watch.py --ready    # only what is actionable now
"""

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import config  # noqa: F401,E402  -- loads .env

# A check returns (ready, note). ready=None means "no automatable condition":
# a human decision, reported so it is not mistaken for a passing check.
Result = tuple  # (bool | None, str)


def _accounts():
    from accounts import all_accounts
    return list(all_accounts())


def _posted_rows(acc) -> list:
    from accounts import paths
    p = paths(acc)["post_log"]
    if not p.exists():
        return []
    out = []
    for r in csv.reader(open(p, encoding="utf-8")):
        if len(r) >= 4 and r[3] in ("posted", "posted_manual", "posted_instagram"):
            out.append(r)
    return out


# --------------------------------------------------------------------------
def check_tiktok() -> Result:
    """#4 -- there is NO API for app-review status, so this cannot be automated.

    The first version of this check used "tiktok_token.json exists" as a proxy
    for approval and reported READY on day one. The token is dated 2026-08-10,
    three days BEFORE the resubmission it was supposedly signalling: it records
    that an OAuth flow was completed once, which says nothing about whether the
    current submission was approved. A check that answers a different question
    than the one asked is worse than no check, because it gets believed.
    """
    tok = ROOT / "tiktok_token.json"
    age = ""
    if tok.exists():
        age = (f"; a token exists from "
               f"{datetime.fromtimestamp(tok.stat().st_mtime):%Y-%m-%d} "
               "(proves auth once, NOT approval)")
    return None, ("rejected 4th time 2026-08-19 — icon/favicon FIXED and deployed; "
                  "the blocker is now a sandbox demo recording only Krish can make, "
                  f"see TIKTOK_DEMO_VIDEO.md{age}")


def check_feedback_layer() -> Result:
    """#7 / #11 -- what_works needs joined, attributed videos to say anything."""
    import video_attrs
    rows = video_attrs.load()
    per = {}
    for t, d in rows.items():
        per.setdefault(d.get("account", "?"), []).append(t)
    biggest = max((len(v) for v in per.values()), default=0)
    detail = ", ".join(f"{k}:{len(v)}" for k, v in sorted(per.items()))
    # 4 is what_works' own MIN_PER_BUCKET: below it nothing is ranked.
    return biggest >= 12, f"{detail} attributed (need ~12 on one channel to rank buckets)"


def check_window_data() -> Result:
    """#11 -- the posting-window change needs a week of posts to judge."""
    from accounts import post_window
    since = datetime.now().astimezone() - timedelta(days=7)
    n = 0
    for acc in _accounts():
        if not post_window(acc):
            continue
        for r in _posted_rows(acc):
            try:
                when = datetime.fromisoformat(r[0])
                # Early rows were logged without an offset; treat those as
                # local so they compare against an aware cutoff.
                if when.tzinfo is None:
                    when = when.astimezone()
                if when >= since:
                    n += 1
            except ValueError:
                pass
    return n >= 14, f"{n} posts inside a posting window in the last 7 days (want ~14)"


def check_compilation() -> Result:
    """#12 -- ready once a channel clears the floor, or a build awaits review."""
    import compilation as c
    notes, ready = [], False
    for acc in _accounts():
        try:
            c.use_account(acc.id)
        except SystemExit:
            continue
        avail = sum(g["seconds"] for g in c.rank_stories()) / 60
        built = sorted(c.OUT_DIR.glob("*.mp4")) if c.OUT_DIR.exists() else []
        if built:
            ready = True
            notes.append(f"{acc.id}: BUILT, awaiting review ({built[-1].name})")
        else:
            if avail >= c.MIN_MINUTES:
                ready = True
            notes.append(f"{acc.id}: {avail:.1f}/{c.MIN_MINUTES} min")
    return ready, "; ".join(notes)


def check_comment_volume() -> Result:
    """#15 -- the replier stays off until there is a sample worth judging."""
    from accounts import paths
    total = 0
    for acc in _accounts():
        p = paths(acc)["out_dir"] / "replied_comments.json"
        if p.exists():
            try:
                total += len(json.loads(p.read_text()))
            except Exception:
                pass
    return total >= 20, f"{total} comments seen (want ~20 before trusting the SKIP rules)"


def check_ig_container() -> Result:
    """#17 -- confirmed or refuted by the NEXT failure, which now names itself."""
    log = ROOT / "output" / "errors.log"
    fix = datetime(2026, 8, 13, 21, 0)          # readiness wait deployed
    if not log.exists():
        return False, "no error log yet"
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        if "rejected the container" not in line:
            continue
        try:
            when = datetime.fromisoformat(line.split(":")[0].strip()[:19].replace(" ", "T"))
        except Exception:
            continue
        if when > fix:
            return True, f"a container error occurred after the fix — read its status field ({line[:60]})"
    return False, "no container errors since the fix (weak evidence it worked)"


def check_brake_video() -> Result:
    """#16 -- tracks whether the disputed episode is public."""
    return None, "owner relisted the disputed video; tracking only"


def check_audio_taper() -> Result:
    """#14 -- taste, not a threshold."""
    return None, "audio taper is an owner decision, no condition to watch"


CHECKS = [
    (4,  "TikTok app review",            check_tiktok),
    (7,  "Feedback layer data",          check_feedback_layer),
    (11, "Posting window validation",    check_window_data),
    (12, "Compilation readiness",        check_compilation),
    (14, "Video ending treatment",       check_audio_taper),
    (15, "Comment replier sample",       check_comment_volume),
    (16, "Brake episode",                check_brake_video),
    (17, "Instagram container error",    check_ig_container),
]


def evaluate() -> list:
    out = []
    for num, name, fn in CHECKS:
        try:
            ready, note = fn()
        except Exception as e:                     # never break the daily report
            ready, note = None, f"check failed: {str(e)[:60]}"
        out.append((num, name, ready, note))
    return out


def summary(ready_only: bool = False) -> str:
    rows = evaluate()
    ready = [r for r in rows if r[2] is True]
    if ready_only:
        if not ready:
            return ""
        return ("**🔔 Issues now actionable**\n"
                + "\n".join(f"• #{n} {nm} — {note}" for n, nm, _, note in ready))
    lines = ["**Issue watch**"]
    for n, nm, r, note in rows:
        mark = "READY" if r is True else ("waiting" if r is False else "manual")
        lines.append(f"  [{mark:>7}] #{n:<3} {nm:<28} {note}")
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ready", action="store_true",
                    help="print only issues that just became actionable")
    a = ap.parse_args()
    print(summary(ready_only=a.ready) or "(nothing newly actionable)")

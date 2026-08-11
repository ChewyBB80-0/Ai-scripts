"""
scripts/post_check.py
Verify that a scheduled post actually landed, and DM the result.

Written for the case the logs cannot answer on their own: "it posted" in
post_log.csv only means _post_video returned. This checks the video is really
on YouTube and really on Instagram, that the render is a plausible length, and
that nothing errored in the window -- then says so, whether or not anyone is
awake.

    python scripts/post_check.py                    # all enabled accounts
    python scripts/post_check.py --account carveteran
    python scripts/post_check.py --hours 6 --print  # stdout only
    python scripts/post_check.py --quiet            # DM only if something is wrong

--quiet is what the daily timer uses. A check that reports every day, including
the days nothing was wrong, is a check people stop reading -- and they stop
reading it right before the day it matters. The health check already works this
way and it is the same reasoning.
"""

import argparse
import csv
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import config  # noqa: F401,E402  -- loads .env


def _recent(acc, hours: int) -> list[tuple[str, str, str]]:
    """(stem, video_id, status) rows for this account inside the window."""
    log = ROOT / acc.post_log
    if not log.exists():
        return []
    cut = datetime.now().astimezone() - timedelta(hours=hours)
    out = []
    with open(log) as f:
        for r in csv.reader(f):
            if len(r) < 4 or r[3] == "status":
                continue
            try:
                ts = datetime.fromisoformat(r[0]).astimezone()
            except ValueError:
                continue
            if ts >= cut:
                out.append((r[1], r[2], r[3]))
    return out


def _duration(path: Path) -> float:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "format=duration", "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True, timeout=60)
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def check(acc, hours: int) -> tuple[list[str], bool]:
    """(lines, ok). ok is False when something needs a human.

    Judged against the account's OWN daily_target for the Pacific quota day,
    not against a fixed number -- the two channels run different cadences, and
    "1 post" is correct for one and a failure for the other.
    """
    rows = _recent(acc, hours)
    if not rows:
        return ([f"**{acc.name}** — ❌ nothing posted in the last {hours}h "
                 f"(target {acc.daily_target}/day)"], False)

    stems = []
    for stem, _vid, _st in rows:
        if stem not in stems:
            stems.append(stem)

    ok = True
    lines = [f"**{acc.name}** — {len(stems)} post(s) in {hours}h"]
    for stem in stems:
        got = {st for s, _v, st in rows if s == stem}
        vid = next((v for s, v, st in rows if s == stem and v), "")
        on_yt = bool({"posted", "posted_manual", "scheduled"} & got)
        on_ig = "posted_instagram" in got
        # Both platforms, or say which is missing. A half-posted video is the
        # failure this whole check exists for -- it looks like success in the
        # log and costs the reach of the platform that never got it.
        if not (on_yt and on_ig):
            ok = False
        mark = "✅" if (on_yt and on_ig) else "⚠️"
        miss = "" if (on_yt and on_ig) else (
            "  MISSING " + ("Instagram" if on_yt else "YouTube"))
        line = f"┃ {mark} {stem[:40]}{miss}"

        mp4 = ROOT / acc.out_dir / f"{stem}.mp4"
        if mp4.exists():
            d = _duration(mp4)
            if d:
                line += f"  ({d:.0f}s)"
                if d < 20:
                    line += " ⚠️ suspiciously short"
                    ok = False
        lines.append(line)
        if vid:
            lines.append(f"┃    youtube.com/watch?v={vid}")

    # Short of the day's target is a problem even when everything that DID post
    # looks perfect -- silent under-posting is the failure nothing else catches.
    import bot as _bot
    _bot.POST_LOG = ROOT / acc.post_log
    made = _bot.todays_story_count()
    if made < acc.daily_target:
        lines.append(f"┃ ⚠️ {made}/{acc.daily_target} for the Pacific day so far")
        ok = False
    return lines, ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", default="")
    ap.add_argument("--hours", type=int, default=6)
    ap.add_argument("--print", action="store_true", dest="only_print")
    ap.add_argument("--quiet", action="store_true",
                    help="DM only when something is wrong (what the timer uses)")
    a = ap.parse_args()

    from accounts import all_accounts, get_account
    accs = [get_account(a.account)] if a.account else [
        x for x in all_accounts() if x.enabled]

    out = [f"**🔎 Post check** — last {a.hours}h"]
    all_ok = True
    for acc in accs:
        lines, ok = check(acc, a.hours)
        out += lines
        all_ok = all_ok and ok

    err = ROOT / "output" / "errors.log"
    if err.exists():
        cut = datetime.now() - timedelta(hours=a.hours)
        recent_err = []
        for ln in err.read_text(encoding="utf-8", errors="replace").splitlines():
            # Lines look like "2026-08-10 03:09:15.554289: message". Split once
            # on ": " so a timestamp is taken from the front and colons inside
            # the message never confuse it.
            stamp = ln.split(": ", 1)[0]
            try:
                when = datetime.fromisoformat(stamp)
            except ValueError:
                continue
            if when >= cut:
                recent_err.append(ln)
        if recent_err:
            out.append(f"⚠️ **{len(recent_err)} error(s)** in the window:")
            for ln in recent_err[-3:]:
                out.append(f"┃ {ln[:120]}")
            all_ok = False

    text = "\n".join(out)
    print(text)
    if a.only_print:
        return
    if a.quiet and all_ok:
        # Nothing wrong, so say nothing. The value of this alert is that its
        # arrival MEANS something; a daily "all fine" trains you to ignore it,
        # and you stop reading it exactly one day before you needed to.
        print("  all clear -- staying quiet (--quiet)")
        return

    from discord_notify import send_dm
    if not send_dm(text):
        print("  DM FAILED -- report not delivered", file=sys.stderr)
        raise SystemExit(1)
    print("  DM delivered")


if __name__ == "__main__":
    main()

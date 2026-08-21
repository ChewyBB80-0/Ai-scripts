"""
discord_notify.py
DMs the owner via the Discord bot: daily report + instant error alerts.
Env: DISCORD_BOT_TOKEN, DISCORD_USER_ID. Bot must share a server with you.

CLI: python scripts/discord_notify.py report   (daily summary DM)
     python scripts/discord_notify.py test     (hello DM)
"""

import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
API = "https://discord.com/api/v10"

# Load .env if nothing else has. config.py does this for the 14 modules that
# import it, but this one deliberately does not import config -- it is the
# notifier, and it must keep working even when config is unimportable. So it
# loads its own. Without it a hand-run send dies on KeyError DISCORD_BOT_TOKEN
# while the systemd timer, which gets EnvironmentFile, works fine.
sys.path.insert(0, str(ROOT))
try:
    import env_file
    env_file.load()
except Exception:
    pass


def _dm_channel(token: str, user_id: str) -> str:
    r = requests.post(f"{API}/users/@me/channels",
                      headers={"Authorization": f"Bot {token}"},
                      json={"recipient_id": user_id}, timeout=15)
    r.raise_for_status()
    return r.json()["id"]


def send_dm(text: str, ping: bool = False, files: list | None = None) -> bool:
    """Send a DM; ping=True prefixes a mention (urgent). files = paths to
    attach (previews, snapshots). Never raises."""
    try:
        token = os.environ["DISCORD_BOT_TOKEN"]
        uid = os.environ["DISCORD_USER_ID"]
        if ping:
            text = f"<@{uid}> {text}"
        ch = _dm_channel(token, uid)
        url = f"{API}/channels/{ch}/messages"
        headers = {"Authorization": f"Bot {token}"}
        paths = [Path(p) for p in (files or []) if Path(p).exists()]
        if paths:
            # multipart: attachments ride alongside a JSON payload part
            opened = [open(p, "rb") for p in paths]
            try:
                multipart = {f"files[{i}]": (p.name, fh)
                             for i, (p, fh) in enumerate(zip(paths, opened))}
                multipart["payload_json"] = (
                    None, json.dumps({"content": text[:1900]}), "application/json")
                r = requests.post(url, headers=headers, files=multipart, timeout=60)
            finally:
                for fh in opened:
                    fh.close()
        else:
            r = requests.post(url, headers=headers,
                              json={"content": text[:1900]}, timeout=15)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"discord notify failed (non-fatal): {e}")
        return False


def _channel_block(acc, bot, cov) -> tuple[list[str], int, int]:
    """One channel's lines, plus its (yt_views, ig_views) for the combined total.

    Returns ([], 0, 0) when nothing has been collected for the channel yet, so a
    configured-but-idle account does not print an empty block every morning.
    """
    d = ROOT / acc.out_dir
    yt = _read_json(d / "channel_stats.json", None)
    ig = _read_json(d / "ig_stats.json", {"totalViews": 0, "media": []})
    if yt is None and not ig.get("media"):
        return [], 0, 0
    yt = yt or {"videos": [], "subscribers": 0}

    vids = yt.get("videos", [])
    # A video can be uploaded but not yet visible -- reported separately so
    # "0 views" on a scheduled video never reads as a flop.
    sched = [v for v in vids if v.get("publishAt")
             or (v.get("privacy") and v.get("privacy") != "public")]
    live = [v for v in vids if v not in sched]
    ytv = sum(v["views"] for v in live)
    igm = ig.get("media", [])
    igv = ig.get("totalViews", 0)
    shares = sum(m.get("shares", 0) for m in igm)

    # Top across BOTH platforms. A YouTube-only "top" is simply wrong on the car
    # channel, whose best post by a wide margin is an Instagram Reel.
    cands = [{"t": v.get("title", ""), "v": v.get("views", 0), "p": "YT"} for v in live]
    cands += [{"t": (m.get("caption") or "").split("\n")[0], "v": m.get("views", 0),
               "p": "IG"} for m in igm]
    top = max(cands + [{"t": "-", "v": 0, "p": ""}], key=lambda c: c["v"])

    off = "" if acc.enabled else "  _(autoposter off)_"
    lines = [
        f"**{yt.get('channel') or acc.name}** {acc.handle}{off}",
        f"┃ YT · {ytv:,} views · {yt.get('subscribers', 0)} subs · {len(live)} live"
        + (f" · {len(sched)} scheduled" if sched else ""),
        f"┃ IG · {igv:,} views · {len(igm)} posts" + (f" · {shares} shares" if shares else ""),
        f"┃ Top · {top['p']} {str(top['t'])[:52]} ({top['v']:,})",
    ]

    # Coverage gaps are per-channel: the module reads one log, so point it at
    # this account's before asking. Without this the car channel could sit
    # half-posted indefinitely and the report would never mention it.
    try:
        cov.LOG = ROOT / acc.post_log
        g = cov.gaps(7)
        if g:
            lines.append("┃ ⚠️ " + f"{len(g)} coverage gap(s) — "
                         + ", ".join(f"{s2} missing {pl}" for s2, pl in g[:2]))
    except Exception:
        pass
    return lines, ytv, igv


def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def daily_report() -> str:
    """One block per channel, then the combined total.

    Every stats path here used to be output/channel_stats.json -- the FIRST
    channel's file -- so once a second channel went live the morning report
    quietly described half the operation while looking complete.
    """
    sys.path.insert(0, str(ROOT))
    import bot
    import config
    import coverage_check as cov
    from accounts import all_accounts
    from pathlib import Path as _P

    lines, tot_yt, tot_ig, shown = ["**📊 Daily report**"], 0, 0, 0
    for acc in all_accounts():
        block, ytv, igv = _channel_block(acc, bot, cov)
        if not block:
            continue
        shown += 1
        tot_yt += ytv
        tot_ig += igv
        lines += block

    if shown == 0:
        return "**📊 Daily report** — no stats collected yet."
    if shown > 1:
        lines.append(f"**All channels** · {tot_yt + tot_ig:,} views "
                     f"({tot_yt:,} YT · {tot_ig:,} IG)")

    # Weekly cap is a channel-level guard on the story pipeline; report it for
    # the account that actually has one.
    try:
        main = next(a for a in all_accounts() if a.content_type == "story")
        bot.POST_LOG = _P(main.post_log)
        weekly = bot.this_weeks_upload_count()
        cap = getattr(config, "WEEKLY_POST_TARGET", 14)
        lines.append(f"**Week** · {weekly}/{cap} posts used ({main.id})")
    except Exception:
        pass

    # nudge when the niche patterns go stale (they drive story generation)
    try:
        from hook_mining import is_stale, load_patterns
        if load_patterns() and is_stale():
            lines.append("_Hook patterns are over a week old — refresh when convenient._")
    except Exception:
        pass

    # Issues whose blocking condition has just cleared. Only the ones that are
    # actionable NOW -- a daily list of things still waiting is noise, and noise
    # is how a report stops being read.
    try:
        from issue_watch import summary as _issues
        block = _issues(ready_only=True)
        if block:
            lines.append("")
            lines.append(block)
    except Exception:
        pass

    return "\n".join(lines)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "report"
    if mode == "test":
        ok = send_dm("👋 Media Maker bot connected — you'll get daily reports and alerts here.")
        print("sent" if ok else "failed")
    else:
        # The hourly task calls this every run. Send ONE report per calendar
        # day, at/after REPORT_HOUR local time -- so it lands with the morning
        # rather than at whatever hour the first run happened to fire. If the
        # machine was off at 8, the first run after it wakes sends it instead
        # (no report is ever skipped, just deferred).
        from datetime import date, datetime
        REPORT_HOUR = 8
        marker = ROOT / "output" / ".last_discord_report"
        today = str(date.today())
        now = datetime.now()
        if marker.exists() and marker.read_text().strip() == today:
            print("report already sent today")
        elif now.hour < REPORT_HOUR and "--now" not in sys.argv:
            print(f"holding report until {REPORT_HOUR:02d}:00 (now {now:%H:%M})")
        else:
            if send_dm(daily_report()):
                marker.write_text(today)
                print("sent")
            else:
                print("failed")

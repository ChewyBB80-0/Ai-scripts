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


def daily_report() -> str:
    yt = {}
    ig = {}
    try:
        yt = json.loads((ROOT / "output/channel_stats.json").read_text())
    except Exception:
        pass
    try:
        ig = json.loads((ROOT / "output/ig_stats.json").read_text())
    except Exception:
        pass
    sys.path.insert(0, str(ROOT))
    import bot
    import config

    vids = yt.get("videos", [])
    # a video can be uploaded but not yet visible -- report those separately so
    # "0 views" on a scheduled video never reads as a flop
    sched = [v for v in vids if v.get("publishAt") or
             (v.get("privacy") and v.get("privacy") != "public")]
    live = [v for v in vids if v not in sched]
    ytv = sum(v["views"] for v in live)
    top = max(live + [{"views": 0, "title": "-"}], key=lambda v: v["views"])
    igm = ig.get("media", [])
    shares = sum(m.get("shares", 0) for m in igm)

    lines = [
        "**📊 ParkourFlux daily report**",
        f"**YouTube** · {ytv:,} views · {yt.get('subscribers', 0)} subs · {len(live)} live",
        f"**Instagram** · {ig.get('totalViews', 0):,} views · {len(igm)} posts · {shares} shares",
        f"**Top** · {top['title'][:58]} ({top['views']:,})",
    ]

    if sched:
        nxt = sorted(sched, key=lambda v: v.get("publishAt", ""))[0]
        when = nxt.get("publishAt", "")[:16].replace("T", " ")
        lines.append(f"**Queued** · {len(sched)} scheduled, next {when} UTC")
    else:
        lines.append("**Queued** · nothing scheduled")

    # half-posted videos are easy to miss and cost reach on the missing platform
    try:
        from coverage_check import gaps
        g = gaps(7)
        if g:
            lines.append(f"⚠️ **{len(g)} coverage gap(s)** — "
                         + ", ".join(f"{s} missing {p}" for s, p in g[:3]))
    except Exception:
        pass

    weekly = bot.this_weeks_upload_count()
    cap = getattr(config, "WEEKLY_POST_TARGET", 14)
    lines.append(f"**Week** · {weekly}/{cap} posts used")

    # nudge when the niche patterns go stale (they drive story generation)
    try:
        from hook_mining import is_stale, load_patterns
        if load_patterns() and is_stale():
            lines.append("_Hook patterns are over a week old — refresh when convenient._")
    except Exception:
        pass

    return "\n".join(lines)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "report"
    if mode == "test":
        ok = send_dm("👋 ParkourFlux bot connected — you'll get daily reports and alerts here.")
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

"""
watch_video.py
Watches specific videos and DMs on Discord when something actually changes --
a scheduled YouTube video going live, or a view-count milestone being crossed.

Why state is tracked: this runs every hour from run_all.py, so it must only
speak when there is news. It remembers what it last reported and stays silent
otherwise; a monitor that pings every hour gets muted, and then it is useless
on the run that matters.

    python watch_video.py --add-yt <videoId> --label "eerie test"
    python watch_video.py --add-ig <mediaId> --label "eerie test"
    python watch_video.py --check          # used by run_all (quiet unless news)
    python watch_video.py --status         # print everything now, no DM
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
WATCH_FILE = ROOT / "output" / "watchlist.json"

# Ping when a video crosses one of these. Sparse on purpose -- these are
# "something is happening" thresholds, not a running commentary.
MILESTONES = [100, 250, 500, 1000, 2500, 5000, 10000, 50000]


def _load() -> list:
    try:
        return json.loads(WATCH_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(rows: list):
    WATCH_FILE.parent.mkdir(parents=True, exist_ok=True)
    WATCH_FILE.write_text(json.dumps(rows, indent=1), encoding="utf-8")


def add(kind: str, ident: str, label: str = "") -> str:
    rows = _load()
    if any(r["id"] == ident for r in rows):
        return f"already watching {ident}"
    rows.append({"kind": kind, "id": ident, "label": label or ident,
                 "lastViews": 0, "lastStatus": "", "added": datetime.now().isoformat(timespec="seconds")})
    _save(rows)
    return f"watching {kind}:{ident} ({label})"


def _yt_state(vid: str) -> dict:
    sys.path.insert(0, str(ROOT / "scripts"))
    from set_privacy import get_service
    items = get_service().videos().list(part="status,statistics,snippet",
                                        id=vid).execute().get("items", [])
    if not items:
        return {"status": "deleted", "views": 0, "title": ""}
    v = items[0]
    st = v["status"]
    live = st["privacyStatus"] == "public" and not st.get("publishAt")
    return {"status": "live" if live else st["privacyStatus"],
            "publishAt": st.get("publishAt", ""),
            "views": int(v["statistics"].get("viewCount", 0)),
            "title": v["snippet"]["title"]}


def _ig_state(mid: str) -> dict:
    import requests
    tok = os.environ.get("IG_ACCESS_TOKEN", "")
    base = f"https://graph.instagram.com/v21.0/{mid}"
    meta = requests.get(base, params={"fields": "permalink,caption", "access_token": tok},
                        timeout=30).json()
    ins = requests.get(f"{base}/insights",
                       params={"metric": "views,likes,comments,shares",
                               "access_token": tok}, timeout=30).json()
    vals = {m["name"]: m["values"][0]["value"] for m in ins.get("data", [])}
    return {"status": "live", "views": vals.get("views", 0),
            "likes": vals.get("likes", 0), "comments": vals.get("comments", 0),
            "shares": vals.get("shares", 0),
            "title": (meta.get("caption") or "")[:60],
            "url": meta.get("permalink", "")}


def _crossed(old: int, new: int) -> int | None:
    """Highest milestone newly crossed, or None."""
    hits = [m for m in MILESTONES if old < m <= new]
    return max(hits) if hits else None


def check(dry_run: bool = False) -> list[str]:
    """Returns the news items; DMs them unless dry_run."""
    rows, news = _load(), []
    for r in rows:
        try:
            s = _yt_state(r["id"]) if r["kind"] == "yt" else _ig_state(r["id"])
        except Exception as e:
            print(f"  {r['label']}: check failed ({e})")
            continue
        plat = "YouTube" if r["kind"] == "yt" else "Instagram"

        # 1. went live (the event actually worth interrupting for)
        if r.get("lastStatus") and r["lastStatus"] != "live" and s["status"] == "live":
            news.append(f"🟢 **LIVE on {plat}** — {r['label']}\n{s.get('title','')}"
                        + (f"\nhttps://youtube.com/watch?v={r['id']}" if r["kind"] == "yt"
                           else f"\n{s.get('url','')}"))
        elif s["status"] == "deleted" and r.get("lastStatus") != "deleted":
            news.append(f"🔴 {r['label']} was deleted from {plat}.")

        # 2. milestone crossed
        m = _crossed(r.get("lastViews", 0), s["views"])
        if m:
            extra = ""
            if r["kind"] == "ig":
                extra = f" · {s['likes']}♥ {s['comments']}💬 {s['shares']}↗"
            news.append(f"📈 **{m:,} views on {plat}** — {r['label']} "
                        f"(now {s['views']:,}){extra}")

        r["lastStatus"], r["lastViews"] = s["status"], s["views"]
    _save(rows)

    if news and not dry_run:
        sys.path.insert(0, str(ROOT / "scripts"))
        from discord_notify import send_dm
        send_dm("\n\n".join(news))
    return news


def status() -> str:
    out = []
    for r in _load():
        try:
            s = _yt_state(r["id"]) if r["kind"] == "yt" else _ig_state(r["id"])
        except Exception as e:
            out.append(f"  {r['label']}: error {e}")
            continue
        plat = "YouTube" if r["kind"] == "yt" else "Instagram"
        when = f" (releases {s['publishAt'][:16]} UTC)" if s.get("publishAt") else ""
        line = f"  {r['label'][:26]:28} {plat:10} {s['status']:9} {s['views']:>7,} views{when}"
        if r["kind"] == "ig":
            line += f"  {s['likes']}♥ {s['comments']}💬 {s['shares']}↗"
        out.append(line)
    return "\n".join(out) or "  (watchlist empty)"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--add-yt"); ap.add_argument("--add-ig")
    ap.add_argument("--label", default="")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.add_yt:
        print(add("yt", a.add_yt, a.label))
    if a.add_ig:
        print(add("ig", a.add_ig, a.label))
    if a.check:
        n = check(dry_run=a.dry_run)
        print("\n".join(n) if n else "no change")
    if a.status or not any([a.add_yt, a.add_ig, a.check]):
        print(status())

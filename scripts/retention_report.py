"""
scripts/retention_report.py
Pulls average-percentage-viewed per video from the YouTube Analytics API.

Why this matters more than view counts: with 900 views and 0 subscribers there
are two possible problems, and they need opposite fixes.

  * LOW retention (<~40%) -- people scroll before the payoff. They never reach
    the end card, never hear the share ask, never see the verdict question. That
    single fact would explain zero comments, near-zero shares AND zero
    subscribers at once. The fix is the hook and the first three seconds.
  * HIGH retention (>~70%) -- they watch the whole thing and still don't
    convert. The fix is the ask, the profile and the reason to follow.

Guessing between those wastes weeks, hence this.

Needs the yt-analytics.readonly scope (see youtube_upload.SCOPES). If the token
predates that scope, re-auth once:  python add_channel.py parkourflux

    python scripts/retention_report.py            # top 10 by views
    python scripts/retention_report.py --all
"""

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _services():
    from googleapiclient.discovery import build
    from youtube_upload import load_credentials

    # load_credentials refreshes with the token's OWN scopes -- see the note
    # there on why handing it the wider SCOPES list breaks the refresh.
    creds = load_credentials(str(ROOT / "token.json"))
    have = set(getattr(creds, "scopes", None) or [])
    if not any("yt-analytics" in s for s in have):
        raise SystemExit(
            "This token has no analytics scope, so retention can't be read.\n"
            "Re-auth once on a machine with a browser:\n"
            "    python add_channel.py parkourflux\n"
            "(youtube_upload.SCOPES already requests it.)\n\n"
            "Or read it by hand: YouTube Studio -> a video -> Analytics ->\n"
            "'Average percentage viewed'.")
    if not creds.valid:
        raise SystemExit("Token invalid -- run: python add_channel.py parkourflux")
    return (build("youtube", "v3", credentials=creds),
            build("youtubeAnalytics", "v2", credentials=creds))


def run(limit: int = 10):
    yt, ya = _services()

    ch = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]
    pl = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, tok = [], None
    while True:
        r = yt.playlistItems().list(part="snippet", playlistId=pl,
                                    maxResults=50, pageToken=tok).execute()
        ids += [i["snippet"]["resourceId"]["videoId"] for i in r["items"]]
        tok = r.get("nextPageToken")
        if not tok:
            break

    meta = {}
    for i in range(0, len(ids), 50):
        for v in yt.videos().list(part="snippet,statistics,status",
                                  id=",".join(ids[i:i + 50])).execute()["items"]:
            if v["status"].get("publishAt"):        # not released yet
                continue
            meta[v["id"]] = (v["snippet"]["title"],
                             int(v["statistics"].get("viewCount", 0)))

    top = sorted(meta.items(), key=lambda kv: -kv[1][1])[:limit]
    start = (date.today() - timedelta(days=365)).isoformat()
    end = date.today().isoformat()

    print(f"{'views':>6}  {'avg%':>5}  {'avg sec':>7}  title")
    print("-" * 78)
    rows = []
    for vid, (title, views) in top:
        try:
            r = ya.reports().query(
                ids="channel==MINE", startDate=start, endDate=end,
                metrics="averageViewPercentage,averageViewDuration",
                filters=f"video=={vid}").execute()
            got = r.get("rows") or [[0, 0]]
            pct, dur = got[0][0], got[0][1]
        except Exception as e:
            print(f"{views:>6}  {'err':>5}          {title[:40]}  ({str(e)[:40]})")
            continue
        rows.append(pct)
        print(f"{views:>6}  {pct:>5.1f}  {dur:>7.0f}  {title[:44]}")

    if rows:
        avg = sum(rows) / len(rows)
        print("-" * 78)
        print(f"  average retention across these: {avg:.1f}%")
        print()
        if avg < 40:
            print("  READ: retention is LOW. Viewers leave before the payoff, so")
            print("  they never see the end card or hear the CTA. Fix the HOOK and")
            print("  the first 3 seconds -- not the ask, not the profile.")
        elif avg < 70:
            print("  READ: retention is MIDDLING. Some drop-off, but many do reach")
            print("  the end. Worth improving hooks AND the follow ask/profile.")
        else:
            print("  READ: retention is HIGH -- people watch the whole thing and")
            print("  still don't convert. The content works; the ASK and the")
            print("  PROFILE are the problem. Fix those, not the stories.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    run(999 if a.all else 10)

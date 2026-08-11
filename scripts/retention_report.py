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
# Which channel's analytics. Overridden by --account; the default keeps the
# bare CLI reading the first account exactly as before.
TOKEN = ROOT / "token.json"
ACCOUNT_ID = ""          # set by use_account; names the channel in error text


def use_account(acc_id: str = "") -> str:
    """Point this module at ONE channel's OAuth token. Returns its name."""
    global TOKEN, ACCOUNT_ID
    import sys as _sys
    _sys.path.insert(0, str(ROOT))
    from accounts import all_accounts, get_account, paths
    acc = get_account(acc_id) if acc_id else all_accounts()[0]
    TOKEN = paths(acc)["yt_token"]
    ACCOUNT_ID = acc.id
    return acc.name
sys.path.insert(0, str(ROOT))


def _services():
    from googleapiclient.discovery import build
    from youtube_upload import load_credentials

    # load_credentials refreshes with the token's OWN scopes -- see the note
    # there on why handing it the wider SCOPES list breaks the refresh.
    creds = load_credentials(str(TOKEN))
    have = set(getattr(creds, "scopes", None) or [])
    if not any("yt-analytics" in s for s in have):
        raise SystemExit(
            "This token has no analytics scope, so retention can't be read.\n"
            "Re-auth once on a machine with a browser:\n"
            f"    python add_channel.py {ACCOUNT_ID or 'parkourflux'}\n"
            "(youtube_upload.SCOPES already requests it.)\n\n"
            "Or read it by hand: YouTube Studio -> a video -> Analytics ->\n"
            "'Average percentage viewed'.")
    if not creds.valid:
        raise SystemExit("Token invalid -- run: python add_channel.py "
                         f"{ACCOUNT_ID or 'parkourflux'}")
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

    def _secs(iso: str) -> int:
        """PT1M4S -> 64. Needed to tell a loop from real watch time."""
        import re
        m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
        if not m:
            return 0
        h, mi, s = (int(g or 0) for g in m.groups())
        return h * 3600 + mi * 60 + s

    meta = {}
    for i in range(0, len(ids), 50):
        for v in yt.videos().list(part="snippet,statistics,status,contentDetails",
                                  id=",".join(ids[i:i + 50])).execute()["items"]:
            if v["status"].get("publishAt"):        # not released yet
                continue
            meta[v["id"]] = (v["snippet"]["title"],
                             int(v["statistics"].get("viewCount", 0)),
                             _secs(v.get("contentDetails", {}).get("duration", "")))

    top = sorted(meta.items(), key=lambda kv: -kv[1][1])[:limit]
    start = (date.today() - timedelta(days=365)).isoformat()
    end = date.today().isoformat()

    # Shorts LOOP, and YouTube counts the replays in averageViewDuration. So
    # averageViewPercentage routinely exceeds 100% and is not "what fraction of
    # the video they saw" -- a 29s Short came back at 247.8% (71s watched), and
    # a 64s one at 2807% (1796s). Reading those as retention, and taking a plain
    # mean across videos, produced "average retention 325.9%" and the advice to
    # stop worrying about hooks. Both wrong.
    #
    # So: separate the two questions. Below 100% means they did not finish one
    # pass -- that is the hook question. Above 100% means looping, which is a
    # good sign but says nothing about drop-off, and is excluded from the
    # first-pass average rather than allowed to dominate it.
    #
    # And weight by views. An 11-view video is noise; it should not outvote a
    # 354-view one.
    print(f"{'views':>6}  {'avg%':>7}  {'avg sec':>7}  {'len':>5}  title")
    print("-" * 78)
    unfinished, looped, nodata = [], [], []
    for vid, (title, views, seconds) in top:
        try:
            r = ya.reports().query(
                ids="channel==MINE", startDate=start, endDate=end,
                metrics="averageViewPercentage,averageViewDuration",
                filters=f"video=={vid}").execute()
            got = r.get("rows") or []
        except Exception as e:
            print(f"{views:>6}  {'err':>7}          {title[:40]}  ({str(e)[:40]})")
            continue
        # NO ROWS IS NOT ZERO. Analytics lags 24-72h, so a video posted
        # yesterday reports nothing at all. Defaulting that to 0% put it in the
        # average as a total drop-off: the car channel's four videos came back
        # "0.0% retention" and the report advised rewriting the hooks, when in
        # fact not one of them was old enough to have data. Missing and awful
        # must not look the same -- that is the same mistake as averaging
        # loopers, in the other direction.
        if not got or got[0][0] is None:
            nodata.append((title, views))
            print(f"{views:>6}  {'n/a':>7}  {'':>7}  {seconds:>4}s  {title[:40]}"
                  f"  (too new -- analytics lag)")
            continue
        pct, dur = got[0][0], got[0][1]
        mark = "  LOOP" if pct > 100 else ""
        (looped if pct > 100 else unfinished).append((pct, views))
        print(f"{views:>6}  {pct:>7.1f}  {dur:>7.0f}  {seconds:>4}s  {title[:40]}{mark}")

    print("-" * 78)
    if looped:
        lv = sum(v for _, v in looped)
        print(f"  {len(looped)} video(s) averaged OVER 100% -- viewers looped them "
              f"({lv} views). Good, but it says nothing about drop-off, so they are\n"
              f"  excluded from the figure below.")
    if nodata:
        nv = sum(v for _, v in nodata)
        print(f"  {len(nodata)} video(s) have no analytics yet ({nv} views) -- "
              f"YouTube reports 24-72h late. Excluded, not counted as 0%.")
    if not unfinished:
        if nodata and not looped:
            # Say nothing rather than something wrong: with no measured video
            # there is no retention figure and no verdict to give.
            print("  No retention data yet -- nothing to read. Check back in a "
                  "day or two.")
        else:
            print("  No video averaged under 100%: nothing dropped off before "
                  "finishing.")
        return
    tv = sum(v for _, v in unfinished) or 1
    avg = sum(p * v for p, v in unfinished) / tv
    print(f"  view-weighted first-pass retention: {avg:.1f}%  "
          f"({len(unfinished)} video(s), {tv} views)")
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
    ap.add_argument("--account", default="", help="channel id (default: the first)")
    a = ap.parse_args()
    print(f"channel: {use_account(a.account)}")
    print()
    run(999 if a.all else 10)

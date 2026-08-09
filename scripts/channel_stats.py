"""
scripts/channel_stats.py
Fetches live view/like/comment counts for every video on EVERY configured
channel and writes each account's numbers to <out_dir>/channel_stats.json.

ParkourFlux's out_dir is "output", so its file stays exactly where it was and
everything already reading output/channel_stats.json is unaffected. A second
channel lands in output/<id>/channel_stats.json.

Disabled accounts are included on purpose: carveteran is disabled (so the
autoposter leaves it alone) but it is live and publishing, so its stats matter.

Usage:
    python scripts/channel_stats.py
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from set_privacy import get_service  # reuses the force-ssl token

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def fetch_stats(token_file: str | None = None) -> dict | None:
    yt = get_service(token_file)
    if yt is None:
        return None
    ch = yt.channels().list(part="contentDetails,snippet,statistics", mine=True).execute()
    item = ch["items"][0]
    uploads_pl = item["contentDetails"]["relatedPlaylists"]["uploads"]

    videos = []
    page_token = None
    while True:
        pl = yt.playlistItems().list(part="snippet", playlistId=uploads_pl,
                                     maxResults=50, pageToken=page_token).execute()
        ids = [i["snippet"]["resourceId"]["videoId"] for i in pl["items"]]
        if ids:
            for v in yt.videos().list(part="snippet,statistics,status",
                                      id=",".join(ids)).execute()["items"]:
                s = v["statistics"]
                st = v.get("status", {})
                videos.append({
                    "videoId": v["id"],
                    "title": v["snippet"]["title"],
                    "publishedAt": v["snippet"].get("publishedAt", ""),
                    # privacy + publishAt let the dashboard separate what is
                    # actually LIVE from what is merely uploaded and waiting
                    # to auto-release.
                    "privacy": st.get("privacyStatus", "public"),
                    "publishAt": st.get("publishAt", ""),
                    "views": int(s.get("viewCount", 0)),
                    "likes": int(s.get("likeCount", 0)),
                    "comments": int(s.get("commentCount", 0)),
                })
        page_token = pl.get("nextPageToken")
        if not page_token:
            break

    return {
        "fetchedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "channel": item["snippet"]["title"],
        "subscribers": int(item["statistics"].get("subscriberCount", 0)),
        "totalViews": int(item["statistics"].get("viewCount", 0)),
        "videos": videos,
    }


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    import config  # noqa: F401  -- loads .env
    from accounts import all_accounts

    ROOT = Path(__file__).resolve().parent.parent
    for acc in all_accounts():
        token = ROOT / acc.yt_token
        stats = fetch_stats(str(token)) if token.exists() else None
        if stats is None:
            print(f"[{acc.id}] no usable YouTube token ({acc.yt_token}) -- skipped")
            continue
        out = ROOT / acc.out_dir / "channel_stats.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(stats, indent=2))
        print(f"[{acc.id}] {stats['channel']}: {stats['subscribers']} subs, "
              f"{stats['totalViews']} total views, {len(stats['videos'])} videos "
              f"-> {out.relative_to(ROOT)}")

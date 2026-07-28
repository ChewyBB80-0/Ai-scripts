"""
scripts/channel_stats.py
Fetches live view/like/comment counts for every video on the channel and
writes output/channel_stats.json. Drop that file onto the ops dashboard to
refresh its numbers.

Usage:
    python scripts/channel_stats.py
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from set_privacy import get_service  # reuses the force-ssl token


def fetch_stats() -> dict:
    yt = get_service()
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
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    stats = fetch_stats()
    out = Path(__file__).parent.parent / "output" / "channel_stats.json"
    out.write_text(json.dumps(stats, indent=2))
    print(f"{stats['channel']}: {stats['subscribers']} subs, {stats['totalViews']} total views")
    for v in stats["videos"]:
        print(f"  {v['videoId']}  {v['views']:>6} views  {v['likes']:>4} likes  {v['title'][:50]}")
    print(f"Written -> {out}")

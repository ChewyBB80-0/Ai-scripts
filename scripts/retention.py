"""
scripts/retention.py
Pulls YouTube Analytics retention data (what Studio shows) for our videos:
per-video views / average view duration / average percentage viewed, plus
the audience-retention curve for one video.

Needs the yt-analytics.readonly scope -> its own token file (first run opens
a browser for consent).

Usage:
    python scripts/retention.py --video 4WOtYo1LFQI
"""

import argparse
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/youtube.readonly",
]
CLIENT_SECRETS_FILE = "client_secret.json"
TOKEN_FILE = "token_analytics.json"


def get_services():
    creds = None
    if Path(TOKEN_FILE).exists():
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        Path(TOKEN_FILE).write_text(creds.to_json())
    return build("youtubeAnalytics", "v2", credentials=creds), build("youtube", "v3", credentials=creds)


def main(video_id: str, start: str, end: str):
    ya, yt = get_services()

    ch = yt.channels().list(part="contentDetails", mine=True).execute()
    uploads_pl = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    pl = yt.playlistItems().list(part="snippet", playlistId=uploads_pl, maxResults=50).execute()
    ids = [i["snippet"]["resourceId"]["videoId"] for i in pl["items"]]

    print("== Per-video (Studio 'engagement' numbers) ==")
    r = ya.reports().query(
        ids="channel==MINE", startDate=start, endDate=end,
        metrics="views,averageViewDuration,averageViewPercentage",
        dimensions="video", filters=f"video=={','.join(ids)}",
    ).execute()
    rows = r.get("rows") or []
    if not rows:
        print("  (analytics has no rows yet -- too few views / data lag)")
    for row in rows:
        vid, views, avg_dur, avg_pct = row
        print(f"  {vid}  views={views}  avgViewDuration={avg_dur:.0f}s  avgViewed={avg_pct:.1f}%")

    print(f"\n== Retention curve for {video_id} (Studio's audience retention graph) ==")
    r = ya.reports().query(
        ids="channel==MINE", startDate=start, endDate=end,
        metrics="audienceWatchRatio",
        dimensions="elapsedVideoTimeRatio", filters=f"video=={video_id}",
    ).execute()
    rows = r.get("rows") or []
    if not rows:
        print("  (no retention curve yet -- YouTube withholds it until enough views)")
    for ratio, watch in rows:
        bar = "#" * int(watch * 40)
        print(f"  {float(ratio)*100:5.1f}% in  {watch*100:5.1f}% watching  {bar}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--start", default="2026-07-14")
    ap.add_argument("--end", default="2026-07-17")
    args = ap.parse_args()
    main(args.video, args.start, args.end)

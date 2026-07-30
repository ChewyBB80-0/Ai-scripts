"""
youtube_upload.py
Uploads a finished video to YouTube via the Data API v3 (Python 3,
current library versions -- not the outdated python2-era sample from
youtube/api-samples).

Setup (one-time):
  1. Follow the Google Cloud Console steps to get client_secret.json
     (Enable YouTube Data API v3, create OAuth Client ID, type "Desktop app").
  2. Put client_secret.json in this project's root. It's already .gitignored
     -- never commit it.
  3. First run opens a browser for you to authorize the channel's Google
     account. After that, token.json is saved and reused automatically.

Usage:
    from youtube_upload import upload_video
    upload_video("output/pending_review/my_video.mp4",
                  title="Wait for the ending...",
                  description="#shorts #redditstories #storytime #fyp",
                  tags=["shorts", "story", "minecraft"])
"""

import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

# youtube.upload = post videos; youtube.force-ssl = read/reply to comments
# (needed by comment_replies.py). Re-auth (add_channel.py) after adding the
# second scope so the token is granted both. Uploads keep working meanwhile.
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    # Read-only analytics: retention, traffic sources, audience. The Data API
    # gives view counts but NOT average-percentage-viewed, and retention is the
    # number that separates "nobody sees it" from "they see it and don't
    # convert" -- the two need opposite fixes. Adding it needs one re-auth
    # (add_channel.py parkourflux) on a machine with a browser.
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
CLIENT_SECRETS_FILE = "client_secret.json"
TOKEN_FILE = "token.json"


def get_authenticated_service(token_file: str = TOKEN_FILE):
    creds = None
    if Path(token_file).exists():
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not Path(CLIENT_SECRETS_FILE).exists():
                raise FileNotFoundError(
                    f"{CLIENT_SECRETS_FILE} not found. Download it from the "
                    "Google Cloud Console (Credentials -> your OAuth Client ID)."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)  # opens a browser for one-time auth

        Path(token_file).write_text(creds.to_json())

    return build("youtube", "v3", credentials=creds)


def upload_video(
    file_path: str,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    category_id: str = "24",       # 24 = Entertainment. See categories doc for others.
    privacy_status: str = "private",  # "private" | "unlisted" | "public"
    made_for_kids: bool = False,
    token_file: str = TOKEN_FILE,   # per-account OAuth token (multi-channel)
    publish_at: str | None = None,  # RFC3339 UTC, e.g. "2026-07-21T13:30:00Z"
) -> str:
    """Uploads a video and returns its YouTube video ID.
    publish_at: schedule a future auto-release. YouTube requires the video to be
    private for this -- it flips to public automatically at that timestamp."""
    youtube = get_authenticated_service(token_file)

    status = {
        "privacyStatus": "private" if publish_at else privacy_status,
        "selfDeclaredMadeForKids": made_for_kids,
    }
    if publish_at:
        status["publishAt"] = publish_at

    body = {
        "snippet": {
            "title": title[:100],           # YouTube title limit
            "description": description[:5000],
            "tags": tags or [],
            "categoryId": category_id,
        },
        "status": status,
    }

    media = MediaFileUpload(file_path, chunksize=-1, resumable=True, mimetype="video/mp4")

    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                print(f"Uploading... {int(status.progress() * 100)}%")
        except HttpError as e:
            if e.resp.status in (500, 502, 503, 504):
                print(f"Retriable error, retrying: {e}")
                continue
            raise

    video_id = response["id"]
    print(f"Upload complete: https://youtube.com/watch?v={video_id}")
    return video_id


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--description", default="")
    ap.add_argument("--tags", default="")
    ap.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    args = ap.parse_args()

    upload_video(
        args.file,
        title=args.title,
        description=args.description,
        tags=[t.strip() for t in args.tags.split(",") if t.strip()],
        privacy_status=args.privacy,
    )

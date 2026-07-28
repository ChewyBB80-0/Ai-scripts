"""
scripts/set_privacy.py
One-off helper: change the privacy status of an already-uploaded video.
Needs the broader youtube.force-ssl scope (upload-only token can't edit
existing videos), so it keeps its own token file.

Usage:
    python scripts/set_privacy.py --video-id KmnIcYedXGs --privacy public
"""

import argparse
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
CLIENT_SECRETS_FILE = "client_secret.json"
TOKEN_FILE = "token_manage.json"
# The main upload token now also carries force-ssl (re-authed 2026-07-19), so
# it can edit videos and read stats too. Prefer it: it's the published-app
# token that refreshes durably, whereas token_manage.json was a separate
# Testing-mode token that expired and silently broke the dashboard's YouTube
# stats on 2026-07-24.
MAIN_TOKEN = "token.json"


def _load(path: str):
    creds = Credentials.from_authorized_user_file(path, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds if creds and creds.valid else None


def get_service():
    creds = None
    # 1. the durable main token (has force-ssl); 2. the legacy manage token;
    # 3. only as a last resort, an interactive re-auth (won't work headless).
    for path in (MAIN_TOKEN, TOKEN_FILE):
        if Path(path).exists():
            try:
                creds = _load(path)
            except Exception:
                creds = None
            if creds:
                break
    if not creds:
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
        creds = flow.run_local_server(port=0)
        Path(TOKEN_FILE).write_text(creds.to_json())
    return build("youtube", "v3", credentials=creds)


def set_privacy(video_id: str, privacy: str):
    youtube = get_service()
    # snippet is required alongside status on update, so fetch current first
    current = youtube.videos().list(part="snippet,status", id=video_id).execute()
    if not current["items"]:
        raise SystemExit(f"Video not found: {video_id}")
    item = current["items"][0]
    item["status"]["privacyStatus"] = privacy
    youtube.videos().update(
        part="snippet,status",
        body={"id": video_id, "snippet": item["snippet"], "status": item["status"]},
    ).execute()
    print(f"{video_id} is now {privacy}: https://youtube.com/watch?v={video_id}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--video-id", required=True)
    ap.add_argument("--privacy", required=True, choices=["private", "unlisted", "public"])
    args = ap.parse_args()
    set_privacy(args.video_id, args.privacy)

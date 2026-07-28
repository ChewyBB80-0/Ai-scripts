"""
approve.py
The manual step during REVIEW_MODE: lists videos waiting in
output/pending_review/ and lets you post one once you've watched it.

Usage:
    python3 approve.py
        -> lists everything waiting for review

    python3 approve.py --post the_locker.mp4 --title "Wait for the ending..."
        -> uploads that file and removes it from the pending folder
"""

import argparse
from pathlib import Path

import config
from bot import log_post, todays_upload_count

PENDING_DIR = Path("output/pending_review")


def list_pending():
    files = sorted(PENDING_DIR.glob("*.mp4"))
    if not files:
        print("Nothing waiting for review.")
        return
    print("Pending review:")
    for f in files:
        print(f"  {f.name}")


def post(filename: str, title: str, description: str = "", tags: str = ""):
    from youtube_upload import upload_video

    if todays_upload_count() >= config.YOUTUBE_DAILY_UPLOAD_LIMIT:
        print("Daily upload limit reached -- try again tomorrow.")
        return

    path = PENDING_DIR / filename
    if not path.exists():
        print(f"Not found: {path}")
        return

    video_id = upload_video(
        str(path),
        title=title or filename.rsplit(".", 1)[0].replace("_", " ").title(),
        description=description,
        tags=[t.strip() for t in tags.split(",") if t.strip()] or ["shorts", "story", "minecraft"],
        privacy_status=config.PRIVACY_STATUS,
    )
    log_post(filename, video_id, "posted_manual")
    path.unlink()
    print(f"Posted and removed from pending: {filename}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--post", help="filename in pending_review to post")
    ap.add_argument("--title", default="")
    ap.add_argument("--description", default="")
    ap.add_argument("--tags", default="")
    args = ap.parse_args()

    if args.post:
        post(args.post, args.title, args.description, args.tags)
    else:
        list_pending()

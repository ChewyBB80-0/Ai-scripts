"""
instagram_upload.py
Posts a Reel via the Instagram Graph API: create a media container from a
public video URL, wait for Instagram to process it, then publish.

One-time setup (see README/ops notes):
  1. Instagram account -> Professional (Business or Creator), linked to a
     Facebook Page.
  2. Meta developer app (developers.facebook.com) with instagram_basic +
     instagram_content_publish permissions; generate a long-lived token.
  3. Env vars (setx, so scheduled runs see them):
       IG_USER_ID       the Instagram professional account's IG User ID
       IG_ACCESS_TOKEN  long-lived access token

Usage:
    from instagram_upload import post_reel
    post_reel("https://host/video.mp4", caption="story time #reels")
"""

import os
import time

import requests

# Instagram API with Instagram Login flow (token starts with IGAA...).
GRAPH = "https://graph.instagram.com/v21.0"


def post_reel(video_url: str, caption: str = "", share_to_feed: bool = True,
              timeout_s: int = 300, ig_user: str | None = None,
              token: str | None = None, attempts: int = 2) -> str:
    """Publish a Reel from a public video URL; returns the IG media id.
    ig_user/token override the env vars (multi-account).

    A container that comes back ERROR is retried once. Instagram's media
    processing fails intermittently on files it accepts perfectly well a minute
    later: car_headlight_restoration_vs_replacement failed on 2026-08-12 with a
    plain {'status_code': 'ERROR'}, and the video was ordinary -- 1080x1920
    h264/aac, a LOWER bitrate than the episode that posted fine four hours
    after it.

    Retrying here is safe and worth doing. Safe, because an ERROR container was
    never published, so a new one cannot duplicate anything -- and the caller's
    dedup runs before we are called. Worth doing, because the alternative path
    is a human running `coverage_check --fix` by hand, which is how a car
    episode ended up on the story channel's Instagram.
    """
    ig_user = ig_user or os.environ["IG_USER_ID"]
    token = token or os.environ["IG_ACCESS_TOKEN"]

    container_id = None
    for attempt in range(1, max(1, attempts) + 1):
        # 1. Create the media container -- Instagram fetches the video itself.
        r = requests.post(f"{GRAPH}/{ig_user}/media", data={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "share_to_feed": "true" if share_to_feed else "false",
            "access_token": token,
        })
        r.raise_for_status()
        container_id = r.json()["id"]

        # 2. Poll until Instagram finishes downloading/processing the video.
        deadline = time.time() + timeout_s
        failed = None
        while time.time() < deadline:
            s = requests.get(f"{GRAPH}/{container_id}",
                             # ASK WHY. status_code is only ever FINISHED /
                             # IN_PROGRESS / ERROR; `status` carries the actual
                             # reason. Two failures were investigated blind
                             # because the code discarded it.
                             params={"fields": "status_code,status",
                                     "access_token": token})
            s.raise_for_status()
            status = s.json().get("status_code")
            if status == "FINISHED":
                break
            if status == "ERROR":
                failed = s.json()
                break
            time.sleep(5)
        else:
            # A timeout is NOT retried: the container may still be processing,
            # and creating a second one risks two Reels from one call.
            raise TimeoutError(
                "Instagram container did not finish processing in time.")

        if failed is None:
            break                       # FINISHED -- go publish it
        if attempt >= attempts:
            raise RuntimeError(f"Instagram rejected the container: {failed}")
        print(f"Instagram rejected the container (attempt {attempt}/{attempts}): "
              f"{failed} -- retrying in 30s")
        time.sleep(30)

    # 3. Publish.
    p = requests.post(f"{GRAPH}/{ig_user}/media_publish", data={
        "creation_id": container_id,
        "access_token": token,
    })
    p.raise_for_status()
    media_id = p.json()["id"]
    print(f"Reel published: media id {media_id}")
    return media_id


def post_story(video_url: str, timeout_s: int = 300,
               ig_user: str | None = None, token: str | None = None) -> str:
    """Publish the video to the account's STORY (the 24h ones at the top of the
    app), returning the media id. Same container->poll->publish flow as a Reel,
    just media_type=STORIES. Stories carry no caption/hashtags -- they're a
    cross-promo to existing followers, not a discovery surface.

    Requirements (all already met by this pipeline): a public video URL, 9:16
    vertical, and <= 60s. Videos longer than 60s are skipped rather than risk an
    API rejection mid-run.
    """
    ig_user = ig_user or os.environ["IG_USER_ID"]
    token = token or os.environ["IG_ACCESS_TOKEN"]

    r = requests.post(f"{GRAPH}/{ig_user}/media", data={
        "media_type": "STORIES",
        "video_url": video_url,
        "access_token": token,
    })
    r.raise_for_status()
    container_id = r.json()["id"]

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        s = requests.get(f"{GRAPH}/{container_id}",
                         params={"fields": "status_code", "access_token": token})
        s.raise_for_status()
        status = s.json().get("status_code")
        if status == "FINISHED":
            break
        if status == "ERROR":
            raise RuntimeError(f"Instagram rejected the story container: {s.json()}")
        time.sleep(5)
    else:
        raise TimeoutError("Instagram story container did not finish in time.")

    p = requests.post(f"{GRAPH}/{ig_user}/media_publish", data={
        "creation_id": container_id, "access_token": token,
    })
    p.raise_for_status()
    media_id = p.json()["id"]
    print(f"Story published: media id {media_id}")
    return media_id


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--video-url", required=True, help="Public URL of the mp4")
    ap.add_argument("--caption", default="")
    ap.add_argument("--story", action="store_true", help="post to Story instead of Reel")
    args = ap.parse_args()
    if args.story:
        post_story(args.video_url)
    else:
        post_reel(args.video_url, args.caption)

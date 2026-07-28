"""
video_host.py
Returns a PUBLIC URL for a finished video so Instagram/TikTok can fetch it
(their APIs can't accept a file upload -- they pull from a URL).

Uses Cloudflare R2 (S3-compatible) when the VIDEO_HOST_* env vars are set;
otherwise falls back to litterbox (catbox's throwaway host, 72h TTL) so
cross-posting works before R2 is configured. R2 is the permanent choice.

R2 env vars (set once with setx):
    VIDEO_HOST_ENDPOINT   https://<accountid>.r2.cloudflarestorage.com
    VIDEO_HOST_BUCKET     bucket name
    VIDEO_HOST_KEY_ID     access key id
    VIDEO_HOST_SECRET     secret access key
    VIDEO_HOST_PUBLIC_URL https://pub-xxxx.r2.dev
"""

import os
from pathlib import Path


def upload_public(path: str | Path) -> str:
    if os.environ.get("VIDEO_HOST_ENDPOINT"):
        return _upload_r2(path)
    return _upload_litterbox(path)


def _upload_litterbox(path: str | Path) -> str:
    import requests
    with open(path, "rb") as f:
        r = requests.post(
            "https://litterbox.catbox.moe/resources/internals/api.php",
            data={"reqtype": "fileupload", "time": "72h"},
            files={"fileToUpload": f}, timeout=120)
    r.raise_for_status()
    url = r.text.strip()
    if not url.startswith("http"):
        raise RuntimeError(f"litterbox upload failed: {url[:200]}")
    return url


def _r2_client():
    import boto3
    return boto3.client(
        "s3", endpoint_url=os.environ["VIDEO_HOST_ENDPOINT"],
        aws_access_key_id=os.environ["VIDEO_HOST_KEY_ID"],
        aws_secret_access_key=os.environ["VIDEO_HOST_SECRET"])


def _upload_r2(path: str | Path) -> str:
    key = Path(path).name
    _r2_client().upload_file(str(path), os.environ["VIDEO_HOST_BUCKET"], key,
                             ExtraArgs={"ContentType": "video/mp4"})
    return f"{os.environ['VIDEO_HOST_PUBLIC_URL'].rstrip('/')}/{key}"


def delete_hosted(path: str | Path) -> None:
    """Remove a video from R2 once Instagram has pulled it -- R2 is only a temp
    relay, so deleting keeps storage near-zero (free forever). No-op when R2
    isn't configured (litterbox auto-expires in 72h on its own)."""
    if not os.environ.get("VIDEO_HOST_ENDPOINT"):
        return
    try:
        _r2_client().delete_object(Bucket=os.environ["VIDEO_HOST_BUCKET"],
                                   Key=Path(path).name)
    except Exception as e:
        print(f"R2 cleanup skipped for {Path(path).name}: {e}")

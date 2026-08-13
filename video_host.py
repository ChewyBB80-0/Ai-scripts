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
    url = (_upload_r2(path) if os.environ.get("VIDEO_HOST_ENDPOINT")
           else _upload_litterbox(path))
    _wait_until_fetchable(url)
    return url


def _wait_until_fetchable(url: str, timeout_s: int = 45) -> None:
    """Block until the object actually serves over HTTP.

    upload_file returns as soon as R2 has the object, which is NOT the same as
    the public r2.dev edge serving it. Instagram fetches the URL itself the
    instant we hand it over, so a brand-new key can be handed to Meta before it
    is retrievable -- and Instagram reports that as a bare
    {'status_code': 'ERROR'} with no reason, which looks like a rejected video
    rather than a 404.

    Two car episodes failed that way (2026-08-12, 2026-08-13) and both were
    ordinary files. The second one was re-staged by hand two hours later and
    Instagram accepted it immediately -- the only difference being that the
    manual check did a HEAD first, which is exactly what this does.

    Never raises: if it cannot confirm, we still hand the URL over and let
    Instagram be the judge, so this can only add reliability, not remove it.
    """
    import time
    import requests
    deadline = time.time() + timeout_s
    delay = 1.0
    while time.time() < deadline:
        try:
            r = requests.head(url, timeout=15, allow_redirects=True)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(delay)
        delay = min(delay * 2, 8.0)
    print(f"(warning: {url} not confirmed fetchable after {timeout_s}s -- "
          "handing it over anyway)")


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

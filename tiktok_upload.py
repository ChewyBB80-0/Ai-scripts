"""
tiktok_upload.py
TikTok Content Posting API -- pushes a rendered video to your TikTok DRAFTS
(inbox). You then open the TikTok app and tap Post. Draft/inbox mode works with
the app in Sandbox (your own account) without the full public-post audit.

Env: TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET  (from your TikTok developer app).

One-time authorize:   python tiktok_upload.py auth
Push a video:         python tiktok_upload.py post output/some_video.mp4
Push the newest one:  python tiktok_upload.py post-latest
"""

import json
import os
import time
import urllib.parse
import webbrowser
from pathlib import Path

import requests

REDIRECT_URI = "https://parkourflux-policy.pages.dev/callback"
SCOPES = "user.info.basic,video.upload"
TOKEN_FILE = Path(__file__).parent / "tiktok_token.json"

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
INBOX_INIT = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
# Direct Post (autopost, no manual tap) -- needs the video.publish scope and an
# AUDITED production app. See post_direct() for why it's not live yet.
CREATOR_INFO = "https://open.tiktokapis.com/v2/post/publish/creator_info/query/"
DIRECT_INIT = "https://open.tiktokapis.com/v2/post/publish/video/init/"


def _key():
    return os.environ["TIKTOK_CLIENT_KEY"]


def _secret():
    return os.environ["TIKTOK_CLIENT_SECRET"]


def _save(tok: dict):
    tok["_obtained"] = time.time()
    TOKEN_FILE.write_text(json.dumps(tok, indent=2))


def authorize():
    """One-time: open the auth URL, take the pasted code, save tokens."""
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_key": _key(), "scope": SCOPES, "response_type": "code",
        "redirect_uri": REDIRECT_URI, "state": "parkourflux",
    })
    print("\n1. Open this URL and authorize your TikTok account:\n")
    print(url)
    print("\n2. You'll land on parkourflux-policy.pages.dev/callback -- that page "
          "shows a 'code'. Copy it.\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    code = input("Paste the code here: ").strip()
    # A copied code can arrive URL-encoded (TikTok codes often end with %2A).
    code = urllib.parse.unquote(code)
    r = requests.post(TOKEN_URL, data={
        "client_key": _key(), "client_secret": _secret(), "code": code,
        "grant_type": "authorization_code", "redirect_uri": REDIRECT_URI,
    }, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
    tok = r.json()
    if "access_token" not in tok:
        raise RuntimeError(f"Token exchange failed: {tok}")
    _save(tok)
    print(f"\nAuthorized -- token saved to {TOKEN_FILE.name} "
          f"(open_id {str(tok.get('open_id',''))[:8]}...). You can post now.")


def _refresh(tok: dict) -> dict:
    r = requests.post(TOKEN_URL, data={
        "client_key": _key(), "client_secret": _secret(),
        "grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
    }, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
    new = r.json()
    if "access_token" not in new:
        raise RuntimeError(f"Token refresh failed: {new}")
    _save(new)
    return new


def _access_token() -> str:
    if not TOKEN_FILE.exists():
        raise RuntimeError("Not authorized yet -- run: python tiktok_upload.py auth")
    tok = json.loads(TOKEN_FILE.read_text())
    # access token lasts ~24h; refresh 5 min early using the ~1-year refresh token
    if time.time() > tok.get("_obtained", 0) + tok.get("expires_in", 86400) - 300:
        tok = _refresh(tok)
    return tok["access_token"]


def post_to_drafts(video_path: str | Path) -> str:
    """Upload one video to the TikTok inbox/drafts. Returns the publish_id.
    Uses FILE_UPLOAD (direct byte upload) so it needs no URL-domain verification."""
    video_path = Path(video_path)
    size = video_path.stat().st_size
    at = _access_token()
    # 1. init a single-chunk file upload (our 720p videos are only ~7-8 MB)
    r = requests.post(INBOX_INIT, headers={
        "Authorization": f"Bearer {at}",
        "Content-Type": "application/json; charset=UTF-8",
    }, json={"source_info": {
        "source": "FILE_UPLOAD", "video_size": size,
        "chunk_size": size, "total_chunk_count": 1,
    }}, timeout=30)
    d = r.json()
    if d.get("error", {}).get("code") not in (None, "ok"):
        raise RuntimeError(f"TikTok init failed: {d.get('error')}")
    publish_id = d["data"]["publish_id"]
    upload_url = d["data"]["upload_url"]
    # 2. PUT the raw bytes to the returned upload URL
    with open(video_path, "rb") as f:
        blob = f.read()
    up = requests.put(upload_url, data=blob, headers={
        "Content-Type": "video/mp4",
        "Content-Length": str(size),
        "Content-Range": f"bytes 0-{size - 1}/{size}",
    }, timeout=300)
    up.raise_for_status()
    print(f"Pushed to TikTok drafts (publish_id {publish_id}). "
          f"Open the TikTok app -> Inbox/Notifications to review and Post.")
    return publish_id


def _upload_bytes(upload_url: str, video_path: Path, size: int):
    """PUT the whole file as a single chunk (our 720p videos are only ~7-8 MB)."""
    with open(video_path, "rb") as f:
        blob = f.read()
    up = requests.put(upload_url, data=blob, headers={
        "Content-Type": "video/mp4",
        "Content-Length": str(size),
        "Content-Range": f"bytes 0-{size - 1}/{size}",
    }, timeout=300)
    up.raise_for_status()


def creator_info() -> dict:
    """Query the account's posting options. TikTok REQUIRES this before a Direct
    Post -- it returns the privacy levels the creator is allowed to use, plus
    whether comment/duet/stitch are available. Also the cheapest way to check
    whether the video.publish scope is actually granted."""
    at = _access_token()
    r = requests.post(CREATOR_INFO, headers={
        "Authorization": f"Bearer {at}",
        "Content-Type": "application/json; charset=UTF-8",
    }, timeout=30)
    return r.json()


def post_direct(video_path: str | Path, title: str = "",
                privacy: str = "PUBLIC_TO_EVERYONE") -> str:
    """AUTOPOST: publish straight to the account with no manual tap in the app.

    PARKED ON PURPOSE -- do not wire this into the pipeline.

    The app was rejected once already, so the resubmission deliberately asks
    for the narrowest set of permissions the tool actually uses:
    user.info.basic + video.upload, drafts only. Requesting a permission we do
    not exercise is a common rejection reason on its own, and video.publish
    additionally triggers TikTok's stricter Direct Post audit -- a higher bar
    to clear on a second attempt. /tiktok on the public site states plainly
    that video.publish is NOT requested, so calling this would contradict our
    own submission.

    To switch it on later, in order:
      1. Swap TIKTOK_CLIENT_KEY/SECRET to the PRODUCTION app's keys.
      2. Add `video.publish` to SCOPES above and in the developer portal, then
         re-run `python tiktok_upload.py auth` (a saved token only carries the
         scopes it was granted -- video.upload alone is not enough).
      3. Pass the Direct Post audit, and update the claims on /tiktok to match.
    Then this becomes a drop-in replacement for post_to_drafts().
    """
    # Checked first, before touching the filesystem or the network: the scope
    # is the real blocker, and reporting it as a missing file or a generic
    # TikTok scope error just sends whoever hits it down the wrong path.
    if "video.publish" not in SCOPES:
        raise RuntimeError(
            "post_direct() needs the video.publish scope, which this app "
            "deliberately does not request -- see the docstring. Use "
            "post_to_drafts() and post from the TikTok app.")
    video_path = Path(video_path)
    size = video_path.stat().st_size
    at = _access_token()
    # TikTok's Direct Post UX rules: only offer privacy levels the creator has.
    info = creator_info()
    opts = (info.get("data") or {}).get("privacy_level_options") or []
    if opts and privacy not in opts:
        privacy = "SELF_ONLY" if "SELF_ONLY" in opts else opts[0]
    r = requests.post(DIRECT_INIT, headers={
        "Authorization": f"Bearer {at}",
        "Content-Type": "application/json; charset=UTF-8",
    }, json={
        "post_info": {
            "title": (title or video_path.stem.replace("_", " "))[:2100],
            "privacy_level": privacy,
            "disable_comment": False,   # comments are a ranking signal -- keep on
            "disable_duet": False,
            "disable_stitch": False,
            "video_cover_timestamp_ms": 1000,
        },
        "source_info": {
            "source": "FILE_UPLOAD", "video_size": size,
            "chunk_size": size, "total_chunk_count": 1,
        },
    }, timeout=30)
    d = r.json()
    if d.get("error", {}).get("code") not in (None, "ok"):
        raise RuntimeError(f"TikTok direct-post init failed: {d.get('error')}")
    publish_id = d["data"]["publish_id"]
    _upload_bytes(d["data"]["upload_url"], video_path, size)
    print(f"Direct-posted to TikTok (publish_id {publish_id}, privacy {privacy}).")
    return publish_id


def check_status(publish_id: str) -> dict:
    """Where a given upload ended up (SEND_TO_USER_INBOX / PUBLISH_COMPLETE / FAILED)."""
    at = _access_token()
    r = requests.post(STATUS_URL, headers={
        "Authorization": f"Bearer {at}",
        "Content-Type": "application/json; charset=UTF-8",
    }, json={"publish_id": publish_id}, timeout=30)
    return r.json()


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "auth":
        authorize()
    elif cmd == "post" and len(sys.argv) > 2:
        post_to_drafts(sys.argv[2])
    elif cmd == "post-latest":
        mp4s = sorted(Path("output").glob("*.mp4"), key=lambda p: p.stat().st_mtime)
        if not mp4s:
            print("No rendered videos in output/.")
        else:
            print(f"Newest: {mp4s[-1].name}")
            post_to_drafts(mp4s[-1])
    elif cmd == "direct" and len(sys.argv) > 2:
        post_direct(sys.argv[2])
    elif cmd == "creator-info":
        print(json.dumps(creator_info(), indent=2))
    elif cmd == "status" and len(sys.argv) > 2:
        print(json.dumps(check_status(sys.argv[2]), indent=2))
    else:
        print("usage:\n  python tiktok_upload.py auth"
              "\n  python tiktok_upload.py post <video.mp4>"
              "\n  python tiktok_upload.py post-latest"
              "\n  python tiktok_upload.py status <publish_id>"
              "\n  python tiktok_upload.py creator-info   (checks autopost readiness)"
              "\n  python tiktok_upload.py direct <video.mp4>   (AUTOPOST -- needs audit)")

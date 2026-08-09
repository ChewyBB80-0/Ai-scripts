"""
ig_stats.py
Pulls live Instagram media + insights (views/reach/likes/comments) for EVERY
account with IG credentials and writes each one's numbers to
<out_dir>/ig_stats.json for the dashboard.

ParkourFlux's out_dir is "output", so its file stays where it was and nothing
reading output/ig_stats.json changes. A second channel lands in
output/<id>/ig_stats.json.

Read-only (instagram_basic). Runs on the hourly bot before gen_dashboard.py.
Credentials come from the account, never from the bare env vars: those belong to
ParkourFlux, and a fallback would silently report one channel's numbers under
another channel's name.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

GRAPH = "https://graph.instagram.com"


def _insights(mid: str, token: str) -> dict:
    # "views" is the current reel metric; fall back to "reach" on older media.
    for metrics in ("views,reach,likes,comments,shares", "reach,likes,comments"):
        r = requests.get(f"{GRAPH}/{mid}/insights",
                         params={"metric": metrics, "access_token": token})
        if r.status_code == 200:
            return {v["name"]: v["values"][0]["value"] for v in r.json().get("data", [])}
    return {}


def _profile(token: str) -> dict:
    """Follower count and account type.

    Needed because Instagram's monetisation gates are on FOLLOWERS, not views --
    so a dashboard that only tracked views could not show how close the account
    was to any of them.
    """
    try:
        r = requests.get(f"{GRAPH}/me", params={
            "fields": "username,account_type,followers_count,media_count",
            "access_token": token}, timeout=30)
        return r.json() if r.status_code == 200 else {}
    except Exception:
        return {}


def fetch(token: str) -> dict:
    r = requests.get(f"{GRAPH}/me/media", params={
        "fields": "id,caption,media_type,permalink,timestamp",
        "access_token": token, "limit": 50})
    r.raise_for_status()
    media = []
    for m in r.json().get("data", []):
        ins = _insights(m["id"], token)
        views = ins.get("views", ins.get("reach", 0))
        cap = (m.get("caption") or "").split("\n")[0][:60]
        media.append({
            "id": m["id"], "caption": cap or "(no caption)",
            "permalink": m.get("permalink", ""),
            "type": m.get("media_type", ""),
            "views": views, "likes": ins.get("likes", 0),
            "comments": ins.get("comments", 0),
            "shares": ins.get("shares", 0),
            "timestamp": m.get("timestamp", ""),
        })
    p = _profile(token)
    return {
        "fetchedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "totalViews": sum(m["views"] for m in media),
        "followers": p.get("followers_count", 0),
        "accountType": p.get("account_type", ""),
        "username": p.get("username", ""),
        "media": media,
    }


if __name__ == "__main__":
    import config  # noqa: F401  -- loads .env
    from accounts import all_accounts

    ROOT = Path(__file__).resolve().parent.parent
    for acc in all_accounts():
        if not acc.ig_token:
            print(f"[{acc.id}] no Instagram token -- skipped")
            continue
        try:
            data = fetch(acc.ig_token)
        except Exception as e:
            # Never fatal: one account's expired token must not stop the others,
            # and the dashboard simply shows that channel's last good numbers.
            print(f"[{acc.id}] IG stats fetch failed (non-fatal): {e}")
            continue
        out = ROOT / acc.out_dir / "ig_stats.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, indent=1))
        print(f"[{acc.id}] IG stats -> {out.relative_to(ROOT)}  "
              f"({data['totalViews']} views across {len(data['media'])} posts)")

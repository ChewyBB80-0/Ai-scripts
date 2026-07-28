"""
ig_stats.py
Pulls live Instagram media + insights (views/reach/likes/comments) for the
connected IG account and writes output/ig_stats.json for the dashboard.
Read-only (instagram_basic). Runs on the hourly bot before gen_dashboard.py.

Env: IG_ACCESS_TOKEN, IG_USER_ID (set via setx).
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

GRAPH = "https://graph.instagram.com"
OUT = Path(__file__).parent.parent / "output" / "ig_stats.json"


def _insights(mid: str, token: str) -> dict:
    # "views" is the current reel metric; fall back to "reach" on older media.
    for metrics in ("views,reach,likes,comments,shares", "reach,likes,comments"):
        r = requests.get(f"{GRAPH}/{mid}/insights",
                         params={"metric": metrics, "access_token": token})
        if r.status_code == 200:
            return {v["name"]: v["values"][0]["value"] for v in r.json().get("data", [])}
    return {}


def fetch() -> dict:
    token = os.environ["IG_ACCESS_TOKEN"]
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
    return {
        "fetchedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "totalViews": sum(m["views"] for m in media),
        "media": media,
    }


if __name__ == "__main__":
    try:
        data = fetch()
        OUT.write_text(json.dumps(data, indent=1))
        print(f"IG stats -> {OUT}  ({data['totalViews']} views across {len(data['media'])} posts)")
    except Exception as e:
        print(f"IG stats fetch failed (non-fatal): {e}")

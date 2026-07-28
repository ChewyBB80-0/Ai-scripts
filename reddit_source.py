"""
reddit_source.py  --  Reddit API usage summary (for reviewers)

WHAT THIS DOES: a few times per day, this module makes READ-ONLY requests to
the public "top" listing of a small fixed set of first-person story subreddits
and selects one already-popular public self-post to use as source material for
a short-form video retelling (created off-platform; text is condensed and any
personal information removed).

WHAT IT DOES NOT DO: it never posts, comments, votes, messages, or performs any
write action; it does not bulk-scrape or archive Reddit data (it stores only a
short local list of already-used post IDs to avoid repeats). It is a single,
low-volume client authenticating via application-only OAuth (client-credentials,
read-only) and stays within published rate limits.

Credentials come from environment variables (never hard-coded):
    REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET  (a free Reddit "script" app).
Any failure returns None so the caller falls back to fully self-generated text.
"""

import json
import os
import random
import time
from pathlib import Path

import requests

UA = "ParkourFluxAI/1.0 (automated story sourcing)"
USED_FILE = Path("output/used_reddit_ids.json")

# genre -> subreddits it can pull from (all first-person story subs)
GENRE_SUBS = {
    "aitah": ["AITAH", "AmItheAsshole"],
    "revenge": ["pettyrevenge", "MaliciousCompliance", "ProRevenge"],
    "confession": ["TrueOffMyChest", "tifu", "confession"],
    "creepy": ["nosleep", "LetsNotMeet", "creepyencounters"],
}

_token_cache = {"token": None, "exp": 0.0}


def _token() -> str | None:
    if _token_cache["token"] and time.time() < _token_cache["exp"]:
        return _token_cache["token"]
    cid = os.environ.get("REDDIT_CLIENT_ID")
    secret = os.environ.get("REDDIT_CLIENT_SECRET")
    if not (cid and secret):
        return None
    r = requests.post(
        "https://www.reddit.com/api/v1/access_token",
        auth=(cid, secret),
        data={"grant_type": "client_credentials"},
        headers={"User-Agent": UA}, timeout=20)
    r.raise_for_status()
    j = r.json()
    _token_cache["token"] = j["access_token"]
    _token_cache["exp"] = time.time() + j.get("expires_in", 3600) - 60
    return _token_cache["token"]


def _used() -> set[str]:
    if USED_FILE.exists():
        try:
            return set(json.loads(USED_FILE.read_text()))
        except Exception:
            return set()
    return set()


def mark_used(post_id: str):
    ids = _used()
    ids.add(post_id)
    USED_FILE.parent.mkdir(parents=True, exist_ok=True)
    USED_FILE.write_text(json.dumps(sorted(ids)))


def fetch_top_post(genres=None, time_filter="week", min_score=300) -> dict | None:
    """Return one unused, filtered top post as
    {id, title, text, subreddit, genre, score} -- or None if unavailable.
    Sourcing failures are swallowed so the caller can fall back to AI."""
    try:
        tok = _token()
        if not tok:
            return None
        pool = [(g, s) for g, subs in GENRE_SUBS.items()
                if (not genres or g in genres) for s in subs]
        random.shuffle(pool)
        used = _used()
        headers = {"User-Agent": UA, "Authorization": f"bearer {tok}"}
        for genre, sub in pool:
            try:
                r = requests.get(
                    f"https://oauth.reddit.com/r/{sub}/top",
                    params={"t": time_filter, "limit": 30},
                    headers=headers, timeout=20)
                if r.status_code != 200:
                    continue
                children = r.json().get("data", {}).get("children", [])
            except Exception:
                continue
            for c in children:
                d = c.get("data", {})
                text = d.get("selftext", "") or ""
                if (d.get("id") in used or d.get("over_18") or d.get("stickied")
                        or text in ("[removed]", "[deleted]", "")
                        or not (300 <= len(text) <= 6000)
                        or d.get("score", 0) < min_score):
                    continue
                return {
                    "id": d["id"], "title": d.get("title", ""),
                    "text": text, "subreddit": sub,
                    "genre": genre, "score": d.get("score", 0),
                }
        return None
    except Exception as e:
        print(f"reddit_source failed (falling back to AI): {e}")
        return None


if __name__ == "__main__":
    p = fetch_top_post()
    if p:
        print(f"[r/{p['subreddit']}] score={p['score']} genre={p['genre']}")
        print(p["title"])
        print(p["text"][:300], "...")
    else:
        print("no post (check REDDIT_CLIENT_ID/SECRET env vars)")

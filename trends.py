"""
trends.py
Self-refreshing trend layer. refresh_trends() has Claude research CURRENT
Reels/Shorts caption + hashtag trends via the API's server-side web_search
tool and writes output/trends.json. The caption writer reads that file, so
captions track what's working now instead of a static list.

Auto-refreshes when the file is older than MAX_AGE_DAYS (checked at caption
time by social_caption.ai_caption). Costs pennies per refresh.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

TRENDS_FILE = Path(__file__).parent / "output" / "trends.json"
MAX_AGE_DAYS = 7

_PROMPT = """Research what is working RIGHT NOW (this month) for Instagram Reels and
YouTube Shorts discovery in the Reddit-story / storytime niche. Search for
current guidance on: trending hashtags for storytime/reddit-story reels,
caption styles that drive shares and saves, and any algorithm changes.

Then respond with ONLY this JSON (no other text):
{"tags": {"aitah": ["#...", 3-4 tags], "revenge": [...], "confession": [...],
  "creepy": [...], "broad": [2-3 tags]},
 "keywords": {"aitah": "one keyword-rich SEO line for captions",
  "revenge": "...", "confession": "...", "creepy": "..."},
 "tips": ["3-5 short current best-practice notes for caption writing"]}"""


def load_trends() -> dict | None:
    try:
        return json.loads(TRENDS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def trends_age_days() -> float:
    t = load_trends()
    if not t or "updated" not in t:
        return 9999
    dt = datetime.fromisoformat(t["updated"])
    return (datetime.now(timezone.utc) - dt).total_seconds() / 86400


def refresh_trends() -> dict:
    import anthropic
    client = anthropic.Anthropic()
    r = client.messages.create(
        model="claude-sonnet-5", max_tokens=2000,
        tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 4}],
        messages=[{"role": "user", "content": _PROMPT}],
    )
    # web-search responses interleave several text blocks -- join them and
    # take the outermost JSON object from the combined text.
    text = "\n".join(b.text for b in r.content if getattr(b, "type", "") == "text")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"no JSON in response: {text[:200]}")
    data = json.loads(text[start:end + 1])
    data["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    TRENDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TRENDS_FILE.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return data


def ensure_fresh() -> dict | None:
    """Refresh if stale; never raises (caption flow must not break)."""
    try:
        if trends_age_days() > MAX_AGE_DAYS:
            return refresh_trends()
    except Exception as e:
        print(f"trend refresh failed (using cached/static): {e}")
    return load_trends()


if __name__ == "__main__":
    d = refresh_trends()
    print(json.dumps(d, indent=1)[:800])

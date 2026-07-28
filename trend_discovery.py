"""
trend_discovery.py
Finds what's currently trending to feed into story_bank.generate_story_via_claude()
as a topic hint, so the bot isn't just picking random themes -- it's leaning
into what's actually getting attention right now.

Two independent sources:
  - Google Trends (via pytrends -- unofficial but widely used, free, no key needed)
  - YouTube trending videos (via your existing YouTube API key -- read-only,
    doesn't need the OAuth flow youtube_upload.py uses, just an API key)

Requires real internet access -- won't run inside the build sandbox.
"""

import random


def get_google_trends(region: str = "united_states", max_results: int = 10) -> list[str]:
    """Realtime Google Trends search terms for a region."""
    from pytrends.request import TrendReq

    pytrends = TrendReq(hl="en-US", tz=360)
    df = pytrends.trending_searches(pn=region)
    return df[0].tolist()[:max_results]


def get_youtube_trending(api_key: str, region_code: str = "US", max_results: int = 10) -> list[str]:
    """
    Titles of currently trending YouTube videos. Needs an API key (not the
    OAuth flow) -- create one in the same Google Cloud project: APIs &
    Services -> Credentials -> Create Credentials -> API Key.
    """
    from googleapiclient.discovery import build

    youtube = build("youtube", "v3", developerKey=api_key)
    response = youtube.videos().list(
        part="snippet",
        chart="mostPopular",
        regionCode=region_code,
        maxResults=max_results,
    ).execute()
    return [item["snippet"]["title"] for item in response.get("items", [])]


def suggest_topic_hint(youtube_api_key: str | None = None) -> str:
    """
    Pulls from whatever sources are available and returns one topic/hook
    string to pass as --topic to bot.py / generate_story_via_claude().
    Falls back to "" (no hint -> generic story) if both sources fail --
    never crashes the pipeline over a trend-lookup hiccup.
    """
    candidates: list[str] = []

    try:
        candidates += get_google_trends()
    except Exception as e:
        print(f"Google Trends lookup failed (non-fatal): {e}")

    if youtube_api_key:
        try:
            candidates += get_youtube_trending(youtube_api_key)
        except Exception as e:
            print(f"YouTube trending lookup failed (non-fatal): {e}")

    return random.choice(candidates) if candidates else ""


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--youtube-key", default=None)
    args = ap.parse_args()

    hint = suggest_topic_hint(youtube_api_key=args.youtube_key)
    print(f"Suggested topic hint: {hint or '(none found -- using generic story)'}")

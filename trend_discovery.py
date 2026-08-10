"""
trend_discovery.py
Finds what's currently trending to feed into story_bank.generate_story_via_claude()
as a topic hint, so the bot isn't just picking random themes -- it's leaning
into what's actually getting attention right now.

ONE source: YouTube trending videos, via a YouTube Data API key (read-only, not
the OAuth flow youtube_upload.py uses).

Google Trends was the other source and has been REMOVED. pytrends is an
unofficial client and Google's endpoint now returns 404 for it -- not flaky,
gone. It failed inside a try/except that printed "non-fatal" and returned an
empty string, which bot.py could not tell apart from "no suggestion today". The
result: every video for an unknown stretch was generated with no hint at all,
0 of 6 attributed videos carry one, and nothing ever said so. A silent fallback
made a dead feature invisible.

So this module now reports its own state rather than degrading quietly, and
preflight checks whether a source is configured at all.

Requires real internet access -- won't run inside the build sandbox.
"""


# People & Blogs is where storytelling, vlogs and personal-drama content sit.
# The unfiltered chart is dominated by music, film trailers and esports, which
# have nothing to do with a channel about landlords and in-laws.
STORY_CATEGORY = "22"


def get_youtube_trending(api_key: str, region_code: str = "US", max_results: int = 10,
                         category_id: str | None = STORY_CATEGORY) -> list[str]:
    """
    Titles of currently trending YouTube videos. Needs an API key (not the
    OAuth flow) -- create one in the same Google Cloud project: APIs &
    Services -> Credentials -> Create Credentials -> API Key.
    """
    from googleapiclient.discovery import build

    youtube = build("youtube", "v3", developerKey=api_key)
    kw = dict(part="snippet", chart="mostPopular", regionCode=region_code,
              maxResults=max_results)
    if category_id:
        kw["videoCategoryId"] = category_id
    response = youtube.videos().list(**kw).execute()
    return [item["snippet"]["title"] for item in response.get("items", [])]


def suggest_topic_hint(youtube_api_key: str | None = None) -> str:
    """One trending topic string, or "" if no source is available.

    Returns "" in two very different situations -- no source configured, and a
    source that returned nothing -- so both are PRINTED with which one it was.
    Callers still treat "" as "no hint", but the reason is no longer invisible.
    """
    import random as _r

    if not youtube_api_key:
        print("  (no trend hint: YOUTUBE_API_KEY is not set, so the only "
              "remaining source is switched off -- see preflight)")
        return ""
    try:
        candidates = get_youtube_trending(youtube_api_key)
    except Exception as e:
        print(f"  (no trend hint: YouTube trending lookup failed -- {e})")
        return ""
    if not candidates:
        print("  (no trend hint: YouTube trending returned nothing)")
        return ""
    return _r.choice(candidates)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--youtube-key", default=None)
    args = ap.parse_args()

    hint = suggest_topic_hint(youtube_api_key=args.youtube_key)
    print(f"Suggested topic hint: {hint or '(none found -- using generic story)'}")

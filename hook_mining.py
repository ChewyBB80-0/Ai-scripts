"""
hook_mining.py
Mines PATTERNS from the highest-performing videos in this niche and feeds them
into story generation.

Design rule: this extracts STRUCTURE, never copy. Competitor titles are read,
analysed, and discarded -- what gets saved (and all the story generator ever
sees) is a set of abstract rules like "opens on an unresolved discovery" or
"names a specific dollar amount". Copying a rival's titles would be plagiarism
AND useless: a title only works attached to its own story. Patterns transfer;
wording doesn't.

Why bother: this channel has ~21 videos of signal. The channels it competes
with have millions of views, and their numbers say which hook shapes work right
now. That's a far bigger dataset than we can generate ourselves.

SOURCE NOTE: this uses the YouTube Data API, not a web crawler. Firecrawl was
tried first and returned only page chrome -- YouTube renders its video grid in
JS and is heavily scraping-hardened. The official API returns exact titles and
view counts, costs nothing beyond existing quota, and stays within YouTube's
terms. Firecrawl remains the right tool for sites without an API.

    python hook_mining.py --refresh      # pull + re-derive patterns
    python hook_mining.py --show         # print current patterns
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
PATTERNS_FILE = ROOT / "output" / "hook_patterns.json"
MAX_AGE_DAYS = 7

# Queries covering the niche. Kept tight -- each search costs 100 quota units.
QUERIES = [
    "reddit story aitah",
    "reddit revenge story",
    "reddit scary story",
    "am i the asshole story",
]
LOOKBACK_DAYS = 60          # recent only: hook fashions move fast
PER_QUERY = 15


def _yt():
    sys.path.insert(0, str(ROOT / "scripts"))
    from set_privacy import get_service
    return get_service()


def fetch_top_videos() -> list[dict]:
    """Top-viewed recent shorts in the niche: [{title, views, channel}]."""
    yt = _yt()
    after = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)) \
        .isoformat(timespec="seconds").replace("+00:00", "Z")
    seen, rows = set(), []
    for q in QUERIES:
        try:
            r = yt.search().list(part="snippet", q=q, type="video",
                                 order="viewCount", maxResults=PER_QUERY,
                                 videoDuration="short", publishedAfter=after).execute()
        except Exception as e:
            print(f"  search failed for {q!r}: {e}")
            continue
        ids = [i["id"]["videoId"] for i in r.get("items", []) if i["id"].get("videoId")]
        ids = [i for i in ids if i not in seen]
        seen.update(ids)
        if not ids:
            continue
        for v in yt.videos().list(part="snippet,statistics",
                                  id=",".join(ids)).execute().get("items", []):
            rows.append({
                "title": v["snippet"]["title"],
                "channel": v["snippet"]["channelTitle"],
                "views": int(v["statistics"].get("viewCount", 0)),
            })
    rows.sort(key=lambda r: -r["views"])
    return rows


def derive_patterns(rows: list[dict], api_key: str | None = None) -> dict:
    """Turn the sample into abstract, reusable structure via Claude.

    The prompt forbids returning titles: only transferable rules are persisted,
    so nothing copyrightable from another creator enters our pipeline.
    """
    import anthropic

    if not rows:
        raise RuntimeError("no videos fetched -- check API quota/credentials")
    # high vs low performers within the same sample is the useful contrast
    top = rows[:25]
    low = rows[-15:] if len(rows) > 30 else []
    fmt = lambda rs: "\n".join(f"{r['views']:>10,} | {r['title']}" for r in rs)

    client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
    r = client.messages.create(
        model="claude-sonnet-5", max_tokens=1600, thinking={"type": "disabled"},
        messages=[{"role": "user", "content": f"""Below are recent short-form video
titles from the Reddit-storytime niche with their view counts.

Work out WHY the high-view titles outperform, and express it as reusable structure.

CRITICAL: do NOT return any of these titles, and do not paraphrase a specific
one. I want transferable PATTERNS only -- if a rule can't be applied to a
completely different story, it is too specific. Think about: what is revealed vs
withheld in the first few words, sentence shape and length, use of concrete
numbers or relationships, who the antagonist is, where the tension sits, and
what makes someone stop scrolling.

HIGH PERFORMERS:
{fmt(top)}

{"LOWER PERFORMERS:" + chr(10) + fmt(low) if low else ""}

Return ONLY JSON:
{{"patterns": ["<8-12 abstract structural rules, one sentence each>"],
  "avoid": ["<3-5 things weaker titles do>"],
  "observed": "<2-3 sentences on what separates high from low>"}}"""}],
    )
    text = next(b.text for b in r.content if b.type == "text").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    data = json.loads(text)
    data["refreshedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data["sampleSize"] = len(rows)
    data["topViews"] = rows[0]["views"] if rows else 0
    return data


def refresh() -> dict:
    print(f"Fetching top niche videos ({len(QUERIES)} queries, last {LOOKBACK_DAYS}d)...")
    rows = fetch_top_videos()
    print(f"  {len(rows)} videos, top = {rows[0]['views']:,} views" if rows else "  none")
    data = derive_patterns(rows)
    PATTERNS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PATTERNS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Derived {len(data.get('patterns', []))} patterns -> {PATTERNS_FILE.name}")
    return data


def load_patterns() -> dict:
    """Current patterns, or {} if never mined. Never raises, so story
    generation is unaffected when this was never set up."""
    try:
        return json.loads(PATTERNS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def is_stale() -> bool:
    d = load_patterns()
    if not d:
        return True
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(d["refreshedAt"])
        return age > timedelta(days=MAX_AGE_DAYS)
    except Exception:
        return True


def prompt_block() -> str:
    """The block story_bank injects. Empty when unavailable, so generation
    behaves exactly as before if mining was never run."""
    d = load_patterns()
    pats = d.get("patterns") or []
    if not pats:
        return ""
    out = ("\nWHAT IS CURRENTLY WORKING IN THIS NICHE (derived from the "
           "highest-performing recent videos on other channels -- these are "
           "structural patterns; apply them to an ORIGINAL story, never copy "
           "anyone's wording):\n")
    out += "".join(f"  - {p}\n" for p in pats[:12])
    if d.get("avoid"):
        out += "Patterns that UNDERperform -- avoid:\n"
        out += "".join(f"  - {a}\n" for a in d["avoid"][:5])
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--weekly", action="store_true",
                    help="refresh only if the patterns are older than "
                         f"{MAX_AGE_DAYS} days; never fails the run")
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()
    if a.weekly:
        # Called every hour by run_all.py, so it must be cheap and silent most
        # of the time, and must never break the pipeline if the API is down.
        if not is_stale():
            d = load_patterns()
            print(f"hook patterns still fresh (refreshed {d.get('refreshedAt','?')})")
            sys.exit(0)
        try:
            refresh()
        except Exception as e:
            print(f"hook mining skipped (non-fatal): {e}")
        sys.exit(0)
    if a.refresh:
        refresh()
    d = load_patterns()
    if a.show or not a.refresh:
        if not d:
            print("No patterns yet -- run: python hook_mining.py --refresh")
        else:
            print(f"refreshed {d.get('refreshedAt')}  "
                  f"(sample {d.get('sampleSize')}, top {d.get('topViews',0):,} views)")
            print(f"\n{d.get('observed','')}\n")
            for p in d.get("patterns", []):
                print(f"  - {p}")
            if d.get("avoid"):
                print("\n  AVOID:")
                for x in d["avoid"]:
                    print(f"  - {x}")

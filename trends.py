"""
trends.py
Self-refreshing trend layer. refresh_trends() has Claude research what is
currently working on Reels/Shorts via the API's server-side web_search tool and
writes output/trends.json.

TWO consumers, deliberately separated (issue #7, Gap 3):
  - `tags` / `keywords` / `tips`  -> social_caption.ai_caption  (captions)
  - `format`                      -> story_bank                 (how stories
                                                                 are written)

The prompt always asked for "any algorithm changes", but the schema had nowhere
to put them, so every format finding was researched and then dropped at parse
time. The caption keys are unchanged, so captions behave exactly as before.

Auto-refreshes when the file is older than MAX_AGE_DAYS (checked at caption
time by social_caption.ai_caption). Costs pennies per refresh.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

# Loads .env. This module is normally imported by social_caption, which runs
# after config is already loaded -- so the missing key only showed up running
# `python trends.py` by hand, where it failed with an authentication error that
# pointed at the SDK rather than at an unloaded environment.
import config  # noqa: F401

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
 "tips": ["3-5 short current best-practice notes for caption writing"],
 "format": {
   "broad": {"hook": ["2-3 notes"], "pacing": ["2-3 notes"],
             "algorithm": ["2-3 notes on what the platforms currently favour"]},
   "aitah": {"hook": ["1-2 notes SPECIFIC to moral-dilemma stories"],
             "pacing": ["1-2 notes"]},
   "revenge": {"hook": ["1-2 notes SPECIFIC to payback stories"],
               "pacing": ["1-2 notes"]},
   "confession": {"hook": ["1-2 notes SPECIFIC to confessions"],
                  "pacing": ["1-2 notes"]},
   "creepy": {"hook": ["1-2 notes SPECIFIC to unsettling stories"],
              "pacing": ["1-2 notes"]}}}

For "format", report only things a WRITER can act on -- how a story opens, how
tension is paced, what makes someone stay. Do NOT give advice about video
length, posting frequency, resolution or editing software: those are set
elsewhere in this pipeline and are not yours to change.

The genres want DIFFERENT things and the per-genre notes must reflect that, not
restate the broad ones: a revenge story earns attention by promising a payoff,
a creepy one by withholding; a confession opens on the admission, a moral
dilemma on the accusation. Put anything that applies to all four in "broad"
and keep the genre entries genuinely specific."""


def load_trends() -> dict | None:
    try:
        return json.loads(TRENDS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def format_notes(genre: str | None = None) -> dict:
    """The format half of the research, merged for one genre.

    Genres do not want the same things -- a revenge story earns attention by
    promising a payoff, a creepy one by withholding it -- so the research is
    scoped the same way `tags` already is, with `broad` for what applies to all
    of them (issue #7, Gap 4).

    Returns {} when absent: a trends.json written before this key existed must
    not change how stories are written until the next refresh populates it.
    Also accepts the earlier FLAT shape ({hook, pacing, algorithm}) so the file
    written between Gap 3 and Gap 4 keeps working instead of silently going
    quiet.
    """
    t = load_trends() or {}
    f = t.get("format")
    if not isinstance(f, dict):
        return {}
    # flat = the pre-per-genre shape; treat the whole thing as broad
    if any(isinstance(v, list) for v in f.values()):
        return f
    out = dict(f.get("broad") or {})
    for k, v in (f.get(genre) or {}).items() if genre else []:
        out[k] = list(out.get(k, [])) + list(v or [])
    return out


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

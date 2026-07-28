"""
rethumb.py
Applies the branded thumbnail to existing uploads, so the channel page reads as
one coherent series instead of 22 unrelated video stills.

Two things worth knowing before using this:

  * On SHORTS a custom thumbnail does NOT appear in the vertical swipe feed --
    YouTube always shows a frame there. It shows in search, the channel grid,
    subscriptions and suggested. So this is a channel-identity change (which is
    the subscriber lever), not a Shorts-performance change.

  * Replacing the thumbnail on a video that is ALREADY performing resets the
    click-through signal YouTube has learned for it. Top performers are skipped
    by default for that reason -- override with --include-top only deliberately.

    python rethumb.py --dry-run        # preview what would change
    python rethumb.py                  # apply (skips top performers)
    python rethumb.py --min-views 50   # change the protection threshold
"""

import argparse
import re
import sys
from pathlib import Path

import thumbnail

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "scripts"))

# Videos at or above this view count keep their existing thumbnail.
PROTECT_ABOVE_VIEWS = 100
QUOTA_PER_SET = 50          # thumbnails.set costs ~50 units of the 10k/day


def _theme_of(title: str) -> str | None:
    """Theme for the accent colour. Creepy is checked FIRST: its cues overlap
    other themes' keywords ("night shift" contains "shift", a work word), and a
    horror story wearing the work accent is the more wrong of the two."""
    import compilation
    t = title.lower()
    if any(k in t for k in compilation.THEMES["creepy"][0]):
        return "creepy"
    return compilation.theme_of({"title": title, "base": ""})


# Words a phrase must never END on -- truncating after one leaves the thumbnail
# reading as an unfinished sentence ("...TO THE CITY OVER").
_DANGLING = {
    "a", "an", "the", "and", "or", "but", "so", "to", "of", "in", "on", "at",
    "for", "with", "from", "by", "over", "under", "about", "into", "my", "his",
    "her", "their", "our", "your", "its", "that", "this", "these", "those",
    "is", "was", "were", "are", "be", "been", "as", "than", "then", "when",
    "while", "after", "before", "because", "if", "i", "we", "he", "she", "they",
}


def _phrase(title: str, use_ai: bool = True) -> str:
    """Thumbnail text: a Claude-written hook when enabled (cached, so it's paid
    once per title), otherwise the mechanical truncation below."""
    if use_ai:
        return thumbnail.hook_phrase(title)
    return _short_text(title)


def _short_text(title: str, max_words: int = 8) -> str:
    """A punchy thumbnail phrase from the video title.

    Titles run long ("My HOA president fined me $500 for 'excessive jumping' on
    my own property"); a thumbnail needs a few words legible at 200px wide.
    Truncation walks back off dangling words so the phrase never ends mid-
    thought, which reads as broken rather than as a teaser.
    """
    t = re.sub(r"\s*\(P(?:ar)?t\s*\d+\)\s*$", "", title, flags=re.I).strip()
    # cut at the first natural break if one comes early enough to still be punchy
    for sep in (r"\s+[-—]\s+", r"\s*\.\.\.", r"(?<=[a-z])[?!]", r",\s+(?:and|so|but)\s"):
        head = re.split(sep, t)[0].strip(" .,")
        if 3 <= len(head.split()) <= max_words:
            t = head
            break
    words = t.strip(" .,").split()
    if len(words) > max_words:
        words = words[:max_words]
    # walk back off any trailing connector/article
    while len(words) > 3 and words[-1].lower().strip(".,'\"") in _DANGLING:
        words.pop()
    return " ".join(words).strip(" .,")


def run(dry_run: bool = False, include_top: bool = False,
        min_views: int = PROTECT_ABOVE_VIEWS) -> None:
    from set_privacy import get_service
    yt = get_service()
    ch = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]
    pl = ch["contentDetails"]["relatedPlaylists"]["uploads"]

    ids, tok = [], None
    while True:
        r = yt.playlistItems().list(part="snippet", playlistId=pl,
                                    maxResults=50, pageToken=tok).execute()
        ids += [i["snippet"]["resourceId"]["videoId"] for i in r["items"]]
        tok = r.get("nextPageToken")
        if not tok:
            break

    vids = []
    for i in range(0, len(ids), 50):
        vids += yt.videos().list(part="snippet,statistics,contentDetails",
                                 id=",".join(ids[i:i + 50])).execute()["items"]

    todo, skipped = [], []
    for v in vids:
        views = int(v["statistics"].get("viewCount", 0))
        title = v["snippet"]["title"]
        # Long-form compilations already get a purpose-built thumbnail (with a
        # story-count subtitle) at upload time -- don't overwrite it here.
        dur = v["contentDetails"]["duration"]
        if "H" in dur or re.search(r"PT(\d+)M", dur) and \
                int(re.search(r"PT(\d+)M", dur).group(1)) >= 4:
            skipped.append((views, f"{title[:44]} [long-form, has its own]"))
            continue
        if views >= min_views and not include_top:
            skipped.append((views, title))
            continue
        todo.append((v["id"], title, views))

    print(f"{len(vids)} videos on the channel")
    if skipped:
        print(f"\nPROTECTED ({len(skipped)}) -- already performing, "
              f"keeping their thumbnails:")
        for vw, t in sorted(skipped, reverse=True):
            print(f"  {vw:>5} views  {t[:58]}")
    print(f"\nWILL RE-THUMBNAIL ({len(todo)}), ~{len(todo)*QUOTA_PER_SET} quota units:")
    for _vid, t, vw in todo[:40]:
        theme = _theme_of(t)
        print(f"  {vw:>5} views  [{theme or 'default':8}] {_short_text(t)[:52]}")
    if dry_run:
        print("\n(dry run -- nothing changed)")
        return

    ok = fail = 0
    for vid, title, _vw in todo:
        try:
            # Claude-written phrase (cached per title, fractions of a cent);
            # falls back to mechanical truncation if it fails.
            phrase = thumbnail.hook_phrase(title)
            if phrase == title:
                phrase = _short_text(title)
            th = thumbnail.build(phrase, theme=_theme_of(title),
                                 out=thumbnail.OUT_DIR / f"{vid}.jpg")
            thumbnail.set_on_video(vid, th)
            ok += 1
        except Exception as e:
            print(f"  FAILED {vid}: {str(e)[:90]}")
            fail += 1
    print(f"\nDone: {ok} updated, {fail} failed, {len(skipped)} protected.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--include-top", action="store_true",
                    help="also re-thumbnail already-performing videos (resets "
                         "their learned click-through signal -- deliberate use only)")
    ap.add_argument("--min-views", type=int, default=PROTECT_ABOVE_VIEWS)
    a = ap.parse_args()
    run(a.dry_run, a.include_top, a.min_views)

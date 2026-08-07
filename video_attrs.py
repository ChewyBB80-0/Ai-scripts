"""
video_attrs.py
Records, at render time, the attributes of each video we CHOSE -- genre, hook,
CTA variant, trend hint, part number, runtime, background set.

Why a sidecar rather than more columns on post_log.csv: several readers index
that file positionally (`row[3] == "posted_instagram"`, and the dedup path that
once caused a double-post), so widening it is a needless risk. This file is
append-only, self-describing, and nothing else reads it yet.

Why record now, before the analytics scope lands: these are facts that exist
only at the moment of generation. Retention can be fetched for any video at any
later date; "which CTA variant did that one use" cannot be recovered after the
fact. Every day this doesn't run is a day of permanently unattributable videos.

    import video_attrs
    video_attrs.record("my_story_title", genre="confession", cta_variant="daily")
    rows = video_attrs.load()          # {title: {...}}
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
STORE = ROOT / "output" / "video_attrs.jsonl"


def record(title: str, **attrs) -> None:
    """Append one video's attributes. Never raises -- a bookkeeping failure must
    not lose a rendered video."""
    try:
        STORE.parent.mkdir(parents=True, exist_ok=True)
        row = {"title": title,
               "at": datetime.now().astimezone().isoformat(timespec="seconds")}
        # drop Nones so absent and null don't become two different states later
        row.update({k: v for k, v in attrs.items() if v is not None})
        with open(STORE, "a", encoding="utf-8", newline="") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"(could not record video attrs for {title}: {e})")


def load() -> dict[str, dict]:
    """All recorded attributes keyed by title. Later rows win, so a re-render
    that changes something is reflected rather than duplicated."""
    out: dict[str, dict] = {}
    if not STORE.exists():
        return out
    for line in STORE.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue          # a torn write shouldn't poison the whole file
        if row.get("title"):
            out[row["title"]] = {**out.get(row["title"], {}), **row}
    return out


def pick_cta_variant(title: str, variants: list) -> tuple[str, str]:
    """Assign a CTA variant to a video, deterministically.

    Deterministic on the title, not random: a re-render must keep the same
    variant, or the measurement quietly attributes one video's performance to
    two different asks. Python's hash() is salted per process and would break
    exactly that, hence an explicit digest -- stable across runs, machines and
    restarts.

    md5 rather than sum(ord(...)): our titles are all lowercase words joined by
    underscores, so their code-point sums cluster hard and mod-4 came out 28 /
    19 / 13 / 19 across the existing 79 stories. A 2x skew between arms is a
    real cost when the arms are what's being compared. The digest spreads them
    evenly. Not used for anything security-sensitive.
    """
    if not variants:
        return ("", "")
    digest = hashlib.md5(title.encode("utf-8")).digest()
    return variants[int.from_bytes(digest[:8], "big") % len(variants)]


if __name__ == "__main__":
    rows = load()
    if not rows:
        raise SystemExit(f"nothing recorded yet ({STORE})")
    print(f"{len(rows)} video(s) recorded in {STORE}\n")
    # A quick read on whether the variants are actually spreading -- an uneven
    # split is worth knowing before anyone tries to draw conclusions from it.
    from collections import Counter
    for field in ("cta_variant", "genre", "source", "background_set"):
        c = Counter(r.get(field, "-") for r in rows.values())
        if len(c) > 1 or "-" not in c:
            print(f"  {field}: " + ", ".join(f"{k}={n}" for k, n in c.most_common()))
    hinted = sum(1 for r in rows.values() if r.get("trend_hint"))
    print(f"  trend hint: {hinted} used, {len(rows) - hinted} without")

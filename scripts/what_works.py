"""
scripts/what_works.py
Joins what we CHOSE (video_attrs.jsonl) to how it DID (YouTube retention +
views), and reports which choices correlate with better performance.

This is issue #7's Gap 1. Everything upstream of it already exists: attributes
are recorded at render time because they cannot be recovered afterwards, and
retention is fetchable for any video at any time.

Two rules it will not break, because both are ways of producing a confident
number that means nothing:

RECENCY. Only videos published inside --days are considered. A finding from
four months ago describes an algorithm, an audience and a format that have all
moved. Old data is not deleted -- it stays in video_attrs.jsonl and is simply
outside the window, so widening --days brings it back.

SAMPLE SIZE. A bucket with fewer than MIN_PER_BUCKET videos is reported as
"insufficient", never as a result. With four CTA variants over six videos, every
variant has one observation, and a ranked table of those is noise wearing the
costume of evidence -- worse than no table, because someone acts on it.

    python scripts/what_works.py                 # last 90 days
    python scripts/what_works.py --days 30
    python scripts/what_works.py --min 5         # stricter bucket threshold
"""

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import config  # noqa: F401,E402  -- loads .env

MIN_PER_BUCKET = 4          # below this a bucket is reported, not ranked
ATTRS = ROOT / "output" / "video_attrs.jsonl"

# Attributes worth ranking. Runtime and part number are bucketed rather than
# used raw -- "68.2 seconds" is not a lever anyone can pull, "60-75s" is.
DIMENSIONS = ["genre", "cta_variant", "background_set", "source",
              "multipart", "part_bucket", "runtime_bucket", "hinted"]


def _load_attrs() -> dict[str, dict]:
    rows = {}
    if not ATTRS.exists():
        return rows
    for line in ATTRS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        t = d.get("title")
        if t:
            rows[t] = d          # later record wins; the file is append-only
    return rows


def _bucket(row: dict) -> dict:
    """Derived, human-actionable buckets."""
    out = dict(row)
    rt = row.get("narration_seconds")
    if isinstance(rt, (int, float)):
        out["runtime_bucket"] = ("<40s" if rt < 40 else "40-55s" if rt < 55
                                 else "55-70s" if rt < 70 else "70s+")
    p = row.get("part")
    if isinstance(p, int):
        out["part_bucket"] = "part 1" if p == 1 else "part 2" if p == 2 else "part 3+"
    out["hinted"] = bool(row.get("trend_hint"))
    return out


def _ids_by_stem(post_log: Path) -> dict[str, str]:
    """{story stem -> videoId} from the post log.

    The join has to route through here. There are three different names for the
    same video: video_attrs keys on the story STEM it rendered
    ("the_referee_swapped_my_run"), YouTube stores the human TITLE ("My best
    friend submitted my parkour run to..."), and only post_log.csv holds both
    the stem and the videoId. Matching attrs to YouTube on title directly finds
    nothing -- it silently joined 0 of 37 videos and read as "not enough data".
    """
    import csv as _csv
    out = {}
    if not post_log.exists():
        return out
    with open(post_log) as f:
        for row in _csv.reader(f):
            if len(row) >= 4 and row[3] in ("posted", "posted_manual", "scheduled") and row[2]:
                out.setdefault(row[1].removesuffix(".mp4"), row[2])
    return out


def _perf(days: int) -> dict[str, dict]:
    """{videoId: {title, views, retention_pct, published}} for our own uploads.

    retention_pct is FIRST-PASS only. Shorts loop and YouTube counts replays in
    averageViewDuration, so averageViewPercentage routinely exceeds 100% -- a
    64s Short came back at 2807%. Averaging those produced "325.9% retention"
    once and the conclusion that hooks did not matter. Anything at or above 100%
    is recorded as a loop, not as retention.
    """
    from retention_report import _services
    yt, ya = _services()

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

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out = {}
    for i in range(0, len(ids), 50):
        for v in yt.videos().list(part="snippet,statistics,status",
                                  id=",".join(ids[i:i + 50])).execute()["items"]:
            if v["status"].get("publishAt"):
                continue
            pub = v["snippet"].get("publishedAt", "")
            try:
                when = datetime.fromisoformat(pub.replace("Z", "+00:00"))
            except Exception:
                continue
            if when < cutoff:
                continue
            out[v["id"]] = {"title": v["snippet"]["title"],
                            "views": int(v["statistics"].get("viewCount", 0)),
                            "published": pub[:10], "retention": None, "loops": False}

    if out:
        start = (date.today() - timedelta(days=days)).isoformat()
        end = date.today().isoformat()
        for vid in out:
            try:
                r = ya.reports().query(
                    ids="channel==MINE", startDate=start, endDate=end,
                    metrics="averageViewPercentage", filters=f"video=={vid}").execute()
                rows = r.get("rows") or []
                if rows and rows[0]:
                    pct = float(rows[0][0])
                    if pct >= 100:
                        out[vid]["loops"] = True
                    else:
                        out[vid]["retention"] = pct
            except Exception:
                pass
    return out


def _stem(s: str) -> str:
    return str(s or "").removesuffix(".mp4").strip().lower()


def analyse(days: int, min_bucket: int,
            post_log: str = "output/post_log.csv") -> str:
    attrs = {k.removesuffix(".mp4"): _bucket(v) for k, v in _load_attrs().items()}
    if not attrs:
        return ("No attributed videos yet. video_attrs.jsonl is written at "
                "render time; nothing published before it existed can be "
                "recovered.")

    perf = _perf(days)                      # keyed by videoId
    ids = _ids_by_stem(ROOT / post_log)     # stem -> videoId
    joined = []
    for stem, a in attrs.items():
        vid = ids.get(stem)
        if not vid:
            continue                        # never posted, or Instagram-only
        p = perf.get(vid)
        if p:
            joined.append({**a, **p})

    lines = [f"WHAT WORKS — last {days} days",
             f"  attributed videos on record : {len(attrs)}",
             f"  published in window         : {len(perf)}",
             f"  joined (have both)          : {len(joined)}",
             ""]

    if len(joined) < min_bucket:
        lines += [
            f"NOT ENOUGH DATA. {len(joined)} joined video(s); a single bucket "
            f"needs {min_bucket}.",
            "",
            "Nothing is ranked below that threshold on purpose. With one or two "
            "videos per bucket, any ordering is noise, and a ranked table reads "
            "as evidence whether or not it is.",
            "",
            f"At the current cadence this becomes answerable in roughly "
            f"{max(1, (min_bucket * 3 - len(joined)) // 3)} more days.",
        ]
        return "\n".join(lines)

    withret = [j for j in joined if j.get("retention") is not None]
    lines.append(f"  with first-pass retention   : {len(withret)}"
                 f"   (loopers excluded: {sum(1 for j in joined if j['loops'])})")
    lines.append("")

    for dim in DIMENSIONS:
        buckets = {}
        for j in joined:
            v = j.get(dim)
            if v is None or v == "":
                continue
            buckets.setdefault(str(v), []).append(j)
        if not buckets:
            continue
        lines.append(f"— {dim} —")
        rows = []
        for name, items in buckets.items():
            n = len(items)
            views = sum(i["views"] for i in items) / n
            rets = [i["retention"] for i in items if i.get("retention") is not None]
            ret = sum(rets) / len(rets) if rets else None
            rows.append((name, n, views, ret))
        rows.sort(key=lambda r: -(r[3] if r[3] is not None else -1))
        for name, n, views, ret in rows:
            if n < min_bucket:
                lines.append(f"    {name:<16} n={n:<3} insufficient "
                             f"(need {min_bucket})")
            else:
                r = f"{ret:5.1f}% retention" if ret is not None else "  no retention data"
                lines.append(f"    {name:<16} n={n:<3} {r}   {views:6.0f} avg views")
        lines.append("")

    lines.append("Ranked on FIRST-PASS retention where available, average views "
                 "otherwise. Buckets under the threshold are shown but never "
                 "ranked.")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90,
                    help="only consider videos published in this window")
    ap.add_argument("--min", type=int, default=MIN_PER_BUCKET, dest="min_bucket",
                    help="minimum videos in a bucket before it is ranked")
    ap.add_argument("--account", default="parkourflux",
                    help="which channel's post log to join through")
    a = ap.parse_args()
    from accounts import get_account
    print(analyse(a.days, a.min_bucket, get_account(a.account).post_log))


if __name__ == "__main__":
    main()

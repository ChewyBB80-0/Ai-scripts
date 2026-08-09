"""
scripts/age_report.py
Compare recent posts AT THE SAME AGE and DM the result.

Why age and not wall clock: a post published two hours ago always looks like a
failure next to one published ten hours ago. Judging a new video against the
previous one only means something if both are measured at the same number of
hours since publish. Reading the raw gap instead is a mistake that has actually
been made on this project.

Reads dashboard/post_history.json, which gen_dashboard.py appends to on every
run. A post therefore only has a curve from the first run after that file
started existing -- there is no backfill.

    python scripts/age_report.py                # DM the report
    python scripts/age_report.py --print        # stdout only
    python scripts/age_report.py --account carveteran --platform Instagram
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

PHIST = ROOT / "dashboard" / "post_history.json"


def _hours(pub: str, at: str) -> float | None:
    try:
        a = datetime.fromisoformat(pub.replace("Z", "+00:00"))
        b = datetime.fromisoformat(at)
        if a.tzinfo is None:
            a = a.replace(tzinfo=timezone.utc)
        if b.tzinfo is None:
            b = b.replace(tzinfo=timezone.utc)
        return (b - a).total_seconds() / 3600
    except Exception:
        return None


def views_at(row: dict, age_h: float) -> tuple[int, float] | None:
    """Views at the reading CLOSEST to age_h, with the age actually used.

    Not interpolated: a real reading is a fact and a straight line between two
    of them is a guess, and view curves are steepest exactly where the guess
    would be worst. So the real reading is returned along with its true age, and
    the caller prints that age rather than implying an exact match.

    A tolerance is required, not optional. History collection started partway
    through this channel's life, so its first post's earliest reading is 10.15h
    old while a later post hits 10.0h -- a strict "at or before" test misses by
    nine minutes and reports nothing, which is the least useful possible answer.
    Tolerance is the larger of one hour or 15% of the target age, so it scales
    with how flat the curve has gone by then.
    """
    tol = max(1.0, age_h * 0.15)
    best = None
    for at, v in row.get("pts", []):
        h = _hours(row.get("pub", ""), at)
        if h is None:
            continue
        d = abs(h - age_h)
        if d <= tol and (best is None or d < best[2]):
            best = (v, h, d)
    return (best[0], best[1]) if best else None


def build(account: str, platform: str, limit: int = 4) -> str:
    try:
        hist = json.loads(PHIST.read_text(encoding="utf-8"))
    except Exception:
        return "No post history yet -- run scripts/gen_dashboard.py first."

    rows = [r for r in hist.values()
            if r.get("ch") == account and r.get("plat") == platform and r.get("pub")]
    rows.sort(key=lambda r: r["pub"], reverse=True)
    rows = rows[:limit]
    if len(rows) < 2:
        return (f"Only {len(rows)} tracked {platform} post(s) for {account} -- "
                f"nothing to compare yet.")

    now = datetime.now(timezone.utc).isoformat()
    ages = [_hours(r["pub"], now) or 0 for r in rows]
    # Compare everything at the age of the YOUNGEST post: that is the oldest
    # age at which every post has a reading, so no row is judged on a number it
    # has not had time to earn.
    age = min(ages)

    lines = [f"**Like-for-like at ~{age:.0f}h old** ({platform}, {account})"]
    prev = None
    missing = False
    for r, a in zip(rows, ages):
        got = views_at(r, age)
        title = (r.get("title") or "")[:44]
        if got is None:
            missing = True
            lines.append(f"┃ {title} — not tracked at that age "
                         f"_(now {r['pts'][-1][1]:,} at {a:.0f}h)_")
            continue
        v, actual = got
        delta = ""
        if prev is not None and prev > 0:
            pct = (v - prev) / prev * 100
            delta = f"  ({pct:+.0f}% vs previous)"
        # Print the age of the reading actually used, not the target -- rounding
        # 10.2h to "10h" in both columns would imply a precision we do not have.
        lines.append(f"┃ {title} — **{v:,}** at {actual:.1f}h{delta}"
                     f"  _(now {r['pts'][-1][1]:,} at {a:.0f}h)_")
        prev = v

    lines.append("")
    lines.append("_Compared at the same age -- raw totals would favour whichever "
                 "post is older._")
    if missing:
        lines.append("_Gaps are posts published before per-post history existed; "
                     "there is no backfill._")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", default="carveteran")
    ap.add_argument("--platform", default="Instagram")
    ap.add_argument("--print", action="store_true", dest="only_print")
    a = ap.parse_args()

    text = build(a.account, a.platform)
    print(text)
    if not a.only_print:
        import config  # noqa: F401  -- loads .env
        from discord_notify import send_dm
        send_dm(text)


if __name__ == "__main__":
    main()

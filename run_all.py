"""
run_all.py
Single-process hourly pipeline runner. Replaces the wscript/.vbs + .bat chain
(which exhausted the Windows Script Host desktop heap -> "not enough memory
resources" errors). Run headless via pythonw.exe from the scheduled task.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
os.chdir(ROOT)

# Locate ffmpeg portably so this runs on any machine (main PC + stick PC).
from ffmpeg_setup import ensure_ffmpeg
ensure_ffmpeg()
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

PY = str(ROOT / "venv" / "Scripts" / "python.exe")
STEPS = [
    ["bot.py"],
    ["comment_replies.py"],          # no-op until ENABLE_COMMENT_REPLIES=True
    ["coverage_check.py"],           # report-only: flags half-posted videos
    ["scripts/channel_stats.py"],
    ["scripts/ig_stats.py"],
    ["scripts/gen_dashboard.py"],
    # Re-derives niche hook patterns, but only when they're over a week old --
    # a no-op on almost every run. Feeds story generation (hook_mining.py).
    ["hook_mining.py", "--weekly"],
    # Builds the weekly long-form compilation (Sundays, if there's enough
    # unused material). Builds only -- never uploads; the owner reviews first.
    ["compilation.py", "--weekly"],
    # Pings on Discord only when a watched video goes live or crosses a view
    # milestone -- silent otherwise, so it stays worth reading.
    ["watch_video.py", "--check"],
    # Sends one report per day, held until 08:00 local (see discord_notify).
    ["scripts/discord_notify.py", "report"],
]
LOG = ROOT / "output" / "daily_run.log"


def _cleanup_old_renders(log):
    """Delete rendered mp4s + voice tracks older than config.CLEANUP_KEEP_DAYS
    so the stick's small eMMC never fills up (posted videos live on YT/IG)."""
    import time
    import config
    cutoff = time.time() - config.CLEANUP_KEEP_DAYS * 86400
    removed = 0
    globs = [ROOT.glob("output/*.mp4"), ROOT.glob("output/accounts/*/*.mp4"),
             ROOT.glob("voice/*.mp3"), ROOT.glob("voice/*.json")]
    for g in globs:
        for f in g:
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    removed += 1
            except OSError:
                pass
    # stray per-process temp segment dirs (assemble cleans its own, but a
    # crashed render can leave one behind)
    import shutil as _sh
    for tmp in ROOT.glob("output/tmp_segments*"):
        _sh.rmtree(tmp, ignore_errors=True)
    log.write(f"--- cleanup: removed {removed} old file(s) "
              f"(>{config.CLEANUP_KEEP_DAYS}d) ---\n")


def main():
    from datetime import datetime
    with open(LOG, "a", encoding="utf-8") as log:
        log.write(f"\n[{datetime.now()}] run_all start\n")
        try:
            _cleanup_old_renders(log)
        except Exception as e:
            log.write(f"--- cleanup FAILED: {e} ---\n")
        for step in STEPS:
            try:
                r = subprocess.run([PY] + step, capture_output=True, text=True,
                                   timeout=1800, cwd=ROOT)
                log.write(f"--- {' '.join(step)} ---\n{r.stdout[-2000:]}{r.stderr[-500:]}\n")
            except Exception as e:
                log.write(f"--- {' '.join(step)} FAILED: {e} ---\n")
        log.write(f"[{datetime.now()}] run_all done\n")


if __name__ == "__main__":
    main()

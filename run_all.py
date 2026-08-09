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

# The venv interpreter lives in a different place per OS -- Scripts/python.exe
# on Windows, bin/python on Linux. Hardcoding the Windows path meant every step
# silently failed to launch on the Ubuntu host (19h of no posts before it was
# noticed), so resolve it per platform and fall back to the interpreter that is
# already running us.
_VENV_PY = ROOT / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
PY = str(_VENV_PY) if _VENV_PY.exists() else sys.executable
STEPS = [
    # Keep Instagram tokens alive. A no-op on almost every run -- it only acts
    # once a token is a week old. Runs BEFORE bot.py so a posting run never
    # starts on a token that was about to lapse. YouTube and TikTok refresh
    # themselves inside their own clients; Instagram had nothing, which made it
    # the one platform with a scheduled outage.
    ["ig_token.py"],
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
    # Pings Discord ONLY when the pipeline has gone quiet for a bad reason,
    # or a token/disk problem appears. Silent when healthy.
    ["health_check.py"],
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


def _self_update(log):
    """Fast-forward to the latest pushed code before running the pipeline.

    Every step below is a fresh subprocess, so a pull here takes effect on this
    very run -- which is the point: a fix pushed from anywhere reaches the box
    without anyone being at it. Failures are logged and ignored; missing an
    update is survivable, missing a posting slot is not.
    """
    import self_update
    changed, msg, files = self_update.pull()
    log.write(f"--- update: {msg} ---\n")
    if not changed:
        return
    stale = self_update.stale_units(files)
    if stale:
        # These keep running the code they booted with, so the pull hasn't
        # actually reached them. Restarting them from here would kill the
        # Discord bot mid-conversation, so say it instead of doing it.
        log.write(f"--- update: restart for new code: {', '.join(stale)} ---\n")
    if "run_all.py" in files and not os.environ.get("MEDIAMAKER_REEXEC"):
        # The runner itself changed. Re-exec once (the sentinel makes a loop
        # impossible) so this run uses the new sequence rather than replaying
        # the old one for another hour.
        log.write("--- update: re-exec into new run_all.py ---\n")
        log.flush()
        os.execve(sys.executable, [sys.executable, str(ROOT / "run_all.py")],
                  {**os.environ, "MEDIAMAKER_REEXEC": "1"})


def main():
    from datetime import datetime
    with open(LOG, "a", encoding="utf-8") as log:
        log.write(f"\n[{datetime.now()}] run_all start\n")
        try:
            _self_update(log)
        except Exception as e:
            log.write(f"--- update FAILED: {e} ---\n")
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

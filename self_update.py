"""
self_update.py
Pulls the latest committed code onto whichever box is running the pipeline.

Why this exists: on 2026-07-30 a YouTube upload outage (invalid_scope) was
diagnosed and fixed within the hour, and then sat on the remote branch unable
to reach the machine, because deploying meant someone being physically at the
playbox to type `git pull`. The owner was away. A fix you can't deploy is not
a fix. Both the hourly runner and the Discord `update` tool call this so a
pushed fix can land on its own.

Deliberately conservative -- this runs unattended on the box that posts:

  * --ff-only. Never invents a merge commit, never rewrites local work. A
    diverged branch fails loudly instead of being silently "resolved".
  * Refuses to touch a dirty tree. Uncommitted changes mean someone is mid-edit
    on the box; burying that under a pull is worse than staying out of date.
  * A failed pull is never fatal. A network blip must not cost a posting slot,
    so the caller logs the failure and runs the code it already has.
  * GIT_TERMINAL_PROMPT=0 plus a timeout. A remote that wants credentials must
    fail in seconds, not block the hourly run forever waiting on a prompt that
    nobody is there to answer.
"""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent

# Non-interactive git: fail instead of prompting for credentials on a headless
# box. Without this a remote that needs auth can hang the whole run.
_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}


def _git(*args, timeout=120):
    return subprocess.run(["git", *args], cwd=str(ROOT), env=_ENV,
                          capture_output=True, text=True, timeout=timeout)


def _head() -> str:
    r = _git("rev-parse", "--short", "HEAD", timeout=15)
    return r.stdout.strip() or "unknown"


def _branch() -> str:
    r = _git("rev-parse", "--abbrev-ref", "HEAD", timeout=15)
    return r.stdout.strip() or "unknown"


def pull(timeout: int = 120) -> tuple[bool, str, list[str]]:
    """Fast-forward the checkout to its tracking branch.

    Returns (changed, human_message, changed_files). `changed` is True only
    when new commits actually landed, so callers can stay quiet on the ~99% of
    runs that are already up to date.
    """
    try:
        # --untracked-files=no is load-bearing. The guard exists to protect a
        # hand-patched box from having its edits clobbered -- that means
        # MODIFIED TRACKED files. Plain --porcelain also lists untracked ones,
        # and the pipeline writes new stories into stories/, a tracked
        # directory, so every story the bot generated left another ?? line
        # here. On the playbox that was 10 of 13 entries and self-update had
        # been refusing to run since the feature shipped: the pipeline's own
        # normal output was switching off its own updates.
        #
        # An untracked file that genuinely collides with an incoming one still
        # stops the pull -- git refuses and the returncode branch below reports
        # it -- so nothing gets silently overwritten by relaxing this.
        dirty = _git("status", "--porcelain", "--untracked-files=no",
                     timeout=30).stdout.strip()
        if dirty:
            n = len(dirty.splitlines())
            return False, (f"Skipped update: {n} modified tracked file(s) on the "
                           "box. Commit or discard them, then update."), []

        before = _head()
        branch = _branch()
        r = _git("pull", "--ff-only", timeout=timeout)
        if r.returncode != 0:
            err = (r.stderr or r.stdout).strip().splitlines()
            detail = err[-1] if err else "unknown error"
            return False, f"Update failed on {branch}: {detail}", []

        after = _head()
        if before == after:
            return False, f"Already up to date ({branch} @ {after}).", []

        files = [f for f in _git("diff", "--name-only", f"{before}..{after}",
                                 timeout=30).stdout.splitlines() if f]
        subject = _git("log", "-1", "--format=%s", timeout=15).stdout.strip()
        return True, f"Updated {branch}: {before} -> {after} ({subject})", files

    except subprocess.TimeoutExpired:
        return False, "Update timed out (git unreachable or awaiting credentials).", []
    except Exception as e:                      # never fatal -- the run goes on
        return False, f"Update skipped: {type(e).__name__}: {e}", []


# Long-running units keep executing the code they started with. Pipeline steps
# are fresh subprocesses each run, so they pick up a pull immediately; these
# two do not, and saying so is the difference between "deployed" and "deployed
# except the part you were talking to".
LONG_RUNNING = {
    "control_server.py": "mediamaker-server",
    "discord_bot.py": "mediamaker-bot",
}


def stale_units(changed_files: list[str]) -> list[str]:
    """Systemd units still running old code after a pull, so callers can say so."""
    return sorted({unit for f, unit in LONG_RUNNING.items() if f in changed_files})

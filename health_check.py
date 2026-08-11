"""
health_check.py
Detects when the pipeline has gone quiet for a BAD reason and pings Discord.

The daily report tells you what posted. Nothing told you when something
*didn't* -- so a stalled pipeline could sit unnoticed for days. This closes
that gap.

Design rules, because a noisy monitor gets muted and then it is worthless:

  * Silence is often CORRECT. A hit weekly cap, a met daily target, or autonomy
    switched off are all legitimate reasons for no posts. This only fires when
    the pipeline SHOULD have posted and didn't.
  * One alert per issue per cooldown window, not one per hourly run.
  * It always exits 0 -- a health check must never be the thing that breaks the
    run it is monitoring.

    python health_check.py            # check, ping Discord if needed
    python health_check.py --dry-run  # print findings, send nothing
    python health_check.py --force    # ignore the cooldown (for testing)
"""

import argparse
import csv
import json
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# systemd supplies .env via EnvironmentFile, so the timer was always fine -- but
# a hand-run without sourcing it saw empty credentials and reported "Instagram
# token is invalid" about a perfectly good token. False alarms are worse here
# than anywhere else in the project: this is the monitor, and the whole reason
# it exists is that a noisy one gets ignored.
import env_file
env_file.load()

STATE = ROOT / "output" / "health_state.json"
POST_LOG = ROOT / "output" / "post_log.csv"
ERROR_LOG = ROOT / "output" / "errors.log"
_PT = ZoneInfo("America/Los_Angeles")

# Generous: the pipeline legitimately idles overnight and between slots, so a
# short gap means nothing. This is "something is wrong", not "it is idle".
# Floor for the staleness alarm. The real threshold is per channel: its own
# expected gap (24 / daily_target) plus GRACE_HOURS, whichever is larger.
STALE_HOURS = 14
GRACE_HOURS = 6
COOLDOWN_HOURS = 8
DISK_FREE_MIN_GB = 5
ERROR_BURST = 5             # this many new errors since last check = a problem


def _state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(s: dict):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=1), encoding="utf-8")


def _last_post(log: Path | None = None) -> datetime | None:
    """Most recent successful publish of any kind, for ONE channel's log."""
    log = log or POST_LOG
    if not log.exists():
        return None
    last = None
    for r in csv.reader(open(log, encoding="utf-8")):
        if len(r) >= 4 and r[3] in ("posted", "posted_manual",
                                    "posted_instagram", "scheduled"):
            try:
                d = datetime.fromisoformat(r[0])
            except ValueError:
                continue
            if d.tzinfo is None:
                d = d.astimezone()
            if last is None or d > last:
                last = d
    return last


def _autonomy_enabled() -> bool:
    """Whether the scheduler is actually meant to be running right now."""
    import subprocess
    try:
        if sys.platform.startswith("win"):
            r = subprocess.run(["schtasks", "/query", "/tn", "MediaMakerHourly",
                                "/fo", "list"], capture_output=True, text=True,
                               timeout=20)
            return "Disabled" not in r.stdout
        r = subprocess.run(["systemctl", "--user", "is-enabled",
                            "mediamaker.timer"], capture_output=True,
                           text=True, timeout=20)
        return "enabled" in r.stdout
    except Exception:
        return True          # can't tell -> assume it should be running


def collect() -> list[str]:
    """Return a list of problems. Empty list = healthy."""
    import config
    import bot
    problems = []

    # --- 1. has it gone quiet when it shouldn't have? --------------------
    # Order matters: check the LEGITIMATE reasons for silence first, so a
    # capped-out week never reads as a stall.
    autonomy = _autonomy_enabled()
    cap = getattr(config, "WEEKLY_POST_TARGET", 14)

    # Per channel, against ITS OWN cadence. A single global threshold read the
    # first account's log only, so a second channel could be dead for days
    # unnoticed -- and the moment ParkourFlux moved to 1/day, a fixed 14h fired
    # a false alarm every single day.
    from accounts import expected_gap_hours, load_accounts, paths
    any_log = False
    for acc in load_accounts():
        pth = paths(acc)
        last = _last_post(pth["post_log"])
        if last is None:
            continue
        any_log = True
        bot.POST_LOG = pth["post_log"]
        weekly = bot.this_weeks_upload_count()
        if weekly >= cap or not autonomy:
            continue                     # legitimately quiet
        age_h = (datetime.now().astimezone() - last).total_seconds() / 3600
        # Expected interval plus grace, so a channel is flagged only once it has
        # genuinely missed a slot rather than merely being between them.
        limit = max(STALE_HOURS, expected_gap_hours(acc) + GRACE_HOURS)
        if age_h > limit:
            problems.append(
                f"**{acc.name}: no post in {age_h:.0f}h** "
                f"(last: {last:%a %d %b %H:%M}, expects one every "
                f"{expected_gap_hours(acc):.0f}h). Weekly cap is {weekly}/{cap} "
                f"and autonomy is ON, so it should have posted by now.")
    if not any_log:
        problems.append("No posts have ever been logged.")

    # Autonomy off is worth ONE mention -- it's usually deliberate, but it's
    # also the most common reason someone finds the pipeline silent for days.
    if not autonomy:
        problems.append("Autonomy is OFF -- nothing will post until it's on.")

    # --- 2. new errors since the last check ------------------------------
    if ERROR_LOG.exists():
        try:
            lines = ERROR_LOG.read_text(encoding="utf-8",
                                        errors="replace").splitlines()
            seen = _state().get("error_lines", 0)
            new = len(lines) - seen
            if new >= ERROR_BURST:
                problems.append(
                    f"**{new} new errors** in errors.log since the last check. "
                    f"Latest: {lines[-1][:120]}")
        except Exception:
            pass

    # --- 3. services running code older than the repo --------------------
    # The pull happens automatically; the long-running services do not pick it
    # up, and the only notice was one line in daily_run.log that nobody reads.
    # A push that "deployed" while the Discord bot kept answering from last
    # week's code is invisible otherwise -- everything looks healthy.
    try:
        import self_update
        stale = self_update.running_stale()
        if stale:
            problems.append(
                f"**Running old code:** {', '.join(stale)} started before the "
                f"current files. A pull landed but these kept the code they "
                f"booted with.\n  Fix: `systemctl --user restart "
                f"{' '.join(stale)}`")
    except Exception as e:
        print(f"(stale-code check skipped: {e})")

    # --- 4. disk ---------------------------------------------------------
    try:
        free_gb = shutil.disk_usage(ROOT).free / 1e9
        if free_gb < DISK_FREE_MIN_GB:
            problems.append(f"**Low disk: {free_gb:.1f}GB free.** Renders will "
                            "start failing.")
    except Exception:
        pass

    # --- 5. credentials still valid --------------------------------------
    # A silently-expired token is the nastiest failure here: everything looks
    # fine and nothing posts.
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from youtube_upload import UPLOAD_SCOPE
        from accounts import load_accounts, paths
        # Per channel. One token per account, and a second channel whose token
        # quietly expired looks identical from here to a healthy one if only the
        # first is checked -- the same blind spot that let the staleness alarm
        # watch one log while the other went dark.
        for acc in load_accounts():
            tok = paths(acc)["yt_token"]
            if not tok.exists():
                problems.append(f"**{acc.name}: no YouTube token** ({tok.name}) "
                                f"-- run: python add_channel.py {acc.id}")
                continue
            # Each account in its own try: a corrupt or unreadable token on the
            # first channel must not abort the loop, or the remaining channels
            # go unchecked behind one generic "token check failed" -- which is
            # the very blind spot this loop was added to close.
            try:
                c = Credentials.from_authorized_user_file(str(tok))
                if c.expired and c.refresh_token:
                    c.refresh(Request())
                if not c.valid:
                    problems.append(f"**{acc.name}: YouTube token is invalid** "
                                    f"-- re-run: python add_channel.py {acc.id}")
                # A token can refresh cleanly and still be missing the scope
                # uploading needs -- which is exactly how the invalid_scope
                # outage looked from here: this check passed while every upload
                # failed. Compare what was granted against what posting needs.
                if UPLOAD_SCOPE not in (c.scopes or []):
                    problems.append(f"**{acc.name}: YouTube token lacks the "
                                    "upload scope** -- uploads will fail while "
                                    "everything else looks healthy. Re-auth: "
                                    f"python add_channel.py {acc.id}")
            except Exception as e:
                problems.append(f"**{acc.name}: YouTube token check failed:** "
                                f"{str(e)[:80]}")
    except Exception as e:
        problems.append(f"**YouTube token check failed:** {str(e)[:90]}")

    try:
        import os
        import requests
        r = requests.get(
            f"https://graph.instagram.com/v21.0/{os.environ.get('IG_USER_ID','')}",
            params={"fields": "username",
                    "access_token": os.environ.get("IG_ACCESS_TOKEN", "")},
            timeout=20).json()
        if "username" not in r:
            problems.append("**Instagram token is invalid** -- "
                            f"{str(r.get('error', {}).get('message', r))[:90]}")
    except Exception as e:
        problems.append(f"**Instagram token check failed:** {str(e)[:90]}")

    return problems


def run(dry_run: bool = False, force: bool = False) -> list[str]:
    problems = collect()
    st = _state()

    # remember how many error lines we've already reported on
    if ERROR_LOG.exists():
        try:
            st["error_lines"] = len(ERROR_LOG.read_text(
                encoding="utf-8", errors="replace").splitlines())
        except Exception:
            pass

    if not problems:
        st.pop("last_alert", None)          # recovered -> next issue alerts at once
        st["last_ok"] = datetime.now().isoformat(timespec="seconds")
        _save(st)
        print("healthy -- nothing to report")
        return []

    # cooldown: don't repeat the same alert every hour
    fingerprint = "|".join(p[:40] for p in problems)
    prev = st.get("last_alert", {})
    if not force and prev.get("fingerprint") == fingerprint:
        try:
            age = datetime.now() - datetime.fromisoformat(prev["at"])
            if age < timedelta(hours=COOLDOWN_HOURS):
                print(f"{len(problems)} problem(s), already alerted "
                      f"{age.total_seconds()/3600:.1f}h ago -- staying quiet")
                _save(st)
                return problems
        except Exception:
            pass

    msg = ("🚨 **Health check**\n"
           + "\n".join(f"• {p}" for p in problems))
    print(msg)
    if not dry_run:
        try:
            sys.path.insert(0, str(ROOT / "scripts"))
            from discord_notify import send_dm
            send_dm(msg, ping=True)
            st["last_alert"] = {"fingerprint": fingerprint,
                                "at": datetime.now().isoformat(timespec="seconds")}
        except Exception as e:
            print(f"(could not send Discord alert: {e})")
    _save(st)
    return problems


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.parse_args()
    a = ap.parse_args()
    try:
        run(a.dry_run, a.force)
    except Exception as e:
        # never let the monitor break the run it monitors
        print(f"health check itself failed (non-fatal): {e}")
    sys.exit(0)

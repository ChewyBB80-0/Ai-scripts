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

STATE = ROOT / "output" / "health_state.json"
POST_LOG = ROOT / "output" / "post_log.csv"
ERROR_LOG = ROOT / "output" / "errors.log"
_PT = ZoneInfo("America/Los_Angeles")

# Generous: the pipeline legitimately idles overnight and between slots, so a
# short gap means nothing. This is "something is wrong", not "it is idle".
STALE_HOURS = 14
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


def _last_post() -> datetime | None:
    """Most recent successful publish of any kind."""
    if not POST_LOG.exists():
        return None
    last = None
    for r in csv.reader(open(POST_LOG, encoding="utf-8")):
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
    weekly = bot.this_weeks_upload_count()
    cap = getattr(config, "WEEKLY_POST_TARGET", 14)
    capped = weekly >= cap
    autonomy = _autonomy_enabled()
    last = _last_post()

    if last is None:
        problems.append("No posts have ever been logged.")
    else:
        age_h = (datetime.now().astimezone() - last).total_seconds() / 3600
        if age_h > STALE_HOURS and not capped and autonomy:
            problems.append(
                f"**No post in {age_h:.0f}h** (last: {last:%a %d %b %H:%M}). "
                f"Weekly cap is {weekly}/{cap} and autonomy is ON, so it "
                "should have posted by now.")

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

    # --- 3. disk ---------------------------------------------------------
    try:
        free_gb = shutil.disk_usage(ROOT).free / 1e9
        if free_gb < DISK_FREE_MIN_GB:
            problems.append(f"**Low disk: {free_gb:.1f}GB free.** Renders will "
                            "start failing.")
    except Exception:
        pass

    # --- 4. credentials still valid --------------------------------------
    # A silently-expired token is the nastiest failure here: everything looks
    # fine and nothing posts.
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        c = Credentials.from_authorized_user_file(str(ROOT / "token.json"))
        if c.expired and c.refresh_token:
            c.refresh(Request())
        if not c.valid:
            problems.append("**YouTube token is invalid** -- re-run add_channel.py.")
        # A token can refresh cleanly and still be missing the scope uploading
        # needs -- which is exactly how the invalid_scope outage looked from
        # here: this check passed while every upload failed. Compare what the
        # token was granted against what posting actually requires.
        from youtube_upload import UPLOAD_SCOPE
        if UPLOAD_SCOPE not in (c.scopes or []):
            problems.append("**YouTube token lacks the upload scope** -- "
                            "uploads will fail while everything else looks "
                            "healthy. Re-auth: python add_channel.py parkourflux")
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

    msg = ("🚨 **ParkourFlux health check**\n"
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

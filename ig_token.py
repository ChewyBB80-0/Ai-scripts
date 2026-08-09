"""
ig_token.py
Keeps Instagram access tokens alive so they never expire.

Instagram long-lived tokens last 60 days. YouTube and TikTok both refresh
themselves in this pipeline; Instagram had no refresh code at all, which made it
the only platform with a scheduled outage -- and it is the traction leader, so
losing it costs the most. The health check would have reported the failure, but
only after posting had already stopped.

Meta's endpoint returns a NEW 60-day token from an existing one, provided the
existing one is at least 24 hours old:

    GET https://graph.instagram.com/refresh_access_token
        ?grant_type=ig_refresh_token&access_token=<current>

Refreshed every three weeks, the token is never older than 21 days and always
has ~39 days left, so an expiry needs the box to be off for well over a month.

WHERE THE TOKEN LIVES. .env stays the source of truth for the FIRST token, the
one you paste in by hand. Refreshed tokens go to output/ig_tokens.json, which
takes precedence. The pipeline never rewrites .env: that file holds fifteen
credentials, is hand-edited, and a concurrent or malformed write there breaks
everything at once. A store the pipeline owns end-to-end is the safer split --
delete it and the system falls back to .env unharmed.

    python ig_token.py            # refresh anything due, report
    python ig_token.py --status   # show ages and expiries, change nothing
    python ig_token.py --force    # refresh regardless of age
"""

import json
import os
import time
from pathlib import Path

import requests

ROOT = Path(__file__).parent
STORE = ROOT / "output" / "ig_tokens.json"
REFRESH_URL = "https://graph.instagram.com/refresh_access_token"

# Refresh once the token is three weeks old. Each refresh resets the clock to
# 60 days, so the token is never older than 21 days and always has ~39 days of
# life left -- that 39 days is also how long the box can stay off before a
# token actually lapses. Comfortably clear of Meta's floor, which rejects a
# refresh on any token under 24h old.
REFRESH_AFTER_DAYS = 21
DAY = 86400


def _read() -> dict:
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write(data: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    # Write-then-rename: a crash mid-write must not leave a truncated store,
    # because that would strand every account back on a stale .env token.
    tmp = STORE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    # Owner-only, matching .env. This file holds live access tokens and the
    # default umask left it 664 -- readable by every account on the box.
    # chmod BEFORE the rename so there is no window where it exists readable.
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass                      # Windows ignores POSIX modes; not fatal
    tmp.replace(STORE)


def env_token(acc_id: str, default_id: str = "parkourflux") -> str | None:
    """The hand-pasted token from .env, with the same per-account rule as
    accounts.Account: shared vars belong to the default account only."""
    own = os.environ.get(f"IG_ACCESS_TOKEN_{acc_id.upper()}")
    if own or acc_id != default_id:
        return own
    return os.environ.get("IG_ACCESS_TOKEN")


def current(acc_id: str, default_id: str = "parkourflux") -> str | None:
    """The token to use right now: the refreshed one if we have it, else .env."""
    rec = _read().get(acc_id)
    if rec and rec.get("access_token"):
        return rec["access_token"]
    return env_token(acc_id, default_id)


def status(acc_id: str) -> dict:
    """Age and remaining life, for reporting. Never raises."""
    rec = _read().get(acc_id) or {}
    got = rec.get("obtained")
    life = rec.get("expires_in", 60 * DAY)
    if not got:
        return {"known": False, "source": "env (never refreshed)"}
    age = time.time() - got
    return {"known": True, "source": "store",
            "age_days": round(age / DAY, 1),
            "expires_in_days": round((life - age) / DAY, 1)}


def refresh(acc_id: str, force: bool = False,
            default_id: str = "parkourflux") -> tuple[bool, str]:
    """Refresh one account's token if it is due. Returns (changed, message).

    Never raises: a failed refresh must not stop a posting run. The old token
    stays valid until its original expiry, so there is always another chance.
    """
    tok = current(acc_id, default_id)
    if not tok:
        return False, f"{acc_id}: no Instagram token configured, skipping"

    data = _read()
    rec = data.get(acc_id) or {}
    got = rec.get("obtained")
    if got and not force:
        age = time.time() - got
        if age < REFRESH_AFTER_DAYS * DAY:
            return False, (f"{acc_id}: {age / DAY:.1f}d old, next refresh at "
                           f"{REFRESH_AFTER_DAYS}d")
        if age < DAY:
            # Meta rejects a refresh on a token younger than 24h.
            return False, f"{acc_id}: under 24h old, too young to refresh"

    try:
        r = requests.get(REFRESH_URL, timeout=30, params={
            "grant_type": "ig_refresh_token", "access_token": tok})
        j = r.json()
    except Exception as e:
        return False, f"{acc_id}: refresh call failed ({type(e).__name__}), token unchanged"

    if "access_token" not in j:
        err = str(j.get("error", j))[:110]
        return False, f"{acc_id}: refresh refused, token unchanged -- {err}"

    data[acc_id] = {"access_token": j["access_token"],
                    "expires_in": int(j.get("expires_in", 60 * DAY)),
                    "obtained": int(time.time())}
    _write(data)
    return True, (f"{acc_id}: refreshed, good for "
                  f"{int(j.get('expires_in', 60 * DAY)) / DAY:.0f} more days")


def refresh_all(force: bool = False) -> list[str]:
    """Refresh every configured account. Used by the hourly runner."""
    import env_file
    env_file.load()
    from accounts import all_accounts

    msgs = []
    for acc in all_accounts():
        # Skip accounts with no Instagram at all, but DO refresh disabled ones:
        # a token that dies while a channel is parked is a nasty surprise on the
        # day it is switched back on.
        if not current(acc.id):
            continue
        changed, msg = refresh(acc.id, force=force)
        msgs.append(msg)
    return msgs


if __name__ == "__main__":
    import sys
    import env_file
    env_file.load()
    from accounts import all_accounts

    if "--status" in sys.argv:
        for acc in all_accounts():
            t = current(acc.id)
            print(f"  {acc.id:14} token={'set' if t else 'NONE':4}  {status(acc.id)}")
    else:
        for m in refresh_all(force="--force" in sys.argv):
            print(" ", m)

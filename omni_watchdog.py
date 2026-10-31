"""
omni_watchdog.py
Checks the OmniRoute gateway on the PC and DMs on Discord when it dies.

Run by omniwatchdog.timer every 5 minutes. Exit 0 = gateway healthy,
exit 1 = gateway down. The unit sets SuccessExitStatus=0 1 because a DOWN
gateway is a finding, not a unit failure.

Two probes, in order of cost:
  1. GET /healthz   -- is the gateway process alive at all
  2. POST /v1/chat/completions with the pinned model -- is the route the
     trading bot actually uses working end to end

Probe 2 exists because the outage this watchdog was written for did NOT
show up as a dead process: /healthz stayed 200 while completions returned
502s and ReadTimeouts, which is what actually stopped the bot from placing
orders. A liveness check alone would have reported "OK" through the whole
incident.

Alerting is edge-triggered via a state file: one DM when it goes down, one
when it recovers. Without that, a 3-hour outage at a 5-minute interval is
36 identical DMs and the next real alert gets ignored.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
STATE = ROOT / "output" / ".omni_watchdog_state.json"
LOG = ROOT / "omni_watchdog.log"

# Alert only after this many consecutive bad checks, so a single dropped
# packet or a PC reboot that finishes inside 5 minutes stays quiet.
FAILS_BEFORE_ALERT = 2

HEALTH_TIMEOUT = 10
COMPLETION_TIMEOUT = 45


def _load_env() -> None:
    """Populate os.environ from both .env files this script straddles.

    The unit deliberately has no EnvironmentFile: the Discord credentials
    live in media_maker/.env and the OmniRoute ones in alpaca_trader/.env,
    and duplicating either into a unit file would leave two copies of a
    secret to rotate. So load them here instead.
    """
    sys.path.insert(0, str(ROOT))
    try:
        import env_file
        env_file.load()
    except Exception:
        pass

    # OMNIBUS_* belong to the trading bot and are not in media_maker/.env.
    bot_env = Path.home() / "alpaca_trader" / ".env"
    if bot_env.exists():
        for line in bot_env.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def _log(msg: str) -> None:
    ts = datetime.now().astimezone().isoformat(timespec="seconds")
    line = f"{ts}  {msg}"
    print(line)
    try:
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def _read_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"consecutive_failures": 0, "alerted": False}


def _write_state(state: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state), encoding="utf-8")
    except Exception as e:
        _log(f"WARN could not persist state: {e}")


def check_healthz(base: str) -> tuple[bool, str]:
    url = f"{base}/healthz"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=HEALTH_TIMEOUT) as r:
            body = r.read(200).decode("utf-8", "replace").strip()
            if r.status == 200:
                return True, f"healthz 200 ({body[:40]})"
            return False, f"healthz HTTP {r.status}"
    except urllib.error.HTTPError as e:
        return False, f"healthz HTTP {e.code}"
    except Exception as e:
        return False, f"healthz unreachable: {type(e).__name__}: {e}"


def check_completion(url: str, key: str, model: str) -> tuple[bool, str]:
    """The probe that matters: a real completion on the pinned model."""
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "reply with OK"}],
        "max_tokens": 64,
    }).encode()
    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=COMPLETION_TIMEOUT) as r:
            raw = r.read().decode("utf-8", "replace")
            if r.status != 200:
                return False, f"completion HTTP {r.status}"
            data = json.loads(raw)
            # Only structural validity is checked. A reasoning model with a
            # small max_tokens legitimately returns content=null and
            # finish_reason=length, so asserting on the text would fail on a
            # perfectly healthy gateway.
            if not data.get("choices"):
                return False, "completion 200 but no choices in response"
            served = data.get("model", "?")
            return True, f"completion 200 (model={served})"
    except urllib.error.HTTPError as e:
        return False, f"completion HTTP {e.code}"
    except Exception as e:
        return False, f"completion failed: {type(e).__name__}: {e}"


def _notify(text: str, ping: bool) -> None:
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        import discord_notify
        if discord_notify.send_dm(text, ping=ping):
            _log("discord DM sent")
        else:
            _log("WARN discord DM failed")
    except Exception as e:
        _log(f"WARN discord notify unavailable: {e}")


def main() -> int:
    _load_env()

    full_url = os.environ.get("OMNIBUS_URL", "").strip()
    key = os.environ.get("OMNIBUS_API_KEY", "").strip()
    model = os.environ.get("OMNIBUS_MODEL", "").strip()
    if not full_url or not key or not model:
        _log("ERROR OMNIBUS_URL / OMNIBUS_API_KEY / OMNIBUS_MODEL not all set "
             "-- cannot check gateway")
        return 1

    # OMNIBUS_URL is the full completions endpoint; /healthz hangs off the root.
    base = full_url.split("/v1/")[0].rstrip("/")

    ok_health, msg_health = check_healthz(base)
    if ok_health:
        ok_completion, msg_completion = check_completion(full_url, key, model)
    else:
        ok_completion, msg_completion = False, "completion skipped (healthz failed)"

    healthy = ok_health and ok_completion
    detail = f"{msg_health}; {msg_completion}"

    state = _read_state()
    fails = int(state.get("consecutive_failures", 0))
    alerted = bool(state.get("alerted", False))

    if healthy:
        _log(f"OK  {detail}")
        if alerted:
            _notify(f"✅ OmniRoute gateway recovered — {detail}", ping=False)
        _write_state({"consecutive_failures": 0, "alerted": False})
        return 0

    fails += 1
    _log(f"DOWN ({fails}x)  {detail}")
    if fails >= FAILS_BEFORE_ALERT and not alerted:
        _notify(
            f"🚨 OmniRoute gateway DOWN ({fails} consecutive checks)\n"
            f"{detail}\n"
            f"Gateway: {base}\n"
            f"The trading bot's primary LLM route is unavailable; it should be "
            f"falling back to local Ollama.",
            ping=True,
        )
        alerted = True
    _write_state({"consecutive_failures": fails, "alerted": alerted})
    return 1


if __name__ == "__main__":
    sys.exit(main())

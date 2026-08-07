"""
env_file.py
Load .env into os.environ when nothing else has.

systemd feeds .env to the services via EnvironmentFile=, so they always have
their credentials. An interactive shell has nothing unless you remember
`set -a; . ./.env; set +a` -- and forgetting produces a KeyError or a
"credential MISSING" report that sends you hunting a transfer problem that
doesn't exist. That has now cost time twice: once on preflight during the
Linux port, once running `tiktok_upload.py auth` by hand.

Existing variables always win, so a value exported deliberately in the shell
is never overwritten by the file.
"""

import os
from pathlib import Path

ROOT = Path(__file__).parent


def load(quiet: bool = True) -> list[str]:
    """Fill any unset variables from .env. Returns the names it set."""
    path = ROOT / ".env"
    if not path.exists():
        return []
    loaded = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        # .strip("'\"") after stripping whitespace: the file is hand-edited and
        # picks up quotes. A trailing \r from a Windows-authored line would
        # otherwise ride along inside the value and fail auth confusingly.
        k, v = k.strip(), v.strip().strip("'\"").strip()
        if k and v and not os.environ.get(k):
            os.environ[k] = v
            loaded.append(k)
    if loaded and not quiet:
        print(f"(loaded {len(loaded)} variables from .env)")
    return loaded


def require(name: str, hint: str = "") -> str:
    """Fetch a variable, loading .env first if it isn't already set."""
    if not os.environ.get(name):
        load()
    val = os.environ.get(name)
    if not val:
        raise SystemExit(
            f"{name} is not set, and .env does not define it.\n"
            f"{hint or 'Add it to ~/media_maker/.env.'}")
    return val

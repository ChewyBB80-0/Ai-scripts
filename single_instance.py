"""
single_instance.py
Stops a second copy of a long-running service starting on the same machine.

Why this exists: the Windows box was believed to be stood down after the move
to the playbox, but discord_bot.py and TWO copies of control_server.py were
still running there. A second Discord bot on the same token receives every
gateway event the first one does, so every "post a video" command ran twice --
on two machines sharing one set of YouTube and Instagram tokens. Nothing
complained, because from each process's point of view it was behaving
correctly.

An OS advisory lock rather than a PID file, because the kernel drops it when
the holder exits for any reason -- crash, kill -9, power cut. A stale PID file
after an unclean shutdown would lock the service out of its own restart, which
is a worse failure than the one being prevented.

    import single_instance
    if not single_instance.acquire("discord_bot"):
        sys.exit(0)
"""

import os
from pathlib import Path

ROOT = Path(__file__).parent
LOCK_DIR = ROOT / "output" / "locks"

# Held open for the life of the process. The lock lives on the file handle, so
# letting it get garbage-collected would silently release it.
_held: list = []


def _pid_note(name: str) -> str:
    """Whatever the previous holder recorded about itself, for the error text."""
    try:
        return (LOCK_DIR / f"{name}.pid").read_text(encoding="utf-8").strip()
    except Exception:
        return "unknown"


def acquire(name: str) -> bool:
    """True if this process now owns `name`, False if someone else already does.

    Never raises -- if locking is somehow unavailable, it returns True and lets
    the service start. Failing open matters: a broken lock must not be able to
    take the pipeline down.
    """
    try:
        LOCK_DIR.mkdir(parents=True, exist_ok=True)
        f = open(LOCK_DIR / f"{name}.lock", "a+")
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            return False
        _held.append(f)
        try:
            import socket
            (LOCK_DIR / f"{name}.pid").write_text(
                f"pid {os.getpid()} on {socket.gethostname()}", encoding="utf-8")
        except Exception:
            pass
        return True
    except Exception as e:
        print(f"(single-instance check unavailable, starting anyway: {e})")
        return True


def require(name: str) -> None:
    """acquire(), or explain and exit 0.

    Exit 0, not 1: under systemd with Restart=always a non-zero exit would
    retry forever against a lock that is being held perfectly legitimately.
    """
    if acquire(name):
        return
    import sys
    print(f"Another {name} is already running on this machine "
          f"({_pid_note(name)}). Not starting a second one.\n"
          f"If that process is wrong, stop it first -- two copies sharing one "
          f"set of API tokens double-post.")
    sys.exit(0)

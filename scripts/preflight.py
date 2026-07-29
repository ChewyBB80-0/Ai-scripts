"""
preflight.py
Run this ON THE HOST MACHINE after copying the project across, BEFORE going
live. It checks every dependency the pipeline needs and prints one PASS/FAIL
line each, so a missing credential surfaces while you're still standing at the
machine instead of at 2am when the scheduled task silently does nothing.

    venv\\Scripts\\python.exe scripts\\preflight.py

Exit code 0 = ready to go live, 1 = something needs fixing.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"
results: list[tuple[str, str, str]] = []


def check(name: str, status: str, detail: str = ""):
    results.append((status, name, detail))


def _mask(v: str) -> str:
    return f"{v[:6]}...{v[-4:]} ({len(v)} chars)" if len(v) > 14 else "(short!)"


# --- interpreter + deps ----------------------------------------------------
v = sys.version_info
check("Python 3.10+", PASS if v >= (3, 10) else FAIL,
      f"{v.major}.{v.minor}.{v.micro}")

for mod, why in [("anthropic", "story generation"), ("edge_tts", "narration"),
                 ("requests", "all APIs"), ("discord", "Discord bot"),
                 ("flask", "control server"), ("googleapiclient", "YouTube"),
                 ("boto3", "Cloudflare R2 host"), ("PIL", "hook card")]:
    try:
        __import__(mod)
        check(f"import {mod}", PASS, why)
    except Exception as e:
        check(f"import {mod}", FAIL, f"{why} -- pip install -r requirements-full.txt ({e})")

# --- ffmpeg ----------------------------------------------------------------
try:
    from ffmpeg_setup import ensure_ffmpeg
    ok = ensure_ffmpeg()
except Exception as e:
    ok = False
    print(f"  (ffmpeg_setup error: {e})")
if ok and shutil.which("ffmpeg"):
    try:
        out = subprocess.run(["ffmpeg", "-version"], capture_output=True,
                             text=True, timeout=30).stdout.splitlines()[0]
    except Exception:
        out = "found"
    check("ffmpeg", PASS, out[:60])
else:
    check("ffmpeg", FAIL, "not on PATH and not in bin/ -- renders will fail")

# --- credentials in the environment ---------------------------------------
REQUIRED = {
    "ANTHROPIC_API_KEY": "story + caption generation",
    "DISCORD_BOT_TOKEN": "Discord control",
    "DISCORD_USER_ID": "Discord control",
    "IG_USER_ID": "Instagram posting",
    "IG_ACCESS_TOKEN": "Instagram posting",
}
OPTIONAL = {
    "VIDEO_HOST_ENDPOINT": "R2 host (IG falls back to litterbox without it)",
    "VIDEO_HOST_BUCKET": "R2 host",
    "VIDEO_HOST_KEY_ID": "R2 host",
    "VIDEO_HOST_SECRET": "R2 host",
    "VIDEO_HOST_PUBLIC_URL": "R2 host",
    "TIKTOK_CLIENT_KEY": "TikTok posting",
    "TIKTOK_CLIENT_SECRET": "TikTok posting",
    "REDDIT_CLIENT_ID": "real Reddit stories (pending API approval)",
    "REDDIT_CLIENT_SECRET": "real Reddit stories (pending API approval)",
}
for k, why in REQUIRED.items():
    val = os.environ.get(k, "")
    check(f"env {k}", PASS if val else FAIL,
          _mask(val) if val else f"MISSING -- {why}. Run scripts\\setup_env.bat then sign out/in.")
for k, why in OPTIONAL.items():
    val = os.environ.get(k, "")
    check(f"env {k}", PASS if val else WARN, _mask(val) if val else f"not set -- {why}")

# --- credential files that must travel with the folder --------------------
for f, why, required in [
    ("token.json", "YouTube auth (works on any machine -- published app)", True),
    ("client_secret.json", "YouTube OAuth client", True),
    ("accounts.json", "channel config", False),
    ("tiktok_token.json", "TikTok auth -- re-run `tiktok_upload.py auth` if absent", False),
]:
    p = ROOT / f
    check(f"file {f}", PASS if p.exists() else (FAIL if required else WARN),
          why if p.exists() else f"missing -- {why}")

# --- the pipeline can actually launch its own steps -----------------------
# run_all.py shells out to a venv interpreter whose path differs per OS. A
# Windows path on a Linux host meant every step silently failed to start while
# systemd still reported success -- 19h of no posts before anyone noticed.
try:
    sys.path.insert(0, str(ROOT))
    import run_all
    _ok = Path(run_all.PY).exists()
    check("pipeline interpreter", PASS if _ok else FAIL,
          run_all.PY if _ok else f"{run_all.PY} DOES NOT EXIST -- every step will fail silently")
except Exception as e:
    check("pipeline interpreter", FAIL, f"could not resolve: {str(e)[:70]}")

# --- content the renderer needs -------------------------------------------
# Recursive: footage is organised into themed subfolders (night_1080/,
# bright_biomes/, orbital_day/, gta/) and picked per video by
# accounts.pick_background_set. A non-recursive glob reported "EMPTY -- every
# render will fail" on a perfectly healthy install.
_fdir = ROOT / "footage"
clips = list(_fdir.rglob("*.mp4")) if _fdir.exists() else []
_sets = sorted({c.parent.name for c in clips if c.parent != _fdir})
check("footage/ clips", PASS if clips else FAIL,
      (f"{len(clips)} clip(s)" + (f" across {len(_sets)} set(s): {', '.join(_sets)}"
                                  if _sets else " (flat pool)"))
      if clips else "EMPTY -- every render will fail")

fonts = list((ROOT / "fonts").glob("*.ttf")) if (ROOT / "fonts").exists() else []
check("fonts/", PASS if fonts else WARN,
      f"{len(fonts)} font(s)" if fonts else "missing -- captions fall back to system fonts")

# --- writability -----------------------------------------------------------
try:
    (ROOT / "output").mkdir(exist_ok=True)
    probe = ROOT / "output" / ".preflight_probe"
    probe.write_text("ok")
    probe.unlink()
    check("output/ writable", PASS)
except Exception as e:
    check("output/ writable", FAIL, str(e))

# --- render profile --------------------------------------------------------
try:
    import config
    low = os.environ.get("MEDIA_MAKER_LOW_SPEC", "")
    check("render profile", PASS,
          f"{config.RENDER_WIDTH}x{config.RENDER_HEIGHT} crf{config.FFMPEG_CRF} "
          f"{config.FFMPEG_PRESET}" + (" [LOW_SPEC on]" if low else " [full quality]"))
    check("cleanup window", PASS, f"keeps {config.CLEANUP_KEEP_DAYS} days of renders")
except Exception as e:
    check("render profile", FAIL, str(e))

# --- live token validity ---------------------------------------------------
try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    c = Credentials.from_authorized_user_file(str(ROOT / "token.json"))
    if c.expired and c.refresh_token:
        c.refresh(Request())
    check("YouTube token refreshes", PASS if c.valid else FAIL,
          "durable refresh token OK" if c.valid else "re-run add_channel.py")
except Exception as e:
    check("YouTube token refreshes", FAIL, str(e)[:70])

try:
    import requests as _rq
    r = _rq.get(f"https://graph.instagram.com/v21.0/{os.environ.get('IG_USER_ID','')}",
                params={"fields": "username",
                        "access_token": os.environ.get("IG_ACCESS_TOKEN", "")}, timeout=20)
    j = r.json()
    check("Instagram token", PASS if "username" in j else FAIL,
          f"@{j['username']}" if "username" in j else str(j.get("error", {}).get("message", j))[:60])
except Exception as e:
    check("Instagram token", FAIL, str(e)[:70])

if (ROOT / "tiktok_token.json").exists():
    try:
        import tiktok_queue
        check("TikTok posting", PASS,
              "direct post available" if tiktok_queue.can_direct_post()
              else "drafts only (audit pending) -- expected")
    except Exception as e:
        check("TikTok posting", WARN, str(e)[:70])

# --- scheduled task --------------------------------------------------------
try:
    r = subprocess.run(["schtasks", "/query", "/tn", "MediaMakerHourly", "/fo", "list"],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        check("MediaMakerHourly task", WARN, "not registered yet -- see the deploy guide Step 6")
    else:
        state = "DISABLED" if "Disabled" in r.stdout else "enabled"
        check("MediaMakerHourly task", PASS, state)
except Exception as e:
    check("MediaMakerHourly task", WARN, str(e)[:60])

# --- report ----------------------------------------------------------------
print("\n" + "=" * 72)
print("  ParkourFlux preflight")
print("=" * 72)
for status, name, detail in results:
    print(f"  [{status}] {name:32} {detail}")
fails = [r for r in results if r[0] == FAIL]
warns = [r for r in results if r[0] == WARN]
print("=" * 72)
if fails:
    print(f"  {len(fails)} BLOCKER(S) -- fix these before going live:")
    for _s, n, d in fails:
        print(f"    - {n}: {d}")
else:
    print(f"  READY TO GO LIVE ({len(warns)} warning(s), none blocking).")
    print("  Remember: disable the OLD machine's task, or both will post the same videos.")
print("=" * 72)
sys.exit(1 if fails else 0)

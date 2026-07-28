"""
ffmpeg_setup.py
Puts ffmpeg/ffprobe on PATH portably so the pipeline runs on any machine --
the main PC and the Atom stick PC (which won't have the main PC's winget path).
Call ensure_ffmpeg() early in any entrypoint that renders video.

Lookup order:
  1. Already on PATH (e.g. installed system-wide via winget/choco/apt) -> use it.
  2. A project-bundled bin/ folder (drop ffmpeg.exe + ffprobe.exe there).
  3. The main PC's winget install (kept as a convenience fallback).
"""

import os
import shutil
from pathlib import Path

_ROOT = Path(__file__).parent
_FALLBACKS = [
    _ROOT / "bin",
    Path(r"C:\Users\Krish\AppData\Local\Microsoft\WinGet\Packages"
         r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
         r"\ffmpeg-8.1.2-full_build\bin"),
]


def ensure_ffmpeg() -> bool:
    """Ensure `ffmpeg` is resolvable. Returns True if found, False otherwise."""
    if shutil.which("ffmpeg"):
        return True
    for cand in _FALLBACKS:
        if (cand / "ffmpeg.exe").exists():
            os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + str(cand)
            return True
    return False

"""
captions.py
Builds the punchy, word-by-word (or 2-3 word) burn-in captions typical of
this format, as an .ass subtitle file ffmpeg can hard-burn onto the video.
"""

import json
from pathlib import Path

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Outline, Shadow, Alignment, MarginL, MarginR, MarginV
Style: Default,Rubik Black,104,&H00FFFFFF,&H00202020,&H80000000,1,7,0,2,80,80,650

[Events]
Format: Layer, Start, End, Style, Text
"""


def _ms_to_ass_time(ms: int) -> str:
    h = ms // 3_600_000
    m = (ms % 3_600_000) // 60_000
    s = (ms % 60_000) // 1000
    cs = (ms % 1000) // 10
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def build_caption_file(word_timings: list[dict], out_path: str | Path, words_per_group: int = 2):
    """
    word_timings: list of {"word": str, "start_ms": int, "end_ms": int}
    Groups words (default 2 at a time) into caption events, all-caps,
    which is the standard style for this format.
    """
    lines = [ASS_HEADER]
    for i in range(0, len(word_timings), words_per_group):
        group = word_timings[i:i + words_per_group]
        text = " ".join(w["word"] for w in group).upper()
        start = _ms_to_ass_time(group[0]["start_ms"])
        end = _ms_to_ass_time(group[-1]["end_ms"])
        lines.append(f"Dialogue: 0,{start},{end},Default,{text}")

    Path(out_path).write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    # smoke test with fake timings
    fake = [
        {"word": "my", "start_ms": 0, "end_ms": 200},
        {"word": "high", "start_ms": 200, "end_ms": 400},
        {"word": "school", "start_ms": 400, "end_ms": 700},
        {"word": "had", "start_ms": 700, "end_ms": 900},
        {"word": "a", "start_ms": 900, "end_ms": 950},
        {"word": "locker.", "start_ms": 950, "end_ms": 1400},
    ]
    build_caption_file(fake, "output/test_captions.ass")
    print("wrote output/test_captions.ass")

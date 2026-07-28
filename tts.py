"""
tts.py
Turns story beats into a narrated voice track PLUS word-level timestamps
(needed for the punchy word-by-word captions this format relies on).

Two backends:
  - "edge"       Free, no API key, decent quality. Good for testing/volume.
  - "elevenlabs" Paid, much more natural/emotive. Swap in once you pick a plan.

Requires real internet access (this will NOT run inside the build sandbox --
run it on your own machine).
"""

import asyncio
import json
from dataclasses import dataclass, asdict
from pathlib import Path

# ---- pick a default voice; browse more with `edge-tts --list-voices` ----
DEFAULT_EDGE_VOICE = "en-US-AndrewMultilingualNeural"  # natural/dynamic, far less monotone than GuyNeural
# alt options: en-US-BrianMultilingualNeural, en-US-ChristopherNeural, en-US-AriaNeural
DEFAULT_EDGE_RATE = "+15%"                   # fast like the winning channels, still clear
                                             # (word-by-word captions carry comprehension)


@dataclass
class WordTiming:
    word: str
    start_ms: int
    end_ms: int


import re


def make_speakable(text: str) -> str:
    """
    Rewrite written-style tokens into what a narrator would actually say,
    so the TTS read flows naturally. Written surfaces (cards, titles) keep
    the original text -- this transform is for narration only.
    """
    # "r/AITAH" or bare "AITAH"/"AITA" -> spoken form
    text = re.sub(r"\br/AITAH?\b", "AITAH", text)
    text = re.sub(r"\bAITAH?\b", "am I the a-hole", text)
    # Capitalize if it starts a sentence
    text = re.sub(r"(^|[.!?]\s+)am I", lambda m: m.group(1) + "Am I", text)
    # "(28F)" / "(34M)" age tags -> "28, female," / "34, male,"
    text = re.sub(r"\s*\((\d+)\s*F\)", lambda m: f", {m.group(1)}, female,", text)
    text = re.sub(r"\s*\((\d+)\s*M\)", lambda m: f", {m.group(1)}, male,", text)
    return text


async def _edge_tts_generate(text: str, out_path: Path, voice: str = DEFAULT_EDGE_VOICE, rate: str = DEFAULT_EDGE_RATE):
    import edge_tts

    communicate = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    submaker = edge_tts.SubMaker()
    words: list[WordTiming] = []

    with open(out_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                words.append(WordTiming(
                    word=chunk["text"],
                    start_ms=int(chunk["offset"] / 10_000),
                    end_ms=int((chunk["offset"] + chunk["duration"]) / 10_000),
                ))
    return words


def generate_voice_edge(text: str, out_path: str | Path, voice: str = DEFAULT_EDGE_VOICE, rate: str = DEFAULT_EDGE_RATE) -> list[WordTiming]:
    out_path = Path(out_path)
    words = asyncio.run(_edge_tts_generate(text, out_path, voice, rate))
    return words


def generate_voice_elevenlabs(text: str, out_path: str | Path, api_key: str, voice_id: str) -> list[WordTiming]:
    """
    Higher quality option. Sign up at https://elevenlabs.io, grab an API key
    and a voice_id. This uses the 'with timestamps' endpoint so we still get
    word-level timing for captions.
    """
    import requests

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"
    resp = requests.post(
        url,
        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
        json={"text": text, "model_id": "eleven_multilingual_v2"},
    )
    resp.raise_for_status()
    data = resp.json()

    import base64
    Path(out_path).write_bytes(base64.b64decode(data["audio_base64"]))

    # Reconstruct word-level timing from character alignment
    chars = data["alignment"]["characters"]
    starts = data["alignment"]["character_start_times_seconds"]
    ends = data["alignment"]["character_end_times_seconds"]

    words, cur_word, w_start = [], "", None
    for ch, s, e in zip(chars, starts, ends):
        if ch == " ":
            if cur_word:
                words.append(WordTiming(cur_word, int(w_start * 1000), int(e * 1000)))
                cur_word, w_start = "", None
        else:
            if w_start is None:
                w_start = s
            cur_word += ch
    if cur_word:
        words.append(WordTiming(cur_word, int(w_start * 1000), int(ends[-1] * 1000)))
    return words


def save_word_timings(words: list[WordTiming], path: str | Path):
    Path(path).write_text(json.dumps([asdict(w) for w in words], indent=2))


if __name__ == "__main__":
    sample = "This is a test of the free edge text to speech voice."
    ts = generate_voice_edge(sample, "voice/test.mp3")
    save_word_timings(ts, "voice/test_timings.json")
    print(f"Generated {len(ts)} word timings")

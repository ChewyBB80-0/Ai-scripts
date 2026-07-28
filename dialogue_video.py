"""
dialogue_video.py
PROTOTYPE -- two-character dialogue videos for the car channel.

Format (the Brian/Peter structure, with original characters):
a grizzled veteran muscle car explains something about cars while a rookie asks
the questions a real person would actually ask. Every question is a micro-hook,
and the series is numbered so following it is how you get the next one.

Why this is a separate module: the main pipeline (bot.py) narrates one story
with one voice. This needs a per-line voice, merged word timings across many
audio clips, and a speaker-aware caption style -- different enough that bolting
it onto bot.run_once would tangle both.

    python dialogue_video.py                 # generate + render one episode
    python dialogue_video.py --topic "..."   # force the subject
    python dialogue_video.py --episode 3     # set the episode number
"""

import argparse
import asyncio
import json
import os
import random
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import config
from captions import build_caption_file
from ffmpeg_setup import ensure_ffmpeg

ROOT = Path(__file__).parent
OUT = ROOT / "output" / "car_channel"

# --- the cast ---------------------------------------------------------------
# Original characters. The comedy is the MISMATCH (a worn-out car dispensing
# hard truths), not any resemblance to an existing character.
VET = {"voice": "en-US-ChristopherNeural", "rate": "-6%", "pitch": "-25Hz"}
ROOKIE = {"voice": "en-US-AndrewMultilingualNeural", "rate": "+8%", "pitch": "+25Hz"}
SPEAKERS = {"VET": VET, "ROOKIE": ROOKIE}

GAP_MS = 180          # beat between lines so it reads as a conversation

# Closing subscribe ask, spoken by VET after the last line. An explainer channel
# earns subscribers differently from a story channel: a story is finished when
# it ends, but a tip implies there are more tips -- so the ask names the ongoing
# value ("learn more") rather than just asking for the click.
END_CTA = True
END_CTA_LINE = "Want to learn more? Hit that subscribe button."


@dataclass
class Line:
    speaker: str
    text: str


def write_episode(topic: str = "", episode: int = 1, api_key: str | None = None) -> dict:
    """Ask Claude for a dialogue script. Returns {title, topic, lines[]}."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
    subject = topic or "pick one specific way drivers waste money or damage their car"
    prompt = f"""Write a short two-character dialogue for a vertical short-form video
about cars. The channel teaches everyday drivers things that save them money.

CHARACTERS (use these exact speaker tags):
- VET: an old, worn-out muscle car. Decades on the road, seen every scam, dry
  and blunt but never mean. He is the one who KNOWS things.
- ROOKIE: a brand-new car, eager and a bit naive. He asks the questions a real
  person would actually ask -- including the slightly dumb ones.

TOPIC: {subject}

RULES:
- 8 to 12 lines total, alternating, starting with ROOKIE or VET.
- Each line is ONE or TWO short sentences. This is spoken aloud -- keep it tight.
- Line 1 must be a HOOK: open a loop or state something surprising and specific
  in the first sentence. No throat-clearing, no greetings, no "hey guys".
- Include at least one CONCRETE number (a real dollar amount, interval, or
  percentage). Specificity is what makes it feel true.
- The information must be genuinely accurate and useful -- real, checkable car
  advice. Never invent a fake statistic.
- VET gets the payoff line. End on ONE short line that either lands the money
  saved or baits a comment (e.g. "How many of you are guilty of this?").
- Keep it PG. Dry humour, not insults.
- Correct grammar and punctuation -- this is displayed on screen as captions.

Return ONLY JSON, no other text:
{{"title": "<scroll-stopping title, under 80 chars, curiosity-driven>",
  "topic": "<3-5 word subject label>",
  "lines": [{{"speaker": "ROOKIE", "text": "..."}}, {{"speaker": "VET", "text": "..."}}]}}"""

    r = client.messages.create(model="claude-sonnet-5", max_tokens=1200,
                               thinking={"type": "disabled"},
                               messages=[{"role": "user", "content": prompt}])
    raw = next(b.text for b in r.content if b.type == "text").strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
    data = json.loads(raw)
    data["episode"] = episode
    return data


async def _speak(text: str, spk: dict, out_path: Path):
    """One line -> mp3 + word timings (relative to that line)."""
    import edge_tts

    c = edge_tts.Communicate(text, spk["voice"], rate=spk["rate"],
                             pitch=spk["pitch"], boundary="WordBoundary")
    words = []
    with open(out_path, "wb") as f:
        async for chunk in c.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                words.append({"word": chunk["text"],
                              "start_ms": int(chunk["offset"] / 10_000),
                              "end_ms": int((chunk["offset"] + chunk["duration"]) / 10_000)})
    return words


def _duration_ms(path: Path) -> int:
    r = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    try:
        return int(float(r.stdout.strip()) * 1000)
    except ValueError:
        return 0


def build_audio(lines: list[Line], stem: str) -> tuple[Path, list[dict]]:
    """Render every line in its speaker's voice, concatenate with a beat
    between them, and shift each line's word timings by where it actually
    starts -- otherwise captions would restart at zero on every line."""
    OUT.mkdir(parents=True, exist_ok=True)
    parts, all_words, offset = [], [], 0
    silence = OUT / "_gap.mp3"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "anullsrc=r=24000:cl=mono", "-t", f"{GAP_MS/1000}",
                    "-q:a", "9", str(silence)], capture_output=True)

    for i, ln in enumerate(lines):
        p = OUT / f"_{stem}_{i:02d}.mp3"
        words = asyncio.run(_speak(ln.text, SPEAKERS[ln.speaker], p))
        for w in words:
            all_words.append({"word": w["word"],
                              "start_ms": w["start_ms"] + offset,
                              "end_ms": w["end_ms"] + offset})
        offset += _duration_ms(p) + GAP_MS
        parts += [p, silence]

    listf = OUT / f"_{stem}_concat.txt"
    listf.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    voice = OUT / f"{stem}.mp3"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                    "-i", str(listf), "-c", "copy", str(voice)], capture_output=True)

    for p in set(parts):
        p.unlink(missing_ok=True)
    listf.unlink(missing_ok=True)
    return voice, all_words


def render(script: dict, footage: list[Path]) -> Path:
    from assemble import assemble_video_dynamic

    lines = [Line(l["speaker"], l["text"]) for l in script["lines"]]
    # VET delivers the closing subscribe ask -- he's the authority voice, so it
    # lands as an offer of more knowledge rather than a plea for a click.
    if END_CTA:
        lines.append(Line("VET", END_CTA_LINE))
    stem = re.sub(r"[^a-z0-9]+", "_", script["topic"].lower()).strip("_")[:40] or "episode"
    stem = f"car_{stem}"

    voice, words = build_audio(lines, stem)
    ass = OUT / f"{stem}_captions.ass"
    build_caption_file(words, ass)

    out = OUT / f"{stem}.mp4"
    assemble_video_dynamic([str(f) for f in footage], str(voice), str(ass), str(out))
    Path(OUT / f"{stem}_script.json").write_text(json.dumps(script, indent=2),
                                                 encoding="utf-8")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", default="")
    ap.add_argument("--episode", type=int, default=1)
    ap.add_argument("--footage", default="footage/gta")
    args = ap.parse_args()

    ensure_ffmpeg()
    clips = sorted((ROOT / args.footage).glob("*.mp4"))
    if not clips:
        raise SystemExit(f"No footage in {args.footage}/")

    print("Writing the episode...")
    script = write_episode(args.topic, args.episode)
    print(f"\nTITLE: {script['title']}\n")
    for l in script["lines"]:
        print(f"  {l['speaker']:6} {l['text']}")

    print("\nRendering...")
    out = render(script, clips)
    print(f"\nDone -> {out}")


if __name__ == "__main__":
    main()

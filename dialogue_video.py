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
# Original characters, deliberately archetypes rather than identifiable models:
# "beat-up 70s muscle" and "shiny modern compact". A recognisable real car given
# a face is two protected things at once -- vehicle trade dress, which makers do
# enforce, plus the anthropomorphised-car look that reads as a certain film. The
# joke is the MISMATCH, not the badge. Faces put the eyes in the HEADLIGHTS,
# which is the older convention and visually distinct from windscreen-eyes.
#
# VOICES: the first pass used two US male neural voices and pitch-shifted them
# +/-25Hz. They still blurred together -- a shared timbre survives pitch
# shifting. Changing the ACCENT is the lever that actually works: you can tell
# them apart inside one word.
VET = {"name": "Rusty", "voice": "en-US-ChristopherNeural",
       "rate": "-10%", "pitch": "-40Hz", "side": "left",
       "faces": ["deadpan", "smug", "eyeroll", "explaining"],
       "default_face": "deadpan"}
ROOKIE = {"name": "Sparky", "voice": "en-GB-RyanNeural",
          "rate": "+10%", "pitch": "+30Hz", "side": "right",
          "faces": ["happy", "question", "shocked", "delighted"],
          "default_face": "happy"}
SPEAKERS = {"VET": VET, "ROOKIE": ROOKIE}

# Character art: branding/carveteran/faces/<name>_<emotion>.png, transparent.
FACE_DIR = ROOT / "branding" / "carveteran" / "faces"
# Fraction of frame width the character occupies. Big enough to read the
# expression on a phone, small enough to leave the captions alone.
FACE_SCALE = 0.42

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
    emotion: str = ""       # which face to show; falls back to the default


def write_episode(topic: str = "", episode: int = 1, api_key: str | None = None) -> dict:
    """Ask Claude for a dialogue script. Returns {title, topic, lines[]}."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
    subject = topic or "pick one specific way drivers waste money or damage their car"
    prompt = f"""Write a short two-character dialogue for a vertical short-form video
about cars. The channel teaches everyday drivers things that save them money.

CHARACTERS (use these exact speaker tags):
- VET, called Rusty: an old, worn-out muscle car. Decades on the road, seen
  every scam, dry and blunt but never mean. He is the one who KNOWS things.
- ROOKIE, called Sparky: a brand-new compact car, eager and a bit naive. He asks
  the questions a real person would actually ask -- including the dumb ones.

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

EXPRESSIONS -- every line also carries the face that character pulls while
saying it. This is what makes the characters feel alive, so pick the one that
actually fits the line rather than defaulting.
- VET (Rusty) may use: deadpan (flat, unimpressed -- his default),
  smug (he is about to reveal the catch), eyeroll (the industry has done
  something stupid again), explaining (delivering the actual information).
- ROOKIE (Sparky) may use: happy (his default), question (he is ASKING --
  use this for any line ending in a question mark), shocked (he just heard a
  number he did not like), delighted (he just learned something great).

Return ONLY JSON, no other text:
{{"title": "<scroll-stopping title, under 80 chars, curiosity-driven>",
  "topic": "<3-5 word subject label>",
  "lines": [{{"speaker": "ROOKIE", "text": "...", "emotion": "question"}},
            {{"speaker": "VET", "text": "...", "emotion": "smug"}}]}}"""

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

    spans = []          # (speaker, emotion, start_ms, end_ms) -- drives the faces
    for i, ln in enumerate(lines):
        p = OUT / f"_{stem}_{i:02d}.mp3"
        words = asyncio.run(_speak(ln.text, SPEAKERS[ln.speaker], p))
        for w in words:
            all_words.append({"word": w["word"],
                              "start_ms": w["start_ms"] + offset,
                              "end_ms": w["end_ms"] + offset})
        dur = _duration_ms(p)
        spk = SPEAKERS[ln.speaker]
        face = ln.emotion if ln.emotion in spk["faces"] else spk["default_face"]
        # Hold the face through the trailing gap so the character does not blink
        # out between lines -- it should feel like they are waiting their turn.
        spans.append((ln.speaker, face, offset, offset + dur + GAP_MS))
        offset += dur + GAP_MS
        parts += [p, silence]

    listf = OUT / f"_{stem}_concat.txt"
    listf.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    voice = OUT / f"{stem}.mp3"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                    "-i", str(listf), "-c", "copy", str(voice)], capture_output=True)

    for p in set(parts):
        p.unlink(missing_ok=True)
    listf.unlink(missing_ok=True)
    return voice, all_words, spans


def overlay_faces(video: Path, spans: list, out: Path) -> Path:
    """Composite the speaking character onto the finished video.

    A second ffmpeg pass rather than a change to assemble_video_dynamic: that
    function is shared with the story pipeline, and timed per-line overlays are
    specific to dialogue. Keeping it here means the main channel cannot break
    because of this.

    Each speaker keeps a FIXED side -- Rusty left, Sparky right -- so position
    becomes a second cue for who is talking, on top of the voice and the face.
    Returns the original video untouched if anything is missing or ffmpeg fails;
    a missing PNG must not cost the whole render.
    """
    used = sorted({(sp, face) for sp, face, _, _ in spans})
    paths = {}
    for sp, face in used:
        p = FACE_DIR / f"{SPEAKERS[sp]['name'].lower()}_{face}.png"
        if not p.exists():
            print(f"  (missing face {p.name} -- skipping the overlay pass)")
            return video
        paths[(sp, face)] = p
    if not paths:
        return video

    idx = {k: i + 1 for i, k in enumerate(paths)}      # input 0 is the video
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(video)]
    for k in paths:
        cmd += ["-i", str(paths[k])]

    # Scale each face once, then overlay it during each of its time ranges.
    # Sized off config.RENDER_WIDTH rather than main_w: scale cannot reference
    # the main input's dimensions, and this keeps it correct on the low-spec
    # 720-wide profile as well as 1080.
    fw = int(config.RENDER_WIDTH * FACE_SCALE)
    fc = [f"[{i}:v]scale={fw}:-1[f{i}]" for i in idx.values()]
    last, n = "0:v", 0
    for (sp, face), i in idx.items():
        ranges = [(a, b) for s, f, a, b in spans if s == sp and f == face]
        enable = "+".join(f"between(t,{a/1000:.2f},{b/1000:.2f})" for a, b in ranges)
        x = "40" if SPEAKERS[sp]["side"] == "left" else "main_w-overlay_w-40"
        nxt = f"v{n}"
        fc.append(f"[{last}][f{i}]overlay=x={x}:y=main_h-overlay_h-320:"
                  f"enable='{enable}'[{nxt}]")
        last, n = nxt, n + 1

    cmd += ["-filter_complex", ";".join(fc), "-map", f"[{last}]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-c:a", "copy", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        print(f"  (face overlay failed, keeping the plain render: "
              f"{r.stderr.strip().splitlines()[-1] if r.stderr.strip() else '?'})")
        return video
    return out


def render(script: dict, footage: list[Path]) -> Path:
    from assemble import assemble_video_dynamic

    lines = [Line(l["speaker"], l["text"], l.get("emotion", "")) for l in script["lines"]]
    # VET delivers the closing subscribe ask -- he's the authority voice, so it
    # lands as an offer of more knowledge rather than a plea for a click.
    if END_CTA:
        lines.append(Line("VET", END_CTA_LINE, "smug"))
    stem = re.sub(r"[^a-z0-9]+", "_", script["topic"].lower()).strip("_")[:40] or "episode"
    stem = f"car_{stem}"

    voice, words, spans = build_audio(lines, stem)
    ass = OUT / f"{stem}_captions.ass"
    build_caption_file(words, ass)

    plain = OUT / f"{stem}_plain.mp4"
    assemble_video_dynamic([str(f) for f in footage], str(voice), str(ass), str(plain))

    out = OUT / f"{stem}.mp4"
    final = overlay_faces(plain, spans, out)
    if final != out:                       # overlay skipped -- keep one artefact
        plain.replace(out)
    else:
        plain.unlink(missing_ok=True)
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

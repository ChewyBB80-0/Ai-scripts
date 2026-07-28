"""
main.py
Full pipeline: story -> voice -> captions -> assembled video.

Usage:
    python3 main.py --background footage/my_parkour_clip.mp4
    python3 main.py --background footage/my_parkour_clip.mp4 --new-story --topic "roommate horror"
    python3 main.py --background footage/my_parkour_clip.mp4 --voice elevenlabs

Run this on a machine with real internet access (not the build sandbox).
"""

import argparse
import json
from pathlib import Path

from story_bank import get_random_story, generate_story_via_claude
from tts import generate_voice_edge, generate_voice_elevenlabs, save_word_timings, WordTiming
from captions import build_caption_file
from assemble import assemble_video


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--background", required=True, help="Path to your recorded Minecraft parkour clip")
    ap.add_argument("--music", default=None, help="Optional background music bed (kept quiet under narration)")
    ap.add_argument("--voice", choices=["edge", "elevenlabs"], default="edge")
    ap.add_argument("--elevenlabs-key", default=None)
    ap.add_argument("--elevenlabs-voice-id", default=None)
    ap.add_argument("--new-story", action="store_true", help="Generate a fresh story via Claude instead of using the local bank")
    ap.add_argument("--topic", default="", help="Optional topic hint for --new-story")
    ap.add_argument("--out", default="output/final.mp4")
    args = ap.parse_args()

    # 1. Get the story
    if args.new_story:
        story = generate_story_via_claude(topic_hint=args.topic)
    else:
        story = get_random_story()
    print(f"Story: {story['title']}")
    full_text = " ".join(story["beats"])

    # 2. Voice + word timings
    voice_out = f"voice/{story['title']}.mp3"
    if args.voice == "edge":
        words = generate_voice_edge(full_text, voice_out)
    else:
        words = generate_voice_elevenlabs(
            full_text, voice_out, api_key=args.elevenlabs_key, voice_id=args.elevenlabs_voice_id
        )
    save_word_timings(words, f"voice/{story['title']}_timings.json")
    print(f"Voice generated: {len(words)} words")

    # 3. Captions
    caption_path = f"output/{story['title']}_captions.ass"
    word_dicts = [w.__dict__ if isinstance(w, WordTiming) else w for w in words]
    build_caption_file(word_dicts, caption_path)

    # 4. Assemble
    result = assemble_video(
        background_path=args.background,
        voice_path=voice_out,
        captions_ass_path=caption_path,
        out_path=args.out,
        music_path=args.music,
    )
    print(f"Done -> {result}")


if __name__ == "__main__":
    main()

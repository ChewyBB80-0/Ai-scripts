"""
assemble.py
Combines: background footage (looped/cropped to 9:16) + voice track +
burned-in captions -> final vertical video ready to post.

Requires ffmpeg on PATH (already standard on most systems / your Ubuntu box).
"""

import os
import random
import shutil
import subprocess
from pathlib import Path

import config

# Project-bundled fonts (Rubik Black for captions) so renders don't depend on
# system-installed fonts. libass reads this via the ass filter's fontsdir.
# Kept relative -- an absolute Windows path (drive-letter colon + spaces) breaks
# ffmpeg filtergraph parsing; the pipeline always runs from the project dir.
FONTS_DIR = "fonts"


def _ass(captions_path) -> str:
    return f"ass={captions_path}:fontsdir={FONTS_DIR}"


def get_duration_seconds(path: str | Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def assemble_video(
    background_path: str | Path,
    voice_path: str | Path,
    captions_ass_path: str | Path,
    out_path: str | Path,
    music_path: str | Path | None = None,
    music_volume: float = 0.08,
):
    """
    background_path: your recorded Minecraft parkour clip (any length -- it
                      loops/trims to match the voice track automatically)
    voice_path:       narration audio from tts.py
    captions_ass_path: subtitle file from captions.py
    music_path:        optional quiet background music bed
    """
    background_path, voice_path, out_path = Path(background_path), Path(voice_path), Path(out_path)
    voice_dur = get_duration_seconds(voice_path)

    # Crop/scale background to the configured 9:16 size, loop it to cover the
    # voice track length, then hard-burn the caption file, then mux audio.
    w, h = config.RENDER_WIDTH, config.RENDER_HEIGHT
    vf = (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},"
        f"{_ass(captions_ass_path)}"
    )

    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", str(background_path),
        "-i", str(voice_path),
    ]
    if music_path:
        cmd += ["-i", str(music_path)]

    cmd += ["-t", str(voice_dur), "-vf", vf]

    if music_path:
        # duck music under the voice
        cmd += [
            "-filter_complex",
            f"[2:a]volume={music_volume},aloop=loop=-1:size=2e9[music];"
            f"[1:a][music]amix=inputs=2:duration=first:dropout_transition=2[aout]",
            "-map", "0:v", "-map", "[aout]",
        ]
    else:
        cmd += ["-map", "0:v", "-map", "1:a"]

    cmd += [
        "-c:v", "libx264", "-preset", config.FFMPEG_PRESET, "-crf", config.FFMPEG_CRF,
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(out_path),
    ]

    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return out_path


def _extract_segment(src: Path, start: float, dur: float, width: int, height: int, out: Path):
    subprocess.run([
        "ffmpeg", "-y", "-ss", f"{start:.2f}", "-i", str(src), "-t", f"{dur:.2f}",
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,"
               f"crop={width}:{height},fps=30",
        "-an", "-c:v", "libx264", "-preset", config.FFMPEG_PRESET, "-crf", config.FFMPEG_CRF,
        "-pix_fmt", "yuv420p", str(out),
    ], check=True, capture_output=True, text=True)


def _build_track(paths: list[Path], duration: float, width: int, height: int,
                 tmp_dir: Path, tag: str, cut_min: float, cut_max: float) -> Path:
    """Stitch short random segments from random clips into one fast-cut track."""
    segs, total, i = [], 0.0, 0
    while total < duration + 1.0:
        src = Path(random.choice(paths))
        clip_dur = get_duration_seconds(src)
        seg = random.uniform(cut_min, cut_max)
        if clip_dur <= seg + 0.5:
            start, seg = 0.0, min(seg, clip_dur)
        else:
            start = random.uniform(0, clip_dur - seg)
        out = tmp_dir / f"{tag}_{i:03d}.mp4"
        _extract_segment(src, start, seg, width, height, out)
        segs.append(out)
        total += seg
        i += 1

    concat_list = tmp_dir / f"{tag}_list.txt"
    concat_list.write_text("".join(f"file '{s.resolve().as_posix()}'\n" for s in segs))
    track = tmp_dir / f"{tag}_track.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
         "-c", "copy", str(track)],
        check=True, capture_output=True, text=True,
    )
    return track


def assemble_video_dynamic(
    footage_paths: list[str | Path],
    voice_path: str | Path,
    captions_ass_path: str | Path,
    out_path: str | Path,
    satisfying_paths: list[str | Path] | None = None,
    music_path: str | Path | None = None,
    music_volume: float = 0.08,
    cut_min: float = 3.5,
    cut_max: float = 5.5,
    hook_card_path: str | Path | None = None,
    hook_card_seconds: float | None = None,
    end_card_path: str | Path | None = None,
    end_card_seconds: float = 6.0,
):
    """
    Fast-cut assembly: background is stitched from short random segments of
    the footage pool. If satisfying_paths is given, renders split-screen --
    parkour top half, satisfying footage bottom half. If hook_card_path is
    given, that PNG is overlaid near the top of the frame -- for the whole
    video, or only the first hook_card_seconds when set (i.e. while the
    hook/title is being narrated).
    """
    voice_dur = get_duration_seconds(voice_path)
    # Unique temp dir per process so a manual post and the hourly autonomous run
    # (or two accounts) never wipe each other's in-flight segments.
    #
    # config.TEMP_DIR can point this at a RAM disk (/dev/shm on Linux). Assembly
    # writes and re-reads dozens of small segment files, which is the access
    # pattern spinning disks are worst at -- on an HDD host that's most of the
    # render's I/O cost, and tmpfs removes it entirely. Falls back to output/ if
    # the configured path isn't usable, so this can never block a render.
    _base = getattr(config, "TEMP_DIR", "") or "output"
    tmp_dir = Path(_base) / f"tmp_segments_{os.getpid()}"
    try:
        tmp_dir.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        tmp_dir = Path("output") / f"tmp_segments_{os.getpid()}"
    shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir(parents=True)

    W, H = config.RENDER_WIDTH, config.RENDER_HEIGHT
    if satisfying_paths:
        video_inputs = [
            _build_track(footage_paths, voice_dur, W, H // 2, tmp_dir, "top", cut_min, cut_max),
            _build_track(satisfying_paths, voice_dur, W, H // 2, tmp_dir, "bottom", cut_min, cut_max),
        ]
        fc = "[0:v][1:v]vstack=inputs=2[bgv]"
    else:
        video_inputs = [
            _build_track(footage_paths, voice_dur, W, H, tmp_dir, "bg", cut_min, cut_max),
        ]
        fc = "[0:v]null[bgv]"
    if hook_card_path:
        card_idx = len(video_inputs)
        # The card PNG is drawn at a fixed ~1000px width; scale it to a
        # consistent fraction of the frame so it fits (and looks) the same at
        # any RENDER_WIDTH (e.g. 720p on the stick). Negligible on 1080p.
        card_w = int(config.RENDER_WIDTH * 0.93)
        # Slide down into place over the first 0.45s; fade away over 0.6s as
        # the hook narration ends (fade start = hook_card_seconds - 0.3).
        if hook_card_seconds:
            fade_st = max(hook_card_seconds - 0.3, 0.6)
            card_pre = (f"[{card_idx}:v]fps=30,format=rgba,scale={card_w}:-1,"
                        f"fade=t=out:st={fade_st:.2f}:d=0.6:alpha=1[cardf];")
        else:
            card_pre = f"[{card_idx}:v]fps=30,format=rgba,scale={card_w}:-1[cardf];"
        fc += (f";[bgv]{_ass(captions_ass_path)}[capped];{card_pre}"
               f"[capped][cardf]overlay=x=(W-w)/2:y='-h+(140+h)*min(t/0.45,1)'[vout]")
        voice_idx = card_idx + 1
    else:
        fc += f";[bgv]{_ass(captions_ass_path)}[vout]"
        voice_idx = len(video_inputs)

    # Closing CTA card: fades in over the last few seconds and holds to the end.
    # The spoken CTA alone is easy to miss while the footage keeps scrolling --
    # a held visual with the handle is what actually converts a viewer.
    if end_card_path:
        end_idx = voice_idx                     # the end card takes this slot
        voice_idx += 1
        cta_st = max(voice_dur - end_card_seconds, 0.5)
        card_w = int(config.RENDER_WIDTH * 0.86)
        fc += (f";[{end_idx}:v]fps=30,format=rgba,scale={card_w}:-1,"
               f"fade=t=in:st={cta_st:.2f}:d=0.5:alpha=1[endc];"
               f"[vout][endc]overlay=x=(W-w)/2:y=(H-h)/2:"
               f"enable='gte(t,{cta_st:.2f})'[vout2]")
        vout_label = "[vout2]"
    else:
        vout_label = "[vout]"
    music_idx = voice_idx + 1

    cmd = ["ffmpeg", "-y"]
    for v in video_inputs:
        cmd += ["-i", str(v)]
    if hook_card_path:
        cmd += ["-loop", "1", "-i", str(hook_card_path)]
    if end_card_path:
        cmd += ["-loop", "1", "-i", str(end_card_path)]
    cmd += ["-i", str(voice_path)]
    if music_path:
        cmd += ["-i", str(music_path)]
        fc += (f";[{music_idx}:a]volume={music_volume},aloop=loop=-1:size=2e9[music];"
               f"[{voice_idx}:a][music]amix=inputs=2:duration=first:dropout_transition=2[aout]")
        audio_map = "[aout]"
    else:
        audio_map = f"{voice_idx}:a"

    cmd += [
        "-filter_complex", fc,
        "-map", vout_label, "-map", audio_map,
        "-t", str(voice_dur),
        "-c:v", "libx264", "-preset", config.FFMPEG_PRESET, "-crf", config.FFMPEG_CRF,
        "-c:a", "aac", "-b:a", "192k",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    shutil.rmtree(tmp_dir, ignore_errors=True)
    return Path(out_path)


if __name__ == "__main__":
    # ---- Smoke test using generated placeholder background + silent audio ----
    # Proves the pipeline mechanics (loop, crop, caption burn-in, mux) work
    # end-to-end. Swap in real footage/voice for actual output.
    import subprocess as sp

    Path("footage").mkdir(exist_ok=True)
    Path("voice").mkdir(exist_ok=True)
    Path("output").mkdir(exist_ok=True)

    # 5s fake "background" (moving color pattern, 16:9 landscape like raw gameplay capture)
    sp.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i",
        "testsrc2=size=1920x1080:rate=30:duration=5",
        "footage/placeholder_bg.mp4",
    ], check=True, capture_output=True)

    # 6s silent "voice" track
    sp.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-t", "6", "voice/placeholder_voice.mp3",
    ], check=True, capture_output=True)

    from captions import build_caption_file
    fake_words = [
        {"word": w, "start_ms": i * 700, "end_ms": i * 700 + 600}
        for i, w in enumerate(["MY", "HIGH", "SCHOOL", "HAD", "A", "LOCKER"])
    ]
    build_caption_file(fake_words, "output/placeholder_captions.ass")

    result = assemble_video(
        "footage/placeholder_bg.mp4",
        "voice/placeholder_voice.mp3",
        "output/placeholder_captions.ass",
        "output/placeholder_final.mp4",
    )
    print(f"Pipeline smoke test OK -> {result}")

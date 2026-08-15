# Media Maker — Operating Instructions

This project generates and posts short-form vertical videos to YouTube,
Instagram, and eventually TikTok.

## Multi-Agent Cowork

This project is worked on by **both Claude Code and Antigravity (Gemini)**.

**Always read `COWORK.md` at session start.** It is the shared task board:
- Check "In Progress" before editing any file to avoid conflicts with the other agent.
- Pick up tasks from "To Do" tagged `[Claude]` or `[Either]`.
- When done, move the task to "Done" with a date and summary.
- Use the "Handoff Queue" to pass context to Antigravity.
- Antigravity's instructions are in `GEMINI.md` — don't modify that file.


It runs **two channels**, and they make different things:

| account | makes | pipeline |
|---|---|---|
| `parkourflux` | narrated AI story over Minecraft parkour footage | `bot.py` story path |
| `carveteran` | two-voice car-tips dialogue over driving footage | `dialogue_video.py` |

`bot.run_once()` dispatches on the account's `content_type`, so one command
serves both and every per-account setting (footage tree, daily target, platform
flags, tags, post log) comes from `accounts.json`. Adding a third channel is a
config change, not a code change.

**Never assume one channel.** Anything that reads `output/channel_stats.json`
or `output/post_log.csv` directly is reading the FIRST channel only — those are
`parkourflux`'s files because its `out_dir` is `output`. Use `acc.out_dir`.

## Your job when this runs on a schedule

Run `python3 bot.py` (this is what `run_all.py` calls). It already
handles all of the following -- your job is mainly to watch for problems
it logs rather than reimplement this logic:

1. Checks `footage/` for available clips. If none, logs to
   `output/errors.log` and stops.
2. Checks today's upload count against `YOUTUBE_DAILY_UPLOAD_LIMIT` in
   `config.py`. Stops before hitting quota.
3. Generates a story (via Claude if `ANTHROPIC_API_KEY` is set, otherwise
   from the local bank in `stories/`).
4. Runs the full pipeline to produce a finished video.
5. **Review mode (`config.REVIEW_MODE`, currently OFF).** When ON, saves to
   `output/pending_review/` and stops -- nothing posts. It is off in normal
   operation: both channels post automatically on the hourly timer. Turn it on
   (or pass `--dry-render`, which sets it for one run) to render without
   publishing. Use `python3 approve.py` to list pending videos, and
   `python3 approve.py --post <filename> --title "..."` to post one.
6. **Once `REVIEW_MODE = False`:** uploads directly via `youtube_upload.py`
   at the privacy level set in `config.PRIVACY_STATUS`, and logs every
   attempt (success or failure) to `output/post_log.csv`.

If you're extending this rather than just running it: keep the "stop and
log, don't retry-loop" behavior for any new failure paths -- burning
quota on a retry storm is worse than a skipped run.

## Hard limits — do not exceed these

- Max 1 generated video per scheduled run.
- YouTube: max 6 uploads/day (API quota ceiling — 1,600 units per upload
  against a 10,000/day budget). Track usage; stop before hitting quota
  and note it rather than erroring silently.
- Never post two videos with the same story title.
- If any API call fails, log the error to `output/errors.log` and stop —
  don't retry-loop and burn quota.

## Story style guardrails

- Hook in the first sentence — no throat-clearing. Undersell the drama
  (misleadingly simple hooks outperform hyped ones).
- On written surfaces (hook card, video title) AITAH stories display as
  "r/AITAH ..." so they read as real subreddit posts; narration keeps plain
  "AITAH" so TTS pronounces it naturally (handled by
  hook_card.format_hook_for_display — don't hand-write "r/" into beats).
- Performed authenticity: first person, confession cadence, (28F)-style age
  tags, specific mundane details. Plant an early detail that pays off late.
- Beats of 1-2 sentences, each landing on a small cliffhanger or twist.
- Multi-part: stories over ~170 words are auto-split into ~55s parts at beat
  boundaries (split_story_into_parts). Each part must end on a cliffhanger;
  non-final parts get follow bait. Post parts on consecutive days — series
  lose momentum past 72h gaps.
- No real named people, no content sexualizing or targeting minors, no
  content designed to mislead viewers into thinking it's a true story
  presented as verified fact — "random story" framing is fine, deceptive
  framing is not.
- Single video: keep narration ≤ ~60s (~170 words). Longer material: write a
  300-450 word saga and let the splitter make a 2-3 part series — multi-part
  converts followers 3-5x better.
- A story JSON may carry an optional `caption` field. If present, it is used
  verbatim for the social caption instead of the AI-written one — but only when
  the story is a single video. A series needs per-part framing and follow bait,
  which one fixed caption can't carry, so multi-part falls back to `ai_caption`
  and logs that it did.

## Switching off review mode

Change `REVIEW_MODE = True` to `False` in `config.py` once you've watched
a batch of outputs and you're happy with quality and posting cadence.
Recommended: don't flip this until at least 5-10 videos have been manually
reviewed and posted without issues.

## File map

| Path | Purpose |
|---|---|
| `story_bank.py` | Story text generation |
| `tts.py` | Voice + word timing |
| `captions.py` | Burn-in caption file builder |
| `assemble.py` | ffmpeg assembly |
| `main.py` | Runs the full pipeline once (manual, no posting logic) |
| `bot.py` | The operations bot -- full loop incl. quota checks + posting/review |
| `trend_discovery.py` | Pulls Google Trends / YouTube trending as a story topic hint |
| `approve.py` | Manual review-and-post CLI for videos awaiting approval |
| `youtube_upload.py` | OAuth + resumable upload to YouTube |
| `config.py` | Review mode switch + limits |
| `run_all.py` | Entry point for the scheduled task (MediaMakerHourly) -- self-updates, then runs `bot.py`, comment replies, coverage check, stats, dashboard, Discord report |
| `self_update.py` | Fast-forward pull so a pushed fix reaches the box unattended (used by `run_all.py` and the Discord `update` tool) |
| `coverage_check.py` | Flags videos that reached only one of YouTube/Instagram |
| `tiktok_upload.py` / `tiktok_queue.py` | TikTok posting + the Discord tap-to-approve gate |
| `output/pending_review/` | Videos waiting for your approval |
| `output/post_log.csv` | Record of everything actually posted |

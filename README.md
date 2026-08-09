# Media Maker

An autonomous short-form video pipeline. It writes a story, narrates it,
renders a captioned vertical video over gameplay footage, publishes to YouTube,
Instagram and TikTok, measures how each post performs, and feeds that back into
what it writes next — on a schedule, with no human in the loop.

Built to run unattended on a spare desktop. It currently does.

---

## What it does

```
story → narration → captions → render → publish → measure → steer
```

1. **Writes** a story with an LLM, constrained by target length, genre,
   originality against everything already posted, and structural patterns mined
   from competing channels.
2. **Narrates** it via TTS, capturing word-level timings.
3. **Builds captions** from those timings — word-by-word, burned in via libass.
4. **Renders** a 1080×1920 vertical video: a fast-cut background montage, an
   overlaid "social post" hook card, and a closing call-to-action card.
5. **Publishes** to YouTube (Data API v3), Instagram Reels + Stories (Graph
   API), and TikTok (Content Posting API) — each independently.
6. **Measures** views, likes, comments and shares; regenerates a dashboard.
7. **Steers** the next story from that data: theme weighting, originality
   guards, and structure derived from what actually performed.

A separate path stitches published Shorts into long-form compilations, because
Shorts earn no watch hours toward monetization and long-form does.

## Architecture

| Module | Role |
|---|---|
| `bot.py` | Orchestrator — one full story→publish pass |
| `story_bank.py` | LLM story generation; length, theme and originality constraints |
| `tts.py` / `captions.py` | Narration and word-level caption timing |
| `assemble.py` | ffmpeg pipeline: montage, overlays, cards, mux |
| `hook_card.py` / `thumbnail.py` | Generated PNG overlays and thumbnails (Pillow) |
| `youtube_upload.py` · `instagram_upload.py` · `tiktok_upload.py` | Per-platform publishing |
| `video_host.py` | Cloudflare R2 relay — Instagram pulls from a URL rather than accepting an upload |
| `control_server.py` | Flask API, dashboard, and LLM tool-calling brain |
| `discord_bot.py` | Remote control from a phone |
| `compilation.py` | Long-form compilations built from published Shorts |
| `hook_mining.py` | Derives structural patterns from competitors' best performers |
| `coverage_check.py` | Detects videos that reached only one platform |
| `run_all.py` | Scheduled entry point; sequences every step |

## Engineering worth pointing at

Most of the interesting work is in the failure modes, not the happy path.

**Independent platform failure.** A YouTube outage must not block the Instagram
post, or vice versa. Each platform publishes independently and logs its own
status — which is what makes a coverage check both necessary and possible.

**Idempotency across a shared log.** Multi-part sagas, scheduled releases and
manual pushes all write to one post log. Guards ensure a story never posts
twice, a later saga part never releases before its predecessor, and a *deleted*
video is never resurrected by a later repair pass.

**Instagram has no upload endpoint.** It fetches from a public URL. The pipeline
uploads to Cloudflare R2, hands Instagram the link, waits for the pull, then
deletes the object — so storage stays near zero and the free tier holds.

**Word-level caption timing.** TTS emits word boundaries; those become ASS
subtitle events, so captions land on the syllable instead of being estimated.

**Cross-platform scheduling.** Windows Task Scheduler and systemd timers are
both supported; the control server detects the platform, so the same
"autonomy on/off" command works on either host.

**LLM cost control.** Common queries (stats, recent posts, status) are answered
from local state with no model call at all. The LLM is reserved for genuinely
open-ended requests.

**Content steering from data.** Themes are weighted by measured performance,
with a deliberate share left unweighted so new angles can still surface. An
originality guard feeds recent premises back into generation, and a shape check
rejects a story whose role-and-conflict pairing is too close to a recent one —
that guard exists because two near-identical stories once shipped an hour apart.

## Stack

Python 3.10+ · ffmpeg · Flask · Anthropic API · YouTube Data API v3 ·
Instagram Graph API · TikTok Content Posting API · Cloudflare R2 (S3) ·
discord.py · Pillow · edge-tts

Runs on Windows or Linux. Deployed on Ubuntu under systemd.

## Setup

```bash
git clone <this-repo> && cd media_maker
python3 -m venv venv
venv/bin/python -m pip install -r requirements.txt
```

Copy a template and fill in your own credentials:

```bash
cp scripts/setup_env.template.bat scripts/setup_env.bat   # Windows
cp deploy/env.template .env                               # Linux
```

You will need: an Anthropic API key, a Google Cloud OAuth client for YouTube,
an Instagram Graph API token (professional account required), and a Discord bot
token. Cloudflare R2 and TikTok credentials are optional.

Background clips go in **that channel's own tree** — `footage/<account_id>/`,
with a subfolder per themed set. Each video commits to one set for its whole run,
so the look stays consistent within a video and varies between videos:

```
footage/parkourflux/{bright_biomes,night_1080,orbital_day}
footage/carveteran/{gameplay,road}
```

A channel with its own tree cannot see anything outside it, so a new folder is
opt-in rather than joining every channel's rotation by default. Folders starting
with `_` are never drawn — that is where a clip goes when it is staged or
withdrawn. `scripts/fetch_footage.py` pulls licence-clean clips from Pexels into
one of these sets and records provenance per clip.

Then verify everything is wired:

```bash
venv/bin/python scripts/preflight.py     # 36 checks, incl. live token refresh
venv/bin/python bot.py --dry-render      # render without publishing
```

Deployment guides: `DEPLOY.md` (Windows) and `DEPLOY_UBUNTU.md` (Linux +
systemd).

## Notes

Credentials are excluded from version control — the committed `.bat` files are
`.template` versions with placeholders.

Background footage is excluded too, for two different reasons depending on which
it is. The Minecraft clips are third-party gameplay and not mine to
redistribute. The driving clips are either my own captures or licensed from
Pexels for commercial use; those are left out for size, and each set carries a
`CREDITS.md` naming the source of every file. Nothing in the pipeline uses
footage scraped from someone else's stream — an early clip was, and it had a
Twitch logo built into the map it was recorded on, which is why provenance is
now recorded per clip rather than assumed.

This is a working system rather than a packaged product, and it shows in
places. The deployment guides and inline comments explain *why* decisions were
made, which tends to be the part that matters when reading someone else's
pipeline.

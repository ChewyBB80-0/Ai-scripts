# Media Maker — Antigravity (Gemini) Instructions

Read `CLAUDE.md` first — it has the full project context, file map, limits, and
story guardrails that apply to ALL agents working on this project.

This file covers Antigravity-specific context.

## Multi-Agent Cowork

This project is worked on by **both Claude Code and Antigravity**.

**Always read `COWORK.md` at session start.** It is the shared task board:
- Check "In Progress" before editing any file to avoid conflicts.
- Pick up tasks from "To Do" tagged `[AGY]` or `[Either]`.
- When done, move the task to "Done" with a date and summary.
- Use the "Handoff Queue" to pass context to Claude Code.

## Current Config (as of 2026-08-15)

| Setting | Value |
|---|---|
| Posting cadence | Every 2 hours (Windows scheduled task `MediaMakerHourly`) |
| Weekly soft cap | 18 videos (Mon-Sun) |
| Daily target | 3 stories/day |
| YouTube daily limit | 6 uploads/day |
| Review mode | OFF (full autonomy) |
| Privacy | Public |
| Instagram cross-post | ON |
| Strategy | **Singles first** — test topics before committing to multi-part series |

## Shared Knowledge Vault

The Obsidian vault at `C:\Users\Krish\claud ai stuff\Claude-obsidian-` is the
persistent memory shared between agents. Use `wiki/hot.md` to leave context
for the next session (either agent).

## Caption Research (2026-07-18)

Key findings from trending caption research — to be implemented in `social_caption.py`:
- Instagram: 3-5 hashtags MAX (more = spam penalty)
- DM Shares are the #1 IG algorithm signal in 2026
- Must-have tags: `#storytime`, `#redditstories`, `#facelesscreator`
- YouTube Shorts titles under 50 chars, state the CONFLICT not the topic
- Rotate hashtag sets every 4-6 weeks
- Comment bait < Save bait < Share/DM bait (in terms of algorithm weight)

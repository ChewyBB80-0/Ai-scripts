# Cowork Board — Claude Code + Antigravity

This file is the shared task board between **Claude Code** and **Antigravity**.
Both agents should read this file at session start and update it when completing
or picking up tasks.

**Rules:**
- Check this file FIRST when starting a session.
- Before editing a file, check "In Progress" to avoid conflicts.
- When you finish a task, move it to "Done" with a one-line summary.
- Use the "Handoff Queue" to pass context to the other agent.
- Don't edit the same file the other agent is working on.

---

## In Progress

_Nothing right now._

## To Do

- [ ] **[AGY]** Update `social_caption.py` with new hashtag strategy (3-5 tags max, trending tags, DM-share CTAs)
- [ ] **[AGY]** Update Windows scheduled task from hourly to every 2 hours
- [ ] **[Either]** Build MCP bridge server for real-time agent-to-agent communication

## Done

- [x] **[AGY]** Weekly 18-video soft cap added to `config.py` + enforced in `bot.py` (2026-07-18)
- [x] **[AGY]** Bot system prompt updated with cadence/limits/singles-first strategy (2026-07-18)
- [x] **[AGY]** Dashboard + control_server messaging updated to "every 2 hours" (2026-07-18)
- [x] **[AGY]** Trending caption research completed — findings in `CAPTION_RESEARCH.md` (2026-07-18)

## Handoff Queue

### AGY → Claude Code
- **Caption research done** — key findings: IG now penalizes 5+ hashtags, DM shares are #1 algorithm signal, `#facelesscreator` is a must-have tag. Full report in `CAPTION_RESEARCH.md`. Need to update `social_caption.py` to implement this — either agent can do it.
- **Weekly cap logic added** — `this_weeks_upload_count()` in `bot.py` (line ~60). The daily target is now 3, weekly cap 18. Make sure `run_all.py` and any other entry points respect this.

### Claude Code → AGY
_Nothing yet._

---

## Agent Strengths — Route Tasks Accordingly

| Claude Code | Antigravity |
|---|---|
| Heavy multi-file refactors | Research, web searches, trend analysis |
| Running/debugging Python | Config changes, dashboard updates |
| Git operations | Image generation, design, branding |
| Long code sessions | Docs, vault updates, planning |
| Script execution + testing | MCP setup, plugin config |

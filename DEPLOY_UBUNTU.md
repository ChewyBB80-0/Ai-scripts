# Deploying ParkourFlux to the playbox (Ubuntu)

Written 2026-07-28. Use this instead of `DEPLOY.md` (Windows) if the playbox
runs Ubuntu.

Ubuntu is the better host here: systemd's `Restart=always` removes the whole
class of "a service died quietly and nothing noticed" problems that plagued the
Windows box, and `Persistent=true` on the timer fires a *missed* run on wake
rather than skipping the slot — which is exactly what cost the 03:23 slot on
2026-07-27.

**The venv did not travel.** A virtualenv hardcodes absolute paths in
`pyvenv.cfg` and its `bin/` shims, and a Windows venv is useless on Linux
regardless. It gets rebuilt in Step 3 — that's expected, not a missing file.

**`bin/` contains Windows ffmpeg binaries.** They won't run on Linux; Step 2
installs the native one instead. Harmless to leave in place.

---

## Step 1 — Copy the project across

From the MOVESPEED drive (exFAT mounts read/write on Ubuntu without setup):

```bash
mkdir -p ~/media_maker
cp -r /media/$USER/MOVESPEED/media_maker/* ~/media_maker/
cd ~/media_maker
```

If the drive mounts elsewhere, find it with `lsblk` or `ls /media/$USER/`.

## Step 2 — System packages

```bash
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3-pip ffmpeg fonts-dejavu-core
```

`ffmpeg` from apt replaces the bundled Windows binaries — `ffmpeg_setup.py`
finds it on `PATH` automatically.

If `python3.12` isn't available on your release:
```bash
sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt update
sudo apt install -y python3.12 python3.12-venv
```

## Step 3 — Build the venv

```bash
cd ~/media_maker
python3.12 -m venv venv
venv/bin/python -m pip install --upgrade pip
venv/bin/python -m pip install -r requirements-full.txt
```

## Step 4 — Secrets

Windows used `setx`; on Linux systemd reads an env file.

```bash
cp deploy/env.template .env
nano .env          # paste each value from scripts/setup_env.bat
chmod 600 .env     # readable only by you -- it holds 13 secrets
```

Leave `MEDIA_MAKER_LOW_SPEC` commented out. That flag exists for the weak Atom
stick; this machine (A10-7700K, 32GB) should render full 1080p.

**On an HDD host, add this line** — the playbox has spinning disks:

```
MEDIA_MAKER_TEMP_DIR=/dev/shm
```

Assembly writes and re-reads dozens of small segment files, which is the exact
access pattern HDDs are worst at. `/dev/shm` is a RAM disk that Ubuntu already
mounts by default at ~half of RAM (16GB here), so this needs no setup and takes
that I/O off the disk entirely. It falls back to `output/` automatically if the
path isn't writable, so it can't break a render.

For interactive commands to see the same values:
```bash
set -a; source ~/media_maker/.env; set +a
```
Add that line to `~/.bashrc` to make it permanent for your shells.

## Step 5 — Preflight

```bash
cd ~/media_maker
set -a; source .env; set +a
venv/bin/python scripts/preflight.py
```

Checks dependencies, ffmpeg, every credential, footage, fonts, write access,
and does a LIVE token refresh against YouTube and Instagram. Exit 0 = ready.

Expected warnings: the Reddit keys (that API application is still pending), and
the scheduled-task check (it looks for Windows Task Scheduler and will say it
can't find the task — harmless on Linux).

## Step 6 — Test render, no posting

```bash
venv/bin/python bot.py --dry-render
```

Writes a real video to `output/pending_review/` without posting. **Open it and
check the hook card and end card actually have proper text** — if the font
fallback failed you'll see tiny mismatched lettering. `hook_card.py` prefers the
bundled `fonts/Rubik-Black.ttf`, so this should be fine, but it's worth one
look because the failure is visual rather than an error.

## Step 7 — Install the services

```bash
mkdir -p ~/.config/systemd/user
cp deploy/systemd/*.service deploy/systemd/*.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now mediamaker-server.service
systemctl --user enable --now mediamaker-bot.service
systemctl --user enable --now mediamaker.timer
systemctl --user enable --now mediamaker-stats.timer
systemctl --user enable --now mediamaker-health.timer
systemctl --user enable --now mediamaker-report.timer
```

Six units, and the split matters:

| unit | does | why separate |
|---|---|---|
| `mediamaker-server` | dashboard + chat API | long-running |
| `mediamaker-bot` | Discord control | long-running |
| `mediamaker.timer` | full pipeline, hourly | generates and posts |
| `mediamaker-stats.timer` | stats refresh, 15 min | keeps the dashboard live without touching upload quota |
| `mediamaker-health.timer` | health check, 2h | **must not** be a pipeline step -- a monitor invoked by the thing it monitors cannot report that thing being broken |
| `mediamaker-report.timer` | daily report, 08:00 local | same reason -- as a pipeline step it went silent when the pipeline did |


The units use `%h` for your home directory, so they work regardless of username
as long as the project sits at `~/media_maker`.

**Keep services running when you're not logged in** (otherwise they stop the
moment you close the SSH session):
```bash
sudo loginctl enable-linger $USER
```

Check status:
```bash
systemctl --user status mediamaker-server mediamaker-bot
systemctl --user list-timers mediamaker.timer
journalctl --user -u mediamaker -f          # live pipeline logs
```

## Step 8 — Never sleep

A sleeping host misses posting slots:
```bash
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
```
(Reverse later with `unmask` if needed.)

## Step 9 — ⚠️ The old PC

Both machines share the same YouTube and Instagram tokens, so **if both run the
pipeline everything double-posts.** This was already done on 2026-07-28 — the
Windows task is Disabled and its services are stopped. Verify before going live:

```powershell
(Get-ScheduledTask -TaskName MediaMakerHourly).State     # must say Disabled
```

## Step 10 — Live

Reboot, confirm the timer is listed, and drive it from Discord. `autonomy on/off`
now maps to `systemctl --user enable/disable --now mediamaker.timer`
automatically — the control server detects the platform.

---

## Notes

- **Wipe the USB drive afterwards.** `scripts/setup_env.bat` holds 13 secrets in
  plaintext and has now travelled on a portable disk. Delete
  `MOVESPEED/media_maker` once deployed; rotate the keys if the drive is ever
  lost.
- **Tokens travel fine.** `token.json` works from any machine — the OAuth app is
  published, so the refresh token is durable. No re-auth needed.
- **The car channel stays parked.** `accounts.json` has `carveteran` with
  `enabled: false` deliberately: it needs the dialogue pipeline, not the story
  one. Its OAuth (`add_channel.py carveteran`) is still outstanding, and that
  step needs a browser — awkward on a headless box, so do it on a desktop and
  copy `token_carveteran.json` across.
- **Headless OAuth generally:** any future `add_channel.py` run needs a browser.
  Run it on a machine with one and copy the resulting token file over.
- **The dashboard** binds to localhost:8000. To view it from another machine use
  an SSH tunnel (`ssh -L 8000:localhost:8000 user@playbox`) rather than exposing
  the port — it can trigger posts.
- **Deploying a fix without being at the box.** `run_all.py` fast-forwards the
  checkout at the top of every hourly run, and the Discord assistant has an
  `update` tool ("update" / "deploy the fix") that pulls on demand. Both go
  through `self_update.py`: fast-forward only, refused on a dirty tree, and
  never fatal — a failed pull logs and the run continues on existing code.

  Two things it deliberately will not do, because both need a human:

  1. **It only pulls the branch the box is checked out on.** A fix pushed to a
     feature branch does not reach a box tracking `main` until it is merged.
     `git -C ~/media_maker rev-parse --abbrev-ref HEAD` says which branch the
     box is actually on.
  2. **It does not restart `mediamaker-server` or `mediamaker-bot`.** Pipeline
     steps are fresh subprocesses so they pick up new code immediately, but
     those two keep running what they booted with. The pull reports when they
     are stale; restarting the server from inside a request it is answering
     would kill the reply. `systemctl --user restart mediamaker-server
     mediamaker-bot` when it says so.

  This needs the box's git remote to authenticate non-interactively (SSH key or
  a stored credential helper). `GIT_TERMINAL_PROMPT=0` means a remote that wants
  a password fails in seconds rather than hanging the hourly run on a prompt
  nobody is there to answer.

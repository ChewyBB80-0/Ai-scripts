# Deploying ParkourFlux to the AWOW stick (Windows)

Target: run the whole pipeline 24/7 on the Atom x5-Z8350 stick, **on the Windows
that's already installed** (Ubuntu on this chip = 32-bit UEFI + WiFi driver
rabbit hole — a next-week project, not a Friday one).

The code is already stick-ready: `MEDIA_MAKER_LOW_SPEC=1` switches it to
**720p + lighter encode + 3-day cleanup**, ffmpeg is bundled in `bin/`, and all
paths are portable. Nothing below changes the main PC.

---

## Step 1 — Copy the project to the stick
Copy the **entire `media_maker` folder** to the stick at **`C:\media_maker`**
(USB drive or network share). This carries everything it needs: code,
`token.json` (YouTube auth), `client_secret.json`, `accounts.json`, `footage/`,
`branding/`, `fonts/`, `bin/` (bundled ffmpeg), `scripts/`, `requirements-full.txt`.
Do **not** copy the `venv/` folder — you'll rebuild it on the stick (Step 3).

## Step 2 — Install Python 3.12 on the stick
Download from python.org, run the installer, and **check "Add python.exe to
PATH"**. Confirm in a new Command Prompt: `python --version`.

## Step 3 — Create the venv + install dependencies
Open Command Prompt in `C:\media_maker`:
```
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements-full.txt
```

## Step 4 — Set the API keys + low-spec flag (one-shot)
```
scripts\setup_env.bat
```
Then **sign out and back in** (or reboot) so the env vars take effect.

## Step 5 — Test a render (measure the speed — the key check)
This generates + renders a REAL video at 720p but does **NOT** post it:
```
venv\Scripts\python.exe bot.py --dry-render
```
It prints the render time and drops the file in `output\pending_review\`. Open
it — confirm it looks right (captions, hook card, footage). Note the time:
- **Under ~8 min** → great, the stick handles it comfortably.
- **8-15 min** → fine for 2/day (machine is idle the rest of the time).
- **Over ~20 min** → tell me; we drop the preset further or shorten stories.

## Step 6 — Register autostart (run as Administrator)
Open an **Admin** Command Prompt in `C:\media_maker`:

**a) Hourly pipeline** (generate/render/post + stats + reports):
```
schtasks /create /tn "MediaMakerHourly" /tr "C:\media_maker\venv\Scripts\pythonw.exe C:\media_maker\run_all.py" /sc hourly /f
```

**b) Server + Discord bot at logon** — create `MediaMaker.vbs` in the Startup
folder. Press `Win+R`, type `shell:startup`, Enter, and drop a file
`MediaMaker.vbs` there containing:
```vbs
Set sh = CreateObject("WScript.Shell")
sh.Run """C:\media_maker\scripts\start_server.bat""", 0, False
WScript.Sleep 3000
sh.Run """C:\media_maker\scripts\start_bot.bat""", 0, False
```

## Step 7 — IMPORTANT: stop the main PC from also posting
Both machines share the same YouTube/Instagram accounts and `token.json`. If both
run the pipeline, **everything double-posts.** Once the stick is live, disable the
main PC's task (run on the MAIN PC, as Admin):
```
schtasks /change /tn "MediaMakerHourly" /disable
```
(Re-enable later with `/enable` if you ever move back.)

## Step 8 — Go live
Reboot the stick. At logon the server + Discord bot start; the hourly task fires
on schedule. Manage it entirely from your phone via the Discord bot. Done.

---

## Notes / gotchas
- **YouTube auth travels** — `token.json` works from any machine (published app,
  durable refresh token). No re-auth needed on the stick.
- **First render is slowest** (cold caches). Subsequent ones are faster.
- **Storage**: 720p videos are ~7-8MB and auto-delete after 3 days, so the 64GB
  eMMC stays healthy. `output/daily_run.log` shows each run + cleanup count.
- **If a service won't stay up**, double-click `scripts\start_server.bat` /
  `scripts\start_bot.bat` manually to see errors.
- **Ubuntu migration** (later): the code already runs on Linux with one small
  font fix; revisit once the Friday deadline is behind us.

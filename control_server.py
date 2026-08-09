"""
control_server.py
Local web app behind the dashboard: serves dashboard/live.html and gives it a
real AI assistant that can DO things -- check performance, post a video on
command, and toggle autonomous mode. Open http://localhost:8000 .

Run: start_control.bat  (or venv/Scripts/python.exe control_server.py)
Needs ANTHROPIC_API_KEY (+ IG creds) in env -- setx already set them.
"""

import base64
import csv
import json
import re
import subprocess
import threading
from pathlib import Path

import anthropic
from flask import Flask, request, jsonify, send_file

from ffmpeg_setup import ensure_ffmpeg
ensure_ffmpeg()  # so dashboard/Discord manual posts can render on any machine
from werkzeug.utils import secure_filename

ROOT = Path(__file__).parent
UPLOADS = ROOT / "output" / "uploads"
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200 MB
client = anthropic.Anthropic()

_busy = {"posting": False, "syncing": False}   # guards against overlapping runs

# The same interpreter running this server -- so the sync subprocesses use the
# venv and inherit the server's env (API keys etc.).
import sys
_PY = sys.executable
# The stats-refresh chain that feeds the dashboard: pull YouTube, pull
# Instagram, then rebuild live.html from the fresh data.
_SYNC_STEPS = [["scripts/channel_stats.py"], ["scripts/ig_stats.py"],
               ["scripts/gen_dashboard.py"]]


def _dash_online() -> bool:
    """True if the dashboard server is actually serving. Called from within the
    server, so this normally succeeds -- it exists so the sync command can say
    'Dash is not online' cleanly if the server is somehow not reachable."""
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _run_sync():
    try:
        for step in _SYNC_STEPS:
            subprocess.run([_PY] + step, cwd=str(ROOT),
                           capture_output=True, timeout=240)
    except Exception as e:
        print("dashboard sync error:", e)
    finally:
        _busy["syncing"] = False

IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".webp": "image/webp", ".gif": "image/gif"}
# where the move_file tool is allowed to put things
DESTS = {"footage": "footage", "music": "music",
         "satisfying": "footage_satisfying", "branding": "branding"}


# ---------------- tools the assistant can call ----------------
def t_get_stats(_):
    yt = json.loads((ROOT / "output/channel_stats.json").read_text()) if (ROOT / "output/channel_stats.json").exists() else {}
    ig = json.loads((ROOT / "output/ig_stats.json").read_text()) if (ROOT / "output/ig_stats.json").exists() else {}
    yv = sorted(yt.get("videos", []), key=lambda v: v["views"], reverse=True)
    iv = sorted(ig.get("media", []), key=lambda v: v["views"], reverse=True)
    return json.dumps({
        "youtube": {"subs": yt.get("subscribers", 0),
                    "total_views": sum(v["views"] for v in yv),
                    "videos": len(yv),
                    "top": [{"title": v["title"], "views": v["views"], "likes": v["likes"]} for v in yv[:5]]},
        "instagram": {"total_views": ig.get("totalViews", 0),
                      "posts": len(iv),
                      "top": [{"caption": v["caption"], "views": v["views"]} for v in iv[:5]]},
    })


def t_post_video(inp):
    if _busy["posting"]:
        return "A video is already being generated right now -- give it a couple minutes."
    _busy["posting"] = True

    def run():
        try:
            import importlib, bot
            importlib.reload(bot)
            bot.run_once(topic_hint=inp.get("topic", ""), force=True,
                         platforms=inp.get("platform", "both"))
        except Exception as e:
            print("post_video error:", e)
        finally:
            _busy["posting"] = False
    threading.Thread(target=run, daemon=True).start()
    hint = f" (topic: {inp['topic']})" if inp.get("topic") else ""
    return f"Started generating and posting a fresh video{hint}. It'll be on YouTube + Instagram in a few minutes."


# The scheduler differs by OS: Task Scheduler on Windows, a systemd timer on
# Linux. Both toggles go through these two helpers so the Discord/dashboard
# commands work identically on either host.
_IS_WIN = sys.platform.startswith("win")
_TIMER = "mediamaker.timer"          # systemd unit name on Linux


def t_set_autonomy(inp):
    on = bool(inp["on"])
    if _IS_WIN:
        subprocess.run(["schtasks", "/change", "/tn", "MediaMakerHourly",
                        "/enable" if on else "/disable"], capture_output=True)
    else:
        subprocess.run(["systemctl", "--user",
                        "enable" if on else "disable",
                        "--now", _TIMER], capture_output=True)
    return f"Autonomous posting {'ENABLED' if on else 'DISABLED'}."


def t_get_autonomy(_):
    if _IS_WIN:
        r = subprocess.run(["schtasks", "/query", "/tn", "MediaMakerHourly",
                            "/fo", "list"], capture_output=True, text=True)
        off = "Disabled" in r.stdout
    else:
        r = subprocess.run(["systemctl", "--user", "is-enabled", _TIMER],
                           capture_output=True, text=True)
        off = "enabled" not in r.stdout
    return ("Autonomy is OFF (manual only)." if off
            else "Autonomy is ON (bot posts on its own hourly).")


def t_move_file(inp):
    name = secure_filename(inp["filename"])
    src = UPLOADS / name
    if not src.exists():
        return f"No uploaded file named {name}. Ask the user to re-attach it."
    dest_key = inp["dest"]
    if dest_key not in DESTS:
        return f"dest must be one of {list(DESTS)}"
    dest = ROOT / DESTS[dest_key] / name
    dest.parent.mkdir(exist_ok=True)
    src.replace(dest)
    return f"Moved {name} -> {DESTS[dest_key]}/. It'll be used by the pipeline automatically."


MEMORY_FILE = ROOT / "output" / "assistant_memory.json"


def _load_memory() -> list:
    try:
        return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def t_remember(inp):
    notes = _load_memory()
    from datetime import date
    notes.append({"d": str(date.today()), "note": inp["note"][:500]})
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    MEMORY_FILE.write_text(json.dumps(notes[-100:], indent=1), encoding="utf-8")
    return "Saved to memory."


def t_forget(inp):
    notes = _load_memory()
    kept = [n for n in notes if inp["match"].lower() not in n["note"].lower()]
    removed = len(notes) - len(kept)
    MEMORY_FILE.write_text(json.dumps(kept, indent=1), encoding="utf-8")
    return f"Removed {removed} matching note(s)." if removed else "No matching notes."


def t_list_uploads(_):
    UPLOADS.mkdir(parents=True, exist_ok=True)
    files = [f"{f.name} ({round(f.stat().st_size/1e6,1)} MB)" for f in UPLOADS.iterdir() if f.is_file()]
    return json.dumps(files) if files else "No uploaded files waiting."


def t_recent(_):
    log = ROOT / "output/post_log.csv"
    if not log.exists():
        return "No posts yet."
    rows = [r for r in csv.reader(open(log)) if len(r) >= 4 and r[3] in ("posted", "posted_manual", "posted_instagram")]
    return json.dumps([{"when": r[0][:16], "title": r[1], "where": r[3]} for r in rows[-8:]])


TOOLS = [
    {"name": "get_stats", "description": "Current YouTube + Instagram performance: views, subs, top videos.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "post_video", "description": "Generate and post a NEW story video right now. Choose the platform: 'both' (default), 'youtube', or 'instagram'. Optional topic hint. If the user asks to post but doesn't say where, ask which platform(s) first.",
     "input_schema": {"type": "object", "properties": {"topic": {"type": "string", "description": "optional topic/theme"}, "platform": {"type": "string", "enum": ["both", "youtube", "instagram"], "description": "which platform(s) to post to (default both)"}}}},
    {"name": "update", "description": "Deploy the latest pushed code to this machine (git pull, fast-forward only). Use when the user says update/deploy/pull/'get the fix', or when a bug has been fixed remotely and needs to reach the box. Safe: it never discards local work, and reports if a restart is still needed.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "set_autonomy", "description": "Turn autonomous posting (every 2 hours) on or off.",
     "input_schema": {"type": "object", "properties": {"on": {"type": "boolean"}}, "required": ["on"]}},
    {"name": "get_autonomy", "description": "Check if autonomous posting is currently on.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "recent_posts", "description": "List the last few things posted and where.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "move_file", "description": "File an uploaded attachment into the pipeline: dest 'footage' (background clips), 'music' (audio beds), 'satisfying' (split-screen clips), or 'branding' (logo).",
     "input_schema": {"type": "object", "properties": {"filename": {"type": "string"}, "dest": {"type": "string", "enum": ["footage", "music", "satisfying", "branding"]}}, "required": ["filename", "dest"]}},
    {"name": "list_uploads", "description": "List files the user has uploaded that are waiting to be filed.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "remember", "description": "Save a lasting note to your persistent memory (user preferences, decisions, plans). Use whenever the user says 'remember...' or states a preference/goal worth keeping.",
     "input_schema": {"type": "object", "properties": {"note": {"type": "string"}}, "required": ["note"]}},
    {"name": "forget", "description": "Delete memory notes containing the given text.",
     "input_schema": {"type": "object", "properties": {"match": {"type": "string"}}, "required": ["match"]}},
    {"name": "refresh_trends", "description": "Re-research current Reels/Shorts caption + hashtag trends via web search and update the caption engine's trend file.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "sync_dashboard", "description": "Force a dashboard refresh: pull the latest YouTube + Instagram stats and rebuild the dashboard (live.html). Use when the user asks to sync/refresh/update the dashboard.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "reply_to_comments", "description": "Run the auto comment-reply engine over new YouTube + Instagram comments. dry_run=true previews the replies WITHOUT posting (default, safe); dry_run=false actually posts them. Needs the YouTube force-ssl re-auth and IG manage_comments permission first.",
     "input_schema": {"type": "object", "properties": {"dry_run": {"type": "boolean", "description": "true = preview only (default); false = actually post"}}}},
    {"name": "check_coverage", "description": "Check whether every recent story actually reached BOTH YouTube and Instagram. The two platforms post independently, so a video can quietly end up on only one. Reports gaps; set fix=true to post the missing side (this publishes real videos -- confirm with the user first). TikTok is shown for info only and is never counted as a gap since it's approval-gated.",
     "input_schema": {"type": "object", "properties": {"days": {"type": "integer", "description": "how far back to look (default 7)"}, "fix": {"type": "boolean", "description": "actually post the missing side (default false = report only)"}}}},
    {"name": "post_to_tiktok", "description": "Push ALREADY-RENDERED video(s) from output/ to the user's TikTok drafts (inbox) -- this is how we cross-post existing YouTube/Instagram content to TikTok. TikTok is DRAFT-ONLY right now: the video lands in the TikTok app and the user taps Post themselves. Use 'count' for the N newest videos (default 1, max 5) or 'filename' for a specific one. This does NOT generate a new story -- use post_video for that.",
     "input_schema": {"type": "object", "properties": {"count": {"type": "integer", "description": "how many of the newest rendered videos to push (default 1, max 5)"}, "filename": {"type": "string", "description": "specific video filename in output/ (optional)"}}}},
]


def _t_coverage(inp):
    import coverage_check
    days = inp.get("days", coverage_check.DEFAULT_DAYS)
    out = coverage_check.report(days)
    if inp.get("fix"):
        out += "\n\n" + coverage_check.fix(days)
    return out


def _t_tiktok(inp):
    """Cross-post already-rendered videos to TikTok drafts."""
    import tiktok_upload
    out = ROOT / "output"
    name = (inp.get("filename") or "").strip()
    if name:
        vid = out / name
        if not vid.exists():
            return f"No rendered video named {name} in output/."
        vids = [vid]
    else:
        n = max(1, min(int(inp.get("count", 1) or 1), 5))
        vids = sorted(out.glob("*.mp4"), key=lambda p: p.stat().st_mtime)[-n:]
        if not vids:
            return "No rendered videos in output/ to push."
    done, failed = [], []
    for v in vids:
        try:
            tiktok_upload.post_to_drafts(v)
            done.append(v.name)
        except Exception as e:
            failed.append(f"{v.name} ({e})")
    msg = (f"Pushed {len(done)} video(s) to TikTok drafts: {', '.join(done)}. "
           "Open the TikTok app -> Inbox/Notifications to review and tap Post.") if done \
        else "Nothing pushed."
    if failed:
        msg += f" FAILED: {'; '.join(failed)}"
    return msg


def _t_reply_comments(inp):
    import comment_replies
    dry = inp.get("dry_run", True)
    totals = comment_replies.run(dry_run=dry)
    n = sum(totals.values())
    mode = "previewed" if dry else "posted"
    # NB: `"a" + "".join(...) or "fallback"` binds as `("a" + join) or "fallback"`,
    # which is never falsy -- the no-comments message could never appear. Explicit now.
    if not n:
        return f"{mode} 0 replies (no new comments)."
    breakdown = ", ".join(f"{k}:{v}" for k, v in totals.items() if v)
    return f"{mode} {n} repl{'y' if n == 1 else 'ies'} across {breakdown}"
def t_update(_):
    """Deploy the latest pushed code to this box, from Discord or the dashboard.

    The reason this tool exists: when the upload pipeline broke, the fix was
    committed within the hour and still could not be deployed, because the only
    way in was standing at the machine. Now it is one message from a phone.
    """
    import self_update
    changed, msg, files = self_update.pull()
    if not changed:
        return msg
    lines = [msg, f"{len(files)} file(s) changed."]
    lines.append("Pipeline steps use the new code from the next run "
                 "(hourly, or say 'post a video' to exercise it now).")
    stale = self_update.stale_units(files)
    if stale:
        # Restarting these from inside this request would kill the process
        # answering it, so report rather than act.
        lines.append(f"Still on old code until restarted: {', '.join(stale)} "
                     f"-- `systemctl --user restart {' '.join(stale)}` on the box.")
    return "\n".join(lines)


DISPATCH = {"get_stats": t_get_stats, "post_video": t_post_video,
            "update": t_update,
            "set_autonomy": t_set_autonomy, "get_autonomy": t_get_autonomy,
            "recent_posts": t_recent, "move_file": t_move_file,
            "list_uploads": t_list_uploads, "remember": t_remember,
            "forget": t_forget,
            "refresh_trends": lambda _: (__import__("trends").refresh_trends() and
                                         "Trends refreshed from live web research."),
            "reply_to_comments": _t_reply_comments,
            "post_to_tiktok": _t_tiktok,
            "check_coverage": _t_coverage,
            "sync_dashboard": lambda _: _fast_reply("sync") or
            "⚠️ Dash is not online. Start it with scripts\\start_server.bat."}

SYSTEM = (
    "You are the ops assistant for 'ParkourFlux AI' -- an autonomous system that generates "
    "AI Reddit-style story videos over Minecraft parkour footage and posts them to YouTube and "
    "Instagram automatically, plus TikTok on request (drafts -- see INFRA). You can check "
    "performance, post a new video on command, cross-post existing videos to TikTok, list "
    "recent activity, and turn autonomous mode on/off.\n\n"
    "POSTING CADENCE & LIMITS:\n"
    "- The bot posts automatically every 2 hours when autonomy is ON.\n"
    "- Soft cap: 14 videos per week (Mon-Sun). Once hit, no new stories start until next Monday.\n"
    "- Daily target: up to 2 new stories per day, and EACH story cross-posts to BOTH "
    "YouTube and Instagram (kept modest to avoid spam flags). Sagas are fine as dailies: "
    "a multi-part saga counts as ONE of the 2 daily stories -- Part 1 posts, then later "
    "parts drip same-day (~2h apart) strictly in order. Always respect the weekly cap.\n"
    "- Hard ceiling: 6 YouTube uploads per day (API quota safety).\n"
    "- 1 video per scheduled run.\n"
    "INFRA (updated 2026-07-20):\n"
    "- Instagram videos are hosted on the user's own Cloudflare R2 bucket "
    "('instagram-bridge'); each is auto-deleted right after IG pulls it, so it's free.\n"
    "- YouTube supports SCHEDULED RELEASE: a video can be uploaded now and set to "
    "auto-publish at a future time (bot.py --schedule-at, RFC3339 UTC).\n"
    "- Posts can target one platform or both (post_video 'platform': youtube|instagram|both).\n"
    "- Saga parts now always post IN ORDER (fixed 2026-07-21): scheduled sagas "
    "release every part in sequence; later parts follow Part 1's platform and never "
    "go live before Part 1 does.\n"
    "- Dashboard (localhost:8000) redesigned 2026-07-22: metric cards (Views/Likes/"
    "Comments/Shares/Engagement), gradient views chart with Cumulative/Delta toggle + "
    "time-range, recent-post thumbnails, per-platform sidebar. IG shares are now tracked "
    "(ig_stats). Regenerated hourly by the bot.\n"
    "- On 2026-07-20 the user manually posted 2 to Instagram now and scheduled 2 on "
    "YouTube for the next morning (9:30 + 9:50am ET). Deployment to a temp Windows "
    "stick PC (720p profile) is in progress; a dedicated VM host is the long-term home.\n"
    "- TIKTOK -- CONNECTED 2026-07-22 (third platform, DRAFT MODE). tiktok_upload.py is "
    "authorized and verified working; use the post_to_tiktok tool to push already-rendered "
    "videos from output/ to the user's TikTok drafts. IMPORTANT NUANCE: TikTok is NOT part "
    "of the automatic posting cadence -- the app is still in TikTok's sandbox, so uploads "
    "land in the TikTok app's Inbox/drafts and the USER must tap Post manually, and sandbox "
    "posts have limited/private visibility until the app passes TikTok's production audit. "
    "So treat TikTok as an on-request cross-post of existing YouTube/Instagram content, not "
    "as a third automatic destination. post_video's 'platform' option covers only "
    "youtube|instagram|both -- TikTok is separate (post_to_tiktok). Full public auto-posting "
    "becomes possible after the audit (needs the video.publish scope + production keys, "
    "which are already noted in scripts/setup_env.bat).\n"
    "- TIKTOK IS PAUSED (2026-07-23, user's call): config.TIKTOK_APPROVAL_GATE is now "
    "False, so nothing new is queued or pushed to TikTok until TikTok's production audit "
    "comes through. Sandbox posts have limited visibility, so feeding it content now buys "
    "nothing. 8 videos already sit in the user's TikTok drafts. Do NOT push to TikTok "
    "unless the user explicitly asks. Flip the flag back to True after the audit.\n"
    "- TIKTOK APPROVAL GATE (built 2026-07-22, config.TIKTOK_APPROVAL_GATE): every video "
    "the pipeline posts is ALSO queued for TikTok (tiktok_queue.py). The Discord bot DMs "
    "the owner a preview with Approve / Skip buttons and only publishes when they tap "
    "Approve. Approving direct-posts if the video.publish scope is granted, otherwise it "
    "falls back to the draft inbox -- so nothing needs rewiring when the audit lands. The "
    "buttons run in the Discord bot process and do NOT call Claude, so approvals cost no "
    "API tokens. Scheduled (publish_at) posts are not queued. If the user asks what's "
    "waiting for approval, the queue lives in output/tiktok_queue.json.\n\n"
    "TOKENS -- ALL THREE PLATFORMS SELF-MAINTAIN (2026-08-08):\n"
    "- YouTube and TikTok already refreshed themselves. Instagram did NOT, which made "
    "it the only platform with a scheduled outage (tokens last 60 days). ig_token.py "
    "now refreshes IG tokens once they are 21 days old, as a step in the hourly run, "
    "for every account including disabled ones. Refreshed tokens live in "
    "output/ig_tokens.json (owner-only) and take precedence over .env; the pipeline "
    "never rewrites .env. So: the user does NOT need to paste Instagram tokens again. "
    "If IG posting ever fails on auth, check `python ig_token.py --status` first.\n"
    "- Per-account Instagram credentials are now STRICT: the shared IG_USER_ID / "
    "IG_ACCESS_TOKEN belong to parkourflux only. Any other account needs its own "
    "IG_USER_ID_<ID> / IG_ACCESS_TOKEN_<ID> or it posts nowhere. This replaced a silent "
    "fallback that made a second channel resolve to ParkourFlux's profile.\n"
    "- PUBLISHING METADATA IS PER-ACCOUNT (2026-08-09): yt_tags / yt_hashtags / "
    "ig_hashtags live in accounts.json. They used to be hardcoded to the story channel, "
    "which would have published car-maintenance advice tagged 'minecraft', 'parkour' and "
    "'short fiction' with #reddit on the Reel -- and those tags are how the platforms pick "
    "an audience, so it is not cosmetic. The 'original short fiction' note is emitted only "
    "for fiction channels; it has no business on factual car advice.\n"
    "- GOTCHA for any one-off posting script: bot.POST_LOG is a module global that only "
    "run_once() rebinds. Calling bot._post_video directly logs to whichever account was "
    "last set (default: ParkourFlux), so a second channel's post would eat the story "
    "channel's daily quota. Rebind bot.POST_LOG = Path(acc.post_log) first.\n\n"
    "SECOND CHANNEL -- carveteran (@thecarveteran) -- LIVE since 2026-08-09:\n"
    "- ** IT IS NOT A REDDIT-STORY CHANNEL. ** Two characters -- Rusty, a grizzled veteran "
    "muscle car, and Sparky, a naive rookie -- in two-voice dialogue teaching money-saving "
    "CAR TIPS. Facts and hacks, not stories. Videos come from dialogue_video.py "
    "(--topic/--episode/--footage), which renders but does NOT post.\n"
    "- FIRST POST went out 2026-08-09: 'Never Let The Shop Touch This One Part' "
    "(youtube LSDr7yu6KRs + an IG Reel + Story). Early numbers: IG 1,037 views / 920 reach "
    "/ 10 likes / 1 save, YouTube 168 views. IG is again the traction leader, ~6x YouTube, "
    "matching the main channel's pattern. It was posted MANUALLY as a one-off test; the "
    "user wants to see how it does before automating anything.\n"
    "- It is STILL `enabled: false` and `ig_enabled: false` ON PURPOSE, so the autonomous "
    "loop never touches it. Do not flip either without the user asking. Both YouTube and "
    "Instagram are fully authorised, so it CAN post the moment they say so.\n"
    "- `bot.py --account carveteran` now RAISES (accounts carry content_type; carveteran "
    "is 'dialogue', bot.py requires 'story'). Note --force bypasses `enabled`, so that flag "
    "was never the real protection. To make a car video: dialogue_video.py.\n"
    "- EPISODE 5 IS THE RENDER BASELINE for this channel: characters carry drop shadows "
    "(scripts/make_faces.py regenerates them from the expression grids), background clips "
    "hold 8-13s so the footage does not appear to cut on every speaker change, Rusty +5% / "
    "Sparky +12% rate, 120ms between lines, captions centred vertically.\n\n"
    "AUTHENTICITY (issue #6, 2026-08-07) -- the stories are ORIGINAL, we do not scrape "
    "Reddit (USE_REDDIT_SOURCE has been False since the API was denied). So: hook cards "
    "no longer print 'posted in r/X', the fake verified tick and '99+' like/comment "
    "counts were removed, YouTube descriptions state the work is original short fiction "
    "and no longer carry #redditstories, and compilation titles say '(Story Compilation)' "
    "rather than '(Reddit Compilation)'. Instagram captions keep #redditstories "
    "deliberately -- it is a real discovery tag there and there is no equivalent policy "
    "pressure. IG captions now drive a PROFILE VISIT instead of pointing at YouTube, "
    "because profile_views measured ZERO over 28 days against 972 reach.\n\n"
    "CURRENT VIDEO FORMAT (updated 2026-07-18):\n"
    "- Narration at +15% speed (fast like winning channels; captions carry clarity).\n"
    "- Video length now VARIES 30-60 seconds (each story gets a random length target, "
    "weighted shorter) for feed variety -- was a fixed ~60s.\n"
    "- Hook card shows the channel logo + handle + highlighted hook. It NO LONGER "
    "prints 'posted in r/X', and no longer shows a verified tick or '99+' engagement "
    "counts -- see AUTHENTICITY above. Do not tell the user the card carries a "
    "subreddit; that changed on 2026-08-07.\n"
    "- Stories and captions are generated with strict grammar/spelling/punctuation.\n"
    "- GROWTH LEVERS (added 2026-07-19, tuned from real data — IG is the traction "
    "leader ~20x YouTube): (1) HOOK — every story opens on an unresolvable curiosity "
    "loop in the first line (the old 'undersell the drama' rule was flipped; it was "
    "killing the first 2 seconds). (2) SHARES — endings land on a send-worthy payoff "
    "(IG's #1 ranking signal). (3) COMMENTS — every video ends on a verdict question "
    "('Was I wrong?') and captions include one too. (4) PT2 cliffhangers — non-final "
    "parts end on 'You are NOT ready for what happens next. Follow for part X.'\n"
    "- Captions are AI-written per video using a weekly web-researched trends file "
    "(refresh with the refresh_trends tool); share-bait focused, 3-5 tags.\n"
    "- HASHTAG RULES (set 2026-07-23): (1) the FIRST tag always matches the subreddit "
    "printed on the video's hook card -- r/nosleep -> #nosleep, r/pettyrevenge -> "
    "#pettyrevenge -- so the caption and the on-screen card never claim different "
    "communities. (2) Tags describe the STORY, never the footage: '#minecraftparkour' "
    "was removed because it went on every post and put landlord/family drama in front "
    "of Minecraft players, which is the wrong audience. The gameplay is only wallpaper. "
    "(3) Subject-specific tags are added from the hook (landlord -> #landlord "
    "#badlandlord, wedding -> #weddingdrama, boss -> #workstories, HOA -> #hoa, etc.). "
    "(4) Capped at 5, deduped -- focused sets beat walls of tags. (5) A guard "
    "(_clean_tags in social_caption) runs on the FINAL tag set every post: it "
    "normalises tags, auto-drops any wallpaper/gaming tag (#minecraftparkour etc.), "
    "and auto-corrects known typos (#proreveng->#prorevenge) -- so even a bad tag from "
    "the weekly trends refresh can't reach a live caption. This class of mistake is "
    "handled and should not recur. (Older posts made before 2026-07-24 may still show "
    "the old tags; not worth editing -- they're all performing.)\n"
    "- Saga parts drip 2 hours apart; singles-first strategy.\n"
    "- AUTO COMMENT REPLIES (comment_replies.py, added 2026-07-19): can reply to new "
    "YouTube + Instagram comments with short on-brand replies (drives comments/community "
    "-> reach + follows). Currently OFF by default. Before it can post it needs: YouTube "
    "re-auth with the force-ssl scope (add_channel.py) and the IG instagram_manage_comments "
    "permission. Use the reply_to_comments tool with dry_run=true to PREVIEW replies safely, "
    "dry_run=false to actually post. It's rate-limited and never double-replies.\n"
    "- Background footage (RESTRUCTURED 2026-08-09): every channel owns a tree and can "
    "see NOTHING outside it. accounts.footage_root() decides: footage/<account_id>/ "
    "first, then the account's footage_dir, then the shared footage/. Layout now is "
    "footage/parkourflux/{bright_biomes,night_1080,orbital_day} (29 Minecraft clips) and "
    "footage/driving/ (15 GTA/driving clips, the car channel). Each video picks ONE themed "
    "subfolder and stays in it, then cuts a fresh random montage inside it.\n"
    "- SO: to add clips for a channel, put them in THAT channel's tree -- new clips "
    "dropped loose in footage/ now reach nobody. A folder starting with '_' is never drawn "
    "(footage/_unusable/ holds a clip with a Twitch logo burned into it). This replaced a "
    "setup where any new folder under footage/ silently joined the story channel's "
    "rotation: renaming one folder put car clips into ParkourFlux's draw at 24%, and two "
    "story videos published over GTA footage on 2026-08-09 before it was caught (the user "
    "deleted them). Do not describe footage/ as a shared auto-split pool any more.\n\n"
    "STRATEGY:\n"
    "- CONTENT LEAN-IN (set 2026-07-22, re-confirmed by the owner 2026-07-23): the only "
    "videos that have broken out are 'parkour-meta' -- the conflict is about the narrator's "
    "own gaming/parkour life (354 and 252 views vs ~11-14 for generic drama, a ~25x gap). "
    "60% of stories are steered there via config.PARKOUR_META_SHARE; 40% stays open so we "
    "keep testing. This was briefly reversed to 0.0 on 2026-07-23 over a concern that the "
    "footage is only wallpaper, then reversed back the same day -- the numbers win. Keep "
    "the lean-in unless it stops breaking out twice running.\n"
    "- WHAT ALSO WINS is a STRUCTURE, worth applying to every story regardless of angle. "
    "Both breakouts shared one: "
    "(a) someone destroys/takes something IRREPLACEABLE the narrator made or kept, and "
    "doesn't think it mattered (354 views), or (b) ABSURD AUTHORITY OVERREACH -- petty "
    "power punishing something harmless with a ridiculous specific number attached (252 "
    "views). Those shapes are portable to ANY real-life premise, and story_bank now aims "
    "for them. Concrete specifics (exact amounts, exact timeframes) are what make it land.\n"
    "- Post singles first to test what resonates. Do NOT start multi-part series unless the "
    "user explicitly requests one or a topic has proven strong engagement.\n"
    "- We're testing what works and what doesn't -- a flopped 4-part saga wastes 4 of our "
    "18 weekly slots. Singles let us test more topics with less risk.\n"
    "- When reporting status, always mention how many of the 14 weekly slots have been used.\n\n"
    "The user can attach files: images you can see directly; "
    "videos (.mp4) are usually background footage -> move_file dest 'footage' (or 'satisfying'); "
    "audio (.mp3) -> 'music'; logo images -> 'branding'. Text files: their content is included "
    "in the message. Ask before filing if the destination is ambiguous. Be concise, friendly, "
    "and action-oriented. Confirm what you did in one line.")


# Refresh the dashboard data if it's older than this when someone opens the
# page. A background timer keeps it broadly current; this makes it current the
# moment you actually look, which is the only time it matters.
STALE_MINUTES = 8


def _stats_age_minutes() -> float:
    """Minutes since the stats were last fetched (inf if never/unreadable)."""
    import time
    try:
        newest = max((ROOT / "output" / f).stat().st_mtime
                     for f in ("channel_stats.json", "ig_stats.json"))
        return (time.time() - newest) / 60
    except Exception:
        return float("inf")


@app.route("/")
def index():
    # Kick a refresh off in the background and serve the current page straight
    # away -- blocking on three API calls would make the dashboard feel broken.
    # The page's own 5-minute auto-reload then picks the new numbers up.
    if not _busy["syncing"] and _stats_age_minutes() > STALE_MINUTES:
        _busy["syncing"] = True
        threading.Thread(target=_run_sync, daemon=True).start()
    return send_file(ROOT / "dashboard" / "live.html")


@app.route("/api/stats-age")
def stats_age():
    """Lets the page decide whether it's worth reloading."""
    return jsonify({"ageMinutes": round(_stats_age_minutes(), 1),
                    "syncing": _busy["syncing"]})


@app.route("/api/upload", methods=["POST"])
def upload():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "no file"}), 400
    UPLOADS.mkdir(parents=True, exist_ok=True)
    name = secure_filename(f.filename)
    f.save(UPLOADS / name)
    ext = Path(name).suffix.lower()
    kind = "image" if ext in IMG_EXT else ("text" if ext in {".txt", ".md", ".json", ".csv"} else "media")
    return jsonify({"name": name, "kind": kind,
                    "size_mb": round((UPLOADS / name).stat().st_size / 1e6, 1)})


def _attachment_blocks(atts):
    """Turn uploaded attachments into content blocks for the model."""
    blocks = []
    for a in atts:
        p = UPLOADS / secure_filename(a.get("name", ""))
        if not p.exists():
            continue
        ext = p.suffix.lower()
        if ext in IMG_EXT and p.stat().st_size < 5_000_000:
            blocks.append({"type": "image", "source": {
                "type": "base64", "media_type": MEDIA_TYPES.get(ext, "image/png"),
                "data": base64.standard_b64encode(p.read_bytes()).decode()}})
            blocks.append({"type": "text", "text": f"[attached image: {p.name}]"})
        elif ext in {".txt", ".md", ".json", ".csv"} and p.stat().st_size < 200_000:
            blocks.append({"type": "text",
                           "text": f"[attached file {p.name}]:\n{p.read_text(encoding='utf-8', errors='replace')[:8000]}"})
        else:
            blocks.append({"type": "text",
                           "text": f"[attached media file: {p.name}, {round(p.stat().st_size/1e6,1)} MB — in uploads, can be filed with move_file]"})
    return blocks


def _fast_reply(text: str):
    """Answer common questions from LOCAL data with no Claude call, to save
    API tokens (every Discord DM would otherwise cost a round-trip, and a tool
    call costs two). Deliberately conservative: only fires on short, clearly
    matching messages, and returns None for anything conversational so the real
    assistant still handles nuance. Reuses the same tool functions the LLM would
    have called, so answers stay identical -- just without the model in the loop.
    """
    t = text.strip().lower()
    words = t.split()
    if not words or len(words) > 8:      # long/complex -> let Claude handle it
        return None

    def has(*keys):
        return any(k in t for k in keys)

    # greetings / thanks / help -- pure static, the most common no-value calls
    if t in {"hi", "hey", "hello", "yo", "sup", "hiya", "gm", "good morning"} or \
            (len(words) <= 2 and has("hello", "howdy")):
        return ("Hey 👋 I'm your ParkourFlux ops bot. Ask me for **stats**, "
                "**recent posts**, whether **autonomy** is on, or what's "
                "**scheduled** — or just tell me what to do.")
    if len(words) <= 3 and has("thank", "thanks", "ty", "appreciate"):
        return "Anytime 👊"
    if t in {"help", "commands", "menu"} or has("what can you do", "what can u do"):
        return ("**Quick commands** (free, instant):\n"
                "• `stats` — views, subs, top video\n"
                "• `recent` — last 8 posts\n"
                "• `health` — is anything broken?\n"
                "• `autonomy` — is auto-posting on?\n"
                "• `sync` — force-refresh the dashboard\n"
                "_Or just tell me what to do_ (post a video, reply to comments, "
                "push to TikTok, remember a note…) and I'll handle it.")

    # stats -- read the two stats JSON files directly (pure local, fast, can't
    # fail on a slow API the way the full daily_report can)
    if has("stats", "report", "how are we doing", "how we doing", "numbers",
           "how's it going", "hows it going", "views", "subs", "subscribers"):
        try:
            yt = json.loads((ROOT / "output/channel_stats.json").read_text())
            ig = json.loads((ROOT / "output/ig_stats.json").read_text())
            vids = yt.get("videos", [])
            live = [v for v in vids if not v.get("publishAt")]
            sched = len(vids) - len(live)
            ytv = sum(v["views"] for v in live)
            top = max(live + [{"views": 0, "title": "-"}], key=lambda v: v["views"])
            igv = ig.get("totalViews", 0)
            sync = yt.get("fetchedAt", "?")[:16].replace("T", " ")
            return (
                "📊 **ParkourFlux stats**\n"
                f"┃ **YouTube** — {ytv:,} views · {yt.get('subscribers',0)} subs\n"
                f"┃ {len(live)} live" + (f" · {sched} scheduled" if sched else "") + "\n"
                f"┃ **Instagram** — {igv:,} views · {len(ig.get('media',[]))} posts\n"
                f"┃ **Combined** — {ytv+igv:,} views\n"
                f"🏆 Top: {top['title'][:50]} — {top['views']:,} views\n"
                f"_synced {sync}_")
        except Exception:
            return None

    # health / preflight -- run the same checks the hourly monitor runs, on
    # demand. Local + API checks only, so it costs no Claude tokens.
    if has("health", "preflight", "everything ok", "everything okay",
           "is it working", "all good", "system check", "healthcheck"):
        lines = []
        try:
            import health_check
            probs = health_check.collect()
            if probs:
                lines.append("🚨 **Problems found:**")
                lines += [f"• {p}" for p in probs]
            else:
                lines.append("✅ **Healthy** — no problems detected.")
        except Exception as e:
            lines.append(f"⚠️ Health check failed to run: {str(e)[:120]}")
        # a couple of at-a-glance numbers so the reply is useful either way
        try:
            import bot as _b
            import config as _c
            lines.append(
                f"_weekly {_b.this_weeks_upload_count()}/{_c.WEEKLY_POST_TARGET} · "
                f"today {_b.todays_story_count()}/{_c.DAILY_POST_TARGET} stories · "
                f"autonomy {'ON' if 'ON' in t_get_autonomy(None) else 'OFF'}_")
        except Exception:
            pass
        return "\n".join(lines)

    # force a dashboard sync -- pull fresh stats + rebuild live.html
    if has("sync", "refresh dash", "refresh the dash", "update dash",
           "update the dash", "force sync", "resync"):
        if not _dash_online():
            return "⚠️ Dash is not online. Start it with `scripts\\start_server.bat`."
        if _busy["syncing"]:
            return "🔄 A sync is already running — give it a few seconds."
        _busy["syncing"] = True
        threading.Thread(target=_run_sync, daemon=True).start()
        return ("🔄 Forcing a dashboard sync — pulling fresh YouTube + Instagram "
                "numbers. Live at localhost:8000 in ~30s (refresh the page).")

    # autonomy on/off -- reuse the schtasks query (no Claude)
    if has("autonomy", "autonomous", "is it on", "is it running", "running?",
           "auto post", "autopost"):
        return t_get_autonomy({})

    # recent activity (only when it's clearly a status question, not "post ...")
    if has("recent", "last post", "last posts", "what did you post",
           "latest", "what's posted", "whats posted") and not has("post a", "make", "create", "new"):
        try:
            log = ROOT / "output/post_log.csv"
            rows = [r for r in csv.reader(open(log))
                    if len(r) >= 4 and r[3] in ("posted", "posted_manual", "posted_instagram")]
            if not rows:
                return "No posts yet."
            where = {"posted": "YouTube", "posted_manual": "YouTube",
                     "posted_instagram": "Instagram"}
            lines = ["**Recent posts**"]
            for r in rows[-8:][::-1]:
                title = r[1].replace("_", " ")[:46]
                day = r[0][:10]
                lines.append(f"• `{day}` {title} → {where.get(r[3], r[3])}")
            return "\n".join(lines)
        except Exception:
            return None

    return None


@app.route("/api/chat", methods=["POST"])
def chat():
    history = request.json.get("messages", [])
    atts = request.json.get("attachments", [])
    # Fast path: answer common questions from local data, no API token spent.
    # Only when there's a single plain-text user turn and no attachments.
    if not atts and history and history[-1].get("role") == "user" \
            and isinstance(history[-1].get("content"), str):
        fr = _fast_reply(history[-1]["content"])
        if fr is not None:
            return jsonify({"reply": fr, "cached": True})
    conv = [{"role": m["role"], "content": m["content"]} for m in history]
    if atts and conv and conv[-1]["role"] == "user":
        text = conv[-1]["content"]
        conv[-1]["content"] = _attachment_blocks(atts) + [{"type": "text", "text": text or "(see attachments)"}]
    mem = _load_memory()
    # Cache the stable prefix. Render order is tools -> system -> messages, so a
    # breakpoint on a system block covers the tool definitions too -- together
    # ~4.3k tokens that were being re-billed at full price on every message and
    # on every tool round-trip below.
    #
    # Two breakpoints, one per stability boundary. The first covers tools +
    # SYSTEM, neither of which changes at runtime, so it still hits after the
    # user saves a memory note. The second adds memory, which changes only on
    # `remember`/`forget`. Memory goes last for that reason: putting it earlier
    # would invalidate the tools and system prompt behind it.
    #
    # Worth it even for a one-off question: a cache write costs ~1.25x and a
    # read ~0.1x, so this pays for itself on the second call -- and any message
    # that triggers a tool makes at least two.
    system = [{"type": "text", "text": SYSTEM,
               "cache_control": {"type": "ephemeral"}}]
    if mem:
        system.append({
            "type": "text",
            "text": "YOUR PERSISTENT MEMORY (notes you saved in past conversations):\n"
                    + "\n".join(f"- [{n['d']}] {n['note']}" for n in mem[-40:]),
            "cache_control": {"type": "ephemeral"},
        })
    for _ in range(6):  # cap tool round-trips
        r = client.messages.create(model="claude-sonnet-5", max_tokens=1024,
                                   system=system, tools=TOOLS, messages=conv,
                                   thinking={"type": "disabled"})
        conv.append({"role": "assistant", "content": r.content})
        if r.stop_reason == "tool_use":
            results = []
            for b in r.content:
                if b.type == "tool_use":
                    out = DISPATCH[b.name](b.input)
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": out})
            conv.append({"role": "user", "content": results})
            continue
        reply = "".join(b.text for b in r.content if b.type == "text")
        return jsonify({"reply": reply})
    return jsonify({"reply": "(stopped after too many steps)"})


if __name__ == "__main__":
    # A second control server can trigger posts through the same tokens as the
    # first. Port 8000 only stops the second one serving HTTP -- it does not
    # stop it existing, and two were found running here alongside the playbox's.
    import single_instance
    single_instance.require("control_server")

    app.run(host="127.0.0.1", port=8000, debug=False)

"""
bot.py
The actual operations bot: checks footage, checks quota, generates a
story + video, and either parks it for review or uploads it -- logging
everything either way. This is what the scheduled task should call.

Usage:
    python3 bot.py
    python3 bot.py --topic "roommate horror"
"""

import csv
import json
import random
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import os

import config
from accounts import (Account, all_accounts, get_account, load_accounts,
                      resolve_footage, pick_background_set)
from story_bank import (generate_story_via_claude, load_story_bank,
                        split_story_into_parts)
from tts import generate_voice_edge, make_speakable, save_word_timings, WordTiming
from captions import build_caption_file
from assemble import assemble_video_dynamic

POST_LOG = Path("output/post_log.csv")
ERROR_LOG = Path("output/errors.log")
QUEUE_FILE = Path("output/post_queue/queue.json")

# YouTube's API quota resets at midnight Pacific -- count "today" the same way.
_PT = ZoneInfo("America/Los_Angeles")


def log_error(msg: str):
    ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(ERROR_LOG, "a") as f:
        f.write(f"{datetime.now()}: {msg}\n")
    # Ping the owner on Discord for real failures (never breaks the run).
    if any(k in msg.lower() for k in ("failed", "exhausted", "invalid", "expired", "quota")):
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).parent / "scripts"))
            from discord_notify import send_dm
            send_dm(f"⚠️ **Bot problem:** {msg}", ping=True)
        except Exception:
            pass


# A story counts as USED once it exists anywhere -- including a YouTube upload
# that's merely SCHEDULED (it will auto-release, so regenerating the story
# double-posts it) and one that only went to Instagram. Leaving those out is
# what let sisters_wedding_dress post twice: scheduled 2026-07-20, then
# generated and posted again 2026-07-22.
USED_STATUSES = ("posted", "posted_manual", "scheduled", "posted_instagram")
# Statuses that consumed a YouTube upload (quota/cap accounting). Instagram
# rows are excluded here or a cross-posted story would be counted twice.
YT_UPLOAD_STATUSES = ("posted", "posted_manual", "scheduled")


def todays_upload_count() -> int:
    if not POST_LOG.exists():
        return 0
    today = datetime.now(_PT).date()
    count = 0
    with open(POST_LOG) as f:
        for row in csv.reader(f):
            if not row or len(row) < 4 or row[3] not in YT_UPLOAD_STATUSES:
                continue
            try:
                if datetime.fromisoformat(row[0]).astimezone(_PT).date() == today:
                    count += 1
            except ValueError:
                continue  # header row
    return count


def this_weeks_upload_count() -> int:
    """Videos posted this week (Mon-Sun, Pacific time). Used to enforce the
    WEEKLY_POST_TARGET soft cap -- once hit, no new stories start until next
    Monday so we can test what resonates instead of burning slots."""
    if not POST_LOG.exists():
        return 0
    now = datetime.now(_PT)
    # Monday of this week at midnight
    week_start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0)
    count = 0
    with open(POST_LOG) as f:
        for row in csv.reader(f):
            if not row or len(row) < 4 or row[3] not in YT_UPLOAD_STATUSES:
                continue
            try:
                ts = datetime.fromisoformat(row[0]).astimezone(_PT)
                if ts >= week_start:
                    count += 1
            except ValueError:
                continue
    return count


def _base_title(name: str) -> str:
    """Strip the .mp4 and the _ptN suffix down to the base story title."""
    return re.sub(r"_pt\d+$", "", name.removesuffix(".mp4"))


def posted_titles() -> set[str]:
    """Base story titles already posted -- never post the same story twice."""
    titles = set()
    if not POST_LOG.exists():
        return titles
    with open(POST_LOG) as f:
        for row in csv.reader(f):
            if row and len(row) >= 4 and row[3] in USED_STATUSES:
                titles.add(_base_title(row[1]))
    return titles


def _stem_posted(stem: str) -> bool:
    """True if this EXACT video (file stem, e.g. 'foo_pt1') is in the post log
    as posted/scheduled -- used to keep saga parts strictly in order."""
    if not POST_LOG.exists():
        return False
    with open(POST_LOG) as f:
        for row in csv.reader(f):
            if (row and len(row) >= 4 and row[1] == stem
                    and row[3] in ("posted", "posted_manual", "scheduled",
                                   "posted_instagram")):
                return True
    return False


def _earlier_part_posted(file_path: str) -> bool:
    """For a '..._ptN' video, True unless it's part >=2 whose immediately
    previous part isn't posted yet (so a later part never goes out first)."""
    import re
    stem = Path(file_path).stem
    m = re.search(r"_pt(\d+)$", stem)
    if not m or int(m.group(1)) < 2:
        return True
    n = int(m.group(1))
    prev = stem[:m.start()] + f"_pt{n - 1}"
    return _stem_posted(prev)


def todays_story_count() -> int:
    """
    Distinct stories posted today (PT). Every part of a multi-part saga shares
    one base title, so a whole saga counts as a single story toward the daily
    target -- while each part still counts against the YouTube upload quota.
    """
    if not POST_LOG.exists():
        return 0
    today = datetime.now(_PT).date()
    stories = set()
    with open(POST_LOG) as f:
        for row in csv.reader(f):
            if not row or len(row) < 4 or row[3] not in USED_STATUSES:
                continue
            try:
                if datetime.fromisoformat(row[0]).astimezone(_PT).date() == today:
                    stories.add(_base_title(row[1]))
            except ValueError:
                continue
    return len(stories)


def _queue_add(items: list[dict]):
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    q = json.loads(QUEUE_FILE.read_text()) if QUEUE_FILE.exists() else []
    q.extend(items)
    QUEUE_FILE.write_text(json.dumps(q, indent=2))
    print(f"Queued {len(items)} later part(s) to drip every 2 hours.")


def _queue_pop_due() -> dict | None:
    """
    Return the earliest queued part whose scheduled time has arrived
    (post_after <= now), removing it. Later parts of a saga drip out one per
    2 hours, so a run before the next part is due returns None.
    """
    if not QUEUE_FILE.exists():
        return None
    q = json.loads(QUEUE_FILE.read_text())
    now = datetime.now(_PT)
    changed = False
    due = None
    remaining = []
    for item in q:
        if due is None:
            try:
                ready = datetime.fromisoformat(item["post_after"]) <= now
            except (KeyError, ValueError):
                ready = True  # malformed -> treat as due so it isn't stuck forever
            # Never release a later part before its earlier part is live.
            if ready and not _earlier_part_posted(item["file"]):
                ready = False
            if ready:
                if Path(item["file"]).exists():
                    due = item
                    changed = True
                    continue
                log_error(f"Queued file missing, dropped: {item['file']}")
                changed = True
                continue
        remaining.append(item)
    if changed:
        QUEUE_FILE.write_text(json.dumps(remaining, indent=2))
    return due


def _norm_platforms(p) -> set[str]:
    """Normalize a platform selector to a subset of {'youtube','instagram'}.
    Accepts None / 'both' / 'all' (=both), a single name, or an iterable.
    Aliases: yt->youtube; ig/insta/reels->instagram."""
    if p is None or p in ("both", "all", ""):
        return {"youtube", "instagram"}
    names = {p} if isinstance(p, str) else set(p)
    alias = {"yt": "youtube", "youtube": "youtube",
             "ig": "instagram", "insta": "instagram", "instagram": "instagram",
             "reels": "instagram", "reel": "instagram"}
    out = {alias.get(str(n).lower().strip()) for n in names}
    out.discard(None)
    return out or {"youtube", "instagram"}


def _assert_may_post():
    """Refuse to publish from a machine that isn't the designated poster.

    A same-machine lock cannot help here: the Windows box and the playbox hold
    copies of the SAME YouTube and Instagram tokens, and each keeps its own
    output/post_log.csv (output/ is gitignored). So neither one's dedup can see
    what the other published -- two hosts will happily post the same story, and
    the logs will each look perfectly consistent afterwards.

    config.POSTING_HOST names the one host allowed to publish. Empty disables
    the check. MEDIAMAKER_ALLOW_POST=1 overrides it for a deliberate one-off
    from another machine, which is a thing we actually do.
    """
    import socket
    want = (getattr(config, "POSTING_HOST", "") or "").strip()
    if not want or os.environ.get("MEDIAMAKER_ALLOW_POST") == "1":
        return
    here = socket.gethostname()
    if here.lower().split(".")[0] != want.lower().split(".")[0]:
        raise RuntimeError(
            f"Refusing to post from {here!r}: config.POSTING_HOST is {want!r}.\n"
            f"{want} shares these tokens, so posting from here double-posts and "
            f"neither machine's post_log would show it.\n"
            f"Deliberate one-off? Set MEDIAMAKER_ALLOW_POST=1 for this run.")


def _post_video(path: str | Path, title: str, acc: Account | None = None,
                platforms=None, publish_at: str | None = None):
    """Post one rendered video. platforms: subset of {'youtube','instagram'}
    (default both). The two platforms are posted independently -- a failure on
    one never blocks the other. publish_at (RFC3339 UTC): schedule the YouTube
    upload to auto-release at that time instead of posting now.

    Returns the set of platforms it ACTUALLY posted to, which is not always
    what was asked for: each block is gated on config flags, account settings
    and a dedup check, and skipping is silent. Callers that report on the
    outcome must use this rather than assume the request succeeded."""
    acc = acc or Account()
    base = Path(path).stem
    platforms = _norm_platforms(platforms)
    _assert_may_post()
    # What actually went out, as opposed to what was asked for. Both platform
    # blocks below are guarded by compound conditions with no else branch, so a
    # skip is silent and indistinguishable from success to the caller --
    # coverage_check's --fix reported "Fixed 2" for two videos it never touched.
    _did: set[str] = set()

    if "youtube" in platforms:
        from youtube_upload import upload_video
        try:
            # Metadata comes from the ACCOUNT. It used to be hardcoded to the
            # story channel, so a second channel would have published its
            # videos tagged minecraft/parkour/short fiction -- wrong on the
            # page, and worse, it tells YouTube to show it to the wrong people.
            # The originality note only belongs on fiction, so it is skipped
            # where the content is factual.
            _note = (getattr(config, "ORIGINALITY_NOTE", "").strip()
                     if "fiction" in acc.yt_hashtags else "")
            video_id = upload_video(
                str(path), title=title,
                description=f"{_note}\n\n{acc.yt_hashtags}".strip(),
                tags=list(acc.yt_tags),
                privacy_status=config.PRIVACY_STATUS,
                token_file=acc.yt_token,
                publish_at=publish_at,
            )
            log_post(base, video_id, "scheduled" if publish_at else "posted")
            _did.add("youtube")
            if publish_at:
                print(f"Scheduled: {title} -> auto-releases {publish_at} "
                      f"(https://youtube.com/watch?v={video_id})")
            else:
                print(f"Posted: {title} -> https://youtube.com/watch?v={video_id}")
            # Branded thumbnail. On Shorts this doesn't show in the swipe feed,
            # but it does in search, the channel grid and suggested -- which is
            # what makes the channel read as one series instead of 22 random
            # frames. Never allowed to fail the upload.
            if getattr(config, "AUTO_THUMBNAIL", True):
                try:
                    import thumbnail
                    from rethumb import _theme_of, _short_text
                    phrase = thumbnail.hook_phrase(title)
                    if phrase == title:
                        phrase = _short_text(title)
                    th = thumbnail.build(phrase, theme=_theme_of(title),
                                         out=thumbnail.OUT_DIR / f"{video_id}.jpg")
                    thumbnail.set_on_video(video_id, th)
                except Exception as te:
                    print(f"Thumbnail skipped (video is fine): {te}")
        except Exception as e:
            log_error(f"Upload failed for {base}: {e}")
            log_post(base, None, "upload_failed")
            print(f"Upload failed, logged to errors.log: {e}")

    # Cross-post to Instagram Reels -- independent of the YouTube post.
    # Dedup: skip if this exact video already went to IG.
    if ("instagram" in platforms and config.POST_TO_INSTAGRAM and acc.ig_enabled
            and acc.ig_token and base not in _ig_posted()):
        try:
            from video_host import upload_public, delete_hosted
            from instagram_upload import post_reel, post_story
            capf = Path(f"{acc.out_dir}/{base}_caption.txt")
            caption = capf.read_text(encoding="utf-8") if capf.exists() else \
                f"{title}\n\n{acc.ig_hashtags}"
            url = upload_public(path)
            post_reel(url, caption=caption, ig_user=acc.ig_user_id, token=acc.ig_token)
            log_post(base, None, "posted_instagram")
            print(f"Cross-posted to Instagram: {base}")
            # Also drop it on the Story (cross-promo to existing followers,
            # pushes them to the Reel). Must run BEFORE delete_hosted -- the
            # Story container re-pulls the same URL. Never blocks the Reel: a
            # Story failure is logged and the run continues. Stories cap at 60s.
            if getattr(config, "POST_TO_IG_STORY", False):
                dur = _video_seconds(path)
                if dur and dur > 60:
                    print(f"Skipped Story (video {dur:.0f}s > 60s limit): {base}")
                else:
                    try:
                        post_story(url, ig_user=acc.ig_user_id, token=acc.ig_token)
                        print(f"Added to Instagram Story: {base}")
                    except Exception as se:
                        log_error(f"Instagram Story failed for {base}: {se}")
                        print(f"Story post failed (Reel unaffected): {se}")
            # IG has now pulled the file (Reel + Story) -> remove it from R2.
            delete_hosted(path)
            _did.add("instagram")
        except Exception as e:
            log_error(f"Instagram cross-post failed for {base}: {e}")
            print(f"Instagram cross-post failed (YouTube post unaffected): {e}")

    # Queue for TikTok behind the approval gate -- the Discord bot DMs a
    # preview and only publishes once the owner taps Approve. Never blocks or
    # affects the YouTube/Instagram posts above.
    if getattr(config, "TIKTOK_APPROVAL_GATE", False) and not publish_at:
        try:
            import tiktok_queue
            capf = Path(f"{acc.out_dir}/{base}_caption.txt")
            tiktok_queue.add(path, title=title,
                             caption=capf.read_text(encoding="utf-8") if capf.exists() else "")
            print(f"Queued for TikTok approval: {base}")
        except Exception as e:
            log_error(f"TikTok queue failed for {base}: {e}")

    return _did


def _video_seconds(path: str | Path) -> float:
    """Duration in seconds via ffprobe, or 0.0 if it can't be read (in which
    case callers treat length limits as unknown and proceed)."""
    import subprocess
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=30)
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def _ig_posted() -> set[str]:
    """Base titles already cross-posted to Instagram (dedup)."""
    t = set()
    if not POST_LOG.exists():
        return t
    with open(POST_LOG) as f:
        for row in csv.reader(f):
            if len(row) >= 4 and row[3] == "posted_instagram":
                t.add(row[1])
    return t


def log_post(story_title: str, video_id: str | None, status: str):
    POST_LOG.parent.mkdir(parents=True, exist_ok=True)
    is_new = not POST_LOG.exists()
    with open(POST_LOG, "a", newline="") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["timestamp", "story_title", "video_id", "status"])
        # Timezone-aware (local) so the Pacific-day quota count is unambiguous.
        writer.writerow([datetime.now().astimezone().isoformat(), story_title, video_id or "", status])


def run_once(background_dir: str | None = None, topic_hint: str = "",
             force: bool = False, account: Account | None = None,
             platforms=None, publish_at: str | None = None,
             story_title: str = ""):
    """One pass for ONE account. force=True: generate+post now, ignoring the
    daily-story target and the saga-drip queue (still respects YT quota).
    account=None -> the default (first) account; data paths (post log, queue)
    are namespaced per account via module globals so all helpers follow."""
    global POST_LOG, QUEUE_FILE
    acc = account or load_accounts()[0]
    POST_LOG = Path(acc.post_log)
    QUEUE_FILE = Path(acc.queue_file)
    # This whole function generates and posts Reddit-style narrated stories. An
    # account that makes something else must never reach it, whatever flags were
    # passed -- --account plus --force is enough to bypass `enabled`, which is
    # exactly how a Reddit revenge story once got generated for a car channel.
    if acc.content_type != "story":
        raise RuntimeError(
            f"Account '{acc.id}' is content_type={acc.content_type!r}, not "
            f"'story'. bot.py only makes narrated Reddit-style stories; posting "
            f"one to this channel puts the wrong channel's content on it. Use "
            f"the renderer for that content type instead (dialogue_video.py).")
    Path(acc.out_dir).mkdir(parents=True, exist_ok=True)
    print(f"[{acc.id}] run")
    # One background SET per video: if footage/ has themed subfolders, each
    # video picks one and stays in it. Consistent look within a video, a
    # different look between videos (cutting between worlds mid-story reads
    # as a glitch). Falls back to the flat pool when there are no subfolders.
    # quiet=True: this is only the "is there any footage at all" guard. The set
    # that actually gets used is re-picked below once the story's genre is
    # known -- announcing this throwaway pick made the logs read as if the
    # wrong background had been chosen.
    footage_files = (sorted(Path(background_dir).glob("*.mp4")) if background_dir
                     else pick_background_set(acc, quiet=True))
    if not footage_files:
        log_error(f"No footage available for account '{acc.id}'. Skipping run.")
        print("No footage available -- add clips to footage/ (or footage/"
              f"{acc.id}/) and re-run.")
        return
    print(f"[{acc.id}] footage pool: {len(footage_files)} clip(s)")

    if not config.REVIEW_MODE:
        # Never exceed the YouTube API upload quota (counts every video file).
        # This is a YOUTUBE limit, so it must only gate YouTube -- it used to
        # abort the whole run, which silently blocked Instagram-only posts on a
        # day when the YouTube quota happened to be spent.
        if todays_upload_count() >= config.YOUTUBE_DAILY_UPLOAD_LIMIT:
            wanted = _norm_platforms(platforms)
            if "youtube" in wanted:
                if wanted == {"youtube"}:
                    print("YouTube daily upload quota reached -- nothing to do.")
                    return
                platforms = sorted(wanted - {"youtube"})
                print("YouTube daily upload quota reached -- posting to "
                      f"{', '.join(platforms)} only.")
        weekly = this_weeks_upload_count()
        weekly_cap = getattr(config, "WEEKLY_POST_TARGET", 999)
        if not force and weekly >= weekly_cap:
            print(f"Weekly soft cap reached ({weekly}/{weekly_cap}) -- "
                  f"saving remaining slots. Nothing to do until next Monday.")
            return
        if not force:
            # Priority 1: a later part of an in-flight saga that's now due.
            # Parts drip one per 2 hours; runs regardless of the daily target so a
            # saga finishes even after the day's new-story slot is used.
            due = _queue_pop_due()
            if due:
                # Post the later part to the SAME platform(s) part 1 used (stored
                # on the queue item), not the current run's default.
                _post_video(due["file"], due["title"], acc,
                            due.get("platforms") or platforms)
                return
            # Priority 2: start a new story only if under the daily target. A
            # whole saga counts as one story here (its base title).
            if todays_story_count() >= acc.daily_target:
                print(f"Daily story target reached ({acc.daily_target}); "
                      f"no parts due -- nothing to do.")
                return

    # 1. Story -- generate fresh via Claude if ANTHROPIC_API_KEY is set,
    # otherwise fall back to the local story bank so the bot still runs.
    # Never post the same story twice.
    already = posted_titles()
    # Provenance for video_attrs: which of these paths produced the story, and
    # whether the topic hint was auto-discovered or handed in. Recorded per
    # video so hinted and unhinted cohorts can be compared later -- right now
    # trend_discovery is used purely on faith, with nothing measuring it.
    story_source = "bank"
    hint_source = "caller" if topic_hint else ""
    if story_title:
        # An explicitly requested story from the bank. The bank path otherwise
        # picks at random, so there was no way to say "post this one" -- which
        # is what you want when a story has been written or edited by hand.
        # Skips generation entirely; the hint and Reddit paths don't apply.
        bank = {s["title"]: s for s in load_story_bank()}
        story = bank.get(story_title)
        if story is None:
            # Match on words, not the raw string: bank titles are
            # underscore_joined, so a natural "fifth floor" would otherwise
            # suggest nothing at all -- the case where help is most wanted.
            def _norm(s):
                return s.lower().replace("_", " ").replace("-", " ").strip()
            _want = _norm(story_title)
            near = [t for t in bank
                    if _want in _norm(t)
                    or all(w in _norm(t).split() for w in _want.split())]
            log_error(f"No story titled {story_title!r} in the bank.")
            print(f"No story titled {story_title!r}."
                  + (f" Did you mean: {', '.join(near[:5])}?" if near else ""))
            return
        if story_title in already and not force:
            print(f"{story_title!r} has already been posted. Re-run with --force "
                  "to post it again.")
            return
        story_source = "requested"
        print(f"Using the requested story: {story_title}")
    elif os.environ.get("ANTHROPIC_API_KEY"):
        story = None
        # Priority: source from a REAL top Reddit post (hybrid -- proven-viral
        # content, then Claude condenses/cleans it). Falls back to fully AI if
        # no usable post (no creds, rate-limited, all filtered/used).
        if getattr(config, "USE_REDDIT_SOURCE", False):
            try:
                from reddit_source import fetch_top_post, mark_used
                from story_bank import condense_reddit_post
                post = fetch_top_post(genres=acc.genres)
                if post:
                    candidate = condense_reddit_post(post)
                    if candidate["title"] not in already:
                        mark_used(post["id"])
                        story = candidate
                        story_source = "reddit"
                        print(f"Sourced from r/{post['subreddit']} "
                              f"(score {post['score']}): {story['title']}")
            except Exception as e:
                log_error(f"Reddit source failed, using AI instead: {e}")
        # Fall back to fully AI-generated.
        if story is None:
            if not topic_hint:
                # Trend discovery (pytrends) is flaky -- a failure must not kill
                # the run; a missing hint just means Claude picks its own angle.
                try:
                    from trend_discovery import suggest_topic_hint
                    topic_hint = suggest_topic_hint(youtube_api_key=os.environ.get("YOUTUBE_API_KEY"))
                    if topic_hint:
                        hint_source = "trend_discovery"
                        print(f"Using trending topic hint: {topic_hint}")
                except Exception as e:
                    log_error(f"Trend discovery failed (continuing without a hint): {e}")
            # Recent premises to steer away from (keeps stories original, not
            # rehashed versions of the same setup).
            recent_premises = []
            if POST_LOG.exists():
                with open(POST_LOG) as _f:
                    for _row in csv.reader(_f):
                        if len(_row) >= 2 and _row[1]:
                            _p = _base_title(_row[1]).replace("_", " ").strip()
                            if _p and _p not in recent_premises:
                                recent_premises.append(_p)
            # 60, not 25: story_bank shows the model only the last 25 but counts
            # recurring words and pairings across everything it is given, and
            # this channel repeats itself slowly. The three near-identical
            # landlord premises never fell inside one 25-item window, so nothing
            # ever noticed they were the same story.
            recent_premises = recent_premises[-60:]
            # Avoid an already-posted title: retry a few times, then stop.
            for attempt in range(3):
                candidate = generate_story_via_claude(topic_hint=topic_hint,
                                                      genres=acc.genres, avoid=recent_premises)
                if candidate["title"] not in already:
                    story = candidate
                    story_source = "ai"
                    break
                log_error(f"Generated duplicate title ({candidate['title']}), retry {attempt + 1}/3")
        if story is None:
            log_error("Could not get a non-duplicate story after retries; stopping.")
            print("Kept getting already-posted titles -- stopping this run.")
            return
    else:
        fresh = [s for s in load_story_bank() if s["title"] not in already]
        if not fresh:
            log_error("Story bank exhausted -- every bank story already posted. Set ANTHROPIC_API_KEY or add stories.")
            print("Story bank exhausted -- nothing new to post.")
            return
        story = random.choice(fresh)
        print("No ANTHROPIC_API_KEY set -- using an unposted story from the local bank.")
    print(f"Story: {story['title']}")

    # A story longer than ~1 minute becomes a Part 1 / Part 2 / ... series --
    # each part ends on a cliffhanger and non-final parts carry follow bait.
    # All parts of one story count as a single run (MAX_VIDEOS_PER_RUN).
    parts = split_story_into_parts(story)
    if len(parts) > 1:
        print(f"Multi-part story: {len(parts)} parts")

    # Now that the story's genre is known, lock in the background SET for this
    # video (the earlier call was only a "do we have any footage at all" guard).
    # One set per story -- every part of a saga shares it, so a series looks
    # like a series instead of cutting to a different world in Part 2.
    if not background_dir:
        footage_files = pick_background_set(acc, genre=story.get("genre"))

    Path("output/pending_review").mkdir(parents=True, exist_ok=True)
    music_files = list(Path(config.MUSIC_DIR).glob("*.mp3")) if Path(config.MUSIC_DIR).exists() else []
    satisfying_files = (list(Path(config.SATISFYING_DIR).glob("*.mp4"))
                        if Path(config.SATISFYING_DIR).exists() else [])
    if satisfying_files:
        print(f"Split-screen mode: {len(satisfying_files)} satisfying clip(s) in pool")

    out_paths = []
    for part in parts:
        title = part["title"]
        # End CTA: non-final saga parts already carry a "follow for part X" line;
        # add a follow ask to the LAST part / singles too (spoken + captioned, so
        # it lands as both audio and on-screen text) to convert views -> follows.
        beats = list(part["beats"])
        if getattr(config, "END_CTA", True) and part["part"] == part["total_parts"]:
            # SHARE ask, not a follow ask. Shares (DM sends) are the top Reels
            # ranking signal, and the share-bait used to live only in the
            # caption -- which most viewers never read, so nothing in the video
            # itself asked for a send. The follow ask still runs, as the visual
            # end card, so the two asks don't compete in the same modality.
            share = (part.get("share_line") or "").strip()
            if getattr(config, "END_CTA_SHARE", True) and share:
                beats.append(share)
            else:
                beats.append(config.END_CTA_LINE)
        # Newline-joined beats give the voice a natural breath between
        # sentences; make_speakable rewrites written tokens for narration.
        full_text = make_speakable("\n".join(beats))

        # 2. Voice
        voice_out = f"voice/{title}.mp3"
        words = generate_voice_edge(full_text, voice_out)
        save_word_timings(words, f"voice/{title}_timings.json")

        # 3. Captions
        caption_path = f"{acc.out_dir}/{title}_captions.ass"
        word_dicts = [w.__dict__ if isinstance(w, WordTiming) else w for w in words]
        build_caption_file(word_dicts, caption_path)

        # 4. Assemble
        if config.REVIEW_MODE:
            out_path = f"output/pending_review/{title}.mp4"
        else:
            out_path = f"{acc.out_dir}/{title}.mp4"
        music = random.choice(music_files) if music_files else None
        if music:
            print(f"Music bed: {music.name}")

        hook_card = None
        hook_card_seconds = None
        if config.HOOK_CARD:
            from hook_card import GENRE_SUBREDDIT, build_hook_card, format_hook_for_display
            hook = part.get("hook") or part["beats"][0]
            part_label = f"PART {part['part']}/{part['total_parts']}" if part["total_parts"] > 1 else None
            hook_card = build_hook_card(format_hook_for_display(hook), f"{acc.out_dir}/{title}_card.png",
                                        handle=acc.handle,
                                        avatar_path=acc.logo,
                                        part_label=part_label,
                                        subreddit=(part.get("subreddit")
                                                   or GENRE_SUBREDDIT.get(part.get("genre"))
                                                   if getattr(config, "SHOW_SUBREDDIT_BADGE", False)
                                                   else None))
            if part["part"] == 1:
                # Card slides away as the hook line's narration ends.
                n_hook_words = len(hook.split())
                if words:
                    idx = min(n_hook_words, len(words)) - 1
                    end_ms = words[idx].end_ms if hasattr(words[idx], "end_ms") else words[idx]["end_ms"]
                    hook_card_seconds = end_ms / 1000 + 0.5
            else:
                # Later parts re-show the hook as context, briefly.
                hook_card_seconds = 3.5

        # Closing CTA card -- only on the LAST part, so a saga doesn't ask for
        # the follow before the story is finished.
        end_card = None
        cta_variant = ""
        if (getattr(config, "END_CARD", True)
                and part["part"] == part["total_parts"]):
            from hook_card import build_end_card
            from video_attrs import pick_cta_variant
            # Which follow-ask this video gets. Deterministic on the title, so
            # a re-render keeps the same variant and the comparison stays honest.
            cta_variant, cta_line = pick_cta_variant(
                title, getattr(config, "CTA_VARIANTS", []))
            if not cta_line:
                cta_line = getattr(config, "END_CARD_LINE", config.END_CTA_LINE)
            end_card = build_end_card(f"{acc.out_dir}/{title}_endcard.png",
                                      handle=acc.handle, avatar_path=acc.logo,
                                      line=cta_line.rstrip("."))

        assemble_video_dynamic(
            footage_files, voice_out, caption_path, out_path,
            satisfying_paths=satisfying_files or None,
            music_path=music, music_volume=config.MUSIC_VOLUME,
            cut_min=config.CUT_MIN_SECONDS, cut_max=config.CUT_MAX_SECONDS,
            hook_card_path=hook_card, hook_card_seconds=hook_card_seconds,
            end_card_path=end_card,
            end_card_seconds=getattr(config, "END_CARD_SECONDS", 6.0),
        )
        # Caption. A hand-written `caption` on the story wins -- if someone
        # took the trouble to write one, generating over it is just discarding
        # their work. Otherwise it's AI-written from current trends
        # (auto-refreshed weekly), falling back to the static template
        # internally if anything fails.
        #
        # Single-part only, deliberately: a series caption has to carry its own
        # part framing and the follow bait for parts 1..n-1, and one fixed
        # string cannot do that for every part. Rather than silently stamp the
        # same caption on all three parts, fall back and say so.
        from social_caption import ai_caption
        cap_hook = part.get("hook") or part["beats"][0]
        written = (part.get("caption") or "").strip()
        if written and part["total_parts"] == 1:
            caption_text = written
            print("Caption: using the story's hand-written caption.")
        else:
            if written:
                print(f"Caption: story has a hand-written caption, but this is "
                      f"part {part['part']}/{part['total_parts']} -- generating "
                      f"a per-part caption instead.")
            # Pass the same subreddit the hook card prints, so the caption's
            # lead hashtag matches what the viewer sees on screen.
            caption_text = ai_caption(cap_hook, handle=acc.handle,
                                      part=part["part"],
                                      total_parts=part["total_parts"],
                                      genre=part.get("genre"),
                                      subreddit=part.get("subreddit"))
        Path(f"{acc.out_dir}/{title}_caption.txt").write_text(
            caption_text, encoding="utf-8")

        out_paths.append(out_path)

        # Record what we CHOSE for this video, while we still know it. Retention
        # can be fetched for any video later; which CTA variant or background set
        # it used cannot be reconstructed after the fact.
        import video_attrs
        _last = words[-1] if words else None
        _end_ms = (getattr(_last, "end_ms", None)
                   or (_last.get("end_ms") if isinstance(_last, dict) else None) or 0)
        video_attrs.record(
            title,
            account=acc.id,
            genre=part.get("genre") or story.get("genre"),
            hook=part.get("hook") or part["beats"][0],
            part=part["part"],
            total_parts=part["total_parts"],
            multipart=part["total_parts"] > 1,
            narration_seconds=round(_end_ms / 1000, 1),
            background_set=(footage_files[0].parent.name if footage_files else None),
            cta_variant=cta_variant or None,
            source=story_source,
            trend_hint=topic_hint or None,
            hint_source=hint_source or None,
        )
        print(f"Assembled: {out_path}  (+ caption: output/{title}_caption.txt)")

    # 5. Hold for review, or post
    if config.REVIEW_MODE:
        for part, out_path in zip(parts, out_paths):
            log_post(part["title"], None, "pending_review")
            print(f"Saved for review: {out_path}")
        print("Run approve.py to review and post.")
        return

    # Autonomous: post part 1 now (title = the hook, the pattern that wins in
    # this niche). Later parts of a saga drip out one per 2 hours (still same day),
    # so the whole series lands while part 1 is fresh but only counts as one
    # story toward the daily target.
    from hook_card import format_hook_for_display
    hook = format_hook_for_display(story.get("hook") or story["beats"][0])
    # Video title = the scroll-stopping display_title if the model gave one,
    # else fall back to the hook. (The on-screen hook card still uses the hook.)
    title_text = format_hook_for_display(story.get("display_title") or hook)
    total = parts[0]["total_parts"]
    first_title = title_text if total == 1 else f"{title_text} (Part 1)"
    _post_video(out_paths[0], first_title, acc, platforms, publish_at)
    if len(parts) > 1:
        interval = timedelta(hours=config.PART_INTERVAL_HOURS)
        if publish_at:
            # SCHEDULED saga: upload every remaining part NOW, each with a
            # publish_at staggered AFTER part 1, so YouTube auto-releases them
            # strictly in order (part 1 first). Never drip a later part publicly
            # while part 1 is still scheduled -- that posts them out of order.
            base = datetime.fromisoformat(publish_at.replace("Z", "+00:00"))
            for p, op in zip(parts[1:], out_paths[1:]):
                pa = (base + interval * (p["part"] - 1)).strftime("%Y-%m-%dT%H:%M:%SZ")
                _post_video(op, f"{title_text} (Part {p['part']})", acc, platforms, pa)
        else:
            # Immediate saga: part 1 is already live, so drip parts 2+ one per
            # PART_INTERVAL_HOURS -- always after part 1, so still in order.
            now = datetime.now(_PT)
            plats = sorted(_norm_platforms(platforms))   # same platform(s) as part 1
            _queue_add([
                {
                    "file": op,
                    "title": f"{title_text} (Part {p['part']})",
                    "post_after": (now + interval * (p["part"] - 1)).isoformat(),
                    "platforms": plats,
                }
                for p, op in zip(parts[1:], out_paths[1:])
            ])


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", default="", help="Optional topic hint for story generation")
    ap.add_argument("--force", action="store_true", help="Post now, ignore the daily target")
    ap.add_argument("--count", type=int, default=1, help="How many fresh stories to push (with --force)")
    ap.add_argument("--account", default="", help="Run only this account id (default: all enabled)")
    ap.add_argument("--platform", default="both", choices=["both", "youtube", "instagram"],
                    help="Which platform(s) to post to (default: both)")
    ap.add_argument("--dry-render", action="store_true",
                    help="Generate + render a real video but DO NOT post it "
                         "(saved to output/pending_review/). Times the run -- "
                         "use this to test render speed on the stick.")
    ap.add_argument("--schedule-at", default="",
                    help="RFC3339 UTC time to auto-release on YouTube instead of "
                         "posting now (e.g. 2026-07-21T13:30:00Z). Forces "
                         "--platform youtube and --force.")
    ap.add_argument("--story", default="",
                    help="Post THIS story from stories/ by title (the filename "
                         "without .json), instead of generating one. Skips "
                         "generation; add --force to re-post one already posted.")
    args = ap.parse_args()
    if args.schedule_at:
        args.force = True
        args.platform = "youtube"

    import time as _time
    if args.dry_render:
        config.REVIEW_MODE = True   # render + save, skip all posting
        args.force = True           # ignore daily/weekly caps for the test
        print("[dry-render] rendering ONE video without posting...")

    accs = load_accounts()
    if args.account:
        # An explicit --account may name a DISABLED channel, on purpose. That is
        # what `enabled: false` is for: the hourly run skips a channel while it
        # is still being set up, but you have to be able to test-post to it by
        # hand before handing it to the bot. Without this you cannot post to a
        # new channel at all -- load_accounts() filters it out and --account
        # then matches nothing, so the run silently does nothing.
        #
        # Autonomous runs pass no --account and never see disabled channels.
        named = [a for a in accs if a.id == args.account]
        if not named:
            try:
                acc = get_account(args.account)      # raises KeyError if absent
            except KeyError:
                print(f"No account named {args.account!r}. Known: "
                      f"{', '.join(a.id for a in all_accounts())}")
                raise SystemExit(1)
            print(f"NOTE: '{acc.id}' is DISABLED. Running it because you asked "
                  f"for it by name -- the hourly run still skips it.")
            named = [acc]
        accs = named
    for acc in accs:
        try:
            for _ in range(args.count):
                _t0 = _time.time()
                run_once(topic_hint=args.topic, force=args.force, account=acc,
                         platforms=args.platform,
                         publish_at=args.schedule_at or None,
                         story_title=args.story)
                if args.dry_render:
                    print(f"[dry-render] done in {_time.time() - _t0:.0f}s "
                          f"-- see output/pending_review/")
        except Exception as e:
            log_error(f"[{acc.id}] run failed: {e}")
            print(f"[{acc.id}] run failed (continuing with next account): {e}")

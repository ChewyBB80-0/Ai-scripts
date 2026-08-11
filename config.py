"""
config.py
Central switches for the autonomous run. Flip REVIEW_MODE to False once
you trust the output quality and posting cadence.
"""

import os

# Load .env here, once, for everything.
#
# systemd hands .env to the services via EnvironmentFile=, so the timers were
# always fine -- but any script run BY HAND got an empty environment, and that
# has now bitten five separate entry points: preflight reported healthy
# credentials as MISSING, tiktok_upload died on a bare KeyError, health_check
# alarmed about a perfectly good Instagram token, ig_stats.py failed to fetch,
# and dialogue_video.py could not reach the Anthropic API. Each was patched
# individually; this stops the sixth.
#
# config is imported by 14 modules including every entry point, which makes it
# the one place that covers all of them. env_file.load() only fills variables
# that are UNSET, so it can never override what systemd already supplied, and
# it is silent and non-fatal when .env is absent.
try:
    import env_file
    env_file.load()
except Exception:
    pass

# Render profile. On a weak machine (the Atom-based stick PC), set the env var
# MEDIA_MAKER_LOW_SPEC=1 to drop to 720x1280 + a lighter encode so renders
# finish in a reasonable time and files stay small (helps the 64GB eMMC). The
# main PC leaves it unset and keeps full 1080x1920. The hook card auto-scales
# to whatever width is set, so the layout looks the same at any resolution.
_LOW_SPEC = os.environ.get("MEDIA_MAKER_LOW_SPEC") == "1"
RENDER_WIDTH = 720 if _LOW_SPEC else 1080
RENDER_HEIGHT = 1280 if _LOW_SPEC else 1920
FFMPEG_PRESET = "veryfast"                 # speed/size balance; good on weak CPUs
FFMPEG_CRF = "26" if _LOW_SPEC else "20"   # higher = smaller + faster to encode

# Auto-cleanup: delete rendered mp4s + voice tracks older than this many days
# each run, so the small eMMC on the stick doesn't fill up. Posted videos are
# already on YouTube/Instagram, so keeping local copies for a few days is
# plenty. Kept longer on the roomy main PC.
CLEANUP_KEEP_DAYS = 3 if _LOW_SPEC else 14

# When True: pipeline generates videos into output/pending_review/ and
# stops -- nothing gets posted automatically. You review and post by hand.
# Flipped False 2026-07-16 after 5 manually reviewed + posted videos.
REVIEW_MODE = False

# Source stories from REAL top Reddit posts (hybrid: pull proven-viral posts,
# Claude condenses/cleans each) instead of fully AI-inventing them. Needs
# REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET env vars (free Reddit "script" app);
# without them it silently falls back to AI-generated. See reddit_source.py.
# OFF -- Reddit DENIED the API application (2026-07-29). This was never used:
# 0 of the posts in the log came from it, because without credentials it always
# fell back to AI generation. Keeping it True just made the fallback look like a
# pending feature.
#
# Not worth pursuing further. Every breakout this channel has had was
# AI-written (354 / 252 / 123 / 81 views), so real posts were an untested
# assumption, and republishing someone's post carries a copyright problem
# regardless of how it is obtained. Scraping around the denial is also against
# Reddit's ToS. The code stays in reddit_source.py in case the API is ever
# granted; flip this back to True if so.
USE_REDDIT_SOURCE = False

# End-of-video call-to-action: append a spoken + captioned follow ask to the
# last part / single (non-final saga parts already say "follow for part X").
# This is the missing piece that converts views -> follows: most viewers never
# read the caption, so the ask has to be in the video itself.
END_CTA = True
END_CTA_LINE = "Follow for a new story every day."
# The visual closing card (last few seconds). A spoken CTA alone is easy to
# miss while the footage keeps scrolling; a held card with the handle is what
# actually converts a viewer into a follower.
END_CARD = True
END_CARD_LINE = "FOLLOW FOR A NEW STORY EVERY DAY"
END_CARD_SECONDS = 6.0

# The ONE machine allowed to publish. Both the playbox and the Windows box
# hold copies of the same YouTube/Instagram tokens, and each keeps its own
# output/post_log.csv -- so if both post, neither one's dedup can see the
# other's uploads and the same story goes out twice with both logs looking
# clean. The playbox is the 24/7 host, so it is the poster.
#
# Set to "" to allow any host. For a deliberate one-off from elsewhere, set
# MEDIAMAKER_ALLOW_POST=1 for that run rather than editing this.
POSTING_HOST = "krishplaybox"

# Situations the DATA says work, exempt from the motif ban's pair check.
#
# The ban catches a repeated SITUATION even when the individual words belong to
# a weighted theme -- that is what stops three near-identical stories shipping.
# But it cannot tell "we keep accidentally writing this" from "this is our best
# performer": "landlord charged" hit 735 views on Instagram against a 124
# median, ~6x the pack, and the ban was about to steer away from it.
#
# So winners are named here explicitly. Adding a line is a deliberate decision
# to make MORE of something, not an accident. Remove it when it stops working.
PROVEN_SITUATIONS = [
    "landlord charged",     # 735v vs 124 median (2026-08-08)
]

# --- Authenticity posture (issue #6) -------------------------------------
# YouTube's 2026 "inauthentic content" rules target, among other things,
# "readings of material you did not create". Our stories are ORIGINAL -- we
# write them, and Reddit sourcing has been off since the API was denied
# (USE_REDDIT_SOURCE = False).
#
# Presenting original fiction as scraped subreddit posts took on exactly that
# risk profile while doing none of the scraping, and originality is our single
# strongest defence. So: keep the confession VOICE, drop the claim that it came
# from Reddit. Set back to True to restore the r/ badge on hook cards.
SHOW_SUBREDDIT_BADGE = False

# The hook card used to draw a blue verified checkmark and "99+" like/comment
# counts. Both are fabricated: the channel is not verified anywhere, and no
# such engagement exists. That is the same problem as the r/ badge, one step
# further -- a subreddit label implied a source, a verification tick imitates a
# platform's own trust affordance and invents social proof to go with it.
# The icons stay (they read as a UI, and "Share" is a real ask); the claims go.
SHOW_FAKE_SOCIAL_PROOF = False

# Stated in every video description. Costs nothing, and it is the defence.
ORIGINALITY_NOTE = (
    "Original short fiction, written for this channel and narrated with a "
    "synthetic voice. Not a real post; any resemblance to real people or "
    "events is coincidental."
)

# CTA variants for the closing card. ~900 views and 0 subscribers means either
# nobody reaches the ask or the ask doesn't work, and one fixed line can never
# tell us which -- there's nothing to compare it against.
#
# Each video is assigned a variant deterministically from its title (see
# video_attrs.pick_cta_variant) and the choice is recorded, so once retention
# and subscriber data are available the variants can be compared instead of
# guessed at. Set to [] to go back to a single fixed END_CARD_LINE.
#
# They differ by the REASON to follow, not by wording: a standing promise, a
# similarity claim, a fear of missing the next one, a concrete next drop. If
# they only differed in phrasing the comparison would measure nothing.
CTA_VARIANTS = [
    ("daily",    "FOLLOW FOR A NEW STORY EVERY DAY"),
    ("more",     "FOLLOW FOR MORE STORIES LIKE THIS"),
    ("miss",     "FOLLOW SO YOU DON'T MISS THE NEXT ONE"),
    # Two short clauses rather than one dash-joined line: the card wraps to two
    # lines and an em dash left dangling at the break reads as a typo.
    ("tomorrow", "NEXT STORY TOMORROW. FOLLOW NOW"),
]

# Autonomous cadence: how many NEW stories to start per day (Pacific time,
# matching YouTube's quota reset). A multi-part saga counts as ONE story here
# even though it uploads several videos -- so this is "stories/day", while
# YOUTUBE_DAILY_UPLOAD_LIMIT caps total video uploads/day.
DAILY_POST_TARGET = 2

# Soft weekly cap -- pipeline skips new stories once this many have been
# posted in the current Mon-Sun window. Resets each Monday at midnight
# Pacific. The daily target above still applies within each day, so
# effective output is min(daily * 7, weekly).
WEEKLY_POST_TARGET = 14

# For a multi-part saga, later parts drip out this many hours apart (still the
# same day) so the series lands while Part 1 is fresh. The scheduled task must
# run at least this often (it runs hourly) for the drip to fire on time.
PART_INTERVAL_HOURS = 2

# Hard ceiling regardless of REVIEW_MODE -- one video per scheduled run.
MAX_VIDEOS_PER_RUN = 1

# YouTube Data API quota safety -- stop uploading before hitting the wall.
YOUTUBE_DAILY_UPLOAD_LIMIT = 6

# Privacy status used when the bot posts automatically (REVIEW_MODE = False).
# Set to "public" 2026-07-16 at the user's direction -- full autonomy.
PRIVACY_STATUS = "public"

# Where footage lives -- pipeline stops (doesn't error-loop) if empty.
FOOTAGE_DIR = "footage"

# Cross-post each YouTube post to Instagram Reels. Needs the one-time Meta
# setup (professional IG account + FB page + dev app token) AND a public
# video host (see video_host.py) -- flip True once IG_USER_ID/IG_ACCESS_TOKEN
# and the VIDEO_HOST_* env vars are set. IG failures never block the
# YouTube post; they log and move on.
POST_TO_INSTAGRAM = True

# Also drop each new Reel onto the Instagram STORY (the 24h ones at the top of
# the app). Pure cross-promotion to existing followers -- it surfaces the video
# to people who already follow and nudges them to the Reel/profile. No caption
# or hashtags on a Story. Only videos <=60s (the Story limit) are posted.
POST_TO_IG_STORY = True

# Auto comment-reply engine (comment_replies.py). Replies to new top-level
# comments on YouTube + Instagram with a short, on-brand, engagement-driving
# reply -- comments/replies are a strong ranking + community signal.
# OFF by default: turn on only AFTER re-authing YouTube with the force-ssl
# scope (add_channel.py) and confirming the IG token has instagram_manage_comments.
# Start with a dry run (python comment_replies.py --dry-run) to preview replies.
ENABLE_COMMENT_REPLIES = False
# Safety rate limit -- max replies posted per platform per run (avoids spam flags).
COMMENT_REPLY_LIMIT_PER_RUN = 15

# Optional background music beds (subtle, movie-style -- ducked under the
# narration). Drop .mp3 files here; bot picks one at random per video.
# Empty dir = videos render with narration only, no error.
MUSIC_DIR = "music"
MUSIC_VOLUME = 0.08

# Fast-cut pacing: backgrounds are stitched from short random segments
# pulled from across the whole footage pool instead of one clip playing
# from 0:00 -- constant visual motion, no dead air.
CUT_MIN_SECONDS = 3.5
CUT_MAX_SECONDS = 5.5

# Optional split-screen ("overstimulation" format): parkour on top,
# satisfying footage (cooking, slime, etc.) on the bottom. Drop licensed
# .mp4 clips here to activate; empty dir = full-frame parkour as usual.
SATISFYING_DIR = "footage_satisfying"

# "Social post" hook card overlay (ZoroTales-style): white rounded card at
# the top of the frame showing the story hook with highlighted keywords.
# The card stays on screen only while the hook line is being narrated.
# Put the channel logo at HOOK_CARD_AVATAR to use it as the card's pfp
# (falls back to a colored initial circle if the file doesn't exist).
HOOK_CARD = True
HOOK_CARD_AVATAR = "branding/logo.png"

# ---------------------------------------------------------------------------
# CONTENT LEAN-IN (set 2026-07-22, confirmed by the owner 2026-07-23)
# ---------------------------------------------------------------------------
# The two clear breakout videos on YouTube were both "parkour-meta" stories --
# the conflict itself was about the narrator's gaming/parkour life:
#   354 views  "My sister deleted the only clip of me beating a course..."
#   252 views  "My HOA president fined me $500 for 'excessive jumping'..."
# Generic Reddit drama on the same channel sits at ~11-14 views: a ~25x gap.
# This share of stories is steered to that angle; the rest stay open-ended so
# we keep testing fresh material and never go all-in on one bet.
#
# Briefly set to 0.0 on 2026-07-23 (concern: the footage is only wallpaper, so
# writing about parkour over-narrows the premises). The owner reversed that the
# same day -- the numbers win, and a generic-drama replacement title read as
# something they personally wouldn't click. Keep the lean-in.
#
# Worth carrying into every story regardless of angle: what those winners had
# structurally was (a) something IRREPLACEABLE destroyed by someone who didn't
# think it mattered, and (b) ABSURD authority overreach with a specific
# ridiculous number attached. Those shapes travel.
# Dial DOWN toward 0.0 only if parkour-meta stops breaking out twice running.
#
# LOWERED 0.6 -> 0.3 on 2026-07-27. Not because the angle stopped working --
# because THEME_WEIGHTS now does the steering job too, and stacking both
# over-narrows the premise space. Evidence: the first two themed stories both
# rolled the open theme bucket and, with a mandatory parkour angle on top,
# collapsed onto nearly the same premise an hour apart ("gym teacher
# confiscated my parkour shoes" / "PE teacher failed my parkour project").
# The originality guard blocks a repeated PREMISE but not a repeated SHAPE,
# and the motif ban needs a word 3+ times before it fires -- so neither
# catches a near-duplicate on the second occurrence.
# At 0.3 the angle still appears often; it just isn't compulsory on top of a
# theme constraint.
#
# TURNED OFF 2026-08-08, deliberately, knowing it was a measured winner.
#
# Parkour-meta stories tie the conflict to the narrator's Minecraft life, and
# two of the three best YouTube performers are that shape. But they only work on
# a channel whose wallpaper is parkour -- they cannot move to a second channel,
# and the owner's goal is now stories good enough to carry any footage. A story
# that needs the background to make sense is a story that only works here.
#
# What is OFF is GAMING-life drama: Minecraft, worlds and saves, servers,
# speedruns, streaming and channel drama. Real-life parkour is NOT off -- a
# story about training, an injury, a spot, a rival or a trespassing charge is a
# real-world story that travels to any channel, same as landlords or in-laws.
# The line is the gaming frame, not the word "parkour".
#
# The parkour footage stays either way. This is about what the stories are ABOUT.
#
# Set back to 0.3 to restore the angle; nothing else needs changing.
PARKOUR_META_SHARE = 0.0

# ---------------------------------------------------------------------------
# Trend hint share (added 2026-08-09)
# ---------------------------------------------------------------------------
# What fraction of AI-generated stories get a trending topic hint. NOT all of
# them, for two reasons.
#
# One: the signal is broad. YouTube's trending chart is global and returns K-pop
# dance practices and film trailers -- most of it has no bearing on a channel
# about landlords and in-laws. Applying that to every story would drag the whole
# output off-niche.
#
# Two: a minority share creates the cohort issue #7's Gap 2 asks for. Hinted and
# unhinted stories accumulate side by side, video_attrs records which is which,
# and retention answers whether hints help. At 1.0 there is nothing to compare
# against; at 0.0 the feature never runs. This is the same shape as
# THEME_WEIGHTS leaving 0.30 unweighted.
#
# Start low. Raise it only if the hinted cohort actually retains better.
TREND_HINT_SHARE = 0.25

# ---------------------------------------------------------------------------
# TikTok approval gate (added 2026-07-22)
# ---------------------------------------------------------------------------
# Every video the pipeline posts is also queued for TikTok; the Discord bot
# DMs a preview with Approve / Skip and only publishes on approval. This
# satisfies TikTok's Direct Post expectation that the creator reviews a post
# before it goes live, and costs one tap from anywhere. Until the production
# audit lands, approving sends the video to the TikTok draft inbox instead of
# publishing (tiktok_queue.approve handles the switch automatically).
# PAUSED 2026-07-23 by the user: no more TikTok pushes until TikTok's
# production audit comes through. Sandbox posts have limited visibility, so
# feeding it content now buys nothing. Flip back to True after the audit --
# tiktok_queue.approve() then direct-posts instead of using drafts, with no
# other change needed.
TIKTOK_APPROVAL_GATE = False

# ---------------------------------------------------------------------------
# THEME WEIGHTING (set 2026-07-26, from the channel's own numbers)
# ---------------------------------------------------------------------------
# Every breakout this channel has had sits in one of three themes:
#   354 views  family   (sister destroyed something irreplaceable)
#   252 views  hoa      (petty authority, absurd specific fine)
#   123 views  wedding  (maid-of-honor betrayal)
# Everything outside them sits at ~6-11 views.
#
# Weighting toward a few themes is what gives a channel an IDENTITY -- the big
# channels in this niche are recognisable lanes, not grab-bags, and that is
# what converts a viewer into a subscriber (the gap behind 800+ views, 0 subs).
# It also fills the themed-compilation buckets ~3x faster.
#
# A share of runs stays OPEN so we keep testing new angles and never go all-in
# on a bet -- same principle as the old parkour-meta lean-in.
THEME_WEIGHTS = {
    "family": 0.25,     # sibling/parent/in-law betrayal
    "hoa": 0.20,        # HOA, neighbour, petty local authority
    "wedding": 0.15,    # weddings, engagements, bridal drama
    "landlord": 0.10,   # landlord/tenant -- promising, tested well
}
# The remainder (0.30) is left unweighted: a free pick, so fresh themes can
# still surface and prove themselves.

# Auto-generate a branded thumbnail for each YouTube SHORT upload.
# OFF (owner's call, 2026-07-26): a custom thumbnail never shows in the Shorts
# swipe feed anyway -- YouTube always uses a frame there -- so it only affected
# search/channel-grid, which wasn't worth the per-upload cost and complexity.
# Compilations still get one automatically (see compilation.upload), where the
# thumbnail genuinely drives click-through.
AUTO_THUMBNAIL = False

# End the video on a SHARE ask (story-specific, generated with the story) rather
# than the follow ask. Shares/DM-sends are the top Reels ranking signal, and the
# share-bait previously lived only in the caption -- which most viewers never
# read, so nothing in the video itself asked for a send. The follow ask still
# runs as the visual END_CARD, so the two don't compete in the same modality.
# Falls back to END_CTA_LINE when a story has no share_line.
END_CTA_SHARE = True

# Scratch space for ffmpeg's intermediate segments during assembly.
# Empty/unset = alongside output/ (the previous behaviour, correct on Windows).
# On a Linux host with an HDD, point this at "/dev/shm" -- tmpfs is already
# mounted there on every Ubuntu install and sized at ~half of RAM, so it costs
# nothing to set up. Assembly writes and re-reads dozens of small files, which
# is precisely the pattern spinning disks handle worst; keeping them in RAM
# removes that I/O entirely. Falls back to output/ automatically if the path
# isn't writable, so setting it wrongly can't break a render.
TEMP_DIR = os.environ.get("MEDIA_MAKER_TEMP_DIR", "")

"""
social_caption.py
Builds an Instagram / TikTok caption for a story that's engineered to pull
comments and cross-traffic -- the caption IS the discovery engine on IG
(no algorithmic push like Shorts, so the hook + a comment-bait question +
hashtags do the work).

Structure: curiosity hook line -> comment-bait question -> follow CTA +
cross-platform nudge -> a focused hashtag set (niche tags first, broad last).
"""

import re

# 2026 algorithm reality: SHARES (DM sends) are the #1 ranking signal, then
# saves and watch time -- so captions end on share-bait/verdict-bait, not
# like-begging. Keyword-rich caption TEXT now beats hashtags for discovery,
# and 3-5 targeted tags outperform a wall of them.
ENGAGE = {
    "aitah": "YTA or NTA? Drop your verdict 👇 then send this to someone who needs the full story",
    "revenge": "Send this to someone who'd take it even further 😏",
    "confession": "Could you keep this secret? Send it to your bestie 👇",
    "creepy": "Send this to someone who wouldn't survive it 💀",
}

# Keyword-rich topic line (caption SEO -- the algorithm reads caption text
# for discovery now more than hashtags).
KEYWORDS = {
    "aitah": "Reddit AITA storytime — whose side are you on?",
    "revenge": "Reddit petty revenge storytime — the payback is unreal",
    "confession": "Reddit true confession storytime",
    "creepy": "Reddit scary storytime — this actually gave me chills",
}

# 3-5 focused tags total (niche-first + one format tag).
NICHE_TAGS = {
    "aitah": ["#aitah", "#redditstories", "#storytime"],
    "revenge": ["#pettyrevenge", "#redditstories", "#storytime"],
    "confession": ["#trueoffmychest", "#redditstories", "#storytime"],
    "creepy": ["#scarystories", "#redditstories", "#storytime"],
}
# Broad tags target the STORY audience, not the wallpaper. "#minecraftparkour"
# used to live here and went on every post -- putting landlord and family drama
# in front of Minecraft players, which is the wrong audience and costs reach.
# The gameplay is only something to watch while listening; nobody searches
# Minecraft tags looking for a story about a security deposit.
BROAD_TAGS = ["#storytimes", "#reels"]

# Extra tags matched to what the story is actually ABOUT. A landlord story
# reaching r/tenant-adjacent viewers converts far better than a generic one.
TOPIC_TAGS = {
    ("landlord", "lease", "tenant", "rent", "deposit", "eviction", "apartment"):
        ["#landlord", "#badlandlord", "#tenantrights"],
    ("hoa", "homeowners association"): ["#hoa", "#hoakaren"],
    ("boss", "manager", "coworker", "fired", "shift", "workplace", "hr "):
        ["#workstories", "#toxicworkplace"],
    ("wedding", "bride", "groom", "maid of honor", "bridesmaid"):
        ["#weddingdrama", "#bridezilla"],
    ("neighbor", "neighbour"): ["#neighbors", "#neighbordrama"],
    ("mother-in-law", "mil ", "in-law", "sister-in-law"): ["#inlaws", "#monsterinlaw"],
    ("nurse", "hospital", "night shift", "patient"): ["#nightshift", "#truestory"],
    ("customer", "server", "waitress", "retail", "tip"): ["#serverlife", "#retailstories"],
}


def topic_tags(text: str, limit: int = 2) -> list[str]:
    """Tags for the story's subject, matched on the hook text."""
    t = text.lower()
    for keys, tags in TOPIC_TAGS.items():
        if any(k in t for k in keys):
            return tags[:limit]
    return []


# Footage/wallpaper tags must never reach a caption -- they target the
# background (Minecraft players) instead of the story audience. The weekly
# AI-researched trends file has introduced these before, so this is enforced
# at use-time, not just in the static lists.
_BLOCKED_TAGS = {"#minecraftparkour", "#minecraft", "#parkour", "#gaming",
                 "#gameplay", "#mcparkour", "#minecraftshorts"}

# Known typos to auto-correct -- a misspelled tag reaches no one. '#proreveng'
# showed up before from the weekly trends refresh; add others here if spotted.
_TAG_FIXES = {"#proreveng": "#prorevenge"}


def _clean_tags(tags: list[str]) -> list[str]:
    """Normalise, drop wallpaper tags, and dedupe. Runs on the FINAL tag set so
    a typo or footage tag from any source (including the weekly trends refresh)
    can't slip into a live caption."""
    seen, out = set(), []
    for raw in tags:
        if not raw:
            continue
        # normalise: single leading #, lowercase, strip anything not a-z0-9
        t = "#" + re.sub(r"[^a-z0-9]", "", str(raw).lstrip("#").lower())
        t = _TAG_FIXES.get(t, t)
        if t in ("#", "") or t in _BLOCKED_TAGS or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _dedupe(tags: list[str]) -> list[str]:
    return _clean_tags(tags)


def subreddit_tag(genre: str | None = None, subreddit: str | None = None) -> str:
    """The hashtag matching the subreddit printed on the video's hook card.

    The card says "posted in r/nosleep", so the caption should carry #nosleep --
    otherwise the video claims one community on screen and tags a different one,
    which reads as careless and misses the audience actually searching that tag.
    """
    if not subreddit:
        from hook_card import GENRE_SUBREDDIT
        subreddit = GENRE_SUBREDDIT.get(genre or "")
    if not subreddit:
        return ""
    return "#" + subreddit.split("/")[-1].strip().lower()


def detect_type(hook: str) -> str:
    h = hook.lower()
    if "aitah" in h or "aita" in h:
        return "aitah"
    if any(w in h for w in ("never told", "confess", "off my chest", "secret", "shame")):
        return "confession"
    if any(w in h for w in ("docked", "fined", "hoa", "boss", "sergeant", "landlord",
                            "malicious", "revenge", "payback", "compliance")):
        return "revenge"
    return "creepy"


def _display_hook(hook: str) -> str:
    # Match the on-card convention: AITAH stories read as a real subreddit post.
    if "r/AITAH" in hook:
        return hook
    return hook.replace("AITAH", "r/AITAH", 1)


def build_caption(hook: str, handle: str, part: int | None = None,
                  total_parts: int = 1, genre: str | None = None,
                  subreddit: str | None = None) -> str:
    # Prefer the story's tagged genre (reliable); fall back to sniffing the hook.
    t = genre if genre in ENGAGE else detect_type(hook)
    # Hook first (first 125 chars decide the expand), then the SEO keyword
    # line so the algorithm categorizes the topic from caption text.
    head = _display_hook(hook).strip()
    # Parts 2+ share Part 1's hook; opening with it verbatim makes the feed
    # show two posts with an identical first line (see ai_caption).
    if total_parts > 1 and part and part > 1:
        head = f"Part {part} — it gets worse. {head}"
    lines = [head, KEYWORDS[t], ""]

    if total_parts > 1 and part and part < total_parts:
        lines.append(f"\U0001F534 PART {part}/{total_parts} — follow so you don't miss the ending, "
                     f"and send this to someone for their verdict \U0001F447")
    elif total_parts > 1 and part == total_parts:
        lines.append("The finale. Start at Part 1 on my page \U0001F440")
    else:
        lines.append(ENGAGE[t])

    # Drives a PROFILE VISIT, not a follow, and not a click to YouTube.
    #
    # This caption is Instagram-only (YouTube builds its own description in
    # bot.py), and it used to end "full library on YouTube" -- sending Reels
    # viewers to the channel with 936 views and 0 subscribers, away from the
    # platform doing 6,209. Measured 2026-08-08: profile_views over 28 days was
    # ZERO against 972 reach, which is why 48 posts converted 12 followers.
    #
    # "More on the page" is also true right now, for every viewer. "Follow for
    # part two" is not -- saga parts drip over ~2 hours, so for most of a part
    # 1's life the next part genuinely is not there yet.
    # The finale line already sends them to the page for Part 1, so adding a
    # second page ask stacks two identical CTAs and reads as filler.
    _is_finale = bool(total_parts > 1 and part == total_parts)
    lines += [
        "",
        (f"New story every day \U0001F3AC {handle}" if _is_finale
         else f"More stories like this on the page \U0001F440 {handle}"),
        "",
        " ".join(_dedupe([subreddit_tag(t, subreddit)] + NICHE_TAGS[t]
                         + topic_tags(hook) + BROAD_TAGS)[:5]),
    ]
    return "\n".join(lines)


def ai_caption(hook: str, handle: str, part: int | None = None,
               total_parts: int = 1, genre: str | None = None,
               subreddit: str | None = None) -> str:
    """
    AI-written caption using CURRENT trends (auto-refreshed weekly via web
    search). Falls back to the static template on any failure, so the
    pipeline never breaks.
    """
    try:
        import anthropic
        from trends import ensure_fresh
        t = genre if genre in ENGAGE else detect_type(hook)
        tr = ensure_fresh() or {}
        # niche + subject-specific + broad, deduped, capped at 5 (focused sets
        # outperform walls of tags)
        # The subreddit shown on the hook card leads, so caption and card agree.
        # _clean_tags normalises + strips wallpaper tags, so a bad tag from the
        # weekly trends refresh can't reach the caption.
        tags = _clean_tags([subreddit_tag(t, subreddit)] +
                           tr.get("tags", {}).get(t, NICHE_TAGS[t]) + topic_tags(hook) +
                           tr.get("tags", {}).get("broad", BROAD_TAGS))[:5]
        kw = tr.get("keywords", {}).get(t, KEYWORDS[t])
        tips = "; ".join(tr.get("tips", [])[:4])
        part_note = ""
        if total_parts > 1 and part and part < total_parts:
            part_note = f"This is PART {part}/{total_parts} — include follow-bait for the next part."
        elif total_parts > 1 and part == total_parts:
            part_note = "This is the FINALE — point new viewers to Part 1 on the page."

        # Every part of a saga carries Part 1's hook, so opening each caption
        # with it verbatim made consecutive posts look like the same post
        # reuploaded -- Instagram shows that first line in-feed. Parts 2+ get a
        # distinct opening instead.
        if total_parts > 1 and part and part > 1:
            line1_rule = (
                f'- Line 1: do NOT repeat Part 1\'s hook -- the previous post already '
                f'opened with it, and an identical first line makes this look like a '
                f'reupload in the feed. Write a DIFFERENT opening line for Part {part} '
                f'that picks the story up mid-escalation, teases where it goes, and '
                f'still makes sense to someone who never saw Part 1. Do not reuse the '
                f'wording of: "{_display_hook(hook)}"')
        else:
            line1_rule = f'- Line 1: the hook verbatim (it IS the hook: "{_display_hook(hook)}")'

        r = anthropic.Anthropic().messages.create(
            model="claude-sonnet-5", max_tokens=400,
            thinking={"type": "disabled"},
            messages=[{"role": "user", "content": f"""Write an Instagram Reels caption for a Reddit-style story video.
Story hook: {_display_hook(hook)}
Genre: {t}. {part_note}
Current trend notes: {tips or 'shares/DM-sends are the top ranking signal; keyword-rich captions beat hashtags; 3-5 tags only'}

Rules:
{line1_rule}
- Line 2: one keyword-rich SEO line similar to: {kw}
- Then ONE verdict QUESTION that baits comments (e.g. "Was I wrong?", "YTA or NTA?", "What would you have done?") — pick one that fits the genre
- Then ONE share-bait line (make the reader want to SEND this to someone specific — vary the phrasing, never generic "share this")
- Then: ONE line that drives a PROFILE VISIT, not a follow. The page already has dozens of these stories, so give them a reason to go and look NOW rather than a request to follow and wait. Vary the phrasing; never "link in bio", never mention YouTube.
- Last line exactly these tags: {' '.join(tags)}
- Correct grammar, spelling, and punctuation throughout (casual tone OK, errors not)
- No other text. Total under 500 characters before the tags."""}],
        )
        cap = next(b.text for b in r.content if b.type == "text").strip()
        # Sanity check: the caption should echo the hook's opening word -- but
        # parts 2+ are deliberately told NOT to reuse the hook's wording, so
        # that check would reject every valid one and fall back to the template.
        is_later_part = bool(total_parts > 1 and part and part > 1)
        echoes_hook = hook.split()[0].lower() in cap.lower()
        if len(cap) > 40 and (is_later_part or echoes_hook):
            return cap
        raise ValueError("caption sanity check failed")
    except Exception as e:
        print(f"ai_caption fell back to template: {e}")
        return build_caption(hook, handle=handle, part=part,
                             total_parts=total_parts, genre=genre,
                             subreddit=subreddit)


if __name__ == "__main__":
    import sys, json
    from pathlib import Path
    story = json.loads(Path(sys.argv[1]).read_text())
    from accounts import get_account
    acc_id = sys.argv[2] if len(sys.argv) > 2 else "parkourflux"
    print(build_caption(story.get("hook") or story["beats"][0],
                        handle=get_account(acc_id).handle))

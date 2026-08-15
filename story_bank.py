"""
story_bank.py
Handles the narration script for each video: either pulled from a local
bank of pre-written stories, or generated fresh via the Anthropic API.

This format lives and dies on the HOOK (first 1-2 sentences) and pacing,
so stories are stored as a list of short "beats" rather than one big
paragraph -- that's what captions.py uses to time word-by-word captions
and what tts.py uses to insert natural pauses.
"""

import json
import os
import random
from pathlib import Path

STORY_DIR = Path(__file__).parent / "stories"
STORY_DIR.mkdir(exist_ok=True)

# A few hand-written starter stories so the pipeline works out of the box
# without an API key. Swap these for your own / generated ones.
STARTER_STORIES = [
    {
        "title": "the_locker",
        "beats": [
            "My high school had a locker that nobody used.",
            "Not because it was broken. Because of what happened in 2009.",
            "I didn't believe the story until I got assigned that exact locker.",
            "The first week, nothing happened. I thought it was just a dumb rumor.",
            "Then I started finding notes inside it. Notes I never wrote.",
            "The last one just said: check the vents.",
            "I never opened that locker again."
        ]
    },
    {
        "title": "the_group_chat",
        "beats": [
            "I got added to a group chat with people I didn't know.",
            "I left immediately. Normal reaction, right?",
            "Ten minutes later I got a friend request from every single one of them.",
            "Then a text from an unknown number. It said, 'wrong chat, delete this before tuesday.'",
            "Tuesday came and went. Nothing happened.",
            "But I still haven't deleted the number, because I'm scared of what happens if I do."
        ]
    },
    {
        "title": "aita_neighbor",
        "beats": [
            "AITA for reporting my neighbor to the city over his 'garden'?",
            "This guy dug a hole in his backyard every single night for two weeks.",
            "I figured it was a pond or something. None of my business, right?",
            "Then my dog dug something up near the fence line and I will not describe what it was.",
            "I called the non-emergency line the next morning.",
            "Three squad cars showed up. I still don't know what they found.",
            "My neighbor hasn't spoken to me since. Reddit, AITA?"
        ]
    },
]


def load_story_bank() -> list[dict]:
    """Load all stories from stories/*.json, falling back to starters."""
    files = list(STORY_DIR.glob("*.json"))
    if not files:
        for s in STARTER_STORIES:
            save_story(s)
        files = list(STORY_DIR.glob("*.json"))
    stories = []
    for f in files:
        stories.append(json.loads(f.read_text()))
    return stories


def save_story(story: dict) -> Path:
    path = STORY_DIR / f"{story['title']}.json"
    path.write_text(json.dumps(story, indent=2))
    return path


def get_random_story() -> dict:
    return random.choice(load_story_bank())


def split_story_into_parts(story: dict, max_words: int = 165, single_max: int = 175,
                           min_tail: int = 70) -> list[dict]:
    """
    Split a story into ~55-second parts at beat boundaries (multi-part series
    convert followers 3-5x better than standalone videos). Stories at or under
    single_max words stay one video. Each non-final part gets a follow bait
    line; part titles get _pt suffixes.
    """
    beats = story["beats"]
    total_words = sum(len(b.split()) for b in beats)
    if total_words <= single_max:
        return [{**story, "part": 1, "total_parts": 1}]

    chunks, cur, cur_w = [], [], 0
    for b in beats:
        bw = len(b.split())
        if cur and cur_w + bw > max_words:
            chunks.append(cur)
            cur, cur_w = [b], bw
        else:
            cur.append(b)
            cur_w += bw
    if cur:
        chunks.append(cur)
    # a stub of a final part reads as filler -- fold it into the previous part
    if len(chunks) > 1 and sum(len(b.split()) for b in chunks[-1]) < min_tail:
        chunks[-2].extend(chunks.pop())

    n = len(chunks)
    numbers = {2: "two", 3: "three", 4: "four", 5: "five"}
    parts = []
    for i, chunk in enumerate(chunks, 1):
        part_beats = list(chunk)
        if i < n:
            part_beats.append(f"You are NOT ready for what happens next. Follow for part {numbers.get(i + 1, i + 1)}.")
        parts.append({
            **story,
            "title": f"{story['title']}_pt{i}" if n > 1 else story["title"],
            "beats": part_beats,
            "hook": story.get("hook") or beats[0],
            "part": i,
            "total_parts": n,
        })
    return parts


def _format_txt(genre: str | None = None) -> str:
    """Current format research, for the story writer (issue #7, Gap 3).

    trends.py has always researched "what the platforms are favouring" and only
    ever handed the result to the caption writer, so findings about how a story
    should OPEN and PACE were discarded. This routes that half here.

    Two deliberate limits. It is advisory, not authoritative -- the channel's
    own proven shapes below it are the stronger signal, and web guidance is
    generic by nature. And it is silent when the key is absent, so a trends.json
    written before this existed changes nothing until the next refresh.

    It never carries length or cadence advice: the prompt that produces it is
    told not to give any, because length is set by the target spec in this file
    and web advice must not quietly override it.

    Scoped by genre (issue #7, Gap 4): the notes are merged from `broad` plus
    the entry for THIS story's genre, because the genres do not want the same
    thing -- a revenge story earns attention by promising a payoff, a creepy one
    by withholding it.
    """
    try:
        from trends import format_notes
        f = format_notes(genre)
    except Exception:
        return ""
    lines = []
    for key, label in (("hook", "Openings"), ("pacing", "Pacing"),
                       ("algorithm", "Platforms currently favour")):
        vals = [str(v).strip() for v in (f.get(key) or []) if str(v).strip()]
        if vals:
            lines.append(f"  {label}: " + "; ".join(vals[:3]))
    if not lines:
        return ""
    return ("\nCURRENT FORMAT RESEARCH (advisory -- the proven shapes below "
            "outrank this if they conflict):\n" + "\n".join(lines) + "\n")


def _hint_txt(topic_hint: str) -> str:
    """How a trending topic enters the prompt.

    It used to go in as `Topic hint: <title>`, which reads as an instruction --
    so a chart entry like "Toxic Official Telugu Trailer" would have been taken
    as the subject of a landlord-revenge story. The hint is a weak, broad signal
    from a global chart; the channel's own proven shapes are the strong one.

    So it is offered as PERMISSION, with an explicit licence to discard it. A
    hint that connects to nothing should produce a normal story, not a contorted
    one, and forcing a connection is worse than having no hint at all.
    """
    if not topic_hint:
        return "Pick any compelling angle."
    return (
        f'SOFT SIGNAL -- something getting attention on YouTube right now:\n'
        f'  "{topic_hint}"\n'
        f'Use it ONLY if a natural, on-brand premise genuinely connects to the '
        f'THEME or EMOTION behind it (betrayal, being underestimated, someone '
        f'taking credit). If nothing connects, IGNORE IT COMPLETELY and pick '
        f'your own angle -- that is the expected outcome most of the time. '
        f'Never name the video, its creator, or anyone in it, and never write '
        f'about the video itself.')


def generate_story_via_claude(topic_hint: str = "", api_key: str | None = None,
                              genres: tuple | list | None = None,
                              avoid: list | None = None) -> dict:
    """
    Generate a fresh story using the Anthropic API. Requires ANTHROPIC_API_KEY
    (get one at https://console.anthropic.com) set as an env var, or passed in.

    Only runs on a machine with real internet access -- not inside this sandbox.
    """
    import anthropic

    client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    all_genres = [
        ("aitah",
         "r/AITAH moral dilemma -- first person with (28F)-style age/gender tags, someone "
         "violates a boundary and OP pushes back, family/friends take sides, ends with the "
         "judgment bait 'So, Reddit... AITAH?'"),
        ("confession",
         "r/TrueOffMyChest raw confession -- a secret the narrator has never told anyone, "
         "finally said out loud; personal, specific, no advice-seeking, ends on the weight of it"),
        ("revenge",
         "malicious compliance / petty revenge told first-person -- narrator gets sweet, "
         "satisfying payback on an unreasonable authority figure (boss, sergeant, landlord, HOA), "
         "ends with the payoff landing"),
        ("creepy",
         "creepy confession / creepypasta -- unsettling, ends on an open question"),
    ]
    # niche filter (multi-account: each channel can restrict to its genres)
    pool = [g for g in all_genres if not genres or g[0] in genres] or all_genres
    genre_key, genre = random.choice(pool)
    # Pick a concrete length target per story (weighted toward the short end) so
    # durations actually vary across 30-60s instead of all clustering near 60s.
    _target = random.choice([30, 30, 40, 40, 45, 50, 60])
    _target_spec = {
        30: "about 30 seconds -- roughly 85 words across 4-5 short beats",
        40: "about 40 seconds -- roughly 115 words across 5-6 beats",
        45: "about 45 seconds -- roughly 130 words across 6-7 beats",
        50: "about 50 seconds -- roughly 145 words across 7-8 beats",
        60: "about 60 seconds -- roughly 165 words across 8-9 beats",
    }[_target]
    # Theme weighting: every breakout this channel has had is family (354),
    # HOA (252) or wedding (123) -- everything else sits at ~6-11 views. Biasing
    # toward a few themes is what gives a channel an IDENTITY (the thing that
    # converts a viewer into a subscriber), and it fills the themed-compilation
    # buckets far faster. A share of runs stays OPEN so new angles can surface.
    import config as _cfg
    _theme_txt = ""
    _weights = getattr(_cfg, "THEME_WEIGHTS", {}) or {}
    if _weights:
        _roll, _acc = random.random(), 0.0
        for _name, _w in _weights.items():
            _acc += _w
            if _roll < _acc:
                _steer = {
                    "family": "a SIBLING, PARENT or IN-LAW -- someone whose "
                              "betrayal cuts because they're family",
                    "hoa": "an HOA, neighbour, or petty local authority "
                           "enforcing something absurd with a specific number",
                    "wedding": "a WEDDING or engagement -- the pressure of the "
                               "event making someone show who they really are",
                    "landlord": "a LANDLORD or property manager abusing the "
                                "lease over something trivial",
                }.get(_name)
                if _steer:
                    _theme_txt = (f"\nTHEME (use it): centre this story on {_steer}. "
                                  "Keep it a genuinely fresh scenario -- the theme "
                                  "is the setting, not a template to repeat.\n")
                break

    # Lean-in: parkour-meta stories (the conflict IS about the narrator's gaming
    # life) are the only ones that have broken out on this channel -- see
    # config.PARKOUR_META_SHARE. The remainder stay open so we keep testing.
    _meta_txt = ""
    if random.random() < getattr(_cfg, "PARKOUR_META_SHARE", 0.0):
        _meta_txt = (
            "\nCHANNEL ANGLE (use it -- this is what performs best here): tie the "
            "conflict to the narrator's gaming life, specifically Minecraft parkour. "
            "The viewer is literally watching a parkour run, so drama about THAT world "
            "lands far harder than generic family drama. The narrator is a player or "
            "small creator; the other person attacks that part of their life -- deletes "
            "the only recording of a record run, wipes a world save they spent months "
            "on, mocks it as childish and tells them to grow up, steals credit for a "
            "course or route they built, gets them banned from a server, breaks or "
            "sells their setup, exposes their channel to family who then pile on, or "
            "demands they quit as a condition of something. Keep it a genuinely human "
            "conflict in the chosen genre -- gaming is the SETTING and what's at stake, "
            "never a technical infodump, and no jargon a non-player wouldn't follow. "
            "Don't name other real games, and don't make it about esports prize money.\n")
    # Originality guard: feed in recently-used premises so it doesn't rehash them.
    # Structural patterns mined from competing channels' best performers.
    # Abstract rules only -- no competitor titles ever reach this prompt (see
    # hook_mining.py). Empty string when mining hasn't been set up, so nothing
    # changes for anyone who never runs it.
    try:
        from hook_mining import prompt_block
        _niche_txt = prompt_block()
    except Exception:
        _niche_txt = ""

    _avoid_txt = ""
    if avoid:
        _avoid_txt = (
            "\nORIGINALITY (critical): this channel has ALREADY posted the stories "
            "listed below. Do NOT reuse their premises, characters, relationships, "
            "settings, or twists, and do NOT just swap a few words on one -- invent a "
            "genuinely DIFFERENT scenario. Vary who the story centers on (rotate widely: "
            "roommate, boss, coworker, neighbor, landlord, sibling, parent, in-law, ex, "
            "best friend, stranger, teacher, HOA, customer, delivery driver, etc.) and the "
            "type of conflict, so consecutive stories never feel like the same template.\n"
            "Recently posted -- AVOID repeating any of these: " + "; ".join(avoid[-25:]) + "\n")
        # Note the asymmetry: the model is SHOWN the last 25 premises to keep
        # the prompt readable, but the repetition counting below runs over the
        # whole list it was handed.
        # Avoiding exact premises isn't enough: the model dodges a repeated
        # premise but keeps reaching for the same relationships, so the channel
        # drifts into one motif. On 2026-07-23, 8 of 19 live videos featured a
        # sister and 7 a wedding. Name the pile-ups and ban them outright.
        import collections
        import re as _re
        _stop = {"that", "this", "with", "from", "they", "them", "when", "what",
                 "about", "just", "into", "over", "after", "before", "your",
                 "their", "have", "been", "were", "would", "could", "told",
                 "said", "asked", "made", "went", "took", "back", "only",
                 "never", "every", "years", "year", "months", "days", "time"}
        # Words belonging to a DELIBERATELY weighted theme must never be banned.
        # Without this the two systems fight: THEME_WEIGHTS steers toward
        # landlord/wedding stories, then the motif ban blocks the word
        # "landlord" for recurring -- which is the whole point of weighting it.
        # The ban exists to catch a repeated SPECIFIC (four "gym teacher"
        # stories), not the themes we are intentionally pursuing.
        _protected = set()
        for _t in (getattr(_cfg, "THEME_WEIGHTS", {}) or {}):
            _protected.update({
                "family": {"sister", "sisters", "brother", "mother", "father",
                           "parent", "parents", "sibling", "cousin", "aunt",
                           "uncle", "inlaw", "inlaws"},
                "hoa": {"neighbor", "neighbour", "neighbors", "association"},
                "wedding": {"wedding", "weddings", "bride", "groom", "bridal",
                            "engagement", "honor", "bridesmaid", "rehearsal"},
                "landlord": {"landlord", "landlords", "tenant", "lease",
                             "rent", "deposit", "apartment"},
            }.get(_t, set()))
        # Brand and genre vocabulary recurs BY DESIGN and must never be banned.
        # Dropping the word threshold to 2 put "parkour" straight onto the ban
        # list, which would fight PARKOUR_META_SHARE the same way banning
        # "landlord" fought THEME_WEIGHTS. "aita" is a genre marker, not a
        # motif. Note these protect the single words only -- a PAIRING like
        # "parkour course" can still be flagged as an overused situation.
        _protected |= {"aita", "aitah", "reddit", "video", "channel"}
        # Only protected while we are DELIBERATELY steering toward that world.
        # With PARKOUR_META_SHARE at 0 these are no longer brand vocabulary in a
        # story -- they are a motif like any other, and a second occurrence
        # should be caught rather than waved through.
        if getattr(_cfg, "PARKOUR_META_SHARE", 0):
            _protected |= {"parkour", "speedrun", "speedrunning", "minecraft"}
        # Words making up a PROVEN_SITUATIONS entry are protected too. Exempting
        # the pair "landlord charged" achieves nothing if "charged" is still on
        # the word ban list -- the model is steered off the winner either way.
        for _s in (getattr(_cfg, "PROVEN_SITUATIONS", []) or []):
            _protected |= {w for w in _s.lower().split() if len(w) > 3}
        # Count over EVERYTHING the caller sent, not just the 25 shown above.
        # Repetition on this channel is slow: the three "landlord charged me
        # for unauthorised X" stories were spread wide enough that they never
        # shared a 25-item window, so nothing ever counted them together.
        _words = [_re.findall(r"[a-z]+", p.lower()) for p in avoid]
        _counts = collections.Counter(
            w for ws in _words for w in ws
            if len(w) > 3 and w not in _stop and w not in _protected)
        # Two, not three. Three means the ban can only fire on the FOURTH
        # telling, and a viewer scrolling the grid notices at the second.
        _over = [w for w, n in _counts.most_common(8) if n >= 2]

        # Pairs are counted WITHOUT the protection filter, deliberately.
        # _protected keeps THEME_WEIGHTS working -- "landlord" recurring is the
        # point of weighting landlords. But "landlord charged" recurring is not
        # a theme, it is the same story told again, and word-level protection
        # hid exactly that: three landlord-charged-me-for-unauthorised-something
        # stories, all legal under the old rule.
        _pairs = collections.Counter(
            f"{a} {b}" for ws in _words
            for a, b in zip(ws, ws[1:])
            if len(a) > 3 and len(b) > 3 and a not in _stop and b not in _stop)
        # Proven winners are never banned. config.PROVEN_SITUATIONS names the
        # pairings the data says to make MORE of -- without this the ban steers
        # away from the best performer precisely because it recurs, which is
        # backwards. Matched loosely so "landlord charged" also exempts
        # "landlord charged me".
        _proven = [s.lower() for s in (getattr(_cfg, "PROVEN_SITUATIONS", []) or [])]
        _over_pairs = [p for p, n in _pairs.most_common(6)
                       if n >= 2 and not any(w in p or p in w for w in _proven)]

        if _over or _over_pairs:
            _avoid_txt += "OVERUSED ON THIS CHANNEL -- BANNED for this story.\n"
            if _over:
                _avoid_txt += (
                    "  Words: " + ", ".join(_over) + ". Do not use these as the "
                    "relationship, setting, or object of the conflict, in any form.\n")
            if _over_pairs:
                _avoid_txt += (
                    "  Situations: " + ", ".join(_over_pairs) + ". These exact "
                    "pairings keep recurring. Even where the individual words are "
                    "fine to reuse, this COMBINATION is not -- it is the same "
                    "story with the numbers changed.\n")
            _avoid_txt += ("  Pick a relationship and situation that appears "
                           "NOWHERE in the list above.\n")
        # Word-level bans only fire once a term has appeared 3+ times, so they
        # can't stop a near-duplicate on its SECOND occurrence -- which is how
        # "gym teacher confiscated my parkour shoes" and "PE teacher failed my
        # parkour project" shipped an hour apart. Ban the SHAPE explicitly.
        _avoid_txt += (
            "SHAPE CHECK (do this before writing): describe your intended story "
            "as 'WHO does WHAT to the narrator'. If any premise in the avoid "
            "list above has the same WHO-role (teacher, coach, boss, landlord, "
            "sibling, parent, neighbour, HOA...) combined with a similar WHAT "
            "(destroyed/confiscated/banned/failed/sold the narrator's thing), "
            "it is TOO CLOSE even if the specific details differ -- discard it "
            "and pick a different role AND a different kind of harm.\n")
    # Deliberately does NOT name the footage. The gameplay is wallpaper -- it
    # keeps the eye busy while the story works -- and a story written "for a
    # Minecraft parkour video" quietly drifts toward gaming references that
    # only make sense over that footage. The goal is stories that would carry
    # any background, so they can move to a second channel unchanged.
    prompt = f"""Write a short first-person story script for a vertical TikTok/Shorts video.
Style: {genre}.
The video is narrated over unrelated background gameplay footage, so the story
must stand entirely on its own. Never reference the footage or the video itself,
and do not tie the conflict to the narrator's GAMING life -- no Minecraft, no
worlds or saves, no servers, no speedruns, no streaming or channel drama. That
kind of story only makes sense to someone watching this particular wallpaper.
Real-world subjects are all fair game, and that INCLUDES real-life parkour or
freerunning -- a story about training, an injury, a spot, a rival, a coach or a
trespassing charge is a real-world story like any other. The line is
gaming-life drama, not the word "parkour".
Craft rules (this is what makes these go viral):
- HOOK -- the first sentence is the WHOLE game. Open an unresolvable curiosity
  loop: state something specific and unfinished that forces the viewer to think
  "wait, WHAT? I have to know how this ends." The first 2 seconds decide whether
  the algorithm pushes the video, so NEVER open with throat-clearing setup ("So
  this happened last year...") and NEVER undersell it -- drop them straight into
  the tension with a concrete, unfinished image.
  Good: "My roommate 'borrowed' my car and it came back with a different license plate."
  Good: "I found my own name on a wedding invitation -- and I wasn't the one getting married."
- Performed authenticity: first person, confession cadence, specific mundane details
  (real-feeling ages, timelines, amounts). Use (28F)/(34M) shorthand where natural.
- Plant a small detail early that becomes devastating later -- an EARNED twist.
- Escalate: problem -> action -> consequences -> verdict/judgment moment.
- Beats of 1-2 sentences, each landing on a mini cliffhanger that pulls to the next.
- ENDING -- engineer it for SHARES (the #1 ranking signal) and COMMENTS (#2):
  * Land the final story beat on a payoff so satisfying, shocking, or relatable
    that a viewer needs to SEND it to a specific person they know.
  * Then close on ONE short verdict QUESTION that baits comments and fits the
    genre -- "So, Reddit... AITAH?", "Was I wrong?", "What would you have done?",
    "Tell me I'm not crazy." This single closing line reliably multiplies comments.
- Use correct grammar, spelling, and punctuation throughout -- the text is
  displayed on-screen word-by-word and on a written post card, so errors are
  visible. Casual tone is fine; sloppy grammar is not.
Length (STRICT -- this controls video duration, obey it exactly): write THIS
story to {_target_spec}. Hit that length and STOP -- do not pad past it. HARD
MAXIMUM 170 words. If a draft runs over, delete whole beats until it fits. Trim
every non-essential word: no recap, no throat-clearing, no over-explaining. A
tight, complete short story beats a padded long one -- a 30-second story can hit
just as hard as a 60-second one. (Ignore this length only for a rare 300-450
word multi-part saga when the material is genuinely exceptional, ~1 in 5 at
most; sagas auto-split into ~55s parts.)
{_hint_txt(topic_hint)}{_format_txt(genre_key)}
{_niche_txt}WHAT ACTUALLY GOES VIRAL ON THIS CHANNEL -- both breakout videos shared a
STRUCTURE, not just a subject. Aim for one of these shapes (or something with
the same emotional weight):
  * Someone destroys or takes something IRREPLACEABLE the narrator made,
    earned, or was keeping -- and doesn't think it mattered.
  * ABSURD authority overreach: a person or institution with petty power
    (boss, HOA, landlord, school, in-law) punishes something harmless, with a
    specific ridiculous number or rule attached.
Use concrete specifics -- exact amounts, exact timeframes -- the specificity is
what makes it feel real.
{_theme_txt}{_meta_txt}{_avoid_txt}
SHARE LINE: also write a "share_line" -- ONE short spoken sentence that ends
the video by making the viewer want to SEND it to a specific person. Shares
(DM sends) are the single biggest ranking signal on Reels, and a generic
"share this" is ignored -- so name the KIND of person this story would land
for, drawn from THIS story ("Send this to whoever is still fighting their
landlord over a cleaning fee"). Under 14 words, natural spoken English, no
hashtags or emoji.

DISPLAY TITLE: also write a "display_title" -- a short, scroll-stopping title
for the video (this is what shows on YouTube). Make it intriguing and
curiosity-driven so someone can't help but click. NEVER boring, flat, or a plain
summary ("My sister's wedding"); open a loop or tease the twist ("My sister
uninvited me from her wedding over a text I never sent"). It can differ from the
story's first line. Keep it under ~90 characters, correct grammar.

Respond ONLY with JSON in this exact format, no other text:
{{"title": "short_snake_case_title", "display_title": "the scroll-stopping title", "share_line": "the send-this-to line", "beats": ["beat 1", "beat 2", ...]}}
"""

    try:
        resp = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=1500,
            thinking={"type": "disabled"},  # simple JSON task; keeps content[0] as text
            messages=[{"role": "user", "content": prompt}],
        )
        # Pull the text block explicitly (robust even if block order changes).
        text = next(b.text for b in resp.content if b.type == "text").strip()
    except anthropic.RateLimitError:
        print("Anthropic rate limit reached. Falling back to next best AI (OpenAI)...")
        import openai
        openai_client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        resp = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500,
        )
        text = resp.choices[0].message.content.strip()

    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    story = json.loads(text)
    story["genre"] = genre_key  # carries to captions/hashtags (propagates to parts)
    save_story(story)
    return story


def condense_reddit_post(post: dict, api_key: str | None = None) -> dict:
    """Turn a REAL Reddit post (from reddit_source.fetch_top_post) into the same
    short story dict the pipeline expects -- keeping the real events but tightened,
    cleaned, and PII-stripped. Returns {title, beats, genre}."""
    import anthropic
    client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
    prompt = f"""Condense this REAL Reddit post into a short first-person video script for a vertical TikTok/Shorts video. It is narrated over unrelated background footage, so never reference the footage or gaming. Keep the REAL events and emotional core -- do NOT invent a different story, just tighten and clean it.

Source post from r/{post.get('subreddit')}:
Title: {post.get('title','')}
Body: {post.get('text','')[:3500]}

Rules (the craft that makes these go viral):
- HOOK: rewrite the very first sentence into an unresolvable curiosity loop that forces "wait, WHAT? I have to know how this ends." The first 2 seconds decide reach.
- Condense to fit 30-60 seconds of narration -- roughly 80-170 words total (shorter for a punchy hit, longer only if the story truly needs it), in beats of 1-2 sentences, each landing on a mini cliffhanger.
- STRIP all personally identifying info: replace real names/usernames with relationships (my sister, my boss) or (28F)/(34M) tags; remove links, "EDIT:"/"UPDATE:" markers, subreddit references, and anything doxxable.
- Keep it POLICY-SAFE for YouTube/Instagram: remove slurs, explicit sexual content, and graphic violence; keep the drama, drop the shock gore.
- ENDING: land on a share-worthy payoff, then ONE short verdict question ("So, Reddit... AITAH?", "Was I wrong?", "What would you have done?").
- SHARE LINE: also write a "share_line" -- one short spoken sentence naming the KIND of person this story would land for ("Send this to whoever is still fighting their landlord"), under 14 words, no emoji.
- DISPLAY TITLE: also write a "display_title" -- a short, scroll-stopping YouTube title, intriguing and curiosity-driven, never boring or a plain summary. Under ~90 characters.
- Correct grammar, spelling, and punctuation throughout.

Respond ONLY with JSON, no other text:
{{"title": "short_snake_case_title", "display_title": "the scroll-stopping title", "share_line": "the send-this-to line", "beats": ["beat 1", "beat 2", ...]}}
"""
    try:
        resp = client.messages.create(
            model="claude-sonnet-5", max_tokens=1500,
            thinking={"type": "disabled"},
            messages=[{"role": "user", "content": prompt}],
        )
        text = next(b.text for b in resp.content if b.type == "text").strip()
    except anthropic.RateLimitError:
        print("Anthropic rate limit reached. Falling back to next best AI (OpenAI)...")
        import openai
        openai_client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        resp = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500,
        )
        text = resp.choices[0].message.content.strip()

    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    story = json.loads(text)
    story["genre"] = post.get("genre")
    story["source"] = f"reddit:{post.get('id')}"
    save_story(story)
    return story


if __name__ == "__main__":
    story = get_random_story()
    print(json.dumps(story, indent=2))

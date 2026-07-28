"""
comment_replies.py
Auto comment-reply engine. For each account, reads NEW top-level comments on
its YouTube videos and Instagram Reels and posts a short, on-brand, engagement-
driving reply. Replying to viewers is a strong ranking + community signal
(more comments -> more reach, and it converts casual viewers into followers).

SAFETY:
- OFF by default (config.ENABLE_COMMENT_REPLIES). Runs as a no-op until enabled.
- --dry-run previews every reply and posts NOTHING (use this first).
- Rate-limited per run (config.COMMENT_REPLY_LIMIT_PER_RUN) to avoid spam flags.
- Never replies to its own comments, never double-replies (tracks replied ids),
  only top-level comments on THIS channel's own videos, and skips spam/hostile
  comments (the reply model returns SKIP for anything not worth engaging).

REQUIREMENTS (do these before flipping ENABLE_COMMENT_REPLIES on):
- YouTube: token must have the youtube.force-ssl scope. It was added to
  youtube_upload.SCOPES -- re-auth once: `python add_channel.py <account_id>`.
- Instagram: the token needs the instagram_manage_comments permission.

Usage:
    python comment_replies.py --dry-run     # preview, post nothing
    python comment_replies.py --live        # actually post replies
"""

import json
import time
from pathlib import Path

import requests

import config
from accounts import Account, load_accounts

IG_GRAPH = "https://graph.instagram.com/v21.0"


# ---- replied-id tracking (per account, so we never reply twice) -------------
def _state_path(acc: Account) -> Path:
    return Path(acc.out_dir) / "replied_comments.json"


def _load_replied(acc: Account) -> set:
    p = _state_path(acc)
    if p.exists():
        try:
            return set(json.loads(p.read_text()))
        except Exception:
            return set()
    return set()


def _save_replied(acc: Account, ids: set):
    p = _state_path(acc)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(sorted(ids)))


# ---- reply generation -------------------------------------------------------
def _generate_reply(comment_text: str, context: str, author: str) -> str | None:
    """A short, warm, engagement-driving reply -- or None to skip (spam/hostile/
    nothing to engage with)."""
    import anthropic
    prompt = f"""You are the friendly voice of a Reddit-story video channel, replying to a viewer's comment.
Video context: "{context}"
Comment from @{author}: "{comment_text}"

Write a SHORT reply (one sentence, under 120 characters) that is warm and human and invites more
engagement -- react to their take, thank them, or ask a light follow-up question. Casual creator
voice, at most one emoji. NEVER argue or get defensive.
If the comment is spam, an ad, hateful, or has nothing worth engaging with, reply with exactly: SKIP
Output ONLY the reply text (or SKIP) -- no quotes, no other text."""
    r = anthropic.Anthropic().messages.create(
        model="claude-sonnet-5", max_tokens=80,
        thinking={"type": "disabled"},
        messages=[{"role": "user", "content": prompt}],
    )
    txt = next(b.text for b in r.content if b.type == "text").strip().strip('"')
    if len(txt) < 2 or txt.upper().startswith("SKIP"):
        return None
    return txt[:180]


# ---- YouTube ----------------------------------------------------------------
def reply_youtube(acc: Account, limit: int, dry_run: bool) -> int:
    from youtube_upload import get_authenticated_service
    yt = get_authenticated_service(acc.yt_token)
    me = yt.channels().list(part="id", mine=True).execute()["items"][0]["id"]
    replied = _load_replied(acc)
    posted = 0
    req = yt.commentThreads().list(
        part="snippet", allThreadsRelatedToChannelId=me,
        maxResults=50, order="time", textFormat="plainText")
    try:
        while req and posted < limit:
            resp = req.execute()
            for item in resp.get("items", []):
                if posted >= limit:
                    break
                # only comments ON this channel's own videos
                if item["snippet"].get("channelId") != me:
                    continue
                top = item["snippet"]["topLevelComment"]
                cid = top["id"]
                if cid in replied:
                    continue
                snip = top["snippet"]
                if snip.get("authorChannelId", {}).get("value") == me:
                    replied.add(cid)  # our own comment
                    continue
                text = snip.get("textOriginal", "")
                author = snip.get("authorDisplayName", "viewer")
                reply = _generate_reply(text, "one of our Reddit story videos", author)
                if not reply:
                    replied.add(cid)
                    continue
                if dry_run:
                    print(f"[YT dry-run] @{author}: {text[:45]!r} -> {reply!r}")
                else:
                    yt.comments().insert(part="snippet", body={
                        "snippet": {"parentId": item["id"], "textOriginal": reply}
                    }).execute()
                    print(f"[YT] replied to @{author}")
                    replied.add(cid)
                posted += 1
                time.sleep(1)
            req = yt.commentThreads().list_next(req, resp)
    finally:
        _save_replied(acc, replied)
    return posted


# ---- Instagram --------------------------------------------------------------
def reply_instagram(acc: Account, limit: int, dry_run: bool) -> int:
    ig_user, token = acc.ig_user_id, acc.ig_token
    if not (ig_user and token):
        return 0
    replied = _load_replied(acc)
    posted = 0
    media = requests.get(f"{IG_GRAPH}/{ig_user}/media",
                         params={"fields": "id,caption", "limit": 25,
                                 "access_token": token}, timeout=30).json()
    try:
        for m in media.get("data", []):
            if posted >= limit:
                break
            cres = requests.get(f"{IG_GRAPH}/{m['id']}/comments",
                                params={"fields": "id,text,username,from",
                                        "access_token": token}, timeout=30).json()
            for c in cres.get("data", []):
                if posted >= limit:
                    break
                cid = c["id"]
                if cid in replied:
                    continue
                if c.get("from", {}).get("id") == ig_user:
                    replied.add(cid)  # our own comment
                    continue
                text = c.get("text", "")
                author = c.get("username", "viewer")
                reply = _generate_reply(text, (m.get("caption") or "")[:60], author)
                if not reply:
                    replied.add(cid)
                    continue
                if dry_run:
                    print(f"[IG dry-run] @{author}: {text[:45]!r} -> {reply!r}")
                else:
                    rr = requests.post(f"{IG_GRAPH}/{cid}/replies",
                                       data={"message": reply, "access_token": token},
                                       timeout=30)
                    if rr.ok:
                        print(f"[IG] replied to @{author}")
                        replied.add(cid)
                    else:
                        print(f"[IG] reply failed ({rr.status_code}): {rr.text[:120]}")
                posted += 1
                time.sleep(1)
    finally:
        _save_replied(acc, replied)
    return posted


# ---- runner -----------------------------------------------------------------
def run(dry_run: bool = False, limit: int | None = None) -> dict:
    limit = limit or config.COMMENT_REPLY_LIMIT_PER_RUN
    totals = {}
    for acc in load_accounts():
        for platform, fn in (("YouTube", reply_youtube), ("Instagram", reply_instagram)):
            try:
                n = fn(acc, limit, dry_run)
                totals[f"{acc.id}/{platform}"] = n
                print(f"[{acc.id}] {platform}: {n} "
                      f"{'preview(s)' if dry_run else 'repl' + ('y' if n == 1 else 'ies')}")
            except Exception as e:
                print(f"[{acc.id}] {platform} comment replies failed: {e}")
    return totals


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="preview replies, post nothing")
    ap.add_argument("--live", action="store_true", help="actually post replies")
    ap.add_argument("--limit", type=int, help="override per-platform reply cap")
    a = ap.parse_args()
    if a.dry_run:
        run(dry_run=True, limit=a.limit)
    elif a.live or config.ENABLE_COMMENT_REPLIES:
        run(dry_run=False, limit=a.limit)
    else:
        print("Comment replies are OFF (config.ENABLE_COMMENT_REPLIES=False). "
              "Preview with --dry-run, post with --live, or enable in config.")

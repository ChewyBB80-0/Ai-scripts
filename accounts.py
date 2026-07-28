"""
accounts.py
Multi-account registry. Each entry in accounts.json is one channel identity
(its own YouTube OAuth token, IG creds, niche/genres, branding, cadence).
The original ParkourFlux setup is the built-in default, so a missing
accounts.json changes nothing.

To add a channel: append an entry to accounts.json, run
`python add_channel.py <id>` once to do the YouTube OAuth sign-in for it,
and set its IG env vars (IG_USER_ID_<ID>, IG_ACCESS_TOKEN_<ID>) if it
cross-posts. The bot picks it up on the next hourly run.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).parent
REGISTRY = ROOT / "accounts.json"

GENRES = ("aitah", "confession", "revenge", "creepy")


@dataclass
class Account:
    id: str = "parkourflux"
    name: str = "ParkourFlux AI"
    enabled: bool = True
    handle: str = "@ParkourFlux"
    genres: tuple = GENRES              # niche filter for story generation
    yt_token: str = "token.json"        # per-account OAuth token file
    footage_dir: str = "footage"
    logo: str = "branding/logo.png"
    daily_target: int = 1
    ig_enabled: bool = True
    # data files (namespaced per account; default = legacy paths)
    post_log: str = "output/post_log.csv"
    queue_file: str = "output/post_queue/queue.json"
    out_dir: str = "output"

    @property
    def ig_user_id(self):
        return os.environ.get(f"IG_USER_ID_{self.id.upper()}") or os.environ.get("IG_USER_ID")

    @property
    def ig_token(self):
        return os.environ.get(f"IG_ACCESS_TOKEN_{self.id.upper()}") or os.environ.get("IG_ACCESS_TOKEN")


def _from_dict(d: dict) -> Account:
    a = Account()
    for k, v in d.items():
        if hasattr(a, k) and not isinstance(getattr(Account, k, None), property):
            setattr(a, k, tuple(v) if k == "genres" else v)
    # non-default accounts get namespaced data files automatically
    if a.id != "parkourflux" and "post_log" not in d:
        a.out_dir = f"output/accounts/{a.id}"
        a.post_log = f"{a.out_dir}/post_log.csv"
        a.queue_file = f"{a.out_dir}/post_queue/queue.json"
    return a


def load_accounts() -> list[Account]:
    """All enabled accounts; defaults to the original single account."""
    if not REGISTRY.exists():
        return [Account()]
    entries = json.loads(REGISTRY.read_text())
    accs = [_from_dict(e) for e in entries]
    return [a for a in accs if a.enabled] or [Account()]


def all_accounts() -> list[Account]:
    """Every configured account, including disabled ones."""
    if not REGISTRY.exists():
        return [Account()]
    return [_from_dict(e) for e in json.loads(REGISTRY.read_text())]


def get_account(acc_id: str) -> Account:
    """Look up one account BY ID, enabled or not.

    Deliberately not filtered by `enabled`: a new channel has to be
    authorised (add_channel.py) and configured before it's safe to switch on,
    so an explicit lookup must be able to see a disabled entry. The posting
    loop uses load_accounts(), which stays filtered.
    """
    for a in all_accounts():
        if a.id == acc_id:
            return a
    raise KeyError(f"no account '{acc_id}' in accounts.json")


def resolve_footage(acc: Account) -> list[Path]:
    """Background clips this account should draw from, most-specific first:

      1. footage/<id>/     -- a folder you curate for THIS account. If it has
                              clips, they are used exclusively (full control:
                              give each channel its own look).
      2. acc.footage_dir   -- honored when the account set a custom dir.
      3. shared footage/    -- the common pool, AUTO-PARTITIONED so each account
                              gets a distinct slice. So even if you just dump
                              every clip into footage/, two accounts won't render
                              over the same backgrounds (near-duplicate videos
                              across your own channels tank reach). Partitioning
                              only kicks in when the pool is big enough (>= 2x the
                              account count) to still give each account variety;
                              otherwise everyone shares the whole pool.

    The assembler already cuts a fresh random montage per video, so within an
    account each new story/series is visually different for free. Returns [] when
    no clips are found (the caller skips the run).
    """
    dedicated = ROOT / "footage" / acc.id
    if dedicated.is_dir():
        clips = sorted(dedicated.glob("*.mp4"))
        if clips:
            return clips
    if acc.footage_dir != "footage":
        clips = sorted((ROOT / acc.footage_dir).glob("*.mp4"))
        if clips:
            return clips
    pool = sorted((ROOT / "footage").glob("*.mp4"))
    if not pool:
        return []
    ids = [a.id for a in load_accounts()]
    if len(ids) > 1 and acc.id in ids and len(pool) >= 2 * len(ids):
        i = ids.index(acc.id)
        slice_ = [c for n, c in enumerate(pool) if n % len(ids) == i]
        if slice_:
            return slice_
    return pool


# Background sets that are NOT background variants: account-specific folders are
# handled above, and 'gta' is staged for a future channel -- mixing driving
# footage into a Minecraft channel looks like a glitch, not variety.
_NOT_A_VARIANT = {"gta"}


def background_variants(acc: Account) -> list[Path]:
    """Themed background folders under footage/ that this account can draw from.

    Drop each background source in its own folder -- footage/parkour_neon/,
    footage/parkour_dropper/ -- and each video uses ONE of them. That gives a
    consistent look WITHIN a video and a different look BETWEEN videos, which
    is what you want; a montage that cuts between two different worlds
    mid-story reads as a mistake.
    """
    root = ROOT / "footage"
    if not root.is_dir():
        return []
    ids = {a.id for a in load_accounts()}
    out = []
    for d in sorted(root.iterdir()):
        if (d.is_dir() and d.name not in _NOT_A_VARIANT and d.name not in ids
                and any(d.glob("*.mp4"))):
            out.append(d)
    return out


# Some backgrounds suit a genre far better than others: the dark, foggy night
# footage sells a creepy story, and would undercut a light-hearted revenge one.
# Folder-name substring -> genres it is preferred for.
_GENRE_SETS = {
    "night": ("creepy",),
    "dark": ("creepy",),
}


def pick_background_set(acc: Account, genre: str | None = None, rng=None,
                        quiet: bool = False) -> list[Path]:
    """Clips for ONE video: one themed folder, chosen for the story's genre when
    a set suits it, otherwise at random. Falls back to the flat pool when there
    are no themed folders. Call once per video."""
    import random as _r
    rng = rng or _r
    variants = background_variants(acc)
    # A dedicated footage/<account_id>/ folder still wins outright.
    if variants and not (ROOT / "footage" / acc.id).is_dir():
        preferred = [d for d in variants
                     for key, genres in _GENRE_SETS.items()
                     if key in d.name.lower() and genre in genres]
        if preferred:
            chosen = rng.choice(preferred)
        else:
            # don't hand a moody-only set to a non-matching genre
            neutral = [d for d in variants
                       if not any(k in d.name.lower() for k in _GENRE_SETS)] or variants
            chosen = rng.choice(neutral)
        clips = sorted(chosen.glob("*.mp4"))
        if clips:
            if not quiet:
                print(f"[{acc.id}] background set: {chosen.name} ({len(clips)} clip(s))")
            return clips
    return resolve_footage(acc)

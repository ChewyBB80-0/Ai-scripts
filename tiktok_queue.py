"""
tiktok_queue.py
Approval gate for TikTok. Rendered videos land here instead of going straight
to TikTok; the Discord bot DMs a preview with Approve / Skip buttons and only
publishes once the owner taps Approve.

Two reasons it works this way:
  1. TikTok's Direct Post UX guidelines expect the creator to review a post
     before it goes live. One tap on a phone satisfies that without having to
     open the TikTok app at posting time.
  2. It publishes the same way before and after the production audit --
     approve() direct-posts when the video.publish scope is actually granted
     and quietly falls back to the draft inbox until then. Nothing to rewire
     on the day the audit lands.

Queue lives in output/tiktok_queue.json. Statuses: pending -> posted / skipped
/ failed.
"""

import json
import subprocess
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).parent
QUEUE_FILE = ROOT / "output" / "tiktok_queue.json"
KEEP = 60          # rows of history to retain


def _load() -> list:
    try:
        return json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(rows: list):
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_FILE.write_text(json.dumps(rows[-KEEP:], indent=1), encoding="utf-8")


def add(video_path: str | Path, title: str = "", caption: str = "") -> str:
    """Queue a rendered video for TikTok approval. Returns the queue id.
    Re-queuing the same file is a no-op so a retried run can't double-post."""
    video_path = Path(video_path)
    rows = _load()
    for r in rows:
        if Path(r["video"]).name == video_path.name and r["status"] in ("pending", "posted"):
            return r["id"]
    qid = uuid.uuid4().hex[:8]
    rows.append({
        "id": qid, "video": str(video_path),
        "title": title or video_path.stem.replace("_", " "),
        "caption": caption, "status": "pending", "notified": False,
        "queued": time.strftime("%Y-%m-%dT%H:%M:%S"), "note": "",
    })
    _save(rows)
    return qid


def get(qid: str) -> dict | None:
    return next((r for r in _load() if r["id"] == qid), None)


def pending() -> list:
    return [r for r in _load() if r["status"] == "pending"]


def unnotified() -> list:
    """Pending rows the owner hasn't been DM'd about yet."""
    return [r for r in _load() if r["status"] == "pending" and not r.get("notified")]


def mark_notified(qid: str):
    rows = _load()
    for r in rows:
        if r["id"] == qid:
            r["notified"] = True
    _save(rows)


def _set(qid: str, status: str, note: str = ""):
    rows = _load()
    for r in rows:
        if r["id"] == qid:
            r["status"], r["note"] = status, note
    _save(rows)


_direct_ok: bool | None = None


def can_direct_post(refresh: bool = False) -> bool:
    """True once TikTok will actually let us publish without a manual tap --
    i.e. the video.publish scope is granted. Cached; the answer only changes
    when the audit lands and the user re-auths."""
    global _direct_ok
    if _direct_ok is None or refresh:
        try:
            import tiktok_upload
            info = tiktok_upload.creator_info()
            _direct_ok = bool((info.get("data") or {}).get("privacy_level_options"))
        except Exception:
            _direct_ok = False
    return _direct_ok


def thumbnail(video_path: str | Path) -> Path | None:
    """Grab a frame so the Discord preview shows something even when the video
    itself is too big to attach. Returns None if ffmpeg isn't available."""
    video_path = Path(video_path)
    out = ROOT / "output" / f".thumb_{video_path.stem}.jpg"
    if out.exists():
        return out
    try:
        from ffmpeg_setup import ensure_ffmpeg
        ensure_ffmpeg()          # puts ffmpeg on PATH; the rest of the code
    except Exception:            # invokes it by name, same as assemble.py
        pass
    try:
        subprocess.run(["ffmpeg", "-y", "-ss", "1.5", "-i", str(video_path),
                        "-frames:v", "1", "-vf", "scale=360:-1", str(out)],
                       capture_output=True, timeout=60)
        return out if out.exists() else None
    except Exception:
        return None


def approve(qid: str) -> str:
    """Publish an approved video. Direct-posts if the scope allows, otherwise
    sends it to the TikTok draft inbox. Returns a human-readable result."""
    row = get(qid)
    if not row:
        return "That video is no longer in the queue."
    if row["status"] != "pending":
        return f"Already {row['status']} — nothing to do."
    path = Path(row["video"])
    if not path.exists():
        _set(qid, "failed", "file deleted")
        return f"The render is gone ({path.name}) — it was probably cleaned up."
    import tiktok_upload
    try:
        if can_direct_post():
            pid = tiktok_upload.post_direct(path, title=row.get("title", ""))
            how = f"Posted to TikTok — {row['title']}"
        else:
            pid = tiktok_upload.post_to_drafts(path)
            how = (f"Sent to your TikTok drafts — {row['title']}. Open the app "
                   "and tap Post (direct posting turns on once the audit lands).")
    except Exception as e:
        _set(qid, "failed", str(e))
        return f"TikTok upload failed: {e}"
    _set(qid, "posted", pid)
    return how


def skip(qid: str) -> str:
    row = get(qid)
    if not row:
        return "That video is no longer in the queue."
    if row["status"] != "pending":
        return f"Already {row['status']}."
    _set(qid, "skipped")
    return f"Skipped — {row['title']} won't go to TikTok."


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "list":
        for r in _load()[-15:]:
            print(f"{r['id']}  {r['status']:8} {r['title'][:55]}")
        print(f"\ndirect posting available: {can_direct_post()}")
    elif cmd == "add" and len(sys.argv) > 2:
        print("queued:", add(sys.argv[2]))
    elif cmd == "approve" and len(sys.argv) > 2:
        print(approve(sys.argv[2]))
    elif cmd == "skip" and len(sys.argv) > 2:
        print(skip(sys.argv[2]))
    else:
        print("usage: tiktok_queue.py [list | add <video> | approve <id> | skip <id>]")

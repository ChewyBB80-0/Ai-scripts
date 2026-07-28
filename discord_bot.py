"""
discord_bot.py
Two-way Discord DM chat with the ops assistant. DM the bot anything and it
answers with the SAME brain as the dashboard assistant (same tools + memory)
by relaying through control_server's /api/chat.

Requires: MESSAGE CONTENT INTENT enabled (Bot tab in the dev portal).
Env: DISCORD_BOT_TOKEN, DISCORD_USER_ID. Started by start_control.bat.
"""

import asyncio
import os
import socket
import sys
from pathlib import Path

import discord
import requests

import tiktok_queue

OWNER = int(os.environ["DISCORD_USER_ID"])
CHAT_URL = "http://127.0.0.1:8000/api/chat"
DISCORD_ATTACH_LIMIT = 9_000_000     # free-tier upload ceiling, with headroom

# Single-instance guard: if a second copy is launched (e.g. Startup entry AND a
# manual double-click), it exits immediately instead of connecting a second bot
# and answering every DM twice. Binding a fixed loopback port is atomic and the
# lock auto-releases the instant this process dies -- no stale lockfile.
_LOCK_PORT = 58731
try:
    _lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _lock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    _lock.bind(("127.0.0.1", _LOCK_PORT))
    _lock.listen(1)
except OSError:
    print("discord_bot already running (lock port in use) -- exiting this copy.")
    sys.exit(0)

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
history: list[dict] = []            # rolling conversation, shared brain does the rest


class ApprovalView(discord.ui.View):
    """Approve / Skip buttons on a queued TikTok post. custom_ids carry the
    queue id so the buttons still work after the bot restarts (re-registered
    in on_ready) instead of going dead mid-queue."""

    def __init__(self, qid: str):
        super().__init__(timeout=None)
        self.qid = qid
        ok = discord.ui.Button(label="Post to TikTok", emoji="✅",
                               style=discord.ButtonStyle.success,
                               custom_id=f"tt:ok:{qid}")
        no = discord.ui.Button(label="Skip", emoji="✖",
                               style=discord.ButtonStyle.secondary,
                               custom_id=f"tt:no:{qid}")
        ok.callback, no.callback = self._approve, self._skip
        self.add_item(ok)
        self.add_item(no)

    async def _owner_only(self, itx: discord.Interaction) -> bool:
        if itx.user.id != OWNER:
            await itx.response.send_message("Not your queue.", ephemeral=True)
            return False
        return True

    async def _run(self, itx: discord.Interaction, fn):
        # Uploading takes several seconds -- defer first so Discord doesn't
        # time the interaction out, and disable the buttons so one tap can't
        # be double-fired into two posts.
        await itx.response.defer()
        for c in self.children:
            c.disabled = True
        try:
            await itx.message.edit(view=self)
        except Exception:
            pass
        result = await client.loop.run_in_executor(None, fn, self.qid)
        await itx.followup.send(result)
        self.stop()

    async def _approve(self, itx: discord.Interaction):
        if await self._owner_only(itx):
            await self._run(itx, tiktok_queue.approve)

    async def _skip(self, itx: discord.Interaction):
        if await self._owner_only(itx):
            await self._run(itx, tiktok_queue.skip)


async def _send_approval(user: discord.User, row: dict):
    """DM one queued video: preview + Approve/Skip."""
    video = Path(row["video"])
    mode = ("posts straight to TikTok" if tiktok_queue.can_direct_post()
            else "goes to your TikTok drafts (direct posting unlocks after the audit)")
    body = (f"**TikTok approval**\n{row['title']}\n"
            f"`{video.name}` · approving {mode}.")
    files = []
    try:
        if video.exists() and video.stat().st_size <= DISCORD_ATTACH_LIMIT:
            files = [discord.File(str(video))]
        else:
            thumb = await client.loop.run_in_executor(
                None, tiktok_queue.thumbnail, video)
            if thumb:
                files = [discord.File(str(thumb))]
                body += "\n_(preview frame — the render is too big to attach)_"
    except Exception as e:
        body += f"\n_(no preview: {e})_"
    await user.send(body, files=files, view=ApprovalView(row["id"]))
    tiktok_queue.mark_notified(row["id"])


async def tiktok_watcher():
    """Poll the queue and DM anything new. Runs for the life of the bot."""
    await client.wait_until_ready()
    try:
        user = await client.fetch_user(OWNER)
    except Exception as e:
        print("tiktok_watcher: cannot reach owner:", e)
        return
    while not client.is_closed():
        try:
            for row in tiktok_queue.unnotified():
                await _send_approval(user, row)
        except Exception as e:
            print("tiktok_watcher error:", e)
        await asyncio.sleep(45)


@client.event
async def on_ready():
    print(f"discord bot ready as {client.user}")
    # Re-attach handlers to buttons on DMs sent before the last restart.
    for row in tiktok_queue.pending():
        if row.get("notified"):
            client.add_view(ApprovalView(row["id"]))
    if not getattr(client, "_tt_watcher", None):
        client._tt_watcher = client.loop.create_task(tiktok_watcher())


@client.event
async def on_message(msg: discord.Message):
    # only the owner's DMs
    if msg.author.id != OWNER or msg.guild is not None:
        return
    text = msg.content.strip()
    if not text:
        return
    history.append({"role": "user", "content": text})
    del history[:-20]
    try:
        async with msg.channel.typing():
            r = await client.loop.run_in_executor(
                None, lambda: requests.post(
                    CHAT_URL, json={"messages": history}, timeout=180))
            reply = r.json().get("reply", "(no reply)")
    except Exception as e:
        reply = f"⚠️ Assistant offline ({e}). Start start_control.bat on the PC."
    history.append({"role": "assistant", "content": reply})
    for i in range(0, len(reply), 1900):
        await msg.channel.send(reply[i:i + 1900])


client.run(os.environ["DISCORD_BOT_TOKEN"])

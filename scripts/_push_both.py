"""One-off: generate+render a fresh story, post Part 1 to YouTube (via bot,
public) AND Instagram (temp public host, since R2 isn't set up yet)."""
import csv
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
import bot
from instagram_upload import post_reel

# 1. Generate + render + post to YouTube (public), queue later parts.
bot.run_once(force=True)

# 2. Find the Part-1 video just posted.
rows = [r for r in csv.reader(open("output/post_log.csv"))
        if len(r) >= 4 and r[3] == "posted"]
title, vid = rows[-1][1], rows[-1][2]
mp4 = Path(f"output/{title}.mp4")
caption = Path(f"output/{title}_caption.txt").read_text(encoding="utf-8")
print(f"YouTube posted: {title} -> {vid}")

# 3. Temp public host (litterbox = catbox's throwaway host, 1h TTL).
with open(mp4, "rb") as f:
    r = requests.post("https://litterbox.catbox.moe/resources/internals/api.php",
                      data={"reqtype": "fileupload", "time": "1h"},
                      files={"fileToUpload": f})
url = r.text.strip()
print(f"Temp host: {url}")

# 4. Post the Reel to Instagram.
mid = post_reel(url, caption=caption)
print(f"Instagram Reel posted: {mid}")

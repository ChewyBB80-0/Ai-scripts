"""
add_channel.py
One-time setup for a NEW YouTube channel account.

1. Add an entry to accounts.json, e.g.:
   {"id": "creepyflux", "name": "CreepyFlux", "handle": "@CreepyFluxAI",
    "genres": ["creepy"], "yt_token": "token_creepyflux.json",
    "footage_dir": "footage", "logo": "branding/logo_creepyflux.png",
    "daily_target": 1, "ig_enabled": false, "enabled": true}
2. Run:  python add_channel.py creepyflux
   A browser opens -- sign in with the Google account that owns that channel.
3. Done. The hourly bot now posts to it automatically.

(For IG cross-posting on the new account, set env vars
 IG_USER_ID_<ID> and IG_ACCESS_TOKEN_<ID> via setx.)
"""

import sys

from accounts import get_account
from youtube_upload import get_authenticated_service


def main(acc_id: str):
    acc = get_account(acc_id)
    print(f"Authorizing YouTube for account '{acc.id}' -> {acc.yt_token}")
    print("A browser window will open. Sign in with the Google account that owns "
          f"the '{acc.name}' channel and approve.")
    get_authenticated_service(acc.yt_token)  # runs the OAuth flow, saves token
    print(f"Authorized. Token saved to {acc.yt_token} -- the bot can now post to this channel.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python add_channel.py <account_id>")
        sys.exit(1)
    main(sys.argv[1])

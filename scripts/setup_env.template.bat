@echo off
rem ============================================================
rem  setup_env.bat  --  RUN ONCE on the stick PC
rem  Sets the API keys + low-spec flag as PERSISTENT user env
rem  vars, so the scheduled task (run_all.py) and the bot/server
rem  all see them. After running this, sign out/in (or reboot)
rem  once so the new vars take effect, then start the services.
rem ============================================================
setx ANTHROPIC_API_KEY "YOUR_KEY_HERE"
setx IG_USER_ID "YOUR_IG_USER_ID"
setx IG_ACCESS_TOKEN "YOUR_KEY_HERE"
setx DISCORD_BOT_TOKEN "YOUR_KEY_HERE"
setx DISCORD_USER_ID "YOUR_DISCORD_USER_ID"
rem Cloudflare R2 temp-relay host (IG pulls from here, auto-deleted after post):
setx VIDEO_HOST_ENDPOINT "YOUR_R2_ENDPOINT"
setx VIDEO_HOST_BUCKET "YOUR_R2_BUCKET"
setx VIDEO_HOST_KEY_ID "YOUR_KEY_HERE"
setx VIDEO_HOST_SECRET "YOUR_KEY_HERE"
setx VIDEO_HOST_PUBLIC_URL "YOUR_R2_PUBLIC_URL"
rem TikTok Content Posting API (draft/inbox upload). SANDBOX keys (for testing).
rem Production keys (swap in after audit for public posting):
rem   key aww73svp61os9ywe  secret iMH7rzUIlVJND4b1klD1RXYNPsIM6sSW
setx TIKTOK_CLIENT_KEY "YOUR_KEY_HERE"
setx TIKTOK_CLIENT_SECRET "YOUR_KEY_HERE"
rem 720p + lighter encode + aggressive cleanup for the weak Atom stick:
setx MEDIA_MAKER_LOW_SPEC "1"
echo.
echo Done. Sign out/in (or reboot) once so these take effect.
pause

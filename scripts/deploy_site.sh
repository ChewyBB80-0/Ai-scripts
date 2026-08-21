#!/usr/bin/env bash
# Deploy site/ to Cloudflare Pages.
#
# Only needed while the Pages project is NOT connected to this GitHub repo. A
# Git-connected project deploys every push on its own and this script becomes
# dead weight -- prefer that, and delete this, if the connection ever works.
#
# Takes a channel: parkourflux (default) or carveteran. Each channel gets its
# OWN Pages project, because the project name IS the hostname and TikTok wants
# the domain to match the app name -- and renaming a Pages project does NOT
# change its hostname (Cloudflare's own rename dialog says so), so a second
# channel means a second project, never a rename. The chosen hostname is also
# registered as the OAuth redirect URI in the TikTok developer portal and must
# agree with REDIRECT_URI in tiktok_upload.py, or authorisation breaks rather
# than the site.
#
#   CLOUDFLARE_API_TOKEN   scoped to Account -> Cloudflare Pages -> Edit
#   CLOUDFLARE_ACCOUNT_ID  from the Workers & Pages overview page
#
# Both are read from ~/media_maker/.env. The token is never printed.
#
#   bash scripts/deploy_site.sh              (parkourflux)
#   bash scripts/deploy_site.sh carveteran
set -euo pipefail

cd "$(dirname "$0")/.."

CHANNEL="${1:-parkourflux}"
case "$CHANNEL" in
    parkourflux) PROJECT="parkourflux";   SRC="site" ;;
    carveteran)  PROJECT="thecarveteran"; SRC="site_carveteran" ;;
    *) echo "unknown channel '$CHANNEL' -- use parkourflux or carveteran" >&2
       exit 1 ;;
esac
[ -d "$SRC" ] || { echo "$SRC/ does not exist" >&2; exit 1; }

if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi

if [ -z "${CLOUDFLARE_API_TOKEN:-}" ]; then
    cat >&2 <<'MSG'
CLOUDFLARE_API_TOKEN is not set.

Create one at: Cloudflare dashboard -> My Profile -> API Tokens ->
Create Token -> Custom token, with the single permission:

    Account -> Cloudflare Pages -> Edit

Then append it to ~/media_maker/.env (chmod 600, gitignored):

    CLOUDFLARE_API_TOKEN=...
    CLOUDFLARE_ACCOUNT_ID=...
MSG
    exit 1
fi

if [ -z "${CLOUDFLARE_ACCOUNT_ID:-}" ]; then
    echo "CLOUDFLARE_ACCOUNT_ID is not set (right-hand side of Workers & Pages)." >&2
    exit 1
fi

# Fail before uploading rather than publishing a half-finished site.
missing=0
for f in index.html how-it-works.html tiktok.html privacy.html terms.html \
         callback.html style.css; do
    [ -f "$SRC/$f" ] || { echo "$SRC/$f is missing" >&2; missing=1; }
done
[ "$missing" -eq 0 ] || exit 1

if grep -rq "REPLACE-WITH" "$SRC"/*.html; then
    echo "$SRC/ still contains REPLACE-WITH placeholders -- fix before deploying." >&2
    exit 1
fi

for f in favicon.ico icon-32.png apple-touch-icon.png; do
    [ -f "$SRC/$f" ] || {
        echo "$SRC/$f is missing -- the browser tab would fall back" >&2
        echo "to no icon, which is what TikTok rejected the app for" >&2
        echo "on 2026-08-19. Regenerate the icon set first." >&2
        exit 1; }
done

echo "Deploying $SRC/ to ${PROJECT}.pages.dev ..."
npx --yes wrangler@latest pages deploy "$SRC" \
    --project-name="$PROJECT" \
    --branch=main \
    --commit-dirty=true

echo
echo "Verifying the live routes ..."
sleep 5
fail=0
for p in / /how-it-works /tiktok /privacy /terms /callback /style.css; do
    # -L: Pages 308s to the canonical path while a deploy propagates, which is
    # correct behaviour, not a broken route. Judge the destination.
    # 2>/dev/null: the snap build of curl prints a multi-line sandbox warning to
    # stderr on every single call, which buried the actual results.
    code=$(curl -sL -o /dev/null -w '%{http_code}' --max-time 20 \
           "https://${PROJECT}.pages.dev${p}?v=$$" 2>/dev/null || echo 000)
    printf '  %-14s %s\n' "$p" "$code"
    [ "$code" = "200" ] || fail=1
done

# A favicon that 200s is not proof of anything: Pages answers a missing
# /favicon.ico with index.html, status 200, content-type text/html. Judge
# the content-type, which is the thing that was actually wrong.
ctype=$(curl -sLI --max-time 20 "https://${PROJECT}.pages.dev/favicon.ico" 2>/dev/null | tr -d '\r' | awk -F': ' 'tolower($1)=="content-type"{print $2}' | tail -1)
case "$ctype" in
    image/*) printf '  %-14s %s\n' "/favicon.ico" "OK ($ctype)" ;;
    *) echo "  /favicon.ico serves '$ctype', not an image -- the browser tab" >&2
       echo "  will show no icon. This is the 2026-08-19 rejection." >&2
       fail=1 ;;
esac

# /callback is the one that breaks TikTok auth rather than just looking wrong.
#
# Check for the CODE THAT READS the parameter, not for the parameter appearing
# in the response. callback.html injects it client-side via URLSearchParams, so
# curl -- which runs no JavaScript -- can never see the value. The first
# version of this grepped for the echoed code and therefore failed on every
# deploy including a perfectly good one. A check that always fails gets
# ignored, and then it is worse than no check.
if curl -sL --max-time 20 "https://${PROJECT}.pages.dev/callback" 2>/dev/null \
   | grep -q "URLSearchParams"; then
    echo "  callback serves its code-reading script  OK"
else
    echo "  callback is missing its URLSearchParams handler -- TikTok auth" >&2
    echo "  would return a code the page cannot display. Check before re-auth." >&2
    fail=1
fi

[ "$fail" -eq 0 ] && echo "Done." || { echo "Some checks failed." >&2; exit 1; }

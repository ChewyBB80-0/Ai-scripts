#!/usr/bin/env bash
# Deploy site/ to Cloudflare Pages.
#
# Only needed while the Pages project is NOT connected to this GitHub repo. A
# Git-connected project deploys every push on its own and this script becomes
# dead weight -- prefer that, and delete this, if the connection ever works.
#
# The project name is deliberately hardcoded. parkourflux-policy.pages.dev is
# registered as the OAuth redirect URI in the TikTok developer portal and is
# hardcoded at tiktok_upload.py:23, so deploying under a different name would
# silently break authorisation rather than the site.
#
#   CLOUDFLARE_API_TOKEN   scoped to Account -> Cloudflare Pages -> Edit
#   CLOUDFLARE_ACCOUNT_ID  from the Workers & Pages overview page
#
# Both are read from ~/media_maker/.env. The token is never printed.
#
#   bash scripts/deploy_site.sh
set -euo pipefail

cd "$(dirname "$0")/.."
PROJECT="parkourflux-policy"

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
    [ -f "site/$f" ] || { echo "site/$f is missing" >&2; missing=1; }
done
[ "$missing" -eq 0 ] || exit 1

if grep -rq "REPLACE-WITH" site/*.html; then
    echo "site/ still contains REPLACE-WITH placeholders -- fix before deploying." >&2
    exit 1
fi

echo "Deploying site/ to ${PROJECT}.pages.dev ..."
npx --yes wrangler@latest pages deploy site \
    --project-name="$PROJECT" \
    --branch=main \
    --commit-dirty=true

echo
echo "Verifying the live routes ..."
sleep 5
fail=0
for p in / /how-it-works /tiktok /privacy /terms /callback /style.css; do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 \
           "https://${PROJECT}.pages.dev${p}?v=$$" || echo 000)
    printf '  %-14s %s\n' "$p" "$code"
    [ "$code" = "200" ] || fail=1
done

# /callback is the one that breaks TikTok auth rather than just looking wrong.
if curl -s --max-time 20 "https://${PROJECT}.pages.dev/callback?code=DEPLOYCHECK" \
   | grep -q "DEPLOYCHECK"; then
    echo "  callback extracts ?code=  OK"
else
    echo "  callback did NOT echo the code -- check before re-authing TikTok" >&2
    fail=1
fi

[ "$fail" -eq 0 ] && echo "Done." || { echo "Some checks failed." >&2; exit 1; }

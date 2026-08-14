#!/usr/bin/env bash
# Publish site/ to the parkourflux Pages project.
#
# This project is DIRECT-UPLOAD, not git-connected: it was created with wrangler
# so the domain could match the TikTok app name without waiting on the
# dashboard. That means pushes do NOT auto-deploy -- run this after changing
# anything under site/.
#
# The old parkourflux-policy project was git-connected and auto-deployed, which
# is how a broken build command sat unnoticed for three days while the live site
# stayed frozen. Manual and visible is not obviously worse.
set -euo pipefail
cd "$(dirname "$0")/.."
npx --yes wrangler@latest pages deploy site --project-name parkourflux --branch main --commit-dirty=true

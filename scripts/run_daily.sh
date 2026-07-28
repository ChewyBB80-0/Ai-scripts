#!/bin/bash
# Entry point for the Claude Code scheduled task / cron job.
# Set this as the command Claude Code runs on its schedule, e.g.:
#   Prompt: "Run scripts/run_daily.sh, then follow CLAUDE.md for review/posting logic"

set -e
cd "$(dirname "$0")/.."

FOOTAGE_COUNT=$(find footage -maxdepth 1 -name "*.mp4" | wc -l)
if [ "$FOOTAGE_COUNT" -eq 0 ]; then
    echo "$(date): No footage found in footage/. Skipping run." >> output/errors.log
    exit 1
fi

mkdir -p output/pending_review

python3 main.py --background "$(find footage -maxdepth 1 -name '*.mp4' | shuf -n 1)" \
    --new-story \
    --out "output/pending_review/$(date +%Y%m%d_%H%M%S).mp4"

echo "$(date): Generated new video, awaiting review in output/pending_review/" >> output/post_log.csv

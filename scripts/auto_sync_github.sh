#!/usr/bin/env bash
# Daily git auto-sync to GitHub. Run via cron 04:13 UTC.
# Requires GH_TOKEN in .env (fine-grained PAT, contents:write).
# If GH_TOKEN is absent, skips push (commits still made locally).
set -euo pipefail

cd /opt/mcp-market

# Source .env (with optional GH_TOKEN)
set -a; . ./.env 2>/dev/null || true; set +a

LOG_TAG="[auto_sync $(date -u +%Y-%m-%dT%H:%M:%SZ)]"

# Stage any tracked changes only (no untracked, to avoid leaking new secrets)
git add -u

if git diff --cached --quiet; then
  echo "$LOG_TAG nothing to commit"
else
  git commit -m "auto: daily sync $(date -u +%Y-%m-%d)" || {
    echo "$LOG_TAG commit failed"; exit 1; }
  echo "$LOG_TAG committed"
fi

LOCAL=$(git rev-parse master)
REMOTE=$(git rev-parse origin/master 2>/dev/null || echo none)

if [ "$LOCAL" = "$REMOTE" ]; then
  echo "$LOG_TAG master already in sync ($LOCAL)"
  exit 0
fi

if [ -z "${GH_TOKEN:-}" ]; then
  AHEAD=$(git rev-list --count origin/master..HEAD 2>/dev/null || echo ?)
  echo "$LOG_TAG GH_TOKEN missing; master is $AHEAD ahead of origin/master, skipping push"
  exit 0
fi

# Push using PAT via URL — does NOT persist credentials on disk
PUSH_URL="https://x-access-token:${GH_TOKEN}@github.com/devids77/mcp-market-ru.git"
if git push "$PUSH_URL" master 2>&1; then
  echo "$LOG_TAG pushed master to origin"
else
  echo "$LOG_TAG push failed"
  exit 1
fi

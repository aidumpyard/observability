#!/usr/bin/env bash
# Auto-commit local changes, then sync with origin if (and only if) auth works.
# Safe to run repeatedly; never prompts, never fails the caller.
set -uo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 0
export GIT_TERMINAL_PROMPT=0
branch="$(git branch --show-current 2>/dev/null)"
[ -z "$branch" ] && exit 0

# 1) auto-commit anything pending (no empty commits)
if [ -n "$(git status --porcelain)" ]; then
  git add -A
  git commit -q -m "auto: snapshot $(date '+%Y-%m-%d %H:%M:%S %Z')" --no-verify || true
  echo "git_sync: committed local changes on $branch"
else
  echo "git_sync: nothing to commit on $branch"
fi

# 2) sync with remote only if we can actually reach it (auth present)
if git ls-remote --heads origin >/dev/null 2>&1; then
  git pull --rebase --autostash origin "$branch" >/dev/null 2>&1 \
    && echo "git_sync: pulled --rebase from origin/$branch" \
    || echo "git_sync: pull skipped/failed"
  git push origin "$branch" >/dev/null 2>&1 \
    && echo "git_sync: pushed to origin/$branch" \
    || echo "git_sync: push failed"
  git push origin --tags >/dev/null 2>&1 || true
else
  echo "git_sync: remote auth not configured -> committed locally only (no push/pull)"
fi

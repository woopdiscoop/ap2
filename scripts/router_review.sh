#!/usr/bin/env bash
# Router review: merge a Worker branch into a detached review worktree and run every gate.
# Usage: scripts/router_review.sh <worker-branch> <venv-bin> [base-branch]
# Prints a short summary only; full pytest output goes to $REVIEW_LOG (default /tmp/router_review.log).
set -u
BR=$1; V=$2; BASE=${3:-claude/new-session-2hmd3s}
LOG=${REVIEW_LOG:-/tmp/router_review.log}
ROOT=$(git rev-parse --show-toplevel); RV="$ROOT/../rv-$(echo "$BR" | tr '/' '-')"
git -C "$ROOT" worktree add --detach "$RV" "$BASE" -q || exit 1
cd "$RV" || exit 1
git merge --no-ff -q -m "Merge $BR" "$BR" || { echo "MERGE CONFLICT"; exit 1; }
git diff --stat HEAD~1 | tail -1
export PYTHONPATH=src
echo "ruff: $("$V/ruff" check . 2>&1 | tail -1)"
echo "format: $("$V/ruff" format --check . 2>&1 | tail -1)"
echo "mypy: $("$V/mypy" 2>&1 | tail -1)"
echo "lock: $("$V/python" -m ale.contracts.lock --check 2>&1 | tail -1)"
"$V/python" -m pytest -m "not slow" -q -p no:cacheprovider >"$LOG" 2>&1
grep -E "^(FAILED|ERROR)" "$LOG" | cut -c1-160
tail -1 "$LOG"
echo "review worktree: $RV"

#!/usr/bin/env bash
# Calibrate the three HTML tasks: Haiku against Codex Sol, 5 fresh starts each.
# The judge runs with threshold 0: every run passes, and the report collects the scores.
# The pages are kept for the judge-noise measurement that sets the real threshold.
# usage: experiments/html/calibrate.sh [task...]   (default: dashboard mortgage landing)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
for task in "${@:-dashboard mortgage landing}"; do
  for t in $task; do
    uv run --project "$REPO" tare calibrate "$(cat "$HERE/$t/prompt.txt")" \
      --check "uv run --project $REPO tare judge --rubric $HERE/$t/rubric.md --threshold 0" \
      --side "claude --model haiku" --side "codex -m gpt-6.1-sol" --runs 5 --jobs 4 --keep \
      --project "$HERE/$t/project" --out "$HOME/.local/state/tare/calibrate/html-$t"
  done
done

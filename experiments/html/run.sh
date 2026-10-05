#!/usr/bin/env bash
# Cliff and Swap on the mortgage task, threshold 86 (see PLAN.md).
# Cliff reruns until an original fails, at most three attempts. Swap runs alongside.
# usage: experiments/html/run.sh [cliff|swap]   (default: both)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
T="$HERE/mortgage"
CHECK="uv run --project $REPO tare judge --rubric $T/rubric.md --threshold 86"
STATE="$HOME/.local/state/tare"

cliff() {
  for i in 1 2 3; do
    out="$STATE/cliff/html-mortgage-$i"
    uv run --project "$REPO" tare cliff claude "$(cat "$T/prompt.txt")" --check "$CHECK" \
      --project "$T/project" --tails 3 --budget 30 --out "$out" -- --model haiku
    grep -q "there is no cliff to find" "$out/report.txt" || break
  done
}

swap() {
  uv run --project "$REPO" tare swap "$(cat "$T/prompt.txt")" --check "$CHECK" \
    --a claude --a-args "--model haiku" --b codex --b-args "-m gpt-6.1-sol" \
    --cuts 0,0.5,1 --tails 3 --jobs 3 --project "$T/project" --out "$STATE/swap/html-mortgage" --port 8778
}

case "${1:-both}" in
  cliff) cliff ;;
  swap) swap ;;
  both) swap & cliff; wait ;;
esac

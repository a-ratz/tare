#!/usr/bin/env bash
# Run one condition of the dirty-twin test (see PLAN.md).
#
# usage: experiments/dirty-twin/run.sh r0|t0|t1
#   r0  real setup, real API (reference)
#   t0  real setup, fake endpoint (the dirty twin)
#   t1  bwrap room + naked config + strict flags, fake endpoint
#
# Output lands in runs/<run>/ (not committed): stream.jsonl, stderr.log, exit,
# fake.log and captures/ with every request the fake received.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
RUN="${1:?usage: run.sh r0|t0|t1}"
OUT="$HERE/runs/$RUN"
WORK="$HERE/runs/work"
PORT="${TARE_FAKE_PORT:-47811}"
rm -rf "$OUT"; mkdir -p "$OUT" "$WORK"

# Start like a plain terminal: drop what a parent Claude Code session exports.
for v in $(compgen -e | grep '^CLAUDE' || true); do unset "$v"; done

ARGS=(-p --output-format stream-json --verbose)
PROMPT="say ok"

start_fake() {
  uv run "$HERE/fake_model.py" "$OUT/captures" --port "$PORT" 2>"$OUT/fake.log" &
  FAKE_PID=$!
  trap 'kill "$FAKE_PID" 2>/dev/null || true' EXIT
  for _ in $(seq 100); do
    (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null && return
    sleep 0.1
  done
  echo "fake endpoint did not start" >&2; exit 1
}

rc=0
case "$RUN" in
  r0)
    (cd "$WORK" && timeout 300 claude "${ARGS[@]}" "$PROMPT") \
      >"$OUT/stream.jsonl" 2>"$OUT/stderr.log" || rc=$? ;;
  t0)
    start_fake
    (cd "$WORK" && ANTHROPIC_BASE_URL="http://127.0.0.1:$PORT" timeout 300 \
      claude "${ARGS[@]}" --dangerously-skip-permissions "$PROMPT") \
      >"$OUT/stream.jsonl" 2>"$OUT/stderr.log" || rc=$? ;;
  t1)
    start_fake
    ANTHROPIC_BASE_URL="http://127.0.0.1:$PORT" timeout 300 \
      "$REPO/prototypes/bwrap-room.sh" "$WORK" claude "${ARGS[@]}" \
      --strict-mcp-config --setting-sources project,local --dangerously-skip-permissions "$PROMPT" \
      >"$OUT/stream.jsonl" 2>"$OUT/stderr.log" || rc=$? ;;
  *) echo "unknown run: $RUN" >&2; exit 2 ;;
esac
echo "$rc" >"$OUT/exit"
echo "$RUN: exit $rc, $(ls "$OUT/captures" 2>/dev/null | wc -l) requests captured"

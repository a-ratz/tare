#!/usr/bin/env bash
# Prototype containment layer for Linux and WSL (bubblewrap, no root, no container).
#
# Inside the room /home is an empty tmpfs. Only the naked homes (from claude-naked)
# and one project directory are mounted, so the real home directory does not exist
# for anything the agent runs. Network stays shared because the CLI needs its API.
#
# usage: prototypes/bwrap-room.sh PROJECT_DIR <command...>
#   e.g. prototypes/bwrap-room.sh ./scratch claude -p --strict-mcp-config \
#          --setting-sources project,local --dangerously-skip-permissions "say hi"
#
# Measured on WSL2 (2026-10-04): the CLI starts, logs in and answers; the real
# ~/.claude, ~/.codex and project .env files are unreachable inside.
set -euo pipefail

PROJECT="$(realpath "${1:?project dir}")"; shift
NAKED_CONFIG="${CLAUDE_NAKED_CONFIG_DIR:-$HOME/.claude-naked}"   # created by claude-naked (holds the copied credentials)
NAKED_HOME="${CLAUDE_NAKED_USER_HOME:-$HOME/.claude-naked-home}"
CLAUDE_BIN="$(readlink -f "$(command -v claude)")"
mkdir -p "$NAKED_HOME"

extra=()
# WSL keeps the resolver behind a symlink into /mnt/wsl; without it DNS fails (EAI_AGAIN)
[ -d /mnt/wsl ] && extra+=(--ro-bind /mnt/wsl /mnt/wsl)

exec bwrap \
  --ro-bind /usr /usr --ro-bind /etc /etc \
  --symlink usr/bin /bin --symlink usr/lib /lib --symlink usr/lib64 /lib64 \
  "${extra[@]}" \
  --proc /proc --dev /dev --tmpfs /tmp --tmpfs /home \
  --bind "$NAKED_HOME" /home/naked \
  --bind "$NAKED_CONFIG" /home/naked/.claude-config \
  --ro-bind "$CLAUDE_BIN" /opt/agent/claude \
  --bind "$PROJECT" /work --chdir /work \
  --unshare-user --unshare-pid --unshare-ipc --unshare-uts --die-with-parent \
  --setenv HOME /home/naked \
  --setenv CLAUDE_CONFIG_DIR /home/naked/.claude-config \
  --setenv PATH /opt/agent:/usr/bin:/bin \
  "$@"

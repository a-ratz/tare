# Dirty-twin test on macOS: results

Ran on 2026-10-06 on macOS 27.0 (arm64) with Claude Code 2.1.289 (subscription login from the
Keychain), Codex CLI 0.159.0 (ChatGPT login) and Pi 0.99.1. The plan, markers and harness were
committed before the first run ([PLAN.md](PLAN.md), commit `7acffa6`). Raw runs stay local in
`runs/`.

## Verdict

**The Seatbelt room is clean for all three agents, and the probe reads it correctly.**

- The dirty twin showed the user's context, and the room showed none of it. tare's own
  `probe.score` read `tare: 0.00` for each agent.
- Parts of the real setup copied into the room were named with their sources.
- Nothing under the home directory, under `/var/folders`, in `/private/tmp/claude-<uid>`,
  `/private/var/tmp` or `/Users/Shared` was reachable from inside, and neither was the
  pasteboard. So the macOS places become the probe's reach targets on macOS.

Two planted parts did not reach the room, for reasons outside the probe, and one prediction
about Codex was wrong. Separately, the line-by-line comparison found two kinds of Codex context
that the probe does not see. The room is clean of them, so they are a blind spot of the probe,
not a leak, and they are not macOS-specific: #109.

## Markers

| Marker | T0 twin | T1 room | T2 room + planted |
|---|---|---|---|
| C1 Claude: plugin skill | yes | no | **yes** |
| C2 Claude: claude.ai connectors | yes | no | no |
| C3 Claude: account skills | yes | no | no |
| C4 Claude: account email | yes | yes (declared) | yes (declared) |
| C5 home path | yes | no | no |
| C6 project AGENTS.md | yes | yes | yes |
| X1 Codex: memories | yes | no | no (yes in T2b, post-hoc) |
| X2 Codex: skill from `~/.agents/skills` | yes | no | **yes** |
| X3 home path | yes | no | no (yes in T2b: the memories name paths under the home) |
| X4 project AGENTS.md | yes | yes | yes |
| X5 Codex: `mcp__qmd__` | no | no | no |
| I1 Pi: skill (XML listing) | yes | no | **yes** |
| I2 Pi: `pi-web-access` tool | yes | no | **yes** |
| I3 home path | yes | no | no |
| I4 project AGENTS.md | yes | yes | yes |

Every run ended with exit 0 and one request with tools. No room was left in `/private/tmp`.

## Readings

`probe.score` over T0 and the room, as `tare probe` prints it (declared login copies and the
email left out):

| Agent | Control (T0) | T1 | T2 |
|---|---|---|---|
| Claude Code | home path, mcp, skills, plugins, email, reach | `tare: 0.00` | 3 leaks: `skills 6 skills` from plugin codies-memory, `plugin codies-memory` with its path in the room, `env TARE_PLANTED_VARIABLE` |
| Codex | memories, home path, skills, reach | `tare: 0.00` | 2 leaks: `skills 1 skill` from `~/.agents/skills`, `env TARE_PLANTED_VARIABLE` |
| Codex T2b (post-hoc) | same | | 4 leaks: `memories` from `~/.codex/memories/memory_summary.md`, `home path`, `skills 1 skill`, `env` |
| Pi | extensions, home path, skills, reach | `tare: 0.00` | 6 leaks: four extension tools (`fetch_content`, `get_search_content`, `source_check`, `web_search`), `skills 1 skill` from `~/.pi/agent/skills`, `env TARE_PLANTED_VARIABLE` |

Reach in T1, for every agent:

- **Paths:** none visible, and no pasteboard.
- **Environment:** the room's variables (`HOME`, `PATH`, `TMPDIR`, `TERM`, `COLORTERM`, `LANG`,
  and the agent's own, plus `ENABLE_TOOL_SEARCH` and `CLAUDE_CODE_TMPDIR` for Claude Code) and the
  shell's `PWD`, `SHLVL` and `_`.
- **Outside (control):** every target existed and the pasteboard was readable.

## Predictions

| | Prediction | Outcome |
|---|---|---|
| C-P1 | T0, T1, T2 complete against the fake | **held** |
| C-P2 | T0 contains C1 to C6 | **held** |
| C-P3 | T1: C6, maybe C4, none of C1, C2, C3, C5 | **held.** C4 appeared and was declared. |
| C-P4 | T2 contains C1, C2, C3 and the reading names them | **failed for C2 and C3.** Without the room flags, the login brought neither connectors nor account skills into the fresh room. That matches CONCEPT.md's note that a fresh room never loaded connected accounts. The plugin (C1) arrived and was named with its skills and its path. The probe named nothing that was not there. |
| X-P1 | T0, T1, T2 complete | **held** |
| X-P2 | T0 contains X1 to X4, not X5 | **held** for the markers. But the claim behind X5, that an `exec` run offers no MCP tools, is wrong here. T0 offered an MCP namespace, `mcp__cua_repl`, just not the one X5 looked for (#109). |
| X-P3 | T1: X4 only | **held** |
| X-P4 | T2 contains X1 and X2, and the reading names them | **failed for X1.** Codex reads memories only when `config.toml` turns them on (`[features] memories`, `[memories] use_memories`), and the room's copy of `config.toml` does not. The plan copied the file, not the setting. The skill arrived and was named. |
| I-P1 | T0, T1, T2 complete | **held** |
| I-P2 | T0 contains I1 to I4 | **held** |
| I-P3 | T1: I4 only | **held** |
| I-P4 | T2 contains I1 and I2, and the reading names them | **held** |
| A-P1 | reach: everything outside, nothing inside, no pasteboard inside | **held** |
| A-P2 | T1 readings `tare: 0.00` with the listed control classes | **held** |
| A-P3 | T2 readings name each planted part with its source, nothing else | **held for every planted part that reached the request.** C2, C3 and X1 did not reach it (C-P4, X-P4), and the readings did not name them. |
| A-P4 | the Claude Keychain item unchanged | **held.** Digest `da4db220e280917e` and 1 item before and after all runs, and after the final `tare probe` checks. |
| A-P5 | every line T0 has and T1 lacks belongs to a claimed class | **held for Claude Code and Pi, failed for Codex** (below) |

## Post-hoc: Codex T2b

Not planned. It is T2 with the two memory settings appended to the room's `config.toml`. The
memories arrived, and the reading named them with their source. It also named the home path,
because the memories mention paths under the home directory.

## What the line difference showed (A-P5)

- **Claude Code** (117 lines): claude.ai connectors and the MCP server of a second plugin
  (`pdf-viewer`); plugin skills and account skills; the auto-memory path, the project files' paths
  and the working directory (home path); one environment line (`Shell: zsh`). All claimed.
- **Pi** (261 lines): extension tools and their guidelines; the XML skills listing; paths under
  the home directory, among them Pi's own package. All claimed.
- **Codex** (268 lines): the memories (claimed), and two classes the probe does not claim:
  - an MCP namespace `mcp__cua_repl` with its tools `js` and `js_reset`
  - skills of Codex plugins, listed as `- <plugin>:<skill>: …`

  The room had neither. The probe cannot see them in the twin or in a room: #109. Neither is
  macOS-specific.

## Found along the way

- **Claude Code updated itself during the session** (2.1.289 to 2.1.290). A room clones the CLI
  that `claude` resolves to at the time, so two rooms of one evaluation could run different
  versions. The probe prints the version per reading.
- **Seatbelt denials do not reach the unified log** (discovery, epic #85). So a run cannot list
  what an agent tried to read. The reach script stays the measure.

## Decision

By the plan:

- **The macOS targets become the probe's reach targets on macOS** (A-P1 held):
  - `~/Library/Keychains`, `~/Library/Preferences`, `~/Library/Application Support`
  - the user's directory under `/var/folders`
  - `/private/tmp/claude-<uid>`, `/private/var/tmp`, `/Users/Shared`

  The pasteboard check joins them: it was readable outside and not inside.
- **The probe needs no macOS-specific marker beyond reach** (A-P2, A-P3).
- **A-P5 found two Codex classes the probe does not claim.** They are not macOS-specific, so they
  became issue #109 rather than part of #89.

## Reproduce

```bash
uv run experiments/dirty-twin-macos/run.py markers
uv run experiments/dirty-twin-macos/run.py keychain
for a in claude codex pi; do for c in t0 t1 t2; do uv run experiments/dirty-twin-macos/run.py run $a $c; done; done
uv run experiments/dirty-twin-macos/run.py run codex t2b   # post-hoc
uv run experiments/dirty-twin-macos/run.py check
uv run experiments/dirty-twin-macos/run.py diff codex      # read locally, not for committing
uv run experiments/dirty-twin-macos/run.py keychain
```

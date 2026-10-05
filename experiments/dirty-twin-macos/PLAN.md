# Dirty-twin test on macOS

Fixed on 2026-10-06, before the measured runs. Decides the probe's markers and reach targets on
macOS (epic #85, feature #89). One test per installed agent: Claude Code 2.1.289, Codex CLI
0.159.0 and Pi 0.99.1, on macOS 27.0 (arm64). Same design as the Linux tests
([dirty-twin](../dirty-twin/PLAN.md), [-codex](../dirty-twin-codex/PLAN.md),
[-pi](../dirty-twin-pi/PLAN.md)). The Antigravity CLI is not installed on this Mac.

## What is known before the runs

- The Linux tests showed that the fake sees what each CLI assembles from the user's setup.
  The CLIs build their requests the same way on macOS. So this test has no R0 reference run.
  It asks what is new on macOS: the Seatbelt room (#88), the Keychain login, and what a room
  there can reach.
- From the discovery on epic #85: the Seatbelt room runs every agent with nothing under the
  home directory readable. Before the profile also denied them, `/var/folders` (the user's
  directory), `/private/tmp/claude-<uid>` and the pasteboard were reachable.
- `tare probe` on the merged branch already read `tare: 0.00` for all three agents
  (ae2a7df). Those runs were checks, not this test.
- The user's setup on this Mac, by names only:
  - Claude Code: no global CLAUDE.md, no hooks, no user MCP server. One plugin
    (`codies-memory`), account skills synced from claude.ai, claude.ai connectors from the login.
  - Codex: no global AGENTS.md. Memories, six skills in `~/.agents/skills`, three MCP servers in
    `config.toml`.
  - Pi: no global AGENTS.md. Five skills (symlinks into `~/.agents/skills`), six packages, among
    them `pi-web-access` with web tools.
  - No instruction file in a parent directory of this repository.

## Conditions

For each agent. The work directory is this repository, as `tare probe` uses it.

| Run | Setup | Model endpoint |
|---|---|---|
| T0 | the dirty twin, started as `tare probe` starts it (Pi on a copy of its agent directory) | fake |
| T1 | the Seatbelt room as `tare probe` builds it, with the agent's room flags | fake |
| T2 | T1 with parts of the real setup copied into the room's own copy (below) | fake |

Planted in T2, only into the room's own copy:

- **Claude Code:** the user's plugin, cloned into the room and loaded with `--plugin-dir`. The
  room flags are left out (`--strict-mcp-config --setting-sources project,local`), so the login
  can bring its connectors and account skills.
- **Codex:** `memories/memory_summary.md` copied into the room's `CODEX_HOME`, and the skill
  `agent-browser` cloned into the room's `~/.agents/skills`.
- **Pi:** the skill `apple-design` cloned into the room's `skills`, and the user's `npm`
  package directory cloned into the room's agent directory with `packages: ["npm:pi-web-access"]`.
- **All three:** the variable `TARE_PLANTED_VARIABLE` set in the room.

Pi also runs once with `--no-extensions` in T1 and T2, as `tare probe` does, so that its own
tools can be told apart from the extension tools.

**Reach** runs in T1 and T2 inside the room, and once outside as the control. It uses tare's
reach script with tare's targets plus the macOS ones:
- `~/Library/Keychains`, `~/Library/Preferences`, `~/Library/Application Support`
- the user's directory under `/var/folders`
- `/private/tmp/claude-<uid>`, `/private/var/tmp`, `/Users/Shared`

It also checks whether the pasteboard is readable.

The harness is `run.py`. T1 and T2 are scored by tare's own `probe.score` against T0, so the
readings are the ones `tare probe` would print.

## Markers

The values are in `markers.local.json`, which is not committed. The first 16 hex digits of
their SHA-256:

| ID | What | sha256 |
|---|---|---|
| C1 | Claude Code: a skill of the user's plugin (`codies-memory:…`) | `cff3fec4006f827a` |
| C2 | Claude Code: claude.ai connector tools (`mcp__claude_ai_`) | `4b9f99c0dd405af9` |
| C3 | Claude Code: account skills from the login (`anthropic-skills:`) | `7efa796ebb4136ee` |
| C4 | Claude Code: the account's email | `3cf00f91d08eb485` |
| C5 | the real home path | `da1dfe65a93bd31c` |
| C6 | the project's own AGENTS.md: legitimate context, not dirt | `685dcb9384372ec6` |
| X1 | Codex: a line of the memories | `fd576a95f29f6323` |
| X2 | Codex: a skill from `~/.agents/skills` | `b7c8dd117a7a3868` |
| X3 | the real home path | `da1dfe65a93bd31c` |
| X4 | the project's own AGENTS.md | `685dcb9384372ec6` |
| X5 | Codex: tools of an MCP server from `config.toml` (`mcp__qmd__`) | `ee1a3aea0c0fb8b1` |
| I1 | Pi: a skill, in Pi's XML listing | `546329229ad5aeed` |
| I2 | Pi: a tool of the `pi-web-access` extension | `2a71962642386c35` |
| I3 | the real home path | `da1dfe65a93bd31c` |
| I4 | the project's own AGENTS.md | `685dcb9384372ec6` |

## Predictions

Claude Code:

- **C-P1:** T0, T1 and T2 complete against the fake (exit 0, a request with tools).
- **C-P2:** T0 contains C1 to C6.
- **C-P3:** T1 contains C6 and none of C1, C2, C3, C5. C4 may appear. The email reaches a clean
  room in some runs only (CONCEPT.md), and either way it is declared, not a leak.
- **C-P4:** T2 contains C1, C2 and C3. The reading names:
  - the connectors as `mcp`, with the source "login (claude.ai connector)"
  - the plugin as `plugin`, with its path in the room
  - its skills as `skills`, with the source "plugin codies-memory"
  - the account skills as `skills`, with the source "login (account skills)"
  - the variable as `env`, with the source "inherited environment"

Codex:

- **X-P1:** T0, T1 and T2 complete against the fake.
- **X-P2:** T0 contains X1 to X4, and not X5: an `exec` run offers no MCP tools in its first
  request, as on Linux.
- **X-P3:** T1 contains X4 and none of X1, X2, X3.
- **X-P4:** T2 contains X1 and X2. The reading names:
  - the memories, with the source `~/.codex/memories/memory_summary.md`
  - one skill, with the source `~/.agents/skills`
  - the variable

Pi:

- **I-P1:** T0, T1 and T2 complete against the fake.
- **I-P2:** T0 contains I1 to I4.
- **I-P3:** T1 contains I4 and none of I1, I2, I3.
- **I-P4:** T2 contains I1 and I2. The reading names:
  - each `pi-web-access` tool as `extension`
  - one skill, with the source `~/.pi/agent/skills`
  - the variable

All three:

- **A-P1 (reach):** outside, every macOS target exists and the pasteboard is readable. In T1,
  none of tare's or the macOS targets is visible, and the pasteboard is not readable. The
  environment holds only the room's variables and the shell's own (`PWD`, `SHLVL`, `_`).
- **A-P2:** the T1 readings are `tare: 0.00`, and their control lines show at least these
  classes:
  - claude: home path, mcp, skills, plugins, email, reach
  - codex: memories, home path, skills, reach
  - pi: extensions, home path, skills, reach
- **A-P3:** the T2 readings name each planted part as listed above, with its source, and no
  other leak.
- **A-P4:** the Claude Keychain item has the same digest and the same item count before and
  after all runs. Before: digest `da4db220e280917e`, 1 item.
- **A-P5 (new classes):** every context line that T0 has and T1 lacks belongs to a class in
  A-P2, or names a path, a date or the environment. I read the line difference locally and
  report only the classes, not the lines.

## Decision

- **A-P1 holds:** the macOS targets become the probe's reach targets on macOS. The pasteboard
  check joins the probe's reach on macOS if it is readable outside and not inside.
- **A-P1 fails** for a path or the pasteboard: that is a finding about the room. The profile is
  fixed before the epic's PR.
- **A-P2 and A-P3 hold:** the probe's markers need nothing macOS-specific beyond reach. Its
  classes are the ones the twins showed.
- **A-P5 finds a class the probe does not claim:** a marker for it is added before #89 closes,
  or an issue is opened if it is not macOS-specific.
- **A-P4 fails:** stop. The Keychain must stay unchanged.

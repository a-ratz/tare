# Dirty-twin test for the GitHub Copilot CLI

Fixed on 2026-11-22, before the measured runs. Decides how `tare probe copilot` reads context,
what its control run is, how the room gets the login, and whether the room needs flags (epic
#189, feature #190). Same design as the tests for Claude Code, Codex, Pi and the Antigravity CLI.

## What is known before the runs

From scratch rooms on macOS 27.0.1 with Copilot CLI 1.0.114 (epic #189), its built-in help and
its documentation; of the user's setup only names and counts were read:

- "Bring your own key" variables point Copilot's model calls at tare's Anthropic Messages fake:
  `COPILOT_PROVIDER_BASE_URL`, `COPILOT_PROVIDER_TYPE=anthropic`, `COPILOT_MODEL`. The context is
  the first `/v1/messages` request with tools: `system`, `messages`, `tools`. Without a login the
  request had 19 tools; with a login in the room's `config.json` (`copilotTokens`, keyed
  `https://github.com:<login>`) it had 40, the extra ones named `github-mcp-server-…`, the
  built-in GitHub MCP server that comes with the login.
- Copilot writes into its home on every run (sessions, logs, `session-store.db`, `config.json`)
  and into its cache folder (`~/Library/Caches/copilot`: the unpacked CLI, the account's reply,
  MCP tool snapshots). `COPILOT_HOME` and `COPILOT_CACHE_HOME` move both. So **the dirty twin runs
  on a copy of `~/.copilot` without the sessions and logs, and an empty cache folder**; `HOME`
  and the environment stay the user's.
- The login is a Keychain item that only the `copilot` binary may read without asking the user.
  Copilot also takes a token from `COPILOT_GITHUB_TOKEN`, `GH_TOKEN`, `GITHUB_TOKEN` and, last,
  `gh auth token`. The user's Copilot login is also logged in with the gh CLI. **The room's
  login here is gh's token for that account**, written into the room's `config.json`.
- Context, by the documentation: instructions in `copilot-instructions.md` and
  `instructions/` in the Copilot home, `AGENTS.md`, `CLAUDE.md` and `.github/` files in the
  project; skills in the Copilot home's `skills/`, in `~/.agents/skills/` (which follows `HOME`,
  not `COPILOT_HOME`) and in the project; agents in the home's `agents/`; MCP servers in
  `mcp-config.json`; plugins in `installed-plugins/`. Online with a login, the account adds the
  GitHub MCP server and may add organisation agents and settings.
- The user's setup: two installed plugins (one with skills, agents and hooks, one with skills),
  seven skills in `~/.agents/skills/`, no `copilot-instructions.md`, no `settings.json`, no
  `mcp-config.json`, no skills or agents of the Copilot home's own, and no `AGENTS.md` or
  `CLAUDE.md` in the home directory.

## Conditions

| Run | Setup | Model endpoint |
|---|---|---|
| T0 | the dirty twin: real `HOME` and environment, a copy of `~/.copilot`, an empty cache folder, online with the user's own login | fake |
| T0off | T0 with `COPILOT_OFFLINE=true` | fake |
| T1 | Seatbelt room: fresh home whose `config.json` holds the login; no flags | fake |
| T1f | T1 with `--disable-builtin-mcps` | fake |
| T2 | T0 plus planted markers, written into the copy only (K8 to K11) | fake |
| R1 | T1 against Copilot's own API, with its default model: one prompt | real |

Every run is `copilot --allow-all-tools --no-auto-update -p <prompt> --output-format json`. The
work directory is a fresh directory directly under the home directory, outside any repository,
holding only a project `AGENTS.md` (K5). It is removed after each run. `~/.copilot` and
`~/.agents` are fingerprinted (paths, sizes, mtimes) before and after each twin.

## Markers

Values in `markers.local.json` (not committed); the sha256 prefixes:

| ID | What | sha256 |
|---|---|---|
| K1 | a skill name from `~/.agents/skills/` | `b7c8dd117a7a3868` |
| K2 | a skill name from an installed plugin | `34cad440a65388bf` |
| K3 | an agent name from an installed plugin | `6138029755379a1e` |
| K4 | the real home path | `da1dfe65a93bd31c` |
| K5 | the project's own AGENTS.md: legitimate context, not dirt | `84192906da053e31` |
| K6 | the account's GitHub login | `f339bfb4af974839` |
| K7 | a tool of the built-in GitHub MCP server (`github-mcp-server-`) | `d2b48a4d18e8edb3` |
| K8 | planted: a line in the Copilot home's `copilot-instructions.md` | `18cddc5d2a0dfbbc` |
| K9 | planted: a skill in the Copilot home's `skills/` | `132a89348ba4fad1` |
| K10 | planted: an agent in the Copilot home's `agents/` | `166f34860b37a043` |
| K11 | planted: an MCP server in the Copilot home's `mcp-config.json` | `50205883e00c36e9` |

## Predictions

- **P1:** T0 and T2 complete against the fake, and their first request with tools holds the
  context.
- **P2:** `~/.copilot` and `~/.agents` are unchanged after T0, T0off and T2.
- **P3:** T0 contains K4 and K5.
- **P4:** T0 contains K1, K2 and K3.
- **P5:** T0 contains K7; T0off does not.
- **P6:** T0 does not contain K6: the login carries the GitHub MCP server, not the account's name.
- **P7:** T2 contains K8, K9, K10 and K11.
- **P8:** T1 contains K5 and K7, and none of K1 to K4, K6 or K8 to K11.
- **P9:** T1f contains K5 and none of the other markers.
- **P10:** Reach in T1: none of the real paths, and no inherited variables.
- **P11:** R1 answers with the room's login: gh's token works for Copilot's own API.

## Decision

- **The fake through the "bring your own key" variables becomes Copilot's context probe, online
  with the login, and the copy twin its control,** if P1 to P3 hold.
- **The room passes `--disable-builtin-mcps`** if T1 shows K7 and T1f does not: the GitHub MCP
  server reaches into the user's GitHub account from inside the room.
- **The room's login is a `config.json` with `copilotTokens`,** filled from the first of
  `COPILOT_GITHUB_TOKEN`, `GH_TOKEN`, `GITHUB_TOKEN`, `gh auth token` for Copilot's own login, if
  P11 holds. Copilot's Keychain item comes last, because reading it asks the user.
- **The probe's classes for Copilot** are those T0 and T2 showed; a class neither showed is not
  claimed.
- If P2 fails, the twin does not ship until it leaves the real setup unchanged.

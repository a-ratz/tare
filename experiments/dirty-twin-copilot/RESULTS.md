# Dirty-twin test for the GitHub Copilot CLI: results

Ran on 2026-11-22 on macOS 27.0.1 (arm64) with Copilot CLI 1.0.114 and the user's own login. The
plan, markers and harness were committed and pushed before the first run (`0032015`). Two
conditions were added after the planned runs and are post-hoc: T2p (an enabled plugin) and T0out
(a work directory outside the home directory). Their code is in `run.py`, committed after they ran.

## Readings

| Marker | T0 twin | T0off | T0out | T1 room | T1f room + flag | T2 twin + planted | T2p twin + plugin |
|---|---|---|---|---|---|---|---|
| K1 a skill from `~/.agents/skills/` | yes | yes | **no** | no | no | yes | yes |
| K2 a skill of an installed plugin | no | no | no | no | no | no | no |
| K3 an agent of an installed plugin | no | no | no | no | no | no | no |
| K4 the real home path | yes | yes | no | no | no | yes | yes |
| K5 the project's AGENTS.md | yes | yes | yes | yes | yes | yes | yes |
| K6 the account's GitHub login | no | no | no | no | no | no | no |
| K7 GitHub MCP server tools | yes | no | yes | yes | **no** | yes | yes |
| K8 planted `copilot-instructions.md` | | | | | | **yes** | |
| K9 planted skill in `skills/` | | | | | | **yes** | |
| K10 planted agent in `agents/` | | | | | | **yes** | |
| K11 planted MCP server | | | | | | **yes** | |
| K12 skill of a planted, enabled plugin | | | | | | | **yes** |

- Every run ended with exit 0 and one model request with tools: 19 tools offline (T0off), 27 in
  the twin online (5 of them the GitHub MCP server's), 40 in the room online (18 of the GitHub
  MCP server's), 21 in the room with `--disable-builtin-mcps`, 31 in T2 (the planted MCP
  server's four tools on top). The extra built-in tools online are `web_fetch`,
  `semantic_code_search` and, with the GitHub MCP server, `web_search`.
- `~/.copilot` and `~/.agents` had the same fingerprint before and after every twin.
- **The skills of `~/.agents/skills/` came as project skills** (`<location>project</location>`):
  Copilot walks up from the working directory and found `~/.agents/skills/` above a work
  directory inside the home. With the work directory outside the home (T0out), none came.
- **All four of the user's installed plugins are disabled** in `config.json`, which is why K2
  and K3 never appeared. An enabled plugin planted into the copy (T2p) brought its skill.
- How the request lists context: skills as `<skill><name>…</name><description>…</description>
  <location>user|project|plugin|builtin</location></skill>`, custom agents as `- **name**:
  description` under "User-provided custom agents", instructions as `<custom_instruction>`
  blocks, MCP tools as `<server>-<tool>`.
- Reach in T1, T1f and R1: no real path; the environment held `HOME`, `TERM`, `COLORTERM`,
  `PATH`, `LANG`, `TMPDIR` and the shell's own `PWD`, `SHLVL` and `_`.
- R1, the room against Copilot's own API with gh's token as the login, answered `ok tare`: the
  project rule reached the real model.

## Predictions

| | Prediction | Outcome |
|---|---|---|
| P1 | T0 and T2 complete against the fake, the first request with tools holds the context | **held** |
| P2 | `~/.copilot` and `~/.agents` unchanged after T0, T0off and T2 | **held** (and after T2p and T0out) |
| P3 | T0 contains K4 and K5 | **held** |
| P4 | T0 contains K1, K2 and K3 | **failed for K2 and K3, held for K1.** The user's plugins are all disabled; an enabled one (T2p) does bring its skill. K1 came through the walk up from the work directory, not from `HOME` (T0out) |
| P5 | T0 contains K7, T0off does not | **held** |
| P6 | T0 does not contain K6 | **held** |
| P7 | T2 contains K8 to K11 | **held** |
| P8 | T1 contains K5 and K7, none of the others | **held** |
| P9 | T1f contains K5 and none of the others | **held** |
| P10 | reach in T1: no real path, no inherited variables | **held** |
| P11 | R1 answers with gh's token as the room's login | **held** |

## Decision

By the plan:

- **The fake through the "bring your own key" variables is Copilot's context probe, online with
  the login, and the copy twin its control** (P1 to P3 held).
- **The room passes `--disable-builtin-mcps`** (T1 showed K7, T1f did not). The GitHub MCP server
  reaches into the user's GitHub account. It is a default for every logged-in user, not a
  setting of theirs, but it is the account's reach into the room.
- **The room's login is a `config.json` with `copilotTokens`** (P11 held), filled from the first
  of `COPILOT_GITHUB_TOKEN`, `GH_TOKEN`, `GITHUB_TOKEN` and `gh auth token` for Copilot's own login,
  with Copilot's Keychain item last.
- **Classes the probe claims for Copilot:** global instructions (`copilot-instructions.md`),
  skills (the Copilot home's `skills/`, enabled plugins, and `.agents/skills/` in the project's
  parent directories), custom agents (the Copilot home's `agents/`), MCP servers
  (`mcp-config.json`, and the login's GitHub MCP server), the home path, and reach. Not claimed,
  because no run showed them: `instructions/*.instructions.md`, hooks, extensions and
  organisation settings.
- Two things the probe must learn: Copilot's MCP tools are named `<server>-<tool>`, not
  `mcp__<server>__<tool>`, and its custom agents are listed as `- **name**: description`.

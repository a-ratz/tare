# Dirty-twin test for Pi

Fixed on 2026-10-05, before the measured runs. Decides how `tare probe pi` reads context
and which flags Pi's room needs (epic #30, feature #31). Same design as the Claude Code and
Codex tests.

## What is known before the runs

From Pi 1.0.2's documentation and the user's setup (names only, no contents read):

- Pi has no environment variable for a base URL. A provider in `models.json` sets
  `baseUrl` and `api`, and `anthropic-messages` is one of the API types. The probe therefore
  reaches the fake through a provider of its own, `tare`.
- The user's default provider is `zai`, with an API key, so no account-carried context is
  expected. The OAuth providers (`openai-codex`, `github-copilot`) are not the default.
- Context files: `AGENTS.md` or `CLAUDE.md` in the agent directory, in the working
  directory and in its parents. User skills live in `<agent dir>/skills/`; there is none.
  One package is installed: `npm:pi-web-access`, an extension with web tools.
- CONCEPT.md's adapter notes seal Pi with `--no-extensions --no-skills --no-context-files`.
  `--no-context-files` would also drop the project's own AGENTS.md.

## Conditions

| Run | Environment | Model endpoint |
|---|---|---|
| R0 | real setup | the real default provider: `pi -p --mode json`, Pi's own event stream (reference) |
| T0 | a copy of the user's agent directory, plus the `tare` provider (the dirty twin) | fake |
| T1 | tare room: fresh agent directory with `auth.json`, `models.json` and a minimal `settings.json`; `--no-extensions --no-skills --no-context-files` | fake |
| T1b | the same room without those flags | fake |

The work directory sits under the user's home and holds a project `AGENTS.md` (Q4).

## Markers

| ID | What | Pattern |
|---|---|---|
| Q1 | an instruction file in a parent of the work directory (`~/AGENTS.md`) | sha256 `eacba40b4f8da8d9` |
| Q2 | a tool from the installed extension package | tool name containing `web` |
| Q3 | the real home path | sha256 `9599eee0f4f5e405` |
| Q4 | the project's own AGENTS.md: legitimate context, not dirt | `Project rule: every answer ends with the word tare.` |

## Predictions

- **P1:** T0 completes against the fake through the `tare` provider.
- **P2:** T0 contains Q1 to Q4.
- **P3:** Every marker found in R0 is also in T0.
- **P4:** T1 contains none of Q1 to Q4: the flags drop the project's AGENTS.md as well.
- **P5:** T1b contains none of Q1 to Q3 but does contain Q4. A fresh agent directory and a
  room without parent directories are enough on their own.
- **P6:** Reach in T1: none of the real paths, and no inherited variables.

## Decision

- **The fake is adopted** if P1 to P3 hold: it becomes Pi's context probe, and T0 its control.
- **No flags in the room** if P5 holds: the project's own context should reach Pi as it
  reaches the other agents. If P5 fails, the flags stay, and the README says the project's
  AGENTS.md is lost with them.

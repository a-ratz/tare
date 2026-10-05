# Dirty-twin test for the Antigravity CLI

Fixed on 2026-10-05, before the measured runs. Decides how `tare probe agy` reads context,
what its dirty twin is, and whether the room needs flags (epic #34, feature #35). Same design
as the tests for Claude Code, Codex and Pi.

## What is known before the runs

From a discovery in a scratch room (epic #34's comments) and agy 1.2.16's built-in
documentation; of the user's setup only names were read:

- `CLOUD_CODE_URL` points agy at the fake, which answers the Cloud Code `v1internal` calls and
  lists one model, `tare-fake`. The context is the first `streamGenerateContent` request with
  tools: `systemInstruction`, `contents`, `tools`.
- agy writes into `~/.gemini` on every run (conversations, caches, onboarding state; nothing
  elsewhere in the home directory). A run against the fake in the real setup would change the
  real setup: in the scratch room it wrote `onboardingComplete: false`. So **the dirty twin runs
  with an overlay over `~/.gemini`**: reads see the real files, writes go to a tmpfs that dies
  with the run. A user namespace mounts it; agy itself runs as the user's own uid with the real
  home path.
- Customization, by the documentation: rules in `GEMINI.md` / `AGENTS.md` from the working
  directory up to the repository root; workspace customizations in `.agents/` found the same
  way; global ones under `~/.gemini/config/` (rules, skills, plugins, `mcp_config.json`).
- The user's setup: `~/AGENTS.md` (a file in a parent directory of every project under home),
  three skills in `~/.agents/skills/`, eleven skills in `~/.gemini/skills/` (the Gemini CLI's
  place), an empty `~/.gemini/GEMINI.md`, an empty `mcp_config.json`, no knowledge items, and
  agy's conversation stores. The login's id token carries the account's email and name.

## Conditions

| Run | Setup | Model endpoint |
|---|---|---|
| T0 | the dirty twin: real setup and environment, real home path, overlay over `~/.gemini` | fake |
| T1 | tare room: fresh home with a copy of the login and the chosen model, nothing else; no flags | fake |
| T2 | T0 plus planted markers, written into the overlay only (Q6 to Q8) | fake |

The work directory is a fresh directory directly under the home directory, outside any
repository (the home directory is none), holding only a project `AGENTS.md` (Q5). It is
removed after each run. `~/.gemini` is fingerprinted (paths, sizes, mtimes) before and after
each twin.

## Markers

Values in `markers.local.json` (not committed); the sha256 prefixes:

| ID | What | sha256 |
|---|---|---|
| Q1 | a line of `~/AGENTS.md`, a parent of the work directory | `e837f16fe261a7fd` |
| Q2 | a skill name from `~/.agents/skills/` | `b7c8dd117a7a3868` |
| Q3 | a skill name from `~/.gemini/skills/` | `f94cdc233d96b658` |
| Q4 | the real home path | `9599eee0f4f5e405` |
| Q5 | the project's own AGENTS.md: legitimate context, not dirt | `dde77151459895e1` |
| Q6 | planted: a line in `~/.gemini/GEMINI.md` (the Gemini CLI's global rules) | `4e2068b2497f405f` |
| Q7 | planted: a rule in `~/.gemini/config/rules/` | `0e653690509660c2` |
| Q8 | planted: a skill in `~/.gemini/config/skills/` | `c479a6d22217ac97` |
| Q9 | the account's email | `3cf00f91d08eb485` |
| Q10 | the account's name | `ff3da60321dff96b` |

## Predictions

- **P1:** T0 and T2 complete against the fake, and their first request with tools holds the
  context.
- **P2:** `~/.gemini` is unchanged after T0 and after T2.
- **P3:** T0 contains Q4 and Q5.
- **P4:** T0 contains Q1 and Q2: without a repository root, the walk up from the work directory
  reaches the home directory.
- **P5:** T0 does not contain Q3: `~/.gemini/skills/` is the Gemini CLI's place, not agy's.
- **P6:** T2 contains Q7 and Q8, and not Q6.
- **P7:** T0 contains neither Q9 nor Q10: the account carries no context into the prompt.
- **P8:** T1 contains Q5 and none of Q1 to Q4 or Q6 to Q10.
- **P9:** Reach in T1: none of the real paths, and no inherited variables.

## Decision

- **The fake through `CLOUD_CODE_URL` becomes agy's context probe, and the overlay twin its
  control,** if P1 to P3 hold.
- **The probe's classes for agy** are those T0 and T2 showed; a class neither showed is not
  claimed.
- **No flags in the room** if P8 holds.
- If P2 fails, the twin does not ship until the overlay keeps `~/.gemini` unchanged.

# Dirty-twin test for the Antigravity CLI: results

Ran on 2026-10-05 on WSL2 with agy 1.2.16 and its OAuth login. The plan, markers and harness were
committed before the first run (`25c9dfc`).

## A failed first attempt

The first T0, T1 and T2 runs all ended before any model request: "model tare-fake is not
recognized as a known model". The fake listed its model under `models` only; agy takes a model
only when a sort group in `agentModelSorts` lists it. That was a harness fault, not a reading.
The fix (`Fake lists its model in agentModelSorts`) was committed, and all three conditions were
run again. Only the repeated runs are reported below.

## Readings

| Marker | T0 twin | T1 room | T2 twin + planted |
|---|---|---|---|
| Q1 `~/AGENTS.md` (a parent of the work directory) | no | no | no |
| Q2 a skill from `~/.agents/skills/` | no | no | no |
| Q3 a skill from `~/.gemini/skills/` | no | no | no |
| Q4 the real home path | yes | no | yes |
| Q5 the project's AGENTS.md | yes | yes | yes |
| Q6 planted `~/.gemini/GEMINI.md` | | | **yes**, as `<RULE[user_global]>` |
| Q7 planted `~/.gemini/config/rules/` | | | no |
| Q8 planted skill in `~/.gemini/config/skills/` | | | **yes**, in the skills list |
| Q9 account email | no | no | no |
| Q10 account name | no | no | no |

- All three runs ended with exit 0 and two model requests each; the first one with tools carried
  34 to 35 thousand characters of context and 11 tools.
- `~/.gemini` had the same fingerprint before and after T0 and T2 (paths, sizes and mtimes of
  every file).
- Line by line, T0 differed from T1 only in paths: the working directory, the app data
  directory, the conversation's artifact directory, and the paths of the built-in skills. Nothing
  else of the user's setup reached the prompt.
- Reach in T1: no real path; the environment held `HOME`, `TERM`, `PATH`, `LANG` and `PWD` only.

## Predictions

| | Prediction | Outcome |
|---|---|---|
| P1 | T0 and T2 complete against the fake, the first request with tools holds the context | **held** |
| P2 | `~/.gemini` unchanged after T0 and T2 | **held** |
| P3 | T0 contains Q4 and Q5 | **held** |
| P4 | T0 contains Q1 and Q2: the walk up reaches home without a repository root | **failed.** agy loaded neither `~/AGENTS.md` nor `~/.agents/`; outside a repository it reads the working directory's rules only |
| P5 | T0 does not contain Q3 | **held** |
| P6 | T2 contains Q7 and Q8, not Q6 | **failed for the rules, held for the skill.** Global rules come from `~/.gemini/GEMINI.md` (labelled `user_global`), not from `~/.gemini/config/rules/`; global skills from `~/.gemini/config/skills/` |
| P7 | no account email or name in T0 | **held** |
| P8 | T1 contains Q5 and nothing else | **held** |
| P9 | reach in T1: no real path, no inherited variables | **held** |

## Decision

By the plan:

- **The fake through `CLOUD_CODE_URL` is agy's context probe, and the overlay twin its control**
  (P1 to P3 held).
- **Classes the probe claims for agy:** global instructions (`~/.gemini/GEMINI.md`), global skills
  (`~/.gemini/config/skills/`), the home path, and reach. Not claimed, because no run showed them:
  instruction files above the project, `~/.agents/`, `~/.gemini/skills/`, global rule files under
  `~/.gemini/config/rules/`, MCP servers and plugins (the user has none to test with).
- **The room takes no flags** (P8 held): a fresh home is clean on its own and keeps the project's
  AGENTS.md.
- One thing to change in the probe: agy lists a skill as `- name (path): description`, which the
  probe's skills check (written for `- name: description`) would not match.

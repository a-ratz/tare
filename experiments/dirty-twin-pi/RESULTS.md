# Dirty-twin test for Pi: results

Ran on 2026-10-05 on WSL2 with Pi 1.0.2, default provider zai (API key). The plan was fixed
beforehand ([PLAN.md](PLAN.md), commit `0993791`). Raw runs stay local in `runs/`.

## Verdict

**The fake is Pi's context probe**, reached through a provider of its own. **Pi's room needs no
flags:** a fresh agent directory in a room without the user's parent directories carries none
of the user's context, and it keeps the project's own AGENTS.md. The flags from CONCEPT.md
(`--no-extensions --no-skills --no-context-files`) would drop that file too.

## Markers

| Run | Q1 parent AGENTS.md | Q2 extension tools | Q3 home path | Q4 project AGENTS.md |
|---|---|---|---|---|
| R0 Pi's own stream (real provider) | yes | yes | yes | yes |
| T0 dirty twin → fake | yes | yes (`fetch_content`, `get_search_content`, `source_check`, `web_search`) | yes | yes |
| T1 room with flags → fake | no | no | no | **no** |
| T1b room without flags → fake | no | no | no | **yes** |

## Predictions

| | Prediction | Outcome |
|---|---|---|
| P1 | T0 completes through the `tare` provider | **held.** Exit 0, one request. |
| P2 | T0 contains Q1 to Q4 | **held.** |
| P3 | every marker in R0 is also in T0 | **held.** |
| P4 | T1 contains none of Q1 to Q4 | **held in substance, with a marker flaw.** The pre-registered Q2 pattern (`web` anywhere) also matched prose in Pi's own system prompt in both rooms. The tool lists settle it: T0 offers 8 tools and both rooms offer 4. The four missing ones are the extension's (see table). |
| P5 | T1b: none of Q1 to Q3, Q4 present | **held** (with the same reading of Q2). |
| P6 | reach in T1: nothing of the user's | **held.** Only the allowlist (`HOME`, `PI_CODING_AGENT_DIR`, `TERM`, `PATH`, `LANG`) and the shell's `PWD`. |

## Found along the way

- **Context files from parent directories.** An instruction file in a parent directory of
  the project (here `~/AGENTS.md`) reaches every Pi run below it. The room removes it, because
  `/work` has no parents but `/`.
- **Extension tools** are user context too. The probe identifies them as the tools the dirty
  twin offers that a room run with extensions disabled does not.
- **Pi's own stream** (`--mode json`) is larger than the captured request: 78k against 25k
  characters, because it repeats messages across events. It contains the same markers.

## Reproduce

```bash
for c in r0 t0 t1 t1b; do uv run experiments/dirty-twin-pi/run.py run $c; done
uv run experiments/dirty-twin-pi/run.py check
```

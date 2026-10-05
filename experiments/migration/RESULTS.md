# Does it hold up: results

Ran on 2026-10-05 on WSL2: Claude Code 2.1.289 (Sonnet, then Haiku after amendment 1) and
Codex 0.160.0 (default model). The plan and its amendment were committed before the runs they
govern ([PLAN.md](PLAN.md): `9c26f30`, amendment `3e16e6c`). Run directories with recipe,
journal and every tail stay local; the reports are quoted below with paths shortened.

## In one paragraph

**Swap showed something non-obvious, and it disproved my own assumption about the task.** The
pre-registered point of no return (deleting the CSV after a Latin-1 import) is not one. Latin-1
decoding loses no byte, so Codex repaired Haiku's finished, failed room in 3 of 3 tails with
`.encode('latin-1').decode('cp1252')`. In the same room, Haiku failed 3 of 3 times. **Cliff was not
put to its real test:** Sonnet never failed (3 of 3 originals passed), and with Haiku Cliff stopped
on a baseline of 0/3, which later turned out to be too eager. Two weaknesses of the reports came to
light, and both are listed below as proposals.

## Cliff

| Attempt | Model | Original | Search |
|---|---|---|---|
| 1 to 3 | Sonnet | passed every time; read the file as cp1252 | none: "there is no cliff to find" |
| Haiku 1 | Haiku | failed after 13 steps: 110 wrong fields (notes read as Latin-1, some amounts) | baseline 0/3 [0.00, 0.56], so "a fresh start fails too: a model gap", after 3 tails |

## Swap: a = Claude Code with Haiku, b = Codex

Run a failed after 12 steps; run b passed after 4.

```text
  cut 0.00: room a at step 0, room b at step 0
                agent a          agent b
    room a      1/3 0.06-0.79    3/3 0.44-1.00
    room b      0/3 0.00-0.56    3/3 0.44-1.00
    state effect  +0.17 [-0.25, +0.53]
    model effect  -0.83 [-0.97, -0.30]
  cut 0.50: room a at step 6, room b at step 2
    room a      0/3 0.00-0.56    3/3 0.44-1.00
    room b      1/3 0.06-0.79    3/3 0.44-1.00
    state effect  -0.17 [-0.53, +0.25]
    model effect  -0.83 [-0.97, -0.30]
  cut 1.00: room a at step 12, room b at step 4
    room a      0/3 0.00-0.56    3/3 0.44-1.00
    room b      3/3 0.44-1.00    3/3 0.44-1.00
    state effect  -0.50 [-0.78, -0.01]
    model effect  -0.50 [-0.78, -0.01]
  null check   passed: no state effect at cut 0, where both rooms are the untouched project
  verdict      the model explains more than the room at every cut
  tails        54
```

The native cells matched the handoff cells within their intervals at every cut (foreignness 0.00
for Codex everywhere; -0.33 to 0.00 for Haiku). So the handoff did not distort the comparison.

## Predictions

| | Prediction | Outcome |
|---|---|---|
| C1 | a failing original fails on the encoding | **held** for Haiku: notes read as Latin-1, plus some amounts. Sonnet never failed. |
| C2 | the cliff is at or before the delete | **not tested:** no search ran (Sonnet passed; Haiku stopped as a model gap). |
| C3 | the cliff is the wrong-encoding write or the delete | **not tested.** |
| S1 | null check at cut 0 | **held.** |
| S2 | at cut 1 a failed run's room cannot be rescued | **failed.** Codex rescued Haiku's room 3/3, although the CSV was deleted. Latin-1 is a lossless byte mapping, so the original bytes were still in the database. |
| S3 | blame passes from the model to the room | **failed as worded.** The model dominates at cuts 0 and 0.5 (-0.83). At cut 1, state and model tie at -0.50, and the one-line verdict calls that "the model at every cut". |

## What the run says about the idea

- **Swap: yes, it has legs.** The matrix is readable in a minute, and its strongest cell
  overturned the experimenter's own assumption, which neither a pass rate nor a transcript
  would have done. Haiku passed 3/3 in Codex's solved room: the room carried the result,
  although in the easy form (Haiku only had to leave it intact). Codex passed 3/3 in Haiku's
  broken room: the room was damaged but repairable, and only the stronger model saw how. So at
  cut 1 both the room and the model mattered, and the numbers say exactly that (a tie).
- **Cliff: not shown yet.** It correctly declined to invent a cliff where a model always
  passes or always fails. But it gave up on Haiku after 0/3, while Haiku's real rate on this task
  is above zero (1 in 3 by handoff at cut 0, 1 in 3 at cut 0.5). A real test needs a model in the
  "sometimes" band and the fix below.

## Proposals (not built; each would be its own issue)

1. **Cliff's early stop:** before declaring a model gap on 0/n, add tails until the baseline's
   upper bound falls below a stated rate (for example 0.2) or the budget runs out. 0/3 has an
   upper bound of 0.56, which is not "never".
2. **Swap's verdict on a tie:** when the state and model effects are within a small margin of
   each other, say "room and model alike" for that cut instead of "model".
3. **A harder point of no return for the next run:** a step that really destroys information
   (for example, rounding amounts to whole euros before the delete), so that S2 can hold or fail
   on a room that is truly lost.

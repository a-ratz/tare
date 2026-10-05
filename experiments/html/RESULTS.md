# Real failure, round 2: results

Ran on 2026-10-05 on WSL2: Claude Code 2.1.289 with Haiku, Codex 0.160.0 with `gpt-6.1-sol`, and
a Sonnet judge (`tare judge`). Calibration and the threshold rule were committed before the
calibration (`f1bd20c`); the threshold, the runs and the predictions before Cliff and Swap
(`e843faf`). Run directories stay local; the reports are quoted below.

## In one paragraph

**Swap held all four predictions, and Cliff gave a verdict I had not foreseen, which the judge's
noise then confirmed.** Sol finished Haiku's page above the threshold 3 of 3 times instead of
accepting it, and Haiku left Sol's page intact 3 of 3 times. Cliff's failed Haiku original
(score 85 at threshold 86) made one tool call, and Cliff called it "unlucky rather than lost".
Judged five more times afterwards, the same page scored 88 every time: the original failed on the
judge's one low score, not on anything Haiku did. Cliff did not invent a cliff where there was
none. The threshold could not be placed outside the judge's noise, as the plan wanted (see
[PLAN.md](PLAN.md)), so the judge decided some of Haiku's runs.

## Calibration and threshold

See [PLAN.md](PLAN.md): only the mortgage task separates the two sides (Haiku 62 to 88, Sol 90 to
93). Haiku's pages fill 76 to 88 without a gap under the judge's noise, so no threshold lies
outside every spread. The threshold is 86: Haiku falls below about 80 % of the time, Sol never.

## Cliff: `claude --model haiku`

| Attempt | Original | Search |
|---|---|---|
| 1 | passed, score 90 | none: "there is no cliff to find" |
| 2 | failed, score 85, after one step (`Write /work/index.html`) | 12 of 30 tails, below |

```text
  step  what the step did                                      tails  pass  rate  95% interval
     0  start                                                     9     1  0.11  0.02-0.44
     1  Write /work/index.html                                    3     2  0.67  0.21-0.94

  verdict   Resumed at the last step, the run still passes about as often as a fresh start:
            the original run was unlucky rather than lost.
```

The fresh starts scored 80, 62, 80, 80, 84, 78, 90, 80, 85. The tails resumed after the one
`Write` scored 88, 90, 85.

**Post-hoc** (not planned): `tare judge-noise` on the original's finished page, 5 scores:
88 88 88 88 88. With the first score, that page has six scores: 85 once and 88 five times. At
threshold 86 it passes 5 times in 6.

## Swap: a = Claude Code with Haiku, b = Codex with `gpt-6.1-sol`

Run a failed after 12 steps (score 78); run b passed after 4 (score 92).

```text
  cut 0.00: room a at step 0, room b at step 0
                agent a          agent b
    room a      0/3 0.00-0.56    3/3 0.44-1.00
    room b      1/3 0.06-0.79    3/3 0.44-1.00
    state effect  -0.17 [-0.53, +0.25]
    model effect  -0.83 [-0.97, -0.30]
  cut 0.50: room a at step 6, room b at step 2
    room a      0/3 0.00-0.56    3/3 0.44-1.00
    room b      1/3 0.06-0.79    3/3 0.44-1.00
    state effect  -0.17 [-0.53, +0.25]
    model effect  -0.83 [-0.97, -0.30]
  cut 1.00: room a at step 11, room b at step 3
    room a      0/3 0.00-0.56    3/3 0.44-1.00
    room b      3/3 0.44-1.00    3/3 0.44-1.00
    state effect  -0.50 [-0.78, -0.01]
    model effect  -0.50 [-0.78, -0.01]
  null check   passed: no state effect at cut 0, where both rooms are the untouched project
  verdict      the model explains more than the room until cut 0.50; from cut 1.00 on, room and model weigh alike
  tails        54
```

Foreignness was 0.00 for both agents at every cut: the native cells matched the handoff cells.

## Predictions

| | Prediction | Outcome |
|---|---|---|
| C1 | a failing original loses its points on table, chart or looks, not on payment or interest | **held** for both failing originals (Cliff 85, Swap 78): the judge found the numbers correct each time |
| C2 | a failing original makes at most three tool calls | **held for Cliff** (one call), **failed for Swap** (12 steps, score 78) |
| C3 | the cliff is the first write of `index.html`, a range containing it, or no separation | **failed as worded**: Cliff said the run was not lost at all. The post-hoc judging agrees |
| S1 | null check at cut 0 | **held** |
| S2 | model effect negative at cut 0, interval excludes zero | **held**: -0.83 [-0.97, -0.30] |
| S3 | Haiku in Sol's finished room passes at least 2 of 3 | **held**: 3/3 |
| S4 | Sol in Haiku's finished room passes at least 2 of 3 | **held**: 3/3 |

## What the run says about the idea

- **Cliff: it told luck from loss.** That is half of its job, and it did it on a case built to be
  hard: an original that failed by one point on a noisy check. It still has not found a real cliff,
  because neither round had a run that went wrong at a step.
- **Swap: the same shape as in the migration round.** The model explains the first half; at the
  end both rooms are repairable. "Room and model weigh alike" at cut 1 follows from arithmetic:
  when both off-diagonal cells pass, the state and model effects are equal. It means "both rooms
  can be finished", not "both are equally to blame", and the report should say so.
- **S4 answers the question that mattered here:** a stronger model that inherits a weaker
  model's finished page does not anchor on it. A task where the inherited state really misleads
  (round 1's proposal 3) is still open.
- **A judge check needs more than one score per tail near the threshold.** The pre-run noise
  measurement (5 scores per page) missed the 85 that decided Cliff's original. A single judge call
  per tail made the original's failure a coin toss.

## Proposals (not built; each would be its own issue)

1. **Resumed Claude Code tails print plain text.** `Claude.resume_args` lacks
   `--output-format stream-json --verbose` (Codex and Pi resume with JSON). Neither the dashboard
   nor a reader can see what a resumed Claude tail did; here it could not be checked whether the
   tails after the `Write` changed the page.
2. **Swap's effect labels** ("room a better than room b" next to a negative effect) state the sign
   convention but read as a claim. Phrase them from the sign, and name the tie at cut 1 as
   "both rooms can be finished".
3. **`judge-noise`**: instead of refusing every threshold inside some page's spread (which a
   continuous quality always triggers), report how often the noise decides pass or fail at that
   threshold, as in PLAN.md's table.
4. **A judge check that scores a page several times** near the threshold (median of three, for
   example), so that a tail's pass is not one draw of the judge.

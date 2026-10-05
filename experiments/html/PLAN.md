# Real failure, round 2: an HTML task

Epic #59. The first part (calibration) is fixed here before it runs; the predictions for Cliff and Swap
follow in this file once a task and threshold are chosen, before those runs.

## Candidates

Three single-file pages whose quality shows in a screenshot of the first render (the judge sees the
page as loaded, not interactions): `dashboard` (charts and a table from embedded data), `mortgage`
(a prefilled calculator with an amortization table and chart), `landing` (a landing page from given
copy). Each has a fixed prompt (`prompt.txt`) and rubric (`rubric.md`). The rubrics hold reference
values the judge can check and the agents never see.

## Calibration

`calibrate.sh`: per task, Haiku (`claude --model haiku`) and Codex with `gpt-6.1-sol`, 5 fresh starts
each, judged by `tare judge` (sonnet) with threshold 0, so every run passes and the report lists the
scores. The pages are kept.

## Choosing the task and the threshold

1. Per task, the score distributions of both sides.
2. `tare judge-noise` on a few kept pages near the candidate threshold, 5 scores each.
3. The task is chosen where a threshold outside the judge's spread has Haiku below it about 80 % of the
   time and Sol almost never. If no task gets there, the closest one is taken and the deviation stated.

## Calibration result and the chosen threshold (2026-10-05, before any Cliff or Swap run)

Judge scores of the fresh starts (5 per side, Sonnet as judge, threshold 0):

| Task | Haiku | Sol |
|---|---|---|
| dashboard | 38 66 76 80 80 | 10 12 14 15 22 |
| mortgage | 62 72 77 85 88 | 90 91 92 93 93 |
| landing | 62 62 66 66 66 | 62 66 72 72 74 |

Dashboard is inverted (every Sol page declares a global `const top`, a `SyntaxError` in the
browser, and its charts stay empty); landing does not separate the two. Only **mortgage** does.
`tare judge-noise` on its pages next to the gap, 5 scores each:

| Page | First score | Scores | Range |
|---|---|---|---|
| Haiku a-2 | 77 | 80 78 76 82 80 | 76-82 |
| Haiku a-3 | 85 | 85 85 85 88 85 | 85-88 |
| Haiku a-4 | 88 | 86 88 82 88 88 | 82-88 |
| Sol b-4 | 90 | 92 93 91 90 88 | 88-93 |
| Sol b-3 | 91 | 93 92 92 93 93 | 92-93 |

**No threshold lies outside every spread.** Haiku's pages fill 76 to 88 without a gap, and Sol's
weakest page reaches down to 88, so step 3 above cannot be met and its fallback applies: mortgage
is taken and the deviation stated. How often each threshold fails each side, from these scores:

| Threshold | Haiku below | Sol below | Where the judge's noise decides |
|---|---|---|---|
| 81 | about 56 % | 0 % | Haiku's 77 page |
| **86** | **about 80 %** | **0 %** | Haiku's two best pages only |
| 89 | about 100 % | about 4 % | Sol's weakest page |

**The threshold is 86.** The deviation: whether Haiku's best runs pass is partly the judge's
noise (its 85 and 88 pages pass 1 and 4 times in 5). Sol's lowest score, 88, stays above it. The
judge is blind to agent and model, so its noise falls alike on every cell; it costs power, it does
not bias a comparison.

## Runs

`run.sh`, the check `tare judge --rubric mortgage/rubric.md --threshold 86`, the mortgage project:

- **Cliff:** `tare cliff claude --model haiku`, 3 tails per probe, budget 30. If the original
  passes, the recipe is rerun until an original fails, at most three times. Each attempt is
  reported.
- **Swap:** a = Claude Code with Haiku, b = Codex with `gpt-6.1-sol`, cuts 0, 0.5, 1, 3 tails per
  cell.

## Predictions

What the calibration already shows: every page, Haiku's too, had the monthly payment and the total
interest right. Haiku's 62 and 72 pages came from runs with one or two tool calls; its 85 and 88
pages from runs with 6 and 12.

- **C1:** A failing original loses its points on the table, the chart or the visual quality, not on
  the monthly payment or the total interest (the judge's reason says which).
- **C2:** A failing original makes at most three tool calls.
- **C3:** Cliff places the cliff at the step that first writes `index.html`, or reports a range
  that contains it, or does not separate within the budget. At a baseline near 0.2, a separation
  within 30 tails would surprise me.
- **S1:** Swap's null check passes at cut 0.
- **S2:** At cut 0 the model effect is negative and its interval excludes zero.
- **S3:** At cut 1, Haiku in Sol's finished room passes at least 2 of 3: it does not spoil a good
  page.
- **S4:** At cut 1, Sol in Haiku's finished room passes at least 2 of 3: a page is never past
  repair, and the stronger model improves what it inherits rather than accepting it.

## What counts as "it holds up"

As in the migration round: Cliff names a range of at most two steps by what the steps did, with
separating intervals; Swap's null check passes and its verdict agrees with what the rooms visibly
contain. A Cliff without separation is reported as such, not as a cliff.

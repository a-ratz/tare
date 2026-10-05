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

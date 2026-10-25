# Judge: scoring results that no test can decide

[← Documentation](README.md) · [Measuring agents in rooms](measuring.md)

Some results have no test, for example how good a web page is. A **judge** is a second agent that
scores the result from 0 to 100 by your **rubric**, a Markdown file that says what earns points.
The judge is Claude Code with Sonnet unless you choose another agent with `--judge`.

## Judging a page

`tare judge DIR` opens the page `DIR/index.html` (another file with `--page`) in headless Google
Chrome inside a room of its own and takes a screenshot. Without `DIR`, it uses the current
directory. The judge then gets the screenshot, the page's source and the rubric in a fresh room,
without any agent or model names, so it cannot favour an agent or a model. It needs a Chromium
browser ([Install](install.md)).

## The judge as a check

`tare judge` exits with 0 when the score reaches the `--threshold` value, so it works as a check:

```bash
tare calibrate "build the page" --check "tare judge --rubric $PWD/rubric.md --threshold 60" \
  --side "claude --model haiku" --runs 5
```

A check runs in the finished workspace, so `tare judge` without `DIR` judges the page that the
agent built. The check does not run where you typed the command. So the rubric needs an absolute
path, which your shell makes from `$PWD/rubric.md`. And `tare` must be on `PATH`, or written as
`uv run --project <checkout> tare`.

## How far the scores vary

A judge does not give the same page the same score every time. One test page scored 55, 60, 58,
58, 66 and 62 in six judgements. Before you set a threshold, let `tare judge-noise` score a few
finished pages several times each, ideally a good one and a weak one:

```bash
tare judge-noise good-page/ weak-page/ --rubric rubric.md --times 10 --threshold 60
```

Each directory holds one finished page. `judge-noise` lists every page's scores and refuses a
threshold that lies inside the range of a page's scores, because there the judge's noise would
decide between pass and fail.

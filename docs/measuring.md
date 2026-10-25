# Measuring agents in rooms

[← Documentation](README.md)

tare's measuring tools start many agent runs and compare them. This page explains what they share;
each tool has its own page:

- [Calibrate](calibrate.md): how often each side passes a task
- [Judge](judge.md): scoring results that no test can decide
- [Swap](swap.md): was it the workspace or the agent?
- [Cliff](cliff.md): where did a failed run go wrong? (experimental)

## Checks and steps

Each run works on its own copy of your project, its **workspace**, in its own room.
tare scores each run with a **check**: any shell command that you pass with `--check`. tare runs
it in the finished workspace, and exit code 0 means that the run passed. A **step** is one
tool call of the agent, such as running a command or writing a file.

Swap and Cliff also continue runs from saved steps. Each continuation is a **tail**. A tail that
starts in another agent's workspace gets a **handoff**: a written summary of the steps so far, in
the same form for every agent.

## Run directories and the dashboard

Each command saves everything in a **run directory** under `~/.local/state/tare/`. It also starts
a live dashboard on your machine and prints its address. Open the address in a browser to follow
the runs. [Dashboard and rerun](dashboard.md) shows what it holds and how to repeat a run.

## The 95% interval

A pass rate comes with a **95% interval**: the range that holds the true pass rate with 95%
confidence. Few runs give a wide interval. Three passes out of three, for example, still allow a
true rate as low as 0.44.

## What it costs

Every Calibrate, Swap and Cliff report ends with the tokens and the cost of each side, of the
check and of the whole run ([Tokens and cost](tokens-and-cost.md)). Each tail is a real agent run,
so a search costs as much as its tails.

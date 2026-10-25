# tare documentation

The [README](../README.md) shows what tare does and gets you to a first clean reading. These pages
hold the details, one topic each.

## Start here

| Page | What it answers |
|---|---|
| [Install](install.md) | What tare needs on Linux, WSL and macOS, and how to install it |
| [The words tare uses](words.md) | Room, probe, reading, leak, control run, and the words of the measuring tools |
| [Running agents in rooms](running-agents.md) | Every command and flag, exit codes, what the room keeps out, the login lifetime |
| [Reading a probe](probe.md) | What each line of a reading means, what a leak looks like, when a probe is blind |

## Measuring agents

| Page | What it answers |
|---|---|
| [Measuring agents in rooms](measuring.md) | Checks, steps, run directories and the likely range, shared by the tools below |
| [Calibrate](calibrate.md) | How often does each side (an agent with its arguments) pass a task? |
| [Judge](judge.md) | How do I score a result that no test can decide, such as a web page? |
| [Swap](swap.md) | Did a run fail because of its workspace or because of the agent? |
| [Cliff](cliff.md) | After which step was a failed run lost? (experimental) |
| [Tokens and cost](tokens-and-cost.md) | What a run used and cost, and where the prices come from |
| [Dashboard and rerun](dashboard.md) | How to follow a run live and repeat it later |

## Background

| Page | What it answers |
|---|---|
| [How it works](how-it-works.md) | The three parts of a probe, and where the design and its measurements are written up |
| [CONCEPT.md](../CONCEPT.md) | The full design and every measurement behind it |
| [AGENTS.md](../AGENTS.md) | How changes to tare are made: issues, branches, checks, conventions |

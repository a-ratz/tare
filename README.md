<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset=".github/logo-light.svg">
    <img alt="tare" src=".github/logo-light.svg" width="260">
  </picture>

  <p>Prove your coding agent starts without your personal setup before you measure it.</p>
</div>

<div align="center">

[![License: MIT][license-shield]][license-url]
[![Version 0.1.0][version-shield]][version-url]
[![Python 3.11+][python-shield]][python-url]
[![Linux | WSL][platform-shield]][platform-url]
[![Claude Code | Codex | Pi | Antigravity][agent-shield]][agent-url]

</div>

<div align="center">
  <a href="#install">Install</a> &middot;
  <a href="#quick-start">Quick Start</a> &middot;
  <a href="#features">Features</a> &middot;
  <a href="#how-it-works">How it works</a> &middot;
  <a href="CONCEPT.md">Concept</a> &middot;
  <a href="https://github.com/AndreRatzenberger/tare/issues/new?template=bug_report.md">Report Bug</a>
</div>

<br>

---

## Why tare?

You test a skill by comparing agent runs with the skill against runs without it. On your own
machine, both runs also carry your personal setup: your global instructions, memories, installed
skills, MCP servers and connected accounts. The comparison then measures your machine, not the
skill.

A separate config directory does not fix this. With Claude Code, the login alone brings your
connected accounts (mail, calendar, documents), your account's skills and your email address
into the session. Evaluation frameworks expect you to provide a clean environment, and nothing
checks that you did.

tare starts the agent in a clean environment and proves that it is clean before every run. It
works with four coding agents on Linux and WSL: Claude Code, Codex, Pi
([`@earendil-works/pi-coding-agent`](https://www.npmjs.com/package/@earendil-works/pi-coding-agent))
and Google's Antigravity CLI (`agy`).

## The words tare uses

The name comes from weighing: you tare a scale, which sets it to zero, before you weigh
something. tare does the same for an agent before you measure it.

| Word | Meaning |
|---|---|
| room | An isolated environment for one agent run. It has an empty home directory, a fresh copy of your login and only a few basic environment variables. Your project appears at `/work`. tare builds the room with [bubblewrap](https://github.com/containers/bubblewrap). |
| probe | The check that tare runs before an agent starts. It makes no paid model calls: the agent talks to a small fake model server on your machine, which records what the agent sends. |
| reading | The result of a probe, one of three. A clean room reads `tare: 0.00`, the zeroed scale. A room with leaks reads, for example, `tare: 4 leaks`. A probe that could not see your setup reads `tare: not proven (blind)`. There are no values in between. |
| leak | Something of your personal setup that reaches the room, for example your global instructions. The reading names each leak and the file it came from. |
| declared | Something of yours that the room holds on purpose, for example the copy of your login. The reading lists it, but it is not a leak and does not stop the run. |
| dirty twin | The same probe in your real setup, outside the room. It proves that the probe can see your setup at all. |

## Features

- **Checks the room before every run.** The agent starts only when the probe reads
  `tare: 0.00`. Otherwise you see every leak with the file it came from.
- **Measures what the agent receives.** tare does not ask the agent about its context. It records
  the request that the agent sends to its model. An agent asked about its own context can refuse
  or be wrong.
- **Tells you when it cannot see.** tare looks at your files to learn what your setup holds, for
  example a global instructions file or installed skills. If the dirty twin's request lacks one of
  these, the probe could not see it, and a clean room would prove nothing. tare then tries once
  more and, if the gap remains, reads `tare: not proven (blind)` instead of `tare: 0.00`.
- **Keeps your files out of reach.** Your home directory, your other logins and your shell's
  secrets do not exist inside the room.
- **Leaves your own session logged in.** Each room gets a fresh copy of your login, which tare
  deletes after the run. Some agents, Claude Code among them, replace the login token when they
  renew it, and the old token in your own session stops working. So tare refuses to start when
  the copy would need renewal within the next hour. Start the agent once outside tare, which
  renews your login, and try again.
- **Works like the agent you know.** Interactive or one-shot, tare passes all your arguments to
  the agent.
- **Compares skills, plugins and models.** `tare calibrate` starts each variant several times
  from scratch, each in its own room, and reports how often each one passes your check.
- **Finds out whether the workspace or the model caused a failure.** `tare swap` lets two agents
  continue each other's unfinished work and compares the results.
- **Looks for the step where a failed run went wrong** (experimental). `tare cliff` restarts a
  failed run from its saved steps and names the step after which it no longer succeeds.

## When to use

| Use tare when | Look elsewhere when |
|---|---|
| you compare agent runs with and without a skill, plugin or prompt | you need protection from a hostile agent: the room has network access and a working login |
| you benchmark agents on your own machine | you are on macOS (not supported) |
| you want a fresh-machine run without a fresh machine | you log in with an API key only (untested) |
| an agent failed a task and you want to know which step lost it | you want a single run explained without running the agent again: Cliff runs it many times |

## Install

| Requirement | Notes |
|---|---|
| Linux or WSL2 | tare builds the room with user namespaces |
| [bubblewrap](https://github.com/containers/bubblewrap) | `sudo apt install bubblewrap` |
| at least one of the four agents | on `PATH` and logged in. Codex must resolve to a path under `/usr` for now, because tare mounts Codex's npm package and Node.js from there. If `which codex` points elsewhere, for example into nvm, install it with the system's npm (`sudo npm install -g @openai/codex`) and put `/usr/bin` first on `PATH`. The other agents can live anywhere on `PATH`. |
| Google Chrome, only for the judge | `google-chrome` on `PATH`, installed under `/usr` or `/opt`. tare takes screenshots of web pages with it. |
| [uv](https://docs.astral.sh/uv/) | Python 3.11 or newer |

Clone the repository, then run tare from the checkout with `uv run tare ...`, or put `tare` on
your `PATH` with `uv tool install .`:

```bash
git clone https://github.com/AndreRatzenberger/tare.git && cd tare
uv tool install .   # optional
```

The examples after Quick Start write `tare` for short. Without `uv tool install .`, write
`uv run --project <checkout> tare` instead. A check runs in a copy of your project, not in the
checkout, so `tare judge` in a check needs one of the two as well.

## Quick Start

With the requirements above in place, run this in the checkout:

```bash
uv run tare probe claude
```

```text
tare probe · claude 2.1.289 · /home/me/tare
  control   dirty twin shows: instructions, home path, mcp, skills, plugins, email, reach
  leaks     none
  declared
    email        account email                                subscription login
    credentials  /home/tare/.claude-config/.credentials.json  copy of the login, needed by the CLI
tare: 0.00
```

This is the output of a real run, with only the home path shortened. Line by line:

- `control` lists the kinds of context that the dirty twin found in the real setup. The probe
  could therefore have seen each of them in the room. Connected accounts count under `mcp`,
  because they reach the agent as MCP tools. `home path` means that your real home path appears
  in the agent's request, for example in the path of a memory file. `reach` comes from a plain
  script that looks for your files: outside the room it finds them, so it would find them inside
  too.
- `leaks none` says that none of these reached the room. Inside the room, tare starts Claude Code
  with flags that keep connected accounts and account skills out.
- `declared` lists the two things that the room holds on purpose. With a subscription login, your
  account email arrives with the login, and tare cannot remove it without removing the login. It
  is one line of text that names you, not instructions, memories or tools, so tare reports it
  instead of hiding it. The room also holds a copy of your login, because the agent needs one to
  run.

The probe starts your real agent with your real configuration for the dirty twin, so your hooks
and MCP servers start too. The Antigravity CLI writes into its config directory on every run, so
tare lets its dirty twin write into a temporary layer that disappears afterwards.

`uv run tare claude` then starts Claude Code in that room. `tare codex`, `tare pi` and `tare agy`
do the same for the other agents.

## Usage

```bash
tare probe claude                  # probe the room: tare: 0.00, the leaks and their sources, or blind
tare claude                        # probe, then start Claude Code in the room
tare claude -- -p "fix the tests"  # arguments after -- go to claude
tare claude --yolo                 # skip the agent's permission prompts
tare claude --allow-dirty          # start even though the reading is not tare: 0.00
tare claude --project ../other     # another project directory (default: the current one)

tare probe codex                   # the same for Codex, Pi and the Antigravity CLI
tare codex -- exec -m MODEL "..."  # one-shot Codex run: arguments after -- go to codex
tare pi                            # Pi in a room
tare agy                           # the Antigravity CLI in a room
```

`tare claude`, `tare codex`, `tare pi` and `tare agy` mount your project at `/work` directly. The
agent changes your real files, as it would outside the room. `--yolo` adds the agent's own flag
for skipping permission prompts. Pi has no such prompts. The commands under
[Measuring agents in rooms](#measuring-agents-in-rooms) work on copies instead.

`tare probe` exits with 0 on `tare: 0.00` and with 1 otherwise. `tare claude` and the other agent
commands refuse to start with exit code 1 unless the reading is `tare: 0.00` or you pass
`--allow-dirty`. Otherwise they return the agent's own exit code.

The room starts with the agent's defaults, not with your settings. Codex, for example, runs its
default model unless you pass `-m`. Set the model explicitly when you compare runs.

A room that is not clean names each leak and where it came from. The excerpt below comes from a
real run in a room that was given copies of real settings on purpose. The home path is
shortened.

```text
  leaks
    instructions global instructions     /home/me/.claude/CLAUDE.md
    home path    /home/me/               the user's files
    skills       1 skill                 /home/me/.claude/skills
    env          SPIKE_API_KEY           inherited environment
tare: 4 leaks
```

## Measuring agents in rooms

The commands in this section start many agent runs. Each run works on its own copy of your
project in its own room. tare scores each run with a **check**: any shell command that you pass
with `--check`. tare runs it in the finished workspace, and exit code 0 means that the run
passed. A **step** is one tool call of the agent, such as running a command or writing a file.

Each command saves everything in a **run directory** under `~/.local/state/tare/`. It also starts
a live dashboard on your machine and prints its address. Open the address in a browser to follow
the runs.

A pass rate comes with a **95% interval**: the range that holds the true pass rate with 95%
confidence. Few runs give a wide interval. Three passes out of three, for example, still allow a
true rate as low as 0.44.

### Calibrate: how often does each variant pass?

```bash
tare calibrate "fix the failing test" --check "uv run pytest -q" \
  --side "claude --model haiku" --side "codex -m gpt-6.1-sol" --runs 10
```

Each `--side` is one variant: an agent with its arguments. tare starts every side `--runs` times
from a fresh copy of the project and reports each side's pass rate with its interval. Use it to
compare skills, plugins or models. It also tells you whether a task suits Swap or Cliff. Swap
needs a task where one side mostly fails and the other mostly passes. Cliff needs a task where a
fresh start passes at least sometimes.

Some skills start with their own command, for example a slash command, so the sides need
different prompts. `--side-prompt` gives a side its own prompt. The sides are named a, b and c in
the order of `--side`:

```bash
tare calibrate --side "claude --plugin-dir plugins/a" --side "claude --plugin-dir plugins/b" \
  --side-prompt "a=/a:ideate a todo app" --side-prompt "b=/b:ideate a todo app" --runs 5
```

Without `--check`, a run counts as finished when its agent exits with 0. tare keeps each finished
workspace, and the report shows the finished runs and their times, so that you can score the
results elsewhere. `--keep` keeps the workspaces when there is a check too.

### Judge: scoring results that no test can decide

Some results have no test, for example how good a web page is. A **judge** is a second agent that
scores the result from 0 to 100 by your **rubric**, a Markdown file that says what earns points.
The judge is Claude Code with Sonnet unless you choose another agent with `--judge`.

tare opens the page (`index.html` in the given directory unless you pass `--page`) in headless
Google Chrome inside a room of its own and takes a screenshot. The judge then gets the screenshot, the
page's source and the rubric in a fresh room, without any agent or model names. `tare judge`
exits with 0 when the score reaches the threshold, so it works as a check:

```bash
tare calibrate "build the page" --check "tare judge --rubric $PWD/rubric.md --threshold 60" \
  --side "claude --model haiku" --runs 5
```

Without a directory, `tare judge` judges the current directory. A check runs in the finished
workspace, so that is the page the agent built. The rubric needs an absolute path, because the
check does not run where you typed the command. Your shell turns `$PWD/rubric.md` into one.

A judge does not give the same page the same score every time. One test page scored 55, 60, 58,
58, 66 and 62 in six judgements. Before you set a threshold, let `tare judge-noise` score a few
finished pages several times each, ideally a good one and a weak one:

```bash
tare judge-noise good-page/ weak-page/ --rubric rubric.md --times 10 --threshold 60
```

Each directory holds one finished page. `judge-noise` lists every page's scores and refuses a
threshold that lies inside the range of a page's scores, because there the judge's chance would
decide between pass and fail.

### Swap: was it the workspace or the model?

```bash
tare swap "fix the failing test" --check "uv run pytest -q" --a claude --a-args "--model sonnet" --b codex
```

Two agents, a and b, each attempt the same task once. When one of them fails, two causes are
possible. The agent may be the weaker one. Or its workspace may have reached a state that no
agent can finish. Swap separates the two causes.

Swap cuts both runs at several points (`--cuts`, as a fraction of each run's steps: 0 is the
start, 1 is the end, the default is `0,0.5,1`). At each cut, each agent continues each workspace,
three times by default (`--tails`). A continuing agent gets the workspace and a **handoff**: a
written summary of the steps so far, in the same form for every agent. Swap then reports two
numbers per cut, each with an interval:

- The **state effect** says how much better the continuations do in a's workspace than in b's.
  It measures what the workspace has become.
- The **model effect** says how much better agent a does than agent b, in the same workspaces.

At cut 0 both workspaces are your untouched project, so the state effect there must be zero. Swap
checks this and calls it the **null check**. Where an agent can continue its own saved session
(Claude Code, Codex and Pi), Swap also runs that, to measure what the handoff itself costs. The
report shows it per agent in a line such as `foreignness a +0.00 [-0.56, +0.56]`: the agent's pass
rate when it continues its own session, minus its pass rate from the handoff, in its own
workspace. A value near zero means that the handoff loses nothing. The example below leaves this
line out.

The report below comes from tare's own test. It drives the real Claude Code CLI against two
scripted models: fake models that follow a fixed script, so the right verdict is known. The test
runs four continuations per cell instead of three. Agent a is competent but trusts a note in the
workspace. Agent b is weak. Run b wrote a wrong note at step 2.

In the report, "room a" means the workspace that run a left at that cut, and each cell shows
passes out of continuations with their interval. "Tails" are the continuations. Positive effects
favour a's workspace or agent a.

```text
  cut 0.00: room a at step 0, room b at step 0
                agent a          agent b
    room a      4/4 0.51-1.00    1/4 0.05-0.70
    room b      4/4 0.51-1.00    1/4 0.05-0.70
    state effect  +0.00 [-0.35, +0.35]  (room a better than room b)
    model effect  +0.75 [+0.28, +0.89]  (agent a better than agent b)

  cut 0.50: room a at step 2, room b at step 2
                agent a          agent b
    room a      4/4 0.51-1.00    1/4 0.05-0.70
    room b      0/4 0.00-0.49    2/4 0.15-0.85
    state effect  +0.38 [-0.03, +0.66]  (room a better than room b)
    model effect  +0.12 [-0.25, +0.44]  (agent a better than agent b)

  null check   passed: no state effect at cut 0, where both rooms are the untouched project
  verdict      blame passes from the model to the room between cut 0.00 and cut 0.50; some
               deciding intervals still include zero, more tails would firm this up
```

At the start, the model explains the difference: agent a passes, agent b mostly fails. After the
wrong note, a's workspace still works and b's does not, even for the competent agent a. The
verdict says so: the blame passes from the model to the workspace. Its last part is a caution.
The intervals behind that verdict still include zero, so more continuations would make it firmer.

### Cliff: where did a failed run go wrong?

> **Experimental.** Cliff finds the known step in tare's scripted test. On real runs it has
> never blamed a step that was not the cause. But it has not yet found a real cliff either,
> because neither of two real test rounds had a failure that sat in one step. The rounds were a
> [data migration](experiments/migration/RESULTS.md) and a [web page](experiments/html/RESULTS.md).

```bash
tare cliff claude "fix the failing test" --check "uv run pytest -q" -- --model sonnet
```

A failed run is a chain of steps. Somewhere in that chain, the run may have taken a turn that it
could not recover from. Cliff looks for that step, the cliff: before it the run could still
succeed, after it the run no longer does.

tare runs the task once in a room and saves the workspace and the conversation after every step.
If the check fails, Cliff restarts the agent from saved steps in fresh rooms. Each restart is a
**tail**. Restarts from the very beginning are the **baseline**: they show how often the task
succeeds at all.

Cliff first runs three baseline tails and three tails from the last step. A step counts as good
while its tails pass at least half as often as the baseline. Cliff then halves the range between
the last good step and the first bad one, three tails at a time. When the two are neighbours, it
adds tails to both until their intervals no longer overlap, or until the budget (`--budget`,
default 30 tails) is spent. Everything after `--` goes to every agent run, so pin the model there.

Cliff can also end without a step. When even the baseline almost never passes, the task is too
hard for the model, and Cliff reports a model gap. It does so only when the upper end of the
baseline's interval lies below `--gap-below` (default 0.2). When tails from the last step pass
about as often as the baseline, the run was unlucky rather than lost, and Cliff says that.

The report below comes from tare's scripted test, with a scripted model that writes the wrong
answer into a note at step 4. Steps that Cliff did not need are missing from the table, and `<`
marks the cliff. `monotone yes` says that no step after the cliff passed again.

```text
  step  what the step did                                      tails  pass  rate  95% interval
     0  start                                                     3     3  1.00  0.44-1.00
     3  Bash echo hi > scratch.txt                                6     5  0.83  0.44-0.97
     4  Bash echo answer=41 > notes.txt                           6     0  0.00  0.00-0.39 <
     6  Bash echo 41 > answer.txt                                 3     0  0.00  0.00-0.56

  verdict   The run became lost at step 4.
  at step 4: Bash echo answer=41 > notes.txt
  changed   notes.txt
  monotone  yes
  tails     18 of a budget of 30
```

Cliff works with all four agents (`tare cliff pi ...`). Claude Code, Codex and Pi continue their
own saved session. The Antigravity CLI stores its sessions in a format that tare cannot cut, so
Cliff continues it with a handoff, as Swap does. Each tail is a real agent run, so a search costs
as much as its tails.

### Watch it live, repeat it exactly

The live dashboard of `tare calibrate`, `tare swap` and `tare cliff` runs at
`http://localhost:8777/` unless that port is taken. It shows the setup of the run, the probe
readings, each run step by step, every tail with what its agent is doing right now, the results as
they come in, and the final report.

```bash
tare watch ~/.local/state/tare/cliff/myproject-20261005-142000   # any run, live or finished
tare watch ~/.local/state/tare/calibrate/*                         # several runs: one row each
tare rerun ~/.local/state/tare/cliff/myproject-20261005-142000   # the same run again
```

Every run directory holds a `recipe.json` with the command, the task and the check, a fingerprint
of the project, the agents with their versions and arguments, and the settings. `tare rerun`
repeats the run in a new directory and says what has changed since.

## How it works

A probe has three parts, and none of them asks the agent anything. First, the real agent runs
inside the room against the fake model server, which keeps the request that it receives. That
request is the context the agent was given. Second, the dirty twin runs the same agent in your
real setup, so tare knows that it can see your context at all. Third, a plain script inside the
room looks for your files and for inherited secrets.

→ [Concept: the design and the measurements behind it](CONCEPT.md)
→ [The dirty-twin experiments that decided the probe design: Claude Code](experiments/dirty-twin/RESULTS.md), [Codex](experiments/dirty-twin-codex/RESULTS.md), [Antigravity CLI](experiments/dirty-twin-agy/RESULTS.md)

## Roadmap

macOS is not supported. A room for macOS is an idea, not yet planned.

## Contributing

The work is organised in epics, each split into features. One epic is one branch and one pull
request. [AGENTS.md](AGENTS.md) describes the process, the checks and the conventions. Run the
tests with `uv run pytest`.

## License

MIT. See [LICENSE](LICENSE).

---

Crafted with [Readme Craft](https://github.com/motiful/readme-craft)

[license-shield]: https://img.shields.io/badge/license-MIT-blue.svg
[license-url]: LICENSE
[version-shield]: https://img.shields.io/badge/version-0.1.0-informational.svg
[version-url]: pyproject.toml
[python-shield]: https://img.shields.io/badge/python-3.11%2B-3776AB.svg
[python-url]: https://www.python.org/
[platform-shield]: https://img.shields.io/badge/platform-Linux%20%7C%20WSL-555555.svg
[platform-url]: #install
[agent-shield]: https://img.shields.io/badge/agents-Claude%20Code%20%7C%20Codex%20%7C%20Pi%20%7C%20Antigravity-D97757.svg
[agent-url]: #install

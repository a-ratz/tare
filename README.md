<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset=".github/logo-light.svg">
    <img alt="tare" src=".github/logo-light.svg" width="260">
  </picture>

  <p>Prove your coding agent starts with nothing of yours before you measure it.</p>
</div>

<div align="center">

[![License: MIT][license-shield]][license-url]
[![Version 0.1.0][version-shield]][version-url]
[![Python 3.11+][python-shield]][python-url]
[![Linux | WSL][platform-shield]][platform-url]
[![Claude Code | Codex][agent-shield]][agent-url]

</div>

<div align="center">
  <a href="#quick-start">Quick Start</a> &middot;
  <a href="#features">Features</a> &middot;
  <a href="#how-it-works">How it works</a> &middot;
  <a href="CONCEPT.md">Concept</a> &middot;
  <a href="https://github.com/AndreRatzenberger/tare/issues/new?template=bug_report.md">Report Bug</a>
</div>

<br>

---

## Why tare?

Skill and agent evaluations compare runs with a skill against runs without it. If your agent
brings your own instructions, memory, skills or connected accounts into both runs, the
comparison measures your machine, not the skill. Moving the config directory is not enough:
with Claude Code, the login alone brings your connectors (mail, calendar, documents), your
account's skills and your email into the session. Eval frameworks assume that you provide a
clean runtime, and nothing checks that you did.

If you run skill evals, A/B comparisons or agent benchmarks with Claude Code or Codex on your
own machine, tare is for you.

## Features

- **Proves the room before the run.** You get `tare: 0.00`, or every leak with its source,
  and the agent does not start until the reading is zero.
- **Measures instead of asking.** tare checks what the agent actually receives. An agent asked
  about its own context can refuse or be wrong.
- **Tells you when it cannot see.** Every probe also checks your real setup. If tare cannot
  find a kind of context there, it reports itself blind instead of reporting clean.
- **Puts nothing of yours within reach.** Your home directory, your other logins and your
  shell's secrets do not exist inside the room.
- **Keeps your own session logged in.** Each run gets a fresh copy of the login, removed
  afterwards. tare refuses to start when that copy would have to refresh, because a refresh
  could log out your real session.
- **Works like the agent you know.** Claude Code or Codex, interactive or one-shot: all of
  the agent's arguments pass through, and your project is mounted at `/work`.

## When to use

| Use tare when | Look elsewhere when |
|---|---|
| you compare agent runs with and without a skill, plugin or prompt | you need a sandbox against a hostile agent: the room has network access and a usable login |
| you benchmark agents on your own machine | you are on macOS (planned, not built) |
| you want a fresh-machine run without a fresh machine | you log in with an API key only (untested) |

## Quick Start

```bash
git clone https://github.com/AndreRatzenberger/tare.git && cd tare
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

This is the output of a real run, with only the home path shortened. Then
`uv run tare claude` starts Claude Code in that room; `uv run tare probe codex` and
`uv run tare codex` do the same for Codex.

## Install

| Requirement | Notes |
|---|---|
| Linux or WSL2 | the room is built with user namespaces |
| [bubblewrap](https://github.com/containers/bubblewrap) | `sudo apt install bubblewrap` |
| Claude Code or Codex | on `PATH`, logged in; Codex installed under `/usr` (`npm install -g @openai/codex`) |
| [uv](https://docs.astral.sh/uv/) | Python 3.11+ |

From a checkout, either run it in place (`uv run tare ...`) or put `tare` on your `PATH`:

```bash
uv tool install .
```

## Usage

```bash
tare probe claude                  # measure the room: tare: 0.00, or every leak and its source
tare claude                        # probe, then start Claude Code in the room
tare claude -- -p "fix the tests"  # arguments after -- go to claude
tare claude --yolo                 # adds --dangerously-skip-permissions
tare claude --allow-dirty          # start even though the reading is not zero
tare claude --project ../other     # another project directory (default: the current one)

tare probe codex                   # the same for Codex
tare codex -- exec -m MODEL "..."  # one-shot Codex run; arguments after -- go to codex
```

The room starts with the agent's defaults, not your settings: Codex runs its default model
unless you pass `-m`. Set the model explicitly when you compare runs.

A room that is not clean names each leak and where it came from. This is an excerpt of a real
run in a room with planted dirt, with the home path shortened:

```text
  leaks
    instructions global instructions     /home/me/.claude/CLAUDE.md
    home path    /home/me/               the user's files
    skills       1 skill                 /home/me/.claude/skills
    env          SPIKE_API_KEY           inherited environment
tare: 4 leaks
```

Two residuals are declared: they appear in the reading but do not block the run. With a
subscription login, your account email arrives with the login. The room also holds a copy of
your login, because the agent needs one to run.

## How it works

tare takes three readings, and none of them asks the agent anything. First, the real CLI runs
inside the room against a local fake model endpoint, which keeps the request it receives: that
request is the context the agent was given. Second, the same run in your real setup is the
control, so tare knows it can see your context at all. Third, a plain script inside the room
looks for your files and inherited secrets.

→ [Concept, the three layers and the measurements behind them](CONCEPT.md)
→ [The dirty-twin experiments that decided the probe design: Claude Code](experiments/dirty-twin/RESULTS.md), [Codex](experiments/dirty-twin-codex/RESULTS.md)

## Roadmap

Next, in this order: [Cliff][epic-cliff], which finds the steps after which a failed run
became lost, then [Swap][epic-swap], which tells whether the room or the model was to blame.

## Contributing

Work is organised as epics with features; each epic is one branch and one PR. The process,
the checks and the conventions are in [AGENTS.md](AGENTS.md). Run the tests with
`uv run pytest`.

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
[agent-shield]: https://img.shields.io/badge/agents-Claude%20Code%20%7C%20Codex-D97757.svg
[agent-url]: #install
[epic-cliff]: https://github.com/AndreRatzenberger/tare/issues/11
[epic-swap]: https://github.com/AndreRatzenberger/tare/issues/17

<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/a-ratz/tare/main/.github/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/a-ratz/tare/main/.github/logo-light.svg">
    <img alt="tare" src="https://raw.githubusercontent.com/a-ratz/tare/main/.github/logo-light.svg" width="260">
  </picture>

  <p><b>Zero the scale before you weigh.</b><br>
  Prove your coding agent starts without your personal setup, then measure it.</p>
</div>

<div align="center">

[![License: MIT][license-shield]][license-url]
[![PyPI][version-shield]][version-url]
[![Python 3.11+][python-shield]][python-url]
[![Linux | WSL | macOS][platform-shield]][platform-url]
[![Claude Code | Codex | Pi | Antigravity][agent-shield]][agent-url]

</div>

<div align="center">
  <a href="#quick-start">Quick start</a> &middot;
  <a href="#features">Features</a> &middot;
  <a href="https://github.com/a-ratz/tare/blob/main/docs/README.md">Documentation</a> &middot;
  <a href="https://github.com/a-ratz/tare/blob/main/CONCEPT.md">Concept</a> &middot;
  <a href="https://github.com/a-ratz/tare/issues/new?template=bug_report.md">Report Bug</a>
</div>

<br>

---

Your coding agent knows you. Every run loads your global instructions, memories, skills, MCP
servers and connected accounts. At work that is the point. In an evaluation it is noise. Compare
runs with and without a skill on your own machine, and both runs carry your setup. You measure
your machine, not the skill.

**tare** starts the agent in a room that holds nothing of yours and proves the room is clean
before every run. It works with Claude Code, Codex, Pi and Google's Antigravity CLI on Linux and
WSL, and with the first three on macOS.

```text
$ tare probe claude
tare probe · claude 2.1.289 · /home/me/tare
  control   your real setup shows: instructions, home path, mcp, skills, plugins, email, reach
  leaks     none
  declared
    email        account email                                subscription login
    credentials  /home/tare/.claude-config/.credentials.json  copy of the login, needed by the CLI
tare: 0.00
```

`tare: 0.00` is the zeroed scale. Nothing of your setup reached the model except what the reading
declares. A reading with leaks names each one and the file it came from, and the agent does not
start.

## Quick start

```bash
uv tool install tare-cli            # or: pipx install tare-cli
tare probe claude                   # prove the room is clean
tare claude -- -p "fix the tests"   # run Claude Code in it
```

On Linux and WSL, tare also needs bubblewrap (`sudo apt install bubblewrap`). The
[install guide](https://github.com/a-ratz/tare/blob/main/docs/install.md) has the details per
platform, and [Reading a probe](https://github.com/a-ratz/tare/blob/main/docs/probe.md) explains
every line of the output above.

## Features

- **Measures what the model receives.** The probe records the request the agent sends to a fake
  model server on your machine. It makes no paid calls and never asks the agent about itself,
  because an agent asked about its own context can refuse or be wrong.
  [How it works](https://github.com/a-ratz/tare/blob/main/docs/how-it-works.md)
- **Knows when it cannot see.** A control run starts the agent in your real setup. If the probe could
  not see your setup there, the reading is `tare: not proven (blind)` instead of a `0.00` that
  proves nothing. [Reading a probe](https://github.com/a-ratz/tare/blob/main/docs/probe.md)
- **Keeps your files out and your login working.** The room has no home directory of yours, no
  credentials of your other tools and no secret environment variables. It gets a fresh copy of
  your login, which tare deletes after the run.
  [Running agents in rooms](https://github.com/a-ratz/tare/blob/main/docs/running-agents.md)
- **Compares skills, plugins and models.** `tare calibrate` starts each side several times from
  scratch and reports pass rates with their intervals.
  [Calibrate](https://github.com/a-ratz/tare/blob/main/docs/calibrate.md)
- **Scores what no test can decide.** `tare judge` lets a second agent score a page by your
  rubric, without agent or model names, and `tare judge-noise` shows how far its scores vary.
  [Judge](https://github.com/a-ratz/tare/blob/main/docs/judge.md)
- **Tells the workspace from the agent.** `tare swap` lets two agents continue each other's
  unfinished work and reports whether the workspace or the agent decided the outcome.
  [Swap](https://github.com/a-ratz/tare/blob/main/docs/swap.md)
- **Finds the step where a failed run was lost** (experimental). `tare cliff` restarts the run
  from its saved steps and names the step after which it no longer passes.
  [Cliff](https://github.com/a-ratz/tare/blob/main/docs/cliff.md)
- **Live dashboard, cost and reruns.** A dashboard follows every run, each report ends with tokens
  and cost, and `tare rerun` repeats a run from its recipe.
  [Dashboard and rerun](https://github.com/a-ratz/tare/blob/main/docs/dashboard.md) ·
  [Tokens and cost](https://github.com/a-ratz/tare/blob/main/docs/tokens-and-cost.md)

## When to use

| Use tare when | Look elsewhere when |
|---|---|
| you compare agent runs with and without a skill, plugin or prompt | you need protection from a hostile agent, because the room has network access and a working login |
| you benchmark agents on your own machine | you use the Antigravity CLI on macOS (not supported there yet) |
| you want a fresh-machine run without a fresh machine | you log in with an API key only (untested) |
| an agent failed a task and you want to know which step lost it | you want a single run explained without running the agent again, because Cliff runs it many times |

## Documentation

| | |
|---|---|
| **Getting started** | [Install](https://github.com/a-ratz/tare/blob/main/docs/install.md) · [The words tare uses](https://github.com/a-ratz/tare/blob/main/docs/words.md) · [Running agents in rooms](https://github.com/a-ratz/tare/blob/main/docs/running-agents.md) · [Reading a probe](https://github.com/a-ratz/tare/blob/main/docs/probe.md) |
| **Measuring** | [Overview](https://github.com/a-ratz/tare/blob/main/docs/measuring.md) · [Calibrate](https://github.com/a-ratz/tare/blob/main/docs/calibrate.md) · [Judge](https://github.com/a-ratz/tare/blob/main/docs/judge.md) · [Swap](https://github.com/a-ratz/tare/blob/main/docs/swap.md) · [Cliff](https://github.com/a-ratz/tare/blob/main/docs/cliff.md) · [Tokens and cost](https://github.com/a-ratz/tare/blob/main/docs/tokens-and-cost.md) · [Dashboard and rerun](https://github.com/a-ratz/tare/blob/main/docs/dashboard.md) |
| **Background** | [How it works](https://github.com/a-ratz/tare/blob/main/docs/how-it-works.md) · [Concept: the design and every measurement](https://github.com/a-ratz/tare/blob/main/CONCEPT.md) · [Experiments](https://github.com/a-ratz/tare/tree/main/experiments) |

## Status

tare is on PyPI as `tare-cli`. Claude Code, Codex and Pi run on Linux, WSL and macOS; the
Antigravity CLI runs on Linux and WSL, and stops with a message on macOS for now. What comes next
is in the [open epics](https://github.com/a-ratz/tare/issues?q=is%3Aissue+is%3Aopen+label%3Atype%3Aepic).

## Contributing

Every change starts as an issue. Larger work is an epic, split into features, and one epic
becomes one branch and one pull request. [AGENTS.md](https://github.com/a-ratz/tare/blob/main/AGENTS.md)
describes the process, the checks and the conventions. Run the tests with `uv run pytest`.

## License

MIT. See [LICENSE](https://github.com/a-ratz/tare/blob/main/LICENSE).

---

Crafted with [Readme Craft](https://github.com/motiful/readme-craft)

[license-shield]: https://img.shields.io/badge/license-MIT-blue.svg
[license-url]: https://github.com/a-ratz/tare/blob/main/LICENSE
[version-shield]: https://img.shields.io/pypi/v/tare-cli.svg
[version-url]: https://pypi.org/project/tare-cli/
[python-shield]: https://img.shields.io/badge/python-3.11%2B-3776AB.svg
[python-url]: https://www.python.org/
[platform-shield]: https://img.shields.io/badge/platform-Linux%20%7C%20WSL%20%7C%20macOS-555555.svg
[platform-url]: https://github.com/a-ratz/tare/blob/main/docs/install.md
[agent-shield]: https://img.shields.io/badge/agents-Claude%20Code%20%7C%20Codex%20%7C%20Pi%20%7C%20Antigravity-D97757.svg
[agent-url]: https://github.com/a-ratz/tare/blob/main/docs/install.md

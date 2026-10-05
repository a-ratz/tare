# tare

tare starts a coding agent (Claude Code, Codex, Pi or the Antigravity CLI) in a room without the
user's personal setup, and proves the room clean before the run. The room is a bubblewrap
sandbox with an empty home directory, a fresh copy of the login and a cleared environment. The
proof is a probe that asks the agent nothing. The real agent CLI runs in the room against a fake
model server, which keeps the request. That request is the context the agent CLI put together.
The same run in the user's real setup (the dirty twin) checks that the probe can see the user's
setup at all. A plain script checks what the room can reach. tare is built for skill and agent
evaluations, where a run that carries the user's own context measures the user's machine
instead of the skill.

The README explains these words for users. Contributors also meet these terms in the code:

- a **marker** is a line of the user's own files that the probe looks for in a request,
- an **unattended run** is a one-shot run without permission prompts (Calibrate, Swap and
  Cliff use them),
- a **capsule** is the archived workspace after one tool call,
- the **trail** is the record of a run in the same format for every agent.

## Layout

| Path | What |
|---|---|
| `src/tare/cli.py` | the `tare` command |
| `src/tare/agents.py` | what tare knows about each agent: its setup, login, probe arguments, request format, markers, unattended runs, saved session and trail |
| `src/tare/room.py` | the room: bwrap arguments, a fresh home with a login copy, the environment allowlist |
| `src/tare/probe.py` | the probe: context, control, reach, scoring and the printed reading |
| `src/tare/capsule.py` | capsules: archive the workspace after every tool call, continue one from the agent's own saved session or by handoff, run the check |
| `src/tare/cliff.py` | Cliff: baseline, adaptive search with Wilson intervals, the report |
| `src/tare/trail.py` | the trail: a run record in the same format for every agent, and the handoff written from it |
| `src/tare/swap.py` | Swap: each agent continues each run's workspace. State effect, model effect, handoff cost, the report |
| `src/tare/journal.py` | the run journal: one JSON line per event of a Calibrate, Cliff or Swap run |
| `src/tare/dashboard.py`, `dashboard.html` | the live dashboard: state from the run directory, one page |
| `src/tare/recipe.py` | recipes: how to repeat a run, and what has changed since |
| `src/tare/calibrate.py` | Calibrate: fresh-start pass rates per side |
| `src/tare/usage.py` | tokens and cost: the shape every adapter reads its stream into, totals, price tables and estimates |
| `src/tare/judge.py` | the judge check: render the page in a room, score it in a room without agent or model names (so the judge cannot favour either), measure how far the scores vary |
| `src/tare/fake.py` | the fake model server (Anthropic Messages for Claude Code and Pi, OpenAI Responses for Codex, Google's Cloud Code API for the Antigravity CLI) |
| `tests/` | pytest. Needs no agent, no login and no network. |
| `experiments/` | pre-registered measurements (`PLAN.md` before the runs, `RESULTS.md` after) |
| `prototypes/` | the first bwrap room, kept as the record |
| `CONCEPT.md` | the design and every measurement behind it |

## Checks

`uv run pytest` runs the unit tests. CI (`.github/workflows/ci.yml`) runs them on every PR and
on `main`, and a PR merges only when they are green.

CI cannot run the probe against real agents, because that needs bubblewrap and a logged-in
agent. So before a PR that touches the room or the probe, run these on your machine:

1. `uv run tare probe claude`, `codex`, `pi` and `agy` must read `tare: 0.00`, and the control
   line must show every kind of context your setup has. The dirty twin of the Antigravity CLI
   (`agy`) must leave `~/.gemini` unchanged.
2. A planted leak must fail the probe. Put known parts of a personal setup (instructions, a
   skill, an environment variable) into the room's copy of the agent's config or its environment, and check that
   the reading names each one with its source.
3. Before a PR that touches Cliff: `uv run experiments/cliff-scripted/world.py` must report
   "The run became lost at step 4". It drives the real Claude Code CLI against a scripted model,
   so it costs no API calls.
4. Before a PR that touches Swap, the trail or capsules: `uv run experiments/swap-scripted/world.py`
   must pass the null check and report "Blame passes from the model to the workspace between
   cut 0.00 and cut 0.50".

## Development process

**Epic → features → one branch and one PR → epic closed.**

1. **Every change starts as an issue**, from a template: Epic, Feature or Bug.
2. **An epic** describes a result and has no deadline. Its title starts with an emoji that
   fits it (`🤖 Codex support`). It is split into **features**, attached as its sub-issues.
   Every feature belongs to an epic.
3. **What is learned goes into the epic's comments.** Features get no comments. Write a comment
   on the epic whenever you learn something the issue does not state yet: a measurement and its
   result, a lesson, a problem and the issue it led to. A comment may link features, but it
   states the point itself:
   - good: "The dirty-twin run showed that a custom base URL turns Claude Code's tool search
     off, so the fake saw every tool schema inline instead of deferred. Probe and run now set
     `ENABLE_TOOL_SEARCH=true`."
   - bad: "The dirty twin had a problem, fixed in the room code."
4. **One branch per epic, from `main`**, named `<epic number>-<short-slug>` (`6-codex`). Features
   get no branches of their own. Each commit names the feature it implements (`Refs #7`).
5. **One PR per epic, when the epic is done.** Its body says `Closes #6` for the epic and for
   each feature done in it, so the merge closes them together. It carries its tests and its doc
   updates.
6. **A bug** stands on its own: its own branch and PR.
7. **The maintainer (Andre Ratzenberger) merges.** Nothing is pushed to `main` directly.

There is no project board. The maintainer decides the order of the open epics.
`gh issue list --label type:epic` lists them.

**Scope:** build what the issue asks. Anything else you notice (a missing feature, a refactor, a
test, a fix next door) becomes a new issue or a question, not part of the PR.

**Pause for the maintainer:**

- **A new epic while two or more are open:** recommend an order and wait until the maintainer
  confirms it.
- **A PR ready for review or merge:** say so, with its link. Go on only with epics whose order
  the maintainer has already confirmed.

## Measurements

- A claim marked *measured* in CONCEPT.md was observed. Say where: OS, agent CLI and version.
- Experiments are pre-registered. Plan, markers and harness are committed before the first run.
  The results follow, including the predictions that failed. A run that was not planned is
  labelled post-hoc.
- Raw runs stay local (`runs/` is ignored), because they hold a real user's whole context.

## Secrets and the user's setup

- Never print a credential, token or key, not even on its way to a hash. Compute the digest
  where the secret is read (`jq -j '.field' file | sha256sum`), compare files directly, and print
  names, not values.
- The fake model server keeps request bodies, never headers, because the login token travels
  in a header.
- Never change the user's real configuration (`~/.claude`, `~/.claude.json`, `~/.codex`, `~/.pi`,
  `~/.gemini`). Plant parts of a setup only into the room's copy, or into the temporary overlay
  that the Antigravity CLI's dirty twin writes into.
- The dirty twin starts the real CLI in the real setup, and the user's hooks fire. Run it only
  through `tare probe` or an experiment.

## Conventions

- Code, docs, issues, commits and PRs are in English.
- Python through uv (`uv run`, `uv add`). tare itself has no runtime dependencies.
- Write like the surrounding code: its naming, its comment density, its idiom.
- A user-visible change updates README.md and CONCEPT.md in the same PR.
- Linux and WSL for now, because the released room uses bubblewrap. A macOS room built on
  Seatbelt, the macOS sandbox, is in progress (epic #85).
- Commits use the `a-ratz` identity (`44863088+a-ratz@users.noreply.github.com`). Pushes go
  through that GitHub account.

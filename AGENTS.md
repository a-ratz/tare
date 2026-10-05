# tare

tare starts a coding agent (Claude Code or Codex) in a room where nothing of the user's came along, and proves it
before the run. The room is a bubblewrap sandbox: an empty home, a fresh copy of the login, a
cleared environment. The proof is a probe that asks the agent nothing. The real CLI runs in the
room against a fake model endpoint that keeps the request, which is the context the harness
assembled. The same run in the user's real setup (the dirty twin) checks that the probe can see
dirt at all. A plain script checks what the room can reach. tare is built for skill and agent
evaluations, where a run that carries the developer's own context measures the developer's
machine instead of the skill.

## Layout

| Path | What |
|---|---|
| `src/tare/cli.py` | the `tare` command |
| `src/tare/agents.py` | what tare knows about each agent: its setup, login, probe arguments, request format, markers, unattended runs, session file and trail |
| `src/tare/room.py` | the room: bwrap arguments, a fresh home with a login copy, the environment allowlist |
| `src/tare/probe.py` | the probe: context, control, reach, scoring and the printed reading |
| `src/tare/capsule.py` | capsules: archive the workspace at every tool call, continue one natively or by handoff, run the check |
| `src/tare/cliff.py` | Cliff: baseline, adaptive search with Wilson intervals, the report |
| `src/tare/trail.py` | the trail: one neutral record of a run for every agent, and the handoff rendered from it |
| `src/tare/swap.py` | Swap: both rooms crossed with both agents, state, model and foreignness effects, the report |
| `src/tare/fake.py` | the fake model endpoint (Anthropic Messages for Claude Code, OpenAI Responses for Codex) |
| `tests/` | pytest; needs no agent, no login and no network |
| `experiments/` | pre-registered measurements (`PLAN.md` before the runs, `RESULTS.md` after) |
| `prototypes/` | the first bwrap room, kept as the record |
| `CONCEPT.md` | the design and every measurement behind it |

## Checks

`uv run pytest` runs the unit tests. CI (`.github/workflows/ci.yml`) runs them on every PR and
on `main`, and a PR merges only when they are green.

CI cannot run the real thing. It needs bubblewrap and a logged-in agent. So before a PR that
touches the room or the probe, run it on the machine:

1. `uv run tare probe claude` and `uv run tare probe codex` must read `tare: 0.00` and show
   every control class.
2. A spike must fail the probe: plant known dirt into a room's own copy (instructions, a skill,
   an environment variable) and check that each piece is named with its source.
3. Before a PR that touches Cliff: `uv run experiments/cliff-scripted/world.py` must report
   "The run became lost at step 4". It drives the real Claude Code CLI against a scripted model,
   so it costs no API calls.
4. Before a PR that touches Swap, the trail or capsules: `uv run experiments/swap-scripted/world.py`
   must pass the null check and report "blame passes from the model to the room between cut
   0.00 and cut 0.50".

## Development process

**Epic → features → one branch and one PR → epic closed.**

1. **Every change starts as an issue**, from a template: Epic, Feature or Bug.
2. **An epic** describes a result and may take as long as it takes. Its title starts with an
   emoji that fits it (`🤖 Codex support`). It is split into **features**, attached as its
   sub-issues. Every feature belongs to an epic: there are no features on their own.
3. **What is learned goes into the epic's comments.** Features get no comments. Write a comment
   on the epic whenever knowledge comes up that the issue does not hold yet: a measurement and
   its result, a learning, a problem and the issue it led to. A comment may link features, but
   it states the point itself:
   - good: "The dirty-twin run showed that a custom base URL turns Claude Code's tool search
     off, so the fake saw every tool schema inline instead of deferred; probe and run now set
     `ENABLE_TOOL_SEARCH=true`."
   - bad: "The dirty twin had a problem, fixed in the room code."
4. **One branch per epic, from `main`**, named `<epic number>-<short-slug>` (`6-codex`). Features
   get no branches of their own; each commit names the feature it does (`Refs #7`).
5. **One PR per epic, when the epic is done.** Its body says `Closes #6` for the epic and for
   each feature done in it, so the merge closes them together. It carries its tests and its doc
   updates.
6. **A bug** stands on its own: its own branch and PR.
7. **Andre merges.** Nothing is pushed to `main` directly.

There is no project board. The order of the open epics is agreed in the chat;
`gh issue list --label type:epic` lists them.

**Scope:** build what the issue asks. Anything else you notice (a missing feature, a refactor, a
test, a fix next door) becomes a new issue or a question, not part of the PR.

**Pause for the human:**

- **A new epic while two or more are open:** recommend an order and wait until it is confirmed.
- **A PR ready for review or merge:** say so, with its link. Go on only with epics whose order
  is already agreed.

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
- The fake endpoint keeps request bodies, never headers: the login token travels in a header.
- Never change the user's real configuration (`~/.claude`, `~/.claude.json`, `~/.codex`). Plant
  dirt only into a room's own copy.
- The dirty twin starts the real CLI in the real setup, and the user's hooks fire. Run it only
  through `tare probe` or an experiment.

## Conventions

- Code, docs, issues, commits and PRs are in English.
- Python through uv (`uv run`, `uv add`). tare itself has no runtime dependencies.
- Write like the surrounding code: its naming, its comment density, its idiom.
- A user-visible change updates README.md and CONCEPT.md in the same PR.
- Linux and WSL only for now (bubblewrap). macOS needs its own room (Seatbelt).
- Commits use the `AndreRatzenberger` identity. Pushes go through that GitHub account.

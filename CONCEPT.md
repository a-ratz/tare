# tare: concept

tare starts a coding agent in an isolated room without your personal setup, and proves the room
clean before the run. It prints `tare: 0.00`, names every leak and where it came from, or says
that it could not see your setup (`tare: not proven (blind)`). It refuses to start the agent
until the reading is `tare: 0.00`, unless you pass `--allow-dirty`. It supports Claude Code, Codex, Pi
and the Antigravity CLI (`agy`) on Linux and WSL.

This document describes the design and the measurements behind it. The [README](README.md)
explains the words this document uses: room, probe, reading, leak, declared, dirty twin, check, tail and
handoff. Every claim marked **measured** was observed on WSL2. The section
[Measurements](#measurements) lists the agent versions and links each result.

## Why

Skill and agent evaluations compare runs with a skill against runs without it. If the agent
brings your own instructions, memories, skills or connected accounts into both runs, the
comparison measures your machine, not the skill. Evaluation frameworks that drive several agent
CLIs exist (see [Prior art](#prior-art)), but they expect you to provide a clean environment.
None of them checks that the environment is clean.

## Three layers

tare keeps your setup out in three layers. Each layer closes a gap that the one before leaves
open.

### 1. Context: nothing of your setup reaches the model

A separate config directory (`CLAUDE_CONFIG_DIR`, `CODEX_HOME`) and a separate `HOME` remove
your instructions, memories, plugins, hooks and skills. That is not enough.

- **Measured:** the login brings context that lives in no config directory. With only a
  separate config directory, a Claude Code session still had the connected accounts
  (mail, calendar, documents) as live tools, the account's skills and the account email.
  `--strict-mcp-config` and `--setting-sources project,local` removed the connected accounts and
  the account skills. The email stays with a subscription login. An API key login without OAuth
  should remove it, but that has not been tested.
- Codex: `CODEX_HOME` does not move `~/.agents/skills`, so Codex still reads your real skills
  there. Account plugins can also bring personal skills back after the login. tare starts Codex with `--disable remote_plugin` and an empty
  home directory.
- Claude Code's own bundled skills stay visible. They belong to the product, not to you.

### 2. Containment: nothing of yours within reach

- **Measured:** with the context layer alone, any process in the session can still read your
  real `~/.claude/CLAUDE.md`, `~/.claude/.credentials.json`, `~/.codex/auth.json` and the
  project's `.env` files. An agent with shell access and skipped permission prompts is one `cat`
  away.
- So tare runs the agent in a room built with bubblewrap (user namespaces, no root). The room
  mounts an empty `/home`, then only the room's own home directory and the project. Your real
  files do not exist inside. On WSL, `/etc/resolv.conf` points into `/mnt/wsl`, so the room
  mounts `/mnt/wsl` read-only, or DNS fails.
- **Measured:** the first prototype (`prototypes/bwrap-room.sh`) passed the calling shell's
  environment into the room, and a secret-like variable was visible inside. tare therefore
  clears the environment and passes only an allowlist (`TERM`, `COLORTERM`, `LANG`, `LC_ALL`).
- The room holds a usable login on purpose, a copy of yours. **Measured:** a stale copy fails to
  renew (`OAuth session expired`), so tare takes a fresh copy at every start and deletes it
  afterwards.

### 3. Proof: measured, not asked

- Asking the agent what it sees is a self-report, and the agent can refuse. **Measured:** Claude
  Code in a room refused a scripted request to list the home directory and search for
  credential files, and called it reconnaissance. That is correct behaviour, but useless for a
  probe. The probe must not depend on the agent's cooperation or honesty.
- **Reach:** a plain script runs inside the room and looks for your files and inherited
  environment variables.
- **Context:** tare points the real agent CLI at a fake model server on your machine. The
  server keeps the request, which is the context the agent CLI put together, and answers "ok".
  The idea is the blank run from analytical chemistry, which runs the whole procedure without a
  sample to see what the procedure itself brings in.
- **Control:** the same agent run in your real setup, the dirty twin, must show your context. The
  risk was that features that come with the login (connected accounts, account skills) would
  not load against a fake server, so the probe would read clean while a real run is not.
  **Measured:** for Claude Code this risk did not occur. Against the fake model server, the
  dirty twin still loaded the connected accounts, account skills, plugin skills, hook output,
  global instructions, memories and the email. The room loaded none of them except the email.
  Pointing Claude Code at a custom base URL turns its tool search off and puts every tool schema
  into the request. So the probe and the runs set `ENABLE_TOOL_SEARCH=true` to see the context as
  a normal run does.

## The parts of tare

### Room

A room is a bubblewrap sandbox for one agent run: an empty `/home` with the room's own home
directory at `/home/tare`, a fresh copy of the login, the agent's executable, the project at
`/work`, and the environment allowlist. `tare claude` and the other agent commands mount your
project directly, so the agent changes your real files. Calibrate, Swap and Cliff give every run
its own copy of the project. The room has network access and a working login. It keeps your setup out of the measurement. It does not protect your machine from a hostile
agent.

Claude Code may replace its login token when it renews it, which could log out your real
session. This has not been tested, so tare refuses to start when the copy would need renewal
within the next hour. **Measured:** the Antigravity CLI's Google login keeps its refresh token
when it renews, so a room may renew its own copy.

### Probe and reading

The probe has the three parts of layer 3: the agent in the room against the fake model server,
the dirty twin, and the reach script. It sorts what it finds into **kinds of context**,
each checked on its own: instructions, memories, home path, MCP servers (connected accounts count
here), skills, plugins, extensions, instruction files above the project, the account email, and
reach.

- A kind of context counts only when you have it. tare learns that from your files, for example
  a global instructions file or a skill folder.
- If you have a kind of context and the dirty twin does not show it, the probe could not see
  it. tare then runs the dirty twin once more after 10 seconds. If the second dirty twin still
  does not show that kind of context, the reading is `tare: not proven (blind)`. **Measured:**
  with six runs starting together, a dirty twin sent its request before its MCP servers were
  connected.
- Every probe makes no paid model call, because both the room and the dirty twin talk to the
  fake model server.

### Agents

Each agent needs its own way to the fake model server, its own login copy and its own markers:
lines of your own files that the probe looks for in a request.

| Agent | How the room is set up | Way to the fake model server | Kinds of context the dirty twin showed on the measuring machine |
|---|---|---|---|
| Claude Code | `CLAUDE_CONFIG_DIR` and `HOME` in the room, a copy of `.credentials.json`, `--strict-mcp-config --setting-sources project,local` | `ANTHROPIC_BASE_URL` | instructions, home path, MCP servers, skills, plugins, email, reach |
| Codex | `CODEX_HOME` and `HOME` in the room, a copy of `auth.json` only, `--disable remote_plugin` | `-c openai_base_url=<server>/v1` keeps the ChatGPT login | instructions, memories, home path, skills, reach |
| Pi | `PI_CODING_AGENT_DIR` and `HOME` in the room, copies of `auth.json` and `models.json`, a minimal `settings.json`, no flags | a provider of its own (`tare`, api `anthropic-messages`), because Pi has no base-URL variable | instruction files above the project, extensions, home path, reach |
| Antigravity CLI | `HOME` in the room, a copy of `antigravity-oauth-token` and the chosen model, no flags | `CLOUD_CODE_URL` | home path, reach. Global rules (`~/.gemini/GEMINI.md`) and global skills (`~/.gemini/config/skills/`) showed after copies were placed in the setup for the test, because the measuring machine had none. |

What each agent needed:

- **Codex:** without `--disable enable_request_compression`, the request arrives compressed.
  Codex tries a websocket five times before it falls back to HTTPS, and it refuses an override
  of its built-in provider that would stop this. So each Codex probe waits about 8 seconds. **Measured:** the captured
  request holds more than `codex debug prompt-input` shows, because Codex's own view leaves out
  the memories. Memories load only when your `config.toml` enables `[features] memories`. Hooks
  did not fire in one-shot runs, and the first request offered no tools from configured MCP
  servers, so the probe cannot check those two kinds of context for Codex. The room has no
  `config.toml` or `hooks.json` of yours, so neither can come in. A fresh `CODEX_HOME` means
  Codex's default model. Pass `-m` when you compare runs.
- **Pi:** a fresh agent directory is clean on its own and keeps the project's `AGENTS.md`, so the
  room uses no flags. `--no-context-files` would drop the project's `AGENTS.md`. tare finds Pi's
  extension tools by comparing the dirty twin's tools with a run that uses `--no-extensions`.
  With standard input left open, Pi waits for piped input and never answers, so tare closes it.
- **Antigravity CLI:** the fake model server speaks Google's Cloud Code `v1internal` API and
  offers one model. It lists that model in the groups the CLI shows models in
  (`agentModelSorts`), because the CLI rejects a model that no group lists. The
  CLI writes into `~/.gemini` on every run, so its dirty twin runs with an overlay over
  `~/.gemini`. A user namespace mounts the overlay, and every write goes to a temporary file
  system that disappears after the run. **Measured:** `~/.gemini` kept its fingerprint (paths,
  sizes, modification times) through every dirty twin. The CLI writes each skill's path into
  its skill list, so the probe compares skill lines without the path. Without that, a skill that
  leaked into the room would not match yours, because its path differs.
- **Instruction files above the project:** Claude Code's one-shot mode, which the probe uses, did
  not load `~/AGENTS.md`. Pi loaded it. So for Claude Code the probe does not show whether an
  interactive session in your real setup loads these files. A room has no parent directories, so these files
  cannot reach a room.
- **Long prompts:** Linux limits a single argument to about 128 KiB. tare passes the task to
  every agent as an argument, so a longer task fails. Pi could read it from a file with `@file`.

### Capsules, trail and handoff

Calibrate, Swap and Cliff need a run they can stop and continue. During a recorded run, a hook
archives the workspace after every tool call. Each archive is a **capsule**. The hook comes from
`--settings` for Claude Code, from the room's `hooks.json` for Codex (with
`--dangerously-bypass-hook-trust`), from a small extension for Pi, and from a global
`PostToolUse` hook in the room's `~/.gemini/config/hooks.json` for the Antigravity CLI.

A run continues from a capsule in one of two ways:

- **Its own saved session.** Claude Code resumes the conversation cut after the step. Codex
  resumes a session file cut after the step, with `codex exec resume <id>`. Pi resumes with
  `--session`. **Measured:** a resumed Codex session kept its id and finished the remaining plan
  from step 1.
- **A handoff.** The **trail** is a record of a run in the same format for every agent: the task,
  the messages, the tool calls and their results. tare writes a handoff from any prefix of it, so
  any agent can continue any run without reading another agent's session format. The Antigravity
  CLI stores its sessions in a format that tare cannot cut, so it always continues with a
  handoff. Its trail comes from `transcript_full.jsonl`.

### Calibrate

`tare calibrate` starts each side (an agent with its arguments) several times from a fresh copy
of the project and reports each side's pass rate with a 95% interval (Wilson). A side can have
its own prompt, so two skills that start with different commands compare in one call. Without a
check, a run counts as finished when its agent exits with 0, and tare keeps its workspace for
scoring elsewhere. **Measured:** in a field test that compared two ideation skills, 18 rooms all
read `tare: 0.00`, including a skill that started `claude -p` inside the room (see
[Measurements](#measurements)).

### Judge

The judge scores results that no test can decide, such as a web page. tare opens the page in
headless Google Chrome inside a room with the workspace read-only and no home directory, and
takes a screenshot. A judge agent (Claude Code with Sonnet by default) then scores the page from
the screenshot, the source and a rubric, in a fresh room without any agent or model names.
**Measured:** one test page scored 55, 60, 58, 58, 66 and 62 in six judgements. `tare judge-noise`
therefore refuses a threshold that lies inside a page's range of scores. On the same page the
judge found a real one-cent rounding bug and an overflow.

### Swap

Swap cuts two runs at several points. At each cut, each agent continues each run's workspace
by handoff. Swap reports a state effect (how much the state of the workspace matters), a model
effect (which agent does better), and, where an agent can continue its own saved session, the
handoff cost. At cut 0 both workspaces are the untouched project, so the state effect there must
be zero. Swap checks this, and the check is called the null check. When the state effect and the
model effect are within 0.1 of each other, Swap says they explain the failure about equally.

**Measured:** against scripted models with a known truth, the null check passed and the blame
passed from the model to the workspace between cut 0 and cut 0.5, as the scripts were written
to cause.

### Cliff

Cliff restarts a failed run from its capsules and names the step after which it no longer
succeeds. The baseline is the set of tails from the start. A step counts as good while its
tails pass at least half as often as the baseline. Cliff halves the range between the last good
and the first bad step, then adds tails to the two neighbours until their intervals separate or
the budget is spent. It reports a model gap instead of a step only when the upper end of the
baseline's 95% interval lies below 0.2.

**Measured:** against a scripted model whose wrong step is known, Cliff found step 4 with
separated intervals in 18 tails. Cliff stays experimental, because neither of two real test
rounds had a failure that sat in one step (see [Measurements](#measurements)). Swap already
shows, at three cuts, how often an agent passes when it continues its own workspace. When a real
Swap shows that rate dropping between two cuts, Cliff can narrow the drop down to one step. Only
then does Cliff get new experiments.

### Run directory, dashboard and recipes

Calibrate, Swap and Cliff write everything into a run directory: a journal (one JSON line per
event), a `recipe.json`, and the live output of every agent. The dashboard reads only the run
directory, so `tare watch` shows a finished run the same way as a live one. The recipe holds the
command, a fingerprint of the project and the agent versions. `tare rerun` repeats a run and
names what has changed since.

## Measurements

All measurements ran on WSL2 on 2026-10-04 and 2026-10-05.

| What | Agent and version | Result | Source |
|---|---|---|---|
| Dirty twin and room, fake model server | Claude Code 2.1.289 | the dirty twin showed every kind of context, the room only the email | [results](experiments/dirty-twin/RESULTS.md) |
| Dirty twin and room | Codex CLI 0.160.0 | the room read `tare: 0.00` | [results](experiments/dirty-twin-codex/RESULTS.md) |
| Dirty twin and room | Pi 1.0.2 | the room read `tare: 0.00` without flags | [results](experiments/dirty-twin-pi/RESULTS.md) |
| Dirty twin and room | Antigravity CLI 1.2.16 | the room read `tare: 0.00` without flags, and `~/.gemini` stayed unchanged | [results](experiments/dirty-twin-agy/RESULTS.md) |
| Rooms given copies of real settings on purpose | all four | Claude Code 4 leaks, Codex 6, Pi 5, Antigravity CLI 3, each named with its source | the results above |
| Scripted Cliff and Swap | Claude Code against scripted models | Cliff found step 4. Swap passed the null check and found the blame passing from the model to the workspace between cut 0 and cut 0.5 | `experiments/cliff-scripted`, `experiments/swap-scripted` |
| Real task 1: a data migration | Claude Code with Sonnet and Haiku, Codex | Deleting the source file after a wrong-encoding import was planned as the point of no return. Swap showed that the workspace could still be repaired. Haiku passed about 1 in 14 runs, Codex with gpt-6.1-sol 4 of 4 | [results](experiments/migration/RESULTS.md) |
| Real task 2: a web page judged by Sonnet | Claude Code with Haiku, Codex with gpt-6.1-sol | Swap confirmed all four predictions of the plan written before the runs. Cliff called a failed run unlucky, and a later rescoring of the same page confirmed it | [results](experiments/html/RESULTS.md) |
| Field test: two ideation skills compared | Claude Code 2.1.289 with Opus 5.5 | all 18 rooms read `tare: 0.00`, including a skill that started `claude -p` inside the room | not published |

## Open questions and ideas

- **Account email:** in a clean room the email reached the first request in 3 of 6 runs, which
  suggests a race with the loading of the account profile. tare declares it whenever it appears.
- **Reused config:** a separate but reused config directory once loaded connected accounts, while
  a fresh room never did. Cached account data is the suspected cause. Not tested.
- **Claude Code login renewal:** whether a renewal inside the room logs out the real session. Not
  tested, so tare avoids it.
- **Codex handoffs:** Codex can run several commands in one tool call, which makes its handoffs
  long.
- **Cost:** every tail is a full agent run, so a Cliff search or a Swap costs as much as its tails.
- **macOS:** a room built on Seatbelt (`sandbox-exec`), which Claude Code and Codex already use
  for their own sandboxes. Not built.
- **Other probes, not built:** weighing the first request's input tokens before and after adding
  junk to the real setup, and file tripwires that report which secret files a run opened.
- **Docker:** could contain files where bubblewrap is missing, but does nothing against context
  that comes with the login.
- **Copilot CLI:** checked once but not supported. Its `--available-tools` ignores an empty list
  without a warning, so only a list that names no real tool turns its tools off.

## Prior art

Checked on 2026-10-04.

- Multi-agent evaluation frameworks: UiPath/coder_eval (Claude Code, Codex, Antigravity,
  OpenCode and Pi, in a temporary directory or Docker), google/skill-reach (skill routing across
  Antigravity, Claude Code, Goose and Pi), mgechev/skillgrade (Docker and graders),
  `claude plugin eval` (A/B with and without a plugin). The documentation of coder_eval states
  that the caller provides a clean environment. None of them documents removing the agent's own
  user context or proving that it is gone.
- Isolation by hand inside test suites, for example setting `CODEX_HOME`, `HOME` and
  `CLAUDE_CONFIG_DIR` in a project's tests (hamza-aziz-ai/codex-claude-council PR #11).
- Fake model servers that could serve as a building block: Aetheria-LabsJP/puppetllm,
  CopilotKit/llmock, litellm's agent harness.
- Orchestrators that run several agent CLIs side by side (Google Scion, agent-manager) isolate
  processes, not user context.

tare is meant to sit underneath such frameworks. They run the evaluation, and tare provides the
clean room.

## Name

The command is `tare`. The package is called `tare-cli`, because `tare` is taken on PyPI and npm.

# Tare: concept

Zero the scale before you weigh. Tare starts a coding agent (Claude Code, Codex,
Gemini CLI, Antigravity, Pi) in a room where nothing of yours came along, and proves
it before the run. It prints `tare: 0.00`, or names every leak and where it came from,
and refuses to start the run until the reading is zero.

Status: `tare probe claude`, `tare claude`, `tare probe codex` and `tare codex` work on Linux
and WSL (2026-10-05; see the README). Written 2026-10-04 from a day of measurements; every
claim below marked *measured* was observed on WSL2 with Claude Code 2.1.289 or Codex CLI
0.160.0. The fake-model blank was tested for both on 2026-10-05
([Claude Code](experiments/dirty-twin/RESULTS.md), [Codex](experiments/dirty-twin-codex/RESULTS.md)).

## Why

Skill and agent evaluations compare runs with a skill against runs without it. If
the agent brings the developer's own instructions, memory, skills or connected
accounts into both runs, the comparison measures the developer's machine, not the
skill. Eval frameworks that drive several agent CLIs exist (see prior art), but they
assume the caller provides a clean runtime. Nothing checks that the room is clean.

## Three layers

### 1. Context: nothing of yours in front of the model

- Relocating the config directory (`CLAUDE_CONFIG_DIR`, `CODEX_HOME`) and `HOME`
  removes instructions, memory, plugins, hooks and user skills. This is what
  `claude-naked` and `codex-naked` in `AndreRatzenberger/codex-naked` do.
- **Measured:** the login brings context that lives in no config directory. With
  only the relocated config, a Claude Code session still had the account's connectors
  (mail, calendar, documents) as live tools, the account's skills, and the account
  email. `--strict-mcp-config` plus `--setting-sources project,local` removed the
  connectors and account skills. The email stays with subscription auth; only an
  API key without OAuth removes it.
- Codex: `CODEX_HOME` does not move `~/.agents/skills`, and account plugins can
  restore personal skills after login (handled in `codex-naked`).
- Claude Code's own bundled skills remain visible. They are part of the product,
  not of the user, and stay.

### 2. Containment: nothing of yours within reach

- **Measured:** with the context layer alone, any process in the session can still
  read the real `~/.claude/CLAUDE.md`, `~/.claude/.credentials.json`,
  `~/.codex/auth.json` and project `.env` files. An agent with shell access and
  bypassed permissions is one `cat` away. Agents under evaluation do look around:
  in a related experiment an agent read the evaluation harness's own scripts.
- **Measured:** `prototypes/bwrap-room.sh` (bubblewrap, user namespaces, no root)
  mounts an empty `/home`, then only the naked homes and one project directory.
  Claude Code starts, logs in and answers inside; the real files do not exist there.
  On WSL the resolver lives behind a symlink into `/mnt/wsl`, which must be mounted
  read-only or DNS fails.
- **Measured (2026-10-05):** the prototype passes the parent environment into the
  room: a secret-like variable from the calling shell was visible inside. The room needs
  `--clearenv` plus an allowlist. It also holds a usable login by construction, the
  copied credentials. A stale copy fails to refresh (`OAuth session expired`), so the
  copy must be taken fresh at every start, as `claude-naked` already does.
- macOS: the same idea with `sandbox-exec` (Seatbelt), which Claude Code and Codex
  already use for their own sandboxes. Untested.
- Fallback: Docker, where it is installed. It contains files but does nothing
  against the login-carried context of layer 1.

### 3. Proof: measured, not asked

- Asking the agent what it sees is a self-report, and it can refuse. **Measured:** a
  jailed Claude Code refused a scripted request to list the home directory and search
  for credential files, calling it reconnaissance. Correct behaviour, useless as a
  probe. The probe must not depend on the agent's cooperation or honesty.
- Reach can be checked by a plain script that runs inside the same room and tries
  the known paths.
- Context needs more. Three candidates, in order of promise:
  1. **Fake-model blank (lead).** Point the real CLI at a local fake model endpoint
     (base-URL options). The endpoint stores the full request, which is the context the
     harness actually assembled, and answers with scripted tool calls (list home, read
     known config paths, print env) that the agent's own executor runs under its real
     permission mode. A script cannot refuse. The idea is the extraction blank from
     analytical chemistry: run the whole procedure without a sample to see what the
     procedure itself brings in.
     **Kill criterion:** login-carried features (connectors, account skills, server-side
     memory) may not load against a fake endpoint, so the probe would report clean
     while the real run is dirty. Test that first with a deliberately dirty twin.
     **Measured (2026-10-05): for Claude Code the kill criterion does not hold.** Run with
     the real setup against the fake, the CLI still loaded connectors, account skills,
     plugin skills, hook output, global instructions, auto-memory and the email. Run
     inside the room, it loaded none of them except the email. One condition applies:
     a custom base URL suppresses tool search and inlines every tool schema, so probes
     set `ENABLE_TOOL_SEARCH=true` to see the context in its real form.
     [Results](experiments/dirty-twin/RESULTS.md).
  2. **Ballast weighing.** Record the provider-reported first-turn input tokens of a
     fixed prompt in the room. Inflate the real context surfaces with junk plus a
     reply canary, run again. Clean means identical counts and no canary. Needs
     temporary edits of real config, and run-to-run noise must stay below the
     smallest real leak.
  3. **Kernel tripwires on secrets.** Arm secret files (atime set before mtime so the
     next read updates it; on Linux also a file lease whose break signals an open).
     Afterwards, list which secrets were touched in the run window. Behaviour differs
     per filesystem and must be checked on each.

## Surface

```
tare claude [--yolo] [-- claude args]    # clean room, interactive or -p
tare codex | gemini | agy | pi
tare probe claude                        # tare: 0.00, or each leak with its source
```

`tare <agent>` runs the probe first and refuses to start when the reading is not zero
(`--allow-dirty` overrides and says so). "Supports agent X" means "probed clean on
OS Y", not "starts".

## Adapters (what each one has to know)

First four, in this order: Claude Code, Codex, Pi, Copilot CLI. All four were sealed and run
end to end on 2026-10-04 (WSL2); the notes below are measured unless marked otherwise.

| Agent | Context knobs | Login-carried leaks | Tools off | Context visible to a probe |
|---|---|---|---|---|
| Claude Code | `CLAUDE_CONFIG_DIR`, `HOME`, `--strict-mcp-config`, `--setting-sources project,local` | connectors, account skills, email | `--tools ""` | stream-json `system/init` lists tools, MCP servers, skills |
| Codex | `CODEX_HOME`, `HOME` (copy only `auth.json`), `--disable remote_plugin` | `~/.agents/skills` outside `CODEX_HOME`, account plugins | `-s read-only`, `-c web_search="disabled"` | `--json` events (messages, web searches, usage) |
| Pi | `PI_CODING_AGENT_DIR`, `HOME` (copy `auth.json`, `models.json`, a minimal `settings.json`), `--no-extensions --no-skills --no-context-files --no-session` | extensions and packages listed in `settings.json` | `--no-tools` | `--mode json` includes the system prompt, sectioned: a free context probe |
| Copilot CLI | `HOME` with a `.copilot/config.json` holding only the login keys, `--no-custom-instructions --disable-builtin-mcps --no-remote` | the real config also carries installed plugins and trusted folders | `--available-tools <a name that is no tool>` | `--output-format json` events |

Traps found while sealing them:

- **Copilot:** an empty `--available-tools` is ignored without a warning; the model kept every
  tool and used `bash` and `curl`. An allowlist naming no real tool works. Checked with a
  command that must fail to write a file, because the model's own list of its tools was wrong.
- **Pi:** with stdin left open it waits for piped input and never answers. Close stdin.
- **Claude Code:** relocating the config is not enough (connectors and account skills come
  with the login, see layer 1).
- **Codex as a probe target** (measured 2026-10-05, Codex 0.160.0):
  - `-c openai_base_url=<fake>/v1` keeps the ChatGPT login and reaches the fake. Without
    `--disable enable_request_compression` the body arrives compressed with zstd.
  - Codex tries a websocket five times (about 8 s) before it falls back to HTTPS.
    Overriding the built-in provider to stop that is refused.
  - The captured request holds more than `codex debug prompt-input`: the memories are
    missing from Codex's own rendering.
  - Memories load only when the user's `config.toml` enables `[features] memories`. The
    files alone do nothing.
  - Hooks did not fire in `exec` runs. The first request offered no tools from configured MCP
    servers. So the probe cannot see either class in the dirty twin. The room has no user
    `config.toml` or `hooks.json`, so neither can come in.
  - A fresh `CODEX_HOME` means Codex's defaults, including its default model. Pass `-m`
    when comparing runs.
- **Long prompts:** Linux caps a single argument near 128 KiB; Pi takes `@file`, Copilot takes
  piped stdin.

## Prior art (checked 2026-10-04)

- Multi-agent eval frameworks: UiPath/coder_eval (Claude Code, Codex, Antigravity,
  OpenCode, Pi; tempdir or Docker; states that the caller provides a clean runtime),
  google/skill-reach (skill routing across Antigravity, Claude Code, Goose, Pi),
  mgechev/skillgrade (Docker, graders), `claude plugin eval` (A/B with and without a
  plugin). None documents removing the agent's own user context or proving it is gone.
- Hand-rolled isolation inside test suites, e.g. setting `CODEX_HOME`, `HOME` and
  `CLAUDE_CONFIG_DIR` in a project's tests (hamza-aziz-ai/codex-claude-council PR #11).
- Fake model servers usable as a building block: Aetheria-LabsJP/puppetllm,
  CopilotKit/llmock, litellm's agent harness.
- Orchestrators that run several agent CLIs side by side (Google Scion, agent-manager)
  isolate processes, not user context.

Tare is meant to sit underneath such frameworks: their exam, Tare's clean room.

## Next steps, in order

1. ~~Dirty-twin test for the fake-model blank~~. Done 2026-10-05: the blank works for
   Claude Code ([results](experiments/dirty-twin/RESULTS.md)).
2. ~~`tare claude`~~. Done 2026-10-05 (v0.1.0).
   **What it does:**
   - fresh credential copy per room, refused when the login would need a refresh;
   - cleared environment with an allowlist;
   - reach probe as a script;
   - context probe through the fake, with the dirty twin as control;
   - `ENABLE_TOOL_SEARCH=true` in both probe and run.

   **Measured on this machine:**
   - The clean room read `tare: 0.00`, and the control saw all seven classes.
   - A spike room was given the user's CLAUDE.md, one skill and an environment variable,
     and was run without the context flags. It read 4 leaks, each with its source.
   - Dropping only the flags is not enough to make a room dirty: a fresh room loaded
     no connectors either way.
   - With the flags, user-level CLAUDE.md and skills that were planted in the room's
     config are not loaded at all. `--setting-sources project,local` is a second line
     of defense.

   **Open:**
   - Yesterday a relocated but reused config did load connectors, while a fresh room
     does not. Cached account features are the suspected cause; this has not been
     tested.
   - The account email reached the first request in 3 of 6 clean-room runs, which
     points to a race with the profile fetch. It is declared whenever it is seen.
   - Not tested: whether a refresh inside the room rotates the token family of the
     real session.
3. ~~Codex adapter~~. Done 2026-10-05: `tare probe codex` and `tare codex`. The probe reads
   `tare: 0.00` on a clean room. A planted room (AGENTS.md, memories with the feature on, a
   skill in each skill directory, an environment variable) read 6 leaks, each with its source.
4. Seatbelt profile for macOS.
5. ~~Bring the `claude-naked` connector fix in~~. `tare claude` carries its own context
   layer (fresh config plus the flags). The fix stays useful for `claude-naked` itself:
   `f61aff7` on `fix/remote-plugin-isolation` in `codex-naked`, pushed, not merged.
6. ~~Cliff~~. Done 2026-10-05 for Claude Code (`tare cliff claude`).
   - **Capsules:** a `PostToolUse` hook from `--settings` archives the workspace after every
     tool call, and it fires with the room flags in place.
   - **Tails:** each tail resumes the transcript cut after that step's tool result.
   - **Measured:**
     - Scripted run against a model whose cliff is known: the search found step 4 with
       separated intervals in 18 tails.
     - Real model: a recorded run resumed from step 1, and the backend accepted the cut
       transcript.
   - **Open:**
     - Cliff for Codex, which resumes differently.
     - The cost of real searches: every tail is a full agent run.
7. ~~Swap~~. Done 2026-10-05 (`tare swap`), for Claude Code and Codex.
   - **The trail:** one neutral record of a run (task, messages, tool calls, results), and one
     renderer that turns any prefix of it into a handoff prompt. Each agent continues a
     capsule by handoff, so no agent ever writes another agent's session format. A new agent
     needs three things: a snapshot hook, a translation of its session into the trail, and a
     way to start a session with a prompt.
   - **Codex specifics:**
     - It takes the `PostToolUse` hook from the room's `hooks.json`, but only with
       `--dangerously-bypass-hook-trust`.
     - In code mode one model call (`exec`) runs several commands; a step carries the
       commands' ids.
   - **Measured:**
     - Scripted models with a known truth: null check passed; blame passed from the model
       to the room between cut 0 and cut 0.5, as built.
     - Real Claude Code (haiku) against real Codex on a small task: both ran, and each
       continued the other's room. Every cell passed, so there was no effect to find.
   - **Open:** Codex's code-mode calls are verbose in a handoff.
8. ~~Every agent in Cliff and Swap~~. Done 2026-10-05.
   - Cliff continues by handoff where an agent has no native resume.
   - Codex resumes natively: a rollout cut after a step, placed under the room's
     `sessions/` with the session id at the end of its file name, continues with
     `codex exec resume <id>`.
   - **Measured:** the resumed thread kept the original id, and from step 1 it finished the
     remaining plan. Swap now has native cells for both agents.
9. ~~Live dashboard and recipes~~. Done 2026-10-05 (epic #39).
   - **The run directory is the source of truth:** the journal, the recipe, and the agents'
     live output. So `tare watch` shows a finished run the same way as a live one.
   - **Recipes** keep the command, the project digest and the CLI versions. `tare rerun`
     repeats a run and names what changed.
10. ~~Pi~~. Done 2026-10-05 (`tare probe pi`, `tare pi`, Cliff and Swap).
    - **Probe:** Pi has no base-URL variable. The fake is reached through a provider of its own
      (`tare`, api `anthropic-messages`), added to a copy of the agent directory for the dirty
      twin and to the room's own.
    - **Room:** no flags, because a fresh agent directory without the user's parent
      directories is clean and keeps the project's AGENTS.md. `--no-context-files` would drop
      it ([results](experiments/dirty-twin-pi/RESULTS.md)).
    - **Extensions:** extension tools are found as the dirty twin's tools that a room run with
      `--no-extensions` does not offer.
    - **Capsules:** a small extension hands every top-level tool call to the snapshot hook.
      Sessions resume with `--session`.
    - **Measured:**
      - The clean room read 0.00.
      - A room planted with the user's extension package and an environment variable read 5
        leaks, each with its source.
      - A real run (zai) recorded three capsules and continued from step 1 both natively and
        by handoff.
    - **Also measured, for every agent:** instruction files in the project's parent
      directories are their own class now. Claude Code's print mode, which the probe uses, did
      not load `~/AGENTS.md`; Pi loaded it. So the probe vouches for print mode only. A room
      has no parent directories, so the class cannot leak into one.
11. Gemini CLI (epic #34), paused until the machine's Google login is renewed.
12. ~~Calibrate before you search~~. Done 2026-10-05 (epic #52).
    - `tare calibrate` gives fresh-start pass rates per side.
    - Cliff samples the baseline until a model gap is clear (upper bound below 0.2).
    - Swap reports a tie as a tie.
    - **Measured** on the migration task: Haiku passed 0/4 and Codex with gpt-6.1-sol passed
      4/4. Across all runs so far, Haiku passed about 1 in 14.

## Name

`tare`: zero the scale before measuring. The command is `tare`; the package name will
need a suffix (`tare-cli`), because `tare` is taken on PyPI and npm.

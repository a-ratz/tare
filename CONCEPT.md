# Tare: concept

Zero the scale before you weigh. Tare starts a coding agent (Claude Code, Codex,
Gemini CLI, Antigravity, Pi) in a room where nothing of yours came along, and proves
it before the run. It prints `tare: 0.00`, or names every leak and where it came from,
and refuses to start the run until the reading is zero.

Status: concept plus one working prototype (`prototypes/bwrap-room.sh`). Written
2026-10-04 from a day of measurements; every claim below marked *measured* was
observed on WSL2 with Claude Code 2.1.289.

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

1. **Dirty-twin test for the fake-model blank** on Claude Code: real login, fake base
   URL. Do connectors and account skills appear in the captured request? The answer
   decides the probe design.
2. Turn the bwrap prototype into `tare claude` with a reach probe that is a script,
   not an agent.
3. Codex adapter on the same pattern.
4. Seatbelt profile for macOS.
5. Bring the `claude-naked` connector fix (v0.2.0, uncommitted in the `codex-naked`
   working tree) in as the Claude adapter's context layer.

## Name

`tare`: zero the scale before measuring. The command is `tare`; the package name will
need a suffix (`tare-cli`), because `tare` is taken on PyPI and npm.

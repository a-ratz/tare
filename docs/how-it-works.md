# How it works

[← Documentation](README.md)

A probe has three parts, and none of them asks the agent anything.

1. **The agent in the room.** The real agent runs inside the room against a fake model server,
   which keeps the request that it receives. That request is the context the agent was given.
2. **The dirty twin.** The same agent runs in your real setup, against a fake server too, so
   tare knows that it can see your setup at all. If it cannot, the reading is
   `tare: not proven (blind)` instead of a clean room that proves nothing.
3. **The reach script.** A plain script inside the room looks for your files and for secret
   environment variables. The same script runs outside as the control.

[Reading a probe](probe.md) shows what the three parts produce.

## Why a separate config directory is not enough

A separate config directory (`CLAUDE_CONFIG_DIR` for Claude Code, `CODEX_HOME` for Codex) does not
give a clean run. With Claude Code, the login alone brings your connected accounts (mail,
calendar, documents), your account's skills and your email address into the session. Evaluation
frameworks that drive agent CLIs, such as UiPath's coder_eval, leave it to you to provide a clean
environment, and none of them checks it.

## Further reading

- [CONCEPT.md](../CONCEPT.md): the design and the measurements behind it
- The dirty-twin experiments that decided the probe design:
  [Claude Code](../experiments/dirty-twin/RESULTS.md),
  [Codex](../experiments/dirty-twin-codex/RESULTS.md),
  [Pi](../experiments/dirty-twin-pi/RESULTS.md),
  [Antigravity CLI](../experiments/dirty-twin-agy/RESULTS.md),
  [the three agents on macOS](../experiments/dirty-twin-macos/RESULTS.md)

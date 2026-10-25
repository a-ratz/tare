# Install

[← Documentation](README.md)

tare runs on Linux, WSL2 and macOS. It needs a way to build rooms and at least one logged-in
agent.

## Requirements

| Requirement | Notes |
|---|---|
| Linux or WSL2, or macOS | on Linux tare builds the room with user namespaces, on macOS with Seatbelt (`sandbox-exec`, part of macOS). On macOS the project must be on an APFS volume for the room's copy to be instant; elsewhere tare copies it in full. |
| [bubblewrap](https://github.com/containers/bubblewrap), Linux and WSL only | `sudo apt install bubblewrap` |
| at least one of the agents | on `PATH` and logged in. On Linux, Codex must resolve to a path under `/usr` for now, because tare mounts Codex's npm package and Node.js from there. If `which codex` points elsewhere, for example into nvm, install it with the system's npm (`sudo npm install -g @openai/codex`) and put `/usr/bin` first on `PATH`. The other agents, and every agent on macOS, can live anywhere on `PATH`. On macOS, Claude Code keeps its login in the Keychain: tare reads it there the way Claude Code does and gives the room a copy. |
| a Chromium browser, only for `tare judge` | Linux: `google-chrome` on `PATH`, installed under `/usr` or `/opt`. macOS: Google Chrome, Chromium or Microsoft Edge in `/Applications`. `tare judge` scores web pages and takes their screenshots with it. |
| [uv](https://docs.astral.sh/uv/) or [pipx](https://pipx.pypa.io/) | Python 3.11 or newer |

The agents tare knows are Claude Code, Codex, Pi
([`@earendil-works/pi-coding-agent`](https://www.npmjs.com/package/@earendil-works/pi-coding-agent))
and Google's Antigravity CLI (`agy`). On macOS it works with Claude Code, Codex and Pi; the
Antigravity CLI stops with a message there for now, because its dirty twin needs an overlay over
`~/.gemini` that macOS does not have.

## From PyPI

The package is `tare-cli`, the command is `tare`:

```bash
uv tool install tare-cli   # or: pipx install tare-cli
```

## From a checkout

To work on tare itself, clone the repository and run it from the checkout with `uv run tare ...`:

```bash
git clone https://github.com/a-ratz/tare.git && cd tare
uv run tare --version
```

Next: [the words tare uses](words.md), then [your first probe](probe.md).

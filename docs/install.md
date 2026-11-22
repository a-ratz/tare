# Install

[← Documentation](README.md)

tare runs on Linux, WSL2 and macOS. It needs a way to build rooms and at least one logged-in
agent.

## Requirements

| Requirement | Notes |
|---|---|
| Linux or WSL2, or macOS | on Linux tare builds the room with user namespaces, on macOS with Seatbelt (`sandbox-exec`, part of macOS). Where `/etc/resolv.conf` is a link into `/run` (systemd-resolved, NetworkManager), the room gets the one file the link names, so host names resolve in the room as on the host. On macOS the project must be on an APFS volume for the room's copy to be instant; elsewhere tare copies it in full. |
| [bubblewrap](https://github.com/containers/bubblewrap), Linux and WSL only | `sudo apt install bubblewrap` |
| at least one of the agents | on `PATH` and logged in. On Linux, Codex must resolve to a path under `/usr` for now, because tare mounts Codex's npm package and Node.js from there. If `which codex` points elsewhere, for example into nvm, install it with the system's npm (`sudo npm install -g @openai/codex`) and put `/usr/bin` first on `PATH`. The other agents, and every agent on macOS, can live anywhere on `PATH`. An agent installed through [mise](https://mise.jdx.dev/) is found behind its shim. On macOS, Claude Code keeps its login in the Keychain: tare reads it there the way Claude Code does and gives the room a copy. |
| a Chromium browser, only for `tare judge` | Linux: `google-chrome` on `PATH`, installed under `/usr` or `/opt`. macOS: Google Chrome, Chromium or Microsoft Edge in `/Applications`. `tare judge` scores web pages and takes their screenshots with it. |
| [uv](https://docs.astral.sh/uv/) or [pipx](https://pipx.pypa.io/) | Python 3.11 or newer |

The agents tare knows are Claude Code, Codex, Pi
([`@earendil-works/pi-coding-agent`](https://www.npmjs.com/package/@earendil-works/pi-coding-agent))
Google's Antigravity CLI (`agy`) and the GitHub Copilot CLI (`copilot`). On macOS it works with
Claude Code, Codex, Pi and the Copilot CLI; the Antigravity CLI stops with a message there for now,
because its control run needs an overlay over `~/.gemini` that macOS does not have. The Copilot
CLI has not been tested on Linux yet. tare runs its native executable (the install script or
Homebrew), not the npm package, and copies its login for the account `copilot` last logged in
with: from `COPILOT_GITHUB_TOKEN`, `GH_TOKEN` or `GITHUB_TOKEN`, else from the gh CLI logged in as
the same account, else from Copilot's Keychain item, which macOS asks you about once.

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

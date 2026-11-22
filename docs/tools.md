# Tools in a room

[← Documentation](README.md) · [Running agents in rooms](running-agents.md)

A task often needs more than the agent: Node.js, a package, a browser to look at the page it
built. The room has none of yours. This page says what it has, how an agent installs the rest, and
what a browser needs in a room.

## What the room has

- **`PATH`** holds the agent's own CLI, `/usr/bin` and `/bin`. On macOS it also holds the active
  developer directory's `usr/bin` (from `xcode-select -p`), so `git`, `python3`, `make` and `pip3`
  run as themselves. Nothing else from your `PATH` comes along: no Homebrew, no `~/.local/bin`, no
  nvm, no uv. That is the point of the room: an evaluation must not depend on what your machine
  happens to have installed.
- **The network is open.** An agent installs what a task needs into the room's home, for example
  Node.js from its tarball and then packages with `npm install -g`, which go into that Node.js
  folder in the home.
- **Writes stay in the room.** The agent can write its home, the project and its temporary
  directory, and nothing else: a `brew install` or a write to `/Applications` fails in the room
  instead of changing your machine. On Linux the room mounts only these writable. On macOS the
  profile denies every other write, `/tmp` included: there the temporary directory is `$TMPDIR`,
  inside the room. Agents often try `/tmp` first, get `Operation not permitted`, and move on to
  `$TMPDIR`.
- **Nothing installed lasts.** The home is new for every run and removed after it. Only the
  project keeps the run's changes, so a tool the next run should find belongs in the project, or the
  next run installs it again.

**Measured** on macOS 27.0.1 with tare's room (one fresh room each, from a home network):

| Install in the room | Took |
|---|---|
| Node.js 22.23.2 from its tarball into the home | 5 s |
| `npm install -g agent-browser@0.39.2` | 2 s |
| `agent-browser install` (Chrome for Testing 158, 191 MB) | 9 s |
| `npm install playwright@1.57.0` and `npx playwright install chromium` | 19 s |

## A browser in a room

agent-browser, Playwright and Puppeteer drive Chromium. Two things about a room stop it, and tare
handles both in a macOS room:

- **Its temporary directory.** On macOS, Chromium ignores `TMPDIR` and takes your temporary
  directory under `/var/folders`, which the room denies (other programs keep their files there).
  Chrome then stops at once with `Failed to create a ProcessSingleton for your profile directory`
  (exit code 21). tare sets `MAC_CHROMIUM_TMPDIR`, which Chromium reads instead, to the room's
  temporary directory.
- **Its own sandbox.** Chromium starts its helper processes in a sandbox of their own. On macOS
  that is a Seatbelt profile, and no Seatbelt profile can start inside the room's
  (`sandbox_apply: Operation not permitted`), so the browser has to run with `--no-sandbox`.
  tare sets `AGENT_BROWSER_ARGS=--no-sandbox`, which agent-browser passes to the browser.
  Playwright passes `--no-sandbox` by default. With Puppeteer, or a Chrome you start yourself,
  pass it yourself.

**Measured** on macOS 27.0.1 with agent-browser 0.39.2 and Chrome for Testing 158, one fresh room
for each variant: the page opened only with both settings. Pointing the home directory elsewhere
(`CFFIXED_USER_HOME`) made no difference. Playwright 1.57 opened the page with its default
headless shell without either setting, and with its full Chromium only with
`MAC_CHROMIUM_TMPDIR`. A Linux room has not been measured with a browser yet.

**Measured** with Claude Code 2.1.330 and Sonnet, two runs on each side, the same task: open
`page.html` with agent-browser, save a screenshot, write down the heading that the page's script
sets. With tare 0.5.0, both runs installed Node.js and agent-browser, then failed on Chrome: the
error names the denied profile path under the real home, so the agent looked there, tried other
profile and launch flags, and gave up after 9 and 11 tool calls. With both settings in the room,
both runs passed after 6 and 7 tool calls; the browser started on the first try.

`tare judge` starts its own Chrome in a room the same way ([Judge](judge.md)).

## Developer tools on macOS

`/usr/bin/git`, `/usr/bin/python3` and the other developer tools in `/usr/bin` are shims that ask
xcrun for the real tool, and xcrun keeps its cache in your temporary directory, which the room
denies. Each call through a shim prints two lines such as

```
git: error: couldn't create cache file '/var/folders/…/T/xcrun_db-…' (errno=Operation not permitted)
```

and then runs the tool. That is why the room's `PATH` has the developer directory's `usr/bin`
before `/usr/bin`. The tools of the toolchain (`clang`, `swift`) are not in that directory, so they
still print the lines; the tool still runs.

## What this does not change

The room keeps your setup out of a measurement. It is not a security boundary against a hostile
agent ([Running agents in rooms](running-agents.md#what-the-room-keeps-out)): outside the places
it denies, the room can still read your disk.

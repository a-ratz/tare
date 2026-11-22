# Running agents in rooms

[← Documentation](README.md)

Every agent command probes the room first and starts the agent only on `tare: 0.00`, unless you
pass `--allow-dirty`. This page lists the commands and flags, what they return, and what the room
keeps out.

## Commands

```bash
tare probe claude                  # probe the room: tare: 0.00, the leaks and their sources, or blind
tare claude                        # probe, then start Claude Code in the room
tare claude -- -p "fix the tests"  # arguments after -- go to claude
tare claude --yolo                 # skip the agent's permission prompts
tare claude --allow-dirty          # start even though the reading is not tare: 0.00
tare claude --project ../other     # another project directory (default: the current one)
tare claude --continue             # a fresh room that resumes this project's last session
tare cleanup                       # remove leftover rooms and the kept sessions (--dry-run lists them)

tare probe codex                   # the same for Codex, Pi and the Antigravity CLI
tare codex -- exec -m MODEL "..."  # one-shot Codex run: arguments after -- go to codex
tare pi                            # Pi in a room
tare agy                           # the Antigravity CLI in a room
tare prices update                 # fetch the price table for costs an agent does not report
```

`tare claude`, `tare codex`, `tare pi` and `tare agy` mount your project at `/work` directly. The
agent changes your real files, as it would outside the room. On macOS the room works on a clone
of your project instead, and the agent's changes are copied back when it exits; sockets and pipes
it left in the project are not copied. When the room closes, tare ends your
processes whose command line names a path in the room or whose working directory is in it: a
browser the agent installed there, a server it started in the project. Unlike on Linux, where
everything of a room ends with it, a process that does neither is not found: a daemon that left the
room's folders and runs a program from elsewhere, or by a bare name, or renamed itself, and anything
started after tare looked. A process of yours that names the room, such as `tail -f` on one of its
files, is ended too. If the run's changes cannot be copied back, tare keeps the clone that holds
them, removes the rest of the room with the login copy, and says where the clone is. `--yolo` adds the agent's own flag
for skipping permission prompts. Pi has no such prompts. The [measuring tools](measuring.md) work
on copies instead.

All your arguments after `--` go to the agent. Interactive or one-shot, the agent runs as it does
outside tare.

Input or output that you redirect to a file reaches the agent through a pipe: Node.js agents (Pi,
the Copilot CLI) stop at start when one of these is a file in a place the room denies, which your
home is (#172). For an input file, tare reads it all into the agent's pipe, whether the agent reads
it or not.

## Exit codes

`tare probe` exits with 0 on `tare: 0.00` and with 1 otherwise. `tare claude` and the other agent
commands refuse to start with exit code 1 unless the reading is `tare: 0.00` or you pass
`--allow-dirty`. When they start, they return the agent's own exit code.

## The agent's defaults, not yours

The room starts with the agent's defaults, not with your settings. Codex, for example, runs its
default model unless you pass `-m`. Set the model explicitly when you compare runs.

## What the room keeps out

Your home directory, the credentials of your other tools and the secret environment variables of
your shell do not exist inside the room. The probe checks this before every run with a plain
script that looks for them ([Reading a probe](probe.md)).

The room is not a security boundary against a hostile agent: it has network access and a working
login. tare keeps your setup out of a measurement. It does not contain an agent that tries to
break out.

None of your tools are in the room either. The agent installs what a task needs into the room's
home, and the install is gone after the run ([Tools in a room](tools.md)).

## Continuing a session

A room's home, with the agent's session in it, is removed when the room closes. Before that, tare
copies the agent's latest session out, whatever ended it: the agent exited or crashed, or the
terminal closed. It says where:

```text
tare: session kept in ~/.local/state/tare/sessions/claude/<project>; `tare claude --continue` resumes it
```

`tare claude --continue` probes as always, opens a fresh room, puts the project's latest kept
session into it where the agent keeps its sessions, and starts the agent resuming it: Claude Code
with `--resume`, Codex with `resume`, Pi with `--session`. Your arguments after `--` follow. The
continued room holds the earlier conversation because you asked for it; the probe reads the room
before it is placed. The Antigravity CLI cannot continue a session yet; tare says so and starts
nothing.

Kept sessions stay until you remove them, in folders only you can read: a session holds the whole
conversation. `tare cleanup` removes them, and the rooms that no running tare holds any more (a
room tare could not remove, for example after a crash, holds a copy of your login). Each tare holds
a lock on its room from the room's making until it is gone, and `tare cleanup` takes only rooms
whose lock is free and that no running process names or works in. A room of tare 0.5.0 or older has
no lock; `tare cleanup` takes it only when it holds what a tare room holds and nothing in it changed
for a day. Any other folder named `tare-room-*` is left alone. Half-written copies of a session that
a killed tare left go too. `tare cleanup --dry-run` lists what it would remove.

**Measured** on macOS 27.0.1 with Claude Code 2.1.330 and Haiku: a first room was told a code word
and closed; `tare claude --continue -- -p "What was the code word I gave you?"` in a second room
answered with it. Codex and Pi are covered by tests only: where tare puts their session (with its
working directory set to the new room, which they work in) and which arguments resume it, not a real
resumed run. For Codex tare keeps the rollout written last, which after a session with subagents
can be a subagent's.

## When a room's login stops working

A long session can outlive its room's copy of the login: the copy runs out, or a new login outside
tare replaces it. Claude Code in the room then says it is logged out, and `/login` cannot help: a
room cannot reach your Keychain, so the login cannot be saved there. On macOS a dialog says the
keychain cannot be found; click **Cancel**, never **Reset To Defaults**, which would set up a new
default keychain on your Mac. Then exit the agent; the session is kept, and `tare claude
--continue` resumes it in a fresh room with a fresh copy of your login (#193).

## Your login

Each room gets a fresh copy of your login, which tare deletes after the run. Claude Code may
replace its login token when it renews it, which could log you out outside tare. That has not
been tested, so tare starts a room only while your login token holds for at least another hour,
and the room never has to renew its copy.

Claude Code renews the token only in its last few minutes, so starting it outside tare does not
help before then. The refusal names the time after which it does:

```text
tare: the claude login token expires in 48 min, at 02:04 CET: to renew it, start claude outside tare after 02:04 CET, then retry; a run that ends well before then can start now with TARE_MIN_LOGIN_MINUTES=48 or less
```

A run that ends sooner can start anyway with `TARE_MIN_LOGIN_MINUTES` (whole minutes, at least
10):

```bash
TARE_MIN_LOGIN_MINUTES=15 tare claude -- -p "fix the tests"   # a short run: 15 minutes are enough
```

Pick the run's length plus ten minutes, so the run ends before the copy needs renewal. With an
API key instead of a login there is nothing to renew; that setup is untested.

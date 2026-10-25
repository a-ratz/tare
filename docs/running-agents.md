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

tare probe codex                   # the same for Codex, Pi and the Antigravity CLI
tare codex -- exec -m MODEL "..."  # one-shot Codex run: arguments after -- go to codex
tare pi                            # Pi in a room
tare agy                           # the Antigravity CLI in a room
tare prices update                 # fetch the price table for costs an agent does not report
```

`tare claude`, `tare codex`, `tare pi` and `tare agy` mount your project at `/work` directly. The
agent changes your real files, as it would outside the room. `--yolo` adds the agent's own flag
for skipping permission prompts. Pi has no such prompts. The [measuring tools](measuring.md) work
on copies instead.

All your arguments after `--` go to the agent. Interactive or one-shot, the agent runs as it does
outside tare.

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

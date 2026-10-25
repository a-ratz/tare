# Reading a probe

[← Documentation](README.md)

Before an agent starts, tare probes its room. The probe makes no paid model calls: the real agent
talks to a fake model server on your machine, which keeps the request. This page walks through a
reading line by line.

## A clean room

```bash
tare probe claude
```

```text
tare probe · claude 2.1.289 · /home/me/tare
  control   dirty twin shows: instructions, home path, mcp, skills, plugins, email, reach
  leaks     none
  declared
    email        account email                                subscription login
    credentials  /home/tare/.claude-config/.credentials.json  copy of the login, needed by the CLI
tare: 0.00
```

This is the output of a real run, with only the home path shortened. Line by line:

- `control` lists the kinds of context that the dirty twin found in your real setup. The probe
  could therefore have seen each of them in the room. Connected accounts count under `mcp`,
  because they reach the agent as MCP tools. `home path` means that your real home path appears
  in the agent's request, for example in the path of a memory file. `reach` comes from a plain
  script that looks for your files. It finds them outside the room, which shows that the script
  works. So when it finds nothing inside the room, that result can be trusted.
- `leaks none` says that none of these reached the room. Inside the room, tare starts Claude Code
  with flags that keep connected accounts and account skills out.
- `declared` lists the two things that the room holds on purpose. With a subscription login, your
  account email arrives with the login, and tare cannot remove it without removing the login. It
  is one line of text that names you, not instructions, memories or tools. So tare reports it
  and lets the run start. The room also holds a copy of your login, because the agent needs one
  to run.

`tare claude` then starts Claude Code in that room. `tare codex`, `tare pi` and `tare agy` do the
same for the other agents ([Running agents in rooms](running-agents.md)).

## What the probe measures

tare does not ask the agent about its context. It records the request that the agent sends to its
model. An agent asked about its own context can refuse or be wrong.

## The dirty twin

For the dirty twin, the probe starts your real agent with your real setup, so your hooks and MCP
servers start too. The Antigravity CLI writes into its config directory on every run, so tare
lets its dirty twin write into a temporary overlay that is discarded after the run. Your
`~/.gemini` stays unchanged.

## A room with leaks

When a room is not clean, the reading names each leak and where it came from. The excerpt below
shows a room that was given copies of real settings on purpose, with the home path shortened.

```text
  leaks
    instructions global instructions     /home/me/.claude/CLAUDE.md
    home path    /home/me/               your files
    skills       1 skill                 /home/me/.claude/skills
    env          SPIKE_API_KEY           inherited environment
tare: 4 leaks
```

The agent does not start, unless you pass `--allow-dirty` ([Running agents in rooms](running-agents.md)).

## A blind probe

tare looks at your files to learn what your setup holds, for example a global instructions file
or installed skills. If the dirty twin's request lacks one of these, the probe could not see it.
A clean room would then prove nothing. tare runs the dirty twin once more, and if that kind of
context is still missing, the reading is `tare: not proven (blind)`.

Next: [how the probe is built](how-it-works.md), or [measuring agents](measuring.md).

# tare

Zero the scale before you weigh: start a coding agent in a room where nothing of
yours came along, and prove it before the run.

Early stage. [CONCEPT.md](CONCEPT.md) has the design, the measurements behind it and
the next steps.

## Use

Linux or WSL, Claude Code with a subscription login, and
[bubblewrap](https://github.com/containers/bubblewrap) installed. From a checkout:

```
uv run tare probe claude              # measure the room: tare: 0.00, or every leak and its source
uv run tare claude                    # probe, then start Claude Code in the room (interactive)
uv run tare claude -- -p "..."        # arguments after -- go to claude
uv run tare claude --yolo             # adds --dangerously-skip-permissions
uv run tare claude --allow-dirty      # start even though the reading is not zero
```

`--project DIR` selects the project directory (default: the current one). Inside the
room it is `/work`, the home directory is `/home/tare`, and nothing else of yours
exists there.

```
tare probe · claude 2.1.289 · /home/me/project
  control   dirty twin shows: instructions, home path, mcp, skills, plugins, email, reach
  leaks     none
  declared
    email        account email                                subscription login
    credentials  /home/tare/.claude-config/.credentials.json  copy of the login, needed by the CLI
tare: 0.00
```

The probe takes three readings, and none of them asks the agent anything:

- **Context.** The real CLI runs inside the room against a local fake model endpoint,
  which keeps the request: the context the harness actually assembled.
- **Control.** The same run in your real setup (the dirty twin). The probe has to find
  your context there, or it reports itself blind.
- **Reach.** A plain script looks for your files and inherited environment variables
  inside the room. The same script outside the room is its control.

There are two declared residuals; they appear in the reading but do not block the run.
With subscription auth, the account email arrives with the login. The room also holds
a fresh copy of the login, because the CLI needs one; the copy is removed afterwards.

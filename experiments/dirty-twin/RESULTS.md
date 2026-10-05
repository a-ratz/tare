# Dirty-twin test: results

Ran on 2026-10-05 on WSL2 with Claude Code 2.1.289 and the model `claude-opus-5-5`. The
plan was fixed beforehand ([PLAN.md](PLAN.md), commit `c93c54e`). Raw runs stay local
in `runs/`, which is not committed: they contain the full context of a real setup.

## Verdict

**The kill criterion did not hold.** Against the fake endpoint, the real CLI assembled the
login-carried context too: connectors, account skills and the email. The fake-model
blank becomes Tare's context probe for Claude Code, and the dirty twin becomes its
positive control. There is one condition: set `ENABLE_TOOL_SEARCH=true`. Otherwise a
custom base URL changes the *form* of the context, though not its content (see P3).

## Predictions

| | Prediction | Outcome |
|---|---|---|
| P1 | T0 completes its loop against the fake | **held.** Two requests to `/v1/messages`; the scripted Bash call executed; the tool result came back; exit 0. No other path was requested. |
| P2 | T0 contains M1 to M8 | **held.** All eight. |
| P3 | T0's offered tools equal R0's `system/init` tools | **failed as worded; the kill criterion was not met.** Every connector, MCP and plugin tool matched, and so did skills (189) and plugins (18). Two differences remained. (a) `system/init` calls a tool `Task` that the request names `Agent`; the tool is the same. (b) `ToolSearch` was missing, because with a custom base URL Claude Code suppresses tool search and sends every MCP schema inline instead of deferring it. A post-hoc rerun with `ENABLE_TOOL_SEARCH=true` (not pre-registered) restored R0's init exactly (111 tools including `ToolSearch`), with deferred loading on the wire. All eight markers were again present. |
| P4 | T1 contains none of M1 to M7, and M8 (email) is present | **held.** |
| P5 | Reach: T0 all `REACH`, T1 all `absent`; parent shell secrets visible in the room | **held.** T0 reached all six paths. In T1 all six were absent. Inside the room the name of an API-key variable from the parent shell was visible, because `bwrap-room.sh` does not clear the environment. |

The only other variable name seen was `CLAUDE_CODE_MESSAGING_TOKEN`. It belongs to the
CLI under test: `run.sh` removes all `CLAUDE*` variables before starting.

## Tare's first reading (T1)

```
markers   M1-M7 absent, M8 (account email) present
reach     6/6 real paths absent
env       1 inherited secret-like variable (an API key)
remaining 19 bundled skills, 3 bundled plugins (cc-plugin-agents-md,
          cc-plugin-telemetry, cc-plugin-plugin-authoring): product, not user
```

So the room is not at zero yet. It has two leaks, both with a known source: the email
(it comes with subscription auth) and the inherited environment (the prototype does not
clear it). The dirty twin shows that the probe can see these classes of leak.

## Found along the way

- **The credential copy went stale.** The first T1 attempt failed with
  `OAuth session expired and could not be refreshed`. The naked copy from the day before
  held no refresh token and an expiry of 0. The prototype uses whatever copy exists;
  `claude-naked` copies fresh on every start. Copying fresh fixed it. Not tested: whether
  a refresh inside the room rotates the token family and logs out the real session.
- **The room holds a usable login by construction.** The CLI needs one, so
  `/home/naked/.claude-config/.credentials.json` is readable by the agent. The reach
  probe checks only the real paths. Holding auth outside the room (a proxy that adds the
  header) would remove this residual.
- **A custom base URL suppresses tool search.** Claude Code's own help text says this,
  and the T0 init shows it. Any probe that compares token counts or the layout of the
  context must set `ENABLE_TOOL_SEARCH=true`, or it measures a different context.

## Reproduce

```
experiments/dirty-twin/run.sh r0      # real API, reference
experiments/dirty-twin/run.sh t0      # dirty twin against the fake
experiments/dirty-twin/run.sh t1      # room against the fake (fresh credential copy first)
ENABLE_TOOL_SEARCH=true experiments/dirty-twin/run.sh t0   # post-hoc variant
uv run experiments/dirty-twin/check.py experiments/dirty-twin/markers.local.json \
  --ref experiments/dirty-twin/runs/r0 experiments/dirty-twin/runs/t0 experiments/dirty-twin/runs/t1
```

`markers.local.json` holds the marker strings. Their hashes are in PLAN.md.

# Dirty-twin test for Codex: results

Ran on 2026-10-05 on WSL2 with Codex CLI 0.160.0 and a ChatGPT login. The plan was fixed
beforehand ([PLAN.md](PLAN.md), commit `38db09e`). Raw runs stay local in `runs/`.

## Verdict

**The fake endpoint is Codex's context probe.** The request it receives holds everything
`codex debug prompt-input` shows, and more: the memories. The room removes every marker of
the user's setup. `--disable remote_plugin` made no difference in a fresh room. It stays in
the room flags as a guard. MCP was not measured: K6 matched only a sentence in the global
AGENTS.md, not an offered tool (see below).

## Markers

| Run | K1 instructions | K2 hook | K3 memories | K4 skill | K5 `.agents` skill | K6 MCP | K7 home path | K8 bundled skill |
|---|---|---|---|---|---|---|---|---|
| R0 `debug prompt-input` | yes | no | **no** | yes | yes | yes | yes | yes |
| T0 dirty twin → fake | yes | no | yes | yes | yes | yes | yes | yes |
| T1 room → fake | no | no | no | no | no | no | no | yes |
| T1b room without `--disable remote_plugin` | no | no | no | no | no | no | no | yes |

## Predictions

| | Prediction | Outcome |
|---|---|---|
| P1 | T0 completes against the fake | **held.** Exit 0, one request body. The websocket was refused, and Codex fell back to HTTPS as in the shakedown. |
| P2 | T0 contains K1 to K8 | **failed on K2, and K6 matched for the wrong reason.** K6 (`mcp__qmd__`) was found only because the global AGENTS.md mentions the server's tools in a sentence. The first request offered no MCP tools at all; its tool namespaces were `functions`, `clock` and `collaboration`, the same as in the room. So configured MCP servers were not measured. Separately, K2 failed: the SessionStart hook output is in neither T0 nor R0. In these non-interactive runs Codex did not run the hook, so this says nothing about the fake. The room has no `hooks.json` anyway. |
| P3 | every marker in R0 is also in T0 | **held, and more than that.** T0 also holds the memories (K3), which Codex's own rendering leaves out: 127k characters of context against 39k. The captured request is the better reading. |
| P4 | T1: none of K1 to K7, K8 present | **held.** |
| P5 | T1b lists skills that T1 does not | **failed.** T1 and T1b are identical (65,840 characters, same skill listing). In a fresh room the login restored nothing. codex-naked's finding was made in a reused home. |
| P6 | reach in T1: no real path, no inherited variable | **held.** Only the allowlist (`CODEX_HOME`, `HOME`, `TERM`, `PATH`, `LANG`) and the shell's `PWD` were set. |

## Found along the way

- **The room changes the model.** In T0 Codex used the model from the user's
  `config.toml` (`gpt-6-astra`). In the room it used its default (`gpt-6.1-sol`), because the
  room has no user config. The same goes for reasoning effort and other settings. An
  evaluation should set the model explicitly (`tare codex -- -m <model> ...`), or it compares
  two defaults rather than two setups.
- **MCP is not measured for Codex.** In `exec` runs the first request offers no tools from
  the configured MCP servers, so neither the dirty twin nor the room shows them. The room has
  no user `config.toml`, so it starts no user MCP server by construction.
- **Hooks are not measured for Codex.** They did not fire in `exec` runs, so the probe cannot
  see them in the dirty twin. The room has none by construction.
- **Probe time.** Each Codex probe run spends about 8 s on websocket retries before it falls
  back to HTTPS.

## Reproduce

```bash
for c in r0 t0 t1 t1b; do uv run experiments/dirty-twin-codex/run.py run $c; done
uv run experiments/dirty-twin-codex/run.py check
```

`markers.local.json` holds the marker strings. Their hashes are in PLAN.md.

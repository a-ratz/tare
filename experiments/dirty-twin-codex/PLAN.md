# Dirty-twin test for Codex

Fixed on 2026-10-05, before the measured runs. Decides how `tare probe codex` reads
context (epic #6, feature #7). Same design as the Claude Code test
([../dirty-twin/PLAN.md](../dirty-twin/PLAN.md)).

## What a shakedown run already showed

One unmeasured run on Codex 0.160.0 was made to build the harness. Its findings:

- With `-c openai_base_url=<fake>/v1`, Codex keeps its ChatGPT login (it sends the
  `chatgpt-account-id` header) and sends its requests to the fake.
- It tries a websocket five times, then falls back to HTTPS. This costs about 8 s. Overriding
  the built-in provider to switch the websocket off is refused.
- It compresses bodies with zstd unless `--disable enable_request_compression` is set.
  That flag changes the transport, not the content.
- The request holds the context as developer and user messages: memory, a skills listing,
  permissions, global AGENTS.md, environment. Tools sit in an `additional_tools` input item.
- Seen in that request: the global AGENTS.md, the SessionStart hook output, a user skill, an
  MCP server's tools and the home path. No account email.

So prediction P1 below is not new. It is restated so that it is measured.

## Question

Does the request the fake receives hold what Codex assembles from the user's setup? Does
the room remove all of it? And what does `--disable remote_plugin` (from codex-naked)
change in a fresh room?

## Conditions

| Run | Environment | Endpoint |
|---|---|---|
| R0 | real setup | none: `codex debug prompt-input`, Codex's own rendering of the model-visible input (reference) |
| T0 | real setup (the dirty twin) | fake |
| T1 | tare room: fresh `CODEX_HOME` with a copy of `auth.json`, cleared environment, `--disable remote_plugin` | fake |
| T1b | the same room without `--disable remote_plugin` | fake |

All runs use an empty work directory and drop the variables that a parent Claude Code
session exports (`CLAUDE*`). Harness: `run.py`.

## Markers

Personal strings are kept in `markers.local.json`, which is not committed. The first 16 hex
digits of their SHA-256 are fixed here.

| ID | What | Pattern |
|---|---|---|
| K1 | global instructions (`~/.codex/AGENTS.md`), a distinctive line | sha256 `a571ecbc534cb0e8` |
| K2 | SessionStart hook output (`~/.codex/hooks.json`), its fixed first sentence | sha256 `96e70dede788d3d7` |
| K3 | memories (`~/.codex/memories/memory_summary.md`), a distinctive line | sha256 `e42d7c7ebfb66f4e` |
| K4 | user skill in `~/.codex/skills` | sha256 `c30bfe27e53b40ea` |
| K5 | user skill in `~/.agents/skills` | sha256 `3aa770beaf9a757b` |
| K6 | MCP server from `config.toml` | tool prefix `mcp__qmd__` |
| K7 | the real home path | sha256 `9599eee0f4f5e405` |
| K8 | bundled system skill (product, not user) | `- imagegen` |

## Predictions

- **P1:** T0 completes against the fake: exit 0, at least one request body.
- **P2:** T0 contains K1 to K8.
- **P3:** Every marker in R0 is also in T0. The fake sees at least what Codex's own rendering
  shows.
- **P4:** T1 contains none of K1 to K7. It does contain K8: the bundled skills are installed
  into the fresh `CODEX_HOME`.
- **P5:** T1b lists skills that T1 does not: account plugins restore skills after login
  (codex-naked's finding in a reused home).
- **P6:** Reach in T1: none of the real paths exist inside, and no inherited environment
  variable is set apart from the allowlist.

## Decision

- **P1 to P3 hold:** the fake endpoint is Codex's context probe, and T0 is its control.
- **T0 misses markers that R0 shows:** the kill criterion holds for Codex. Fall back to
  `codex debug prompt-input` inside the room as the context reading, and note that it is
  Codex's own rendering, not a captured request.
- **P5 holds:** `--disable remote_plugin` stays in Codex's room flags. **P5 fails:** the
  flag stays anyway, as a guard, and the README says it was not needed in a fresh room.
- **P4 or P6 fails:** that is a finding about the room, and it is fixed before the probe ships.

# Dirty-twin test of the fake-model blank

Fixed on 2026-10-05, before any run. This test decides CONCEPT.md, layer 3, candidate 1.

## Question

A real Claude Code CLI can be pointed at a local fake model endpoint with
`ANTHROPIC_BASE_URL`. Does it then assemble the same context it assembles against the
real API, including what arrives with the login? If it does, the request the fake
stores works as a context probe that does not rely on the agent's cooperation. If
login-carried features drop out against the fake, the probe would report a dirty room
as clean. That outcome is the kill criterion.

## Code reading before the run (not a measurement)

Claude Code 2.1.289, minified bundle:

- The claude.ai connector list comes from `${BASE_API_URL}/v1/mcp_servers`. Here
  `BASE_API_URL` is the OAuth config constant `https://api.anthropic.com`, not
  `ANTHROPIC_BASE_URL`.
- Connectors are skipped only in these cases: `ENABLE_CLAUDEAI_MCP_SERVERS` is set
  falsy or `disableClaudeAiConnectors` is set; safe mode is on; the provider is a third
  party (Bedrock, Vertex, Foundry, gateway login); or API-key auth takes precedence.
  `ANTHROPIC_BASE_URL` appears in none of these checks.

## Harness

- `fake_model.py` is a stdlib HTTP server on 127.0.0.1. It stores every request as JSON,
  with `authorization`, `x-api-key`, `cookie` and `proxy-authorization` redacted.
  Answers to `/v1/messages` (streamed or not):
  - The first main-loop request, meaning the first one that offers a `Bash` tool, gets
    one scripted Bash call.
  - A request that already carries a tool result gets the text `ok`.
  - A request without tools gets `ok`.

  `/v1/messages/count_tokens` gets a fixed count. Any other path is stored and gets 404.
- The scripted call reports reach, never content:
  - For each known secret path of the real user, it prints `REACH <path>` if the path is
    readable, else `absent <path>`.
  - It prints the names (not the values) of environment variables that match
    token/key/secret/passw/auth.
- `run.sh r0|t0|t1` runs one condition from an empty work directory with
  `claude -p "say ok" --output-format stream-json --verbose`. It first removes the
  variables that a parent Claude Code session sets (`CLAUDE*`), so each run starts the
  way it would from a plain terminal.
- `check.py` reports, for each run: which markers occur in the stored requests, the
  tool names offered, the reach lines and the `system/init` tool list.

## Conditions

| Run | Environment | Endpoint |
|---|---|---|
| R0 | real user setup | real API (reference: what a real run loads, read from `system/init`) |
| T0 | real user setup (the dirty twin) | fake |
| T1 | bwrap room (`prototypes/bwrap-room.sh`), naked config, `--strict-mcp-config --setting-sources project,local` | fake |

T0 and T1 add `--dangerously-skip-permissions`, so the scripted Bash call executes in
print mode.

## Markers

Each marker is known context of the real setup. Personal strings live in
`markers.local.json`, which is not committed; the first 16 hex digits of their SHA-256
are fixed here.

| ID | What | Pattern |
|---|---|---|
| M1 | global user instructions (`~/.claude/CLAUDE.md`), a distinctive heading | sha256 `c7aa6641d046a77f` |
| M2 | SessionStart hook output, its fixed first sentence | sha256 `0009c23291dae3d5` |
| M3 | claude.ai connectors | tool prefix `mcp__claude_ai_` |
| M4 | local plugin skill, a namespaced skill name | sha256 `4193001faeac4c60` |
| M5 | skills that arrive with the login (CONCEPT layer 1) | namespace `anthropic-skills:` |
| M6 | auto-memory section | `/.claude/projects/` |
| M7 | user-configured local MCP server | tool prefix `mcp__qmd__` |
| M8 | account email | sha256 `3cf00f91d08eb485` |

## Predictions

- **P1:** In T0 the CLI completes its loop against the fake: the request is stored, the
  scripted Bash call executes, the tool result comes back, and the CLI exits 0.
- **P2:** T0 contains M1 to M8.
- **P3:** The tool names offered in T0's main request equal the tools in R0's
  `system/init`. In particular, connectors (M3) are present in both.
- **P4:** T1 contains none of M1 to M7. M8, the email, is present, because it stays with
  subscription auth (CONCEPT layer 1).
- **P5 (reach):**
  - T0: every real path prints `REACH`.
  - T1: every real path prints `absent`.
  - Inside the room, the names of secret-like variables from the parent shell are still
    visible, because `bwrap-room.sh` does not clear the environment. This would be a
    leak class that CONCEPT does not list yet.

## Decision

- **The kill criterion holds** if P1 fails, or if P3 fails because login-carried tools or
  skills are missing in T0 but present in R0. Then the fake-model blank cannot be the
  context probe on its own. Next would be the same capture behind a TLS-intercepting
  proxy at the real URL (`HTTPS_PROXY` + `NODE_EXTRA_CA_CERTS`).
- **The blank is adopted** if P1 to P3 hold. It becomes Tare's context probe for Claude
  Code, and T0 becomes its built-in positive control: a probe that finds nothing in the
  dirty twin is blind.
- **Deviations from P4 or P5** are findings about the room, not about the probe.

## Not tested here

Codex, Pi and Copilot CLI; server-side memory; interactive mode; macOS.

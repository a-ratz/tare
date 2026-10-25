# Calibrate: how often does each side pass?

[← Documentation](README.md) · [Measuring agents in rooms](measuring.md)

Use Calibrate to compare skills, plugins or models: it starts each side several times from
scratch, each run in its own room, and reports how often each side passes a check.

```bash
tare calibrate "fix the failing test" --check "uv run pytest -q" \
  --side "claude --model haiku" --side "codex -m gpt-6.1-sol" --runs 10
```

Each `--side` is an agent with its arguments. tare starts every side `--runs` times from a fresh
copy of the project and reports each side's pass rate with its [interval](measuring.md#the-95-interval).

Calibrate also tells you whether a task suits Swap or Cliff. [Swap](swap.md) needs a task where
one side mostly fails and the other mostly passes. [Cliff](cliff.md) needs a task where a fresh
start passes at least sometimes.

## Different prompts per side

Some skills start with their own command, for example a slash command, so the sides need
different prompts. `--side-prompt` gives a side its own prompt. The sides are named a, b and c in
the order of `--side`:

```bash
tare calibrate --side "claude --plugin-dir plugins/a" --side "claude --plugin-dir plugins/b" \
  --side-prompt "a=/a:ideate a todo app" --side-prompt "b=/b:ideate a todo app" --runs 5
```

## Without a check

Without `--check`, a run counts as finished when its agent exits with 0. tare keeps each finished
workspace, and the report shows the finished runs and their times, so that you can score the
results elsewhere, for example with a [judge](judge.md). `--keep` keeps the workspaces when there
is a check too.

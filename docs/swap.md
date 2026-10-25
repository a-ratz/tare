# Swap: was it the workspace or the agent?

[← Documentation](README.md) · [Measuring agents in rooms](measuring.md)

When one agent fails a task and another passes, two causes are possible. The agent may be the
weaker one. Or its workspace may have reached a state that no agent can finish. Swap lets the two
agents continue each other's unfinished work and separates the two causes.

```bash
tare swap "fix the failing test" --check "uv run pytest -q" --a claude --a-args "--model sonnet" --b codex
```

Two agents, a and b, each attempt the same task once. [Calibrate](calibrate.md) first tells you
whether a task suits Swap: it needs one side that mostly fails and one that mostly passes.

## Cuts, tails and the two effects

Swap cuts both runs at several points. `--cuts` sets them as fractions of each run's steps,
where 0 is the start and 1 is the end. The default is `0,0.5,1`. At each cut, each agent continues
each workspace, three times by default (`--tails`). Each such continuation is a **tail**. A tail
gets the workspace and a **handoff**: a written summary of the steps so far, in the same form for
every agent. Swap then reports two numbers per cut, each with an
[interval](measuring.md#the-95-interval):

- The **state effect** says how much better the tails do in a's workspace than in b's, which is
  how much the state of the workspace matters.
- The **model effect** says how much better agent a does than agent b, in the same workspaces.
  The model effect covers the agent CLI and its model together.

## The null check and the handoff cost

At cut 0 both workspaces are your untouched project, so the state effect there must be zero. Swap
checks this and calls it the **null check**. Where an agent can continue its own saved session
(Claude Code, Codex and Pi), Swap also lets each agent continue its own session from each cut.
That measures what the handoff itself costs. The report shows it per agent as a **handoff cost**
line: the agent's pass rate when it continues its own session, minus its pass rate from the
handoff, in its own workspace. A value near zero means that the handoff loses nothing.

## A report

The report below comes from tare's own test. It drives the real Claude Code CLI against two
scripted models: fake models that follow a fixed script, so the right verdict is known. The test
runs four tails per workspace and agent instead of three. Agent a is competent but trusts a note
in the workspace. Agent b is weak. Run b wrote a wrong note at step 2.

Each cell shows passes out of tails and their interval. Positive effects favour a's workspace or
agent a. The report continues with cut 1.00, left out here.

```text
  cut 0.00: workspace a at step 0, workspace b at step 0
                agent a          agent b
    workspace a 4/4 0.51-1.00    1/4 0.05-0.70
    workspace b 4/4 0.51-1.00    1/4 0.05-0.70
    state effect  +0.00 [-0.35, +0.35]  (positive: workspace a better)
    model effect  +0.75 [+0.28, +0.89]  (positive: agent a better)
    handoff cost a +0.00 [-0.49, +0.49]  (own session 4/4 against handoff 4/4, both in its own workspace)
    handoff cost b +0.50 [-0.14, +0.79]  (own session 3/4 against handoff 1/4, both in its own workspace)

  cut 0.50: workspace a at step 2, workspace b at step 2
                agent a          agent b
    workspace a 4/4 0.51-1.00    1/4 0.05-0.70
    workspace b 0/4 0.00-0.49    2/4 0.15-0.85
    state effect  +0.38 [-0.03, +0.66]  (positive: workspace a better)
    model effect  +0.12 [-0.25, +0.44]  (positive: agent a better)
    handoff cost a +0.00 [-0.49, +0.49]  (own session 4/4 against handoff 4/4, both in its own workspace)
    handoff cost b -0.25 [-0.66, +0.32]  (own session 1/4 against handoff 2/4, both in its own workspace)

  null check   passed: no state effect at cut 0, where both workspaces are the untouched project
  verdict      Blame passes from the model to the workspace between cut 0.00 and cut 0.50. The intervals behind this verdict include zero. More tails would settle it.
```

At the start, the model effect explains the difference. Agent a passes, agent b mostly fails.
After the wrong note, a's workspace still works and b's does not, even for the competent agent
a. The verdict says so.

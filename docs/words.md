# The words tare uses

[← Documentation](README.md)

The name comes from weighing. You tare a scale, which sets it to zero, before you weigh
something. tare does the same for an agent before you measure it.

| Word | Meaning |
|---|---|
| room | An isolated environment for one agent run. It has an empty home directory, a fresh copy of your login (the file in which the agent keeps your sign-in) and only four basic environment variables from your shell (an allowlist), plus its own `HOME` and `PATH`. Your project appears at `/work`. tare builds the room with [bubblewrap](https://github.com/containers/bubblewrap). On macOS it builds the room with Seatbelt, the sandbox built into macOS: the agent works on a copy of your project inside the room, and its changes are copied back to your project when the room closes. |
| probe | The test that tare runs before an agent starts. It makes no paid model calls. The agent talks to a fake model server on your machine, which records what the agent sends. |
| reading | The result of a probe, one of three. A clean room reads `tare: 0.00`, the zeroed scale. A room with leaks reads, for example, `tare: 4 leaks`. A probe that could not see your setup reads `tare: not proven (blind)`. There are no values in between. |
| leak | Something of your personal setup that reaches the room, for example your global instructions. The reading names each leak and the file it came from. |
| declared | Something of yours that the room holds on purpose, for example the copy of your login. The reading lists it, but it is not a leak and does not stop the run. |
| control run | The same agent run in your real setup, outside the room. It is part of the probe and proves that the probe can see your setup at all. |

## Words of the measuring tools

| Word | Meaning |
|---|---|
| check | A shell command tare runs in the finished workspace. Exit code 0 means the run passed. |
| step | One tool call of the agent, such as running a command or writing a file. |
| workspace | A run's own copy of your project. |
| restart | The agent continues from a saved step of a run, in a fresh room. |
| fresh start | A restart from the very beginning: it shows how often the task passes at all. |
| handover point | Where Swap stops both runs and lets each agent continue the other's workspace: 0 is the start, 0.5 halfway, 1 the end. |
| handover note | A written summary of the steps so far, the same for every agent, given to the agent that continues. |
| workspace effect, agent effect | How much the workspace decides the outcome, and how much the agent does. |
| likely range | The range that holds the true pass rate with 95% confidence (a 95% interval). Few runs give a wide range. |
| judge | A second agent that scores a result from 0 to 100 by your rubric, without knowing which agent made it. |

[Measuring agents in rooms](measuring.md) shows how the tools use them. In older experiment
records under `experiments/`, the control run is called the dirty twin and a restart a tail.

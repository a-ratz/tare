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
| dirty twin | The same agent run in your real setup, outside the room. It is part of the probe and proves that the probe can see your setup at all. |

The measuring tools add a few more: check, step, run directory, tail, handoff and the 95%
interval. [Measuring agents in rooms](measuring.md) explains them.

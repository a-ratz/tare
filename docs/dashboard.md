# Dashboard and rerun

[← Documentation](README.md) · [Measuring agents in rooms](measuring.md)

## Watch it live

The live dashboard of `tare calibrate`, `tare swap` and `tare cliff` runs at
`http://localhost:8777/` unless that port is taken. It shows the setup of the run, the probe
readings, each run step by step, every tail with what its agent is doing, the results as they
come in, and the final report.

```bash
tare watch ~/.local/state/tare/cliff/myproject-20261005-142000   # any run, live or finished
tare watch ~/.local/state/tare/calibrate/*                         # several runs: one row each
```

## Repeat it

```bash
tare rerun ~/.local/state/tare/cliff/myproject-20261005-142000   # the same run again
```

Every run directory holds a `recipe.json` with the command, the task and the check, a fingerprint
of the project, the agents with their versions and arguments, and the settings. `tare rerun`
repeats the run in a new directory with the same settings and says what has changed since and
what the repeated run used. Agent runs are not deterministic, so a repeated run can still come out
differently.

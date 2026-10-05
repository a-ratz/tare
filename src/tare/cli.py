"""tare: zero the scale before you weigh.

  tare probe {claude,codex} [--project DIR]
  tare {claude,codex} [--project DIR] [--allow-dirty] [--yolo] [-- AGENT_ARGS...]
  tare cliff claude PROMPT --check CMD [--tails N] [--budget N] [--jobs N] [-- CLAUDE_ARGS...]
  tare swap PROMPT --check CMD [--a claude] [--b codex] [--a-args ARGS] [--b-args ARGS] [--cuts 0,0.5,1]
"""
import argparse
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

from .agents import AGENTS
from .cliff import cliff
from .swap import Side, swap
from .probe import probe, render
from .room import TareError, bwrap, room_home


def _exit_on(signum, _frame):
    # SystemExit unwinds through room_home, so the login copy is removed
    raise SystemExit(128 + signum)


def _run_attached(argv: list[str]) -> int:
    """Run the room in the foreground. Ctrl-C belongs to the agent (it interrupts a
    turn there), so tare ignores it instead of dying and removing the room under it."""
    previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        return subprocess.call(argv)
    finally:
        signal.signal(signal.SIGINT, previous)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    passthrough: list[str] = []
    if "--" in argv:
        at = argv.index("--")
        argv, passthrough = argv[:at], argv[at + 1:]

    ap = argparse.ArgumentParser(prog="tare", description="Start a coding agent in a room where nothing "
                                 "of yours came along, and prove it before the run.")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("probe", help="measure the room: tare: 0.00, or every leak and its source")
    p.add_argument("agent", choices=sorted(AGENTS))
    p.add_argument("--project", type=Path, default=Path.cwd())
    for name in sorted(AGENTS):
        c = sub.add_parser(name, help=f"probe, then start {name} in the room (args after --)")
        c.add_argument("--project", type=Path, default=Path.cwd())
        c.add_argument("--allow-dirty", action="store_true", help="start even if the reading is not zero")
        c.add_argument("--yolo", action="store_true", help="skip the agent's permission prompts and sandbox")
    k = sub.add_parser("cliff", help="find where a failed run became lost (args after -- go to every agent run)")
    k.add_argument("agent", choices=["claude"])
    k.add_argument("prompt", help="the task, as given to the agent")
    k.add_argument("--check", required=True, help="shell command run in the finished workspace; exit 0 passes")
    k.add_argument("--project", type=Path, default=Path.cwd())
    k.add_argument("--tails", type=int, default=3, help="tails per probe (default 3)")
    k.add_argument("--budget", type=int, default=30, help="tails in total, baseline included (default 30)")
    k.add_argument("--jobs", type=int, default=3, help="tails run at the same time (default 3)")
    k.add_argument("--out", type=Path, help="run directory (default ~/.local/state/tare/cliff/<project>-<time>)")
    k.add_argument("--allow-dirty", action="store_true", help="run even if the probe reading is not zero")
    w = sub.add_parser("swap", help="cross two runs' rooms with two agents: was it the room or the model")
    w.add_argument("prompt", help="the task, as given to both agents")
    w.add_argument("--check", required=True, help="shell command run in the finished workspace; exit 0 passes")
    w.add_argument("--a", default="claude", choices=sorted(AGENTS), help="agent a (default claude)")
    w.add_argument("--b", default="codex", choices=sorted(AGENTS), help="agent b (default codex)")
    w.add_argument("--a-args", default="", help="arguments for every run of agent a, e.g. '--model sonnet'")
    w.add_argument("--b-args", default="", help="arguments for every run of agent b, e.g. '-m MODEL'")
    w.add_argument("--cuts", default="0,0.5,1", help="where to cut each run, as fractions (default 0,0.5,1)")
    w.add_argument("--tails", type=int, default=3, help="tails per cell (default 3)")
    w.add_argument("--jobs", type=int, default=3, help="tails run at the same time (default 3)")
    w.add_argument("--handoff", choices=["trail", "workspace"], default="trail",
                   help="what a continuing agent is given besides the workspace (default: the rendered trail)")
    w.add_argument("--project", type=Path, default=Path.cwd())
    w.add_argument("--out", type=Path, help="run directory (default ~/.local/state/tare/swap/<project>-<time>)")
    w.add_argument("--allow-dirty", action="store_true", help="run even if a probe reading is not zero")
    args = ap.parse_args(argv)
    if args.command == "swap":
        names = [args.a, args.b]
    else:
        names = [args.agent if args.command in ("probe", "cliff") else args.command]
    project = args.project.resolve()
    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, _exit_on)

    try:
        reals = {}
        for name in dict.fromkeys(names):
            agent = AGENTS[name]
            reals[name] = agent.discover()
            reading = probe(agent, reals[name], project)
            print(render(reading, project), file=sys.stderr)
            if args.command == "probe":
                return 0 if reading.zero else 1
            if not reading.zero:
                if not args.allow_dirty:
                    print("tare: not starting; fix the leaks or pass --allow-dirty", file=sys.stderr)
                    return 1
                print(f"tare: --allow-dirty given, running {name} in a room that is not zero", file=sys.stderr)
        agent, real = AGENTS[names[0]], reals[names[0]]
        if args.command in ("cliff", "swap"):
            out = args.out or (Path.home() / ".local/state/tare" / args.command
                               / f"{project.name}-{time.strftime('%Y%m%d-%H%M%S')}")
            out.mkdir(parents=True, exist_ok=False)
            print(f"tare {args.command}: run directory {out}", file=sys.stderr)
        if args.command == "cliff":
            print(cliff(agent, real, project, args.prompt, args.check, out, tails=args.tails, budget=args.budget,
                        jobs=args.jobs, claude_args=passthrough), end="")
            return 0
        if args.command == "swap":
            a = Side("a", AGENTS[args.a], reals[args.a], shlex.split(args.a_args), out / "a")
            b = Side("b", AGENTS[args.b], reals[args.b], shlex.split(args.b_args), out / "b")
            cuts = [float(c) for c in args.cuts.split(",")]
            print(swap(a, b, project, args.prompt, args.check, out, cuts=cuts, tails=args.tails, jobs=args.jobs,
                       workspace_only=args.handoff == "workspace"), end="")
            return 0
        flags = agent.room_flags + (agent.yolo if args.yolo else [])
        with room_home(agent, real) as home:
            return _run_attached(bwrap(agent, real, home, project, [agent.name, *flags, *passthrough]))
    except TareError as err:
        print(f"tare: {err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

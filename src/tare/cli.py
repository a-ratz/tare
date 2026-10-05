"""tare: zero the scale before you weigh.

  tare probe {claude,codex} [--project DIR]
  tare {claude,codex} [--project DIR] [--allow-dirty] [--yolo] [-- AGENT_ARGS...]
  tare cliff claude PROMPT --check CMD [--tails N] [--budget N] [--jobs N] [-- CLAUDE_ARGS...]
"""
import argparse
import signal
import subprocess
import sys
import time
from pathlib import Path

from .agents import AGENTS
from .cliff import cliff
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
    args = ap.parse_args(argv)
    agent = AGENTS[args.agent if args.command in ("probe", "cliff") else args.command]
    project = args.project.resolve()
    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, _exit_on)

    try:
        real = agent.discover()
        reading = probe(agent, real, project)
        print(render(reading, project), file=sys.stderr)
        if args.command == "probe":
            return 0 if reading.zero else 1
        if not reading.zero:
            if not args.allow_dirty:
                print("tare: not starting; fix the leaks or pass --allow-dirty", file=sys.stderr)
                return 1
            print("tare: --allow-dirty given, starting in a room that is not zero", file=sys.stderr)
        if args.command == "cliff":
            out = args.out or Path.home() / ".local/state/tare/cliff" / f"{project.name}-{time.strftime('%Y%m%d-%H%M%S')}"
            out.mkdir(parents=True, exist_ok=False)
            print(f"tare cliff: run directory {out}", file=sys.stderr)
            print(cliff(agent, real, project, args.prompt, args.check, out, tails=args.tails, budget=args.budget,
                        jobs=args.jobs, claude_args=passthrough), end="")
            return 0
        flags = agent.room_flags + (agent.yolo if args.yolo else [])
        with room_home(agent, real) as home:
            return _run_attached(bwrap(agent, real, home, project, [agent.name, *flags, *passthrough]))
    except TareError as err:
        print(f"tare: {err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

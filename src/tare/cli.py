"""tare: zero the scale before you weigh.

  tare probe claude [--project DIR]
  tare claude [--project DIR] [--allow-dirty] [--yolo] [-- CLAUDE_ARGS...]
"""
import argparse
import signal
import subprocess
import sys
from pathlib import Path

from .probe import probe, render
from .room import ROOM_FLAGS, Real, TareError, bwrap, room_home


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
    p.add_argument("agent", choices=["claude"])
    p.add_argument("--project", type=Path, default=Path.cwd())
    c = sub.add_parser("claude", help="probe, then start Claude Code in the room (args after --)")
    c.add_argument("--project", type=Path, default=Path.cwd())
    c.add_argument("--allow-dirty", action="store_true", help="start even if the reading is not zero")
    c.add_argument("--yolo", action="store_true", help="pass --dangerously-skip-permissions")
    args = ap.parse_args(argv)
    project = args.project.resolve()
    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, _exit_on)

    try:
        real = Real.discover()
        reading = probe(real, project)
        print(render(reading, project), file=sys.stderr)
        if args.command == "probe":
            return 0 if reading.zero else 1
        if not reading.zero:
            if not args.allow_dirty:
                print("tare: not starting; fix the leaks or pass --allow-dirty", file=sys.stderr)
                return 1
            print("tare: --allow-dirty given, starting in a room that is not zero", file=sys.stderr)
        flags = ROOM_FLAGS + (["--dangerously-skip-permissions"] if args.yolo else [])
        with room_home(real) as home:
            return _run_attached(bwrap(home, project, real.claude, ["claude", *flags, *passthrough]))
    except TareError as err:
        print(f"tare: {err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

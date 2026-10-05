"""tare: zero the scale before you weigh.

  tare probe {claude,codex,pi,agy} [--project DIR]
  tare {claude,codex,pi,agy} [--project DIR] [--allow-dirty] [--yolo] [-- AGENT_ARGS...]
  tare cliff {claude,codex,pi,agy} PROMPT --check CMD [--tails N] [--budget N] [--jobs N] [-- AGENT_ARGS...]
  tare swap PROMPT --check CMD [--a claude] [--b codex] [--a-args ARGS] [--b-args ARGS] [--cuts 0,0.5,1]
  tare calibrate [PROMPT] [--check CMD] --side "claude --model haiku" --side "codex" [--side-prompt b=TEXT] [--runs N]
  tare judge [DIR] --rubric FILE --threshold N [--judge "claude --model sonnet"]   a check: exit 0 at or above N
  tare judge-noise DIR... --rubric FILE --times K [--threshold N]                  how far the judge's scores vary
  tare watch DIR... [--port N]   the dashboard of a run, live or finished (several runs on one page)
  tare rerun DIR [--out DIR]     repeat a run from its recipe
"""
import argparse
import json
import shlex
import threading
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import dashboard, recipe
from . import usage as usages
from .agents import AGENTS
from . import calibrate as calibration
from .cliff import cliff
from .journal import Journal
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


def _serve(out: Path | list[Path], port: int) -> str:
    try:
        return dashboard.serve(out, port)[1]
    except OSError:
        return dashboard.serve(out, 0)[1]  # the usual port is taken


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    original_argv = list(argv)
    if argv[:1] == ["watch"]:
        return _watch(argv[1:])
    if argv[:1] == ["rerun"]:
        return _rerun(argv[1:])
    if argv[:1] in (["judge"], ["judge-noise"]):
        return _judge(argv[0], argv[1:])
    passthrough: list[str] = []
    if "--" in argv:
        at = argv.index("--")
        argv, passthrough = argv[:at], argv[at + 1:]

    ap = argparse.ArgumentParser(prog="tare", description="Start a coding agent in an isolated room without your "
                                 "personal setup, and prove the room clean before the run.")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("probe", help="probe the room: tare: 0.00, the leaks and their sources, or not proven (blind)")
    p.add_argument("agent", choices=sorted(AGENTS))
    p.add_argument("--project", type=Path, default=Path.cwd())
    for name in sorted(AGENTS):
        c = sub.add_parser(name, help=f"probe, then start {name} in the room (args after --)")
        c.add_argument("--project", type=Path, default=Path.cwd())
        c.add_argument("--allow-dirty", action="store_true", help="start even if the reading is not tare: 0.00")
        c.add_argument("--yolo", action="store_true", help="skip the agent's permission prompts (for Codex also its own sandbox). The room stays.")
    k = sub.add_parser("cliff", help="find where a failed run became lost (args after -- go to every agent run)")
    k.add_argument("agent", choices=sorted(AGENTS))
    k.add_argument("prompt", help="the task, as given to the agent")
    k.add_argument("--check", required=True, help="shell command run in the finished workspace (exit 0 passes)")
    k.add_argument("--project", type=Path, default=Path.cwd())
    k.add_argument("--tails", type=int, default=3, help="tails (continuations from a saved step) per step tried (default 3)")
    k.add_argument("--budget", type=int, default=30, help="tails in total, baseline included (default 30)")
    k.add_argument("--jobs", type=int, default=3, help="tails run at the same time (default 3)")
    k.add_argument("--gap-below", type=float, default=0.2,
                   help="report a model gap (the task is too hard for the model) only when the upper end of the "
                        "baseline's 95%% interval is below this (default 0.2)")
    k.add_argument("--out", type=Path, help="run directory (default ~/.local/state/tare/cliff/<project>-<time>)")
    k.add_argument("--allow-dirty", action="store_true", help="run even if the reading is not tare: 0.00")
    w = sub.add_parser("swap", help="each agent continues both workspaces: was it the workspace or the agent")
    w.add_argument("prompt", help="the task, as given to both agents")
    w.add_argument("--check", required=True, help="shell command run in the finished workspace (exit 0 passes)")
    w.add_argument("--a", default="claude", choices=sorted(AGENTS), help="agent a (default claude)")
    w.add_argument("--b", default="codex", choices=sorted(AGENTS), help="agent b (default codex)")
    w.add_argument("--a-args", default="", help="arguments for every run of agent a, e.g. '--model sonnet'")
    w.add_argument("--b-args", default="", help="arguments for every run of agent b, e.g. '-m MODEL'")
    w.add_argument("--cuts", default="0,0.5,1", help="where to cut each run, as fractions of its steps (default 0,0.5,1)")
    w.add_argument("--tails", type=int, default=3, help="tails (continuations) per cut, workspace and agent (default 3)")
    w.add_argument("--jobs", type=int, default=3, help="tails run at the same time (default 3)")
    w.add_argument("--handoff", choices=["trail", "workspace"], default="trail",
                   help="what a continuing agent gets besides the workspace: a written summary of the steps so far "
                        "(trail, the default) or nothing (workspace)")
    w.add_argument("--project", type=Path, default=Path.cwd())
    w.add_argument("--out", type=Path, help="run directory (default ~/.local/state/tare/swap/<project>-<time>)")
    w.add_argument("--allow-dirty", action="store_true", help="run even if a reading is not tare: 0.00")
    c = sub.add_parser("calibrate", help="how often each side (an agent with its arguments) passes a task")
    c.add_argument("prompt", nargs="?", help="the task, as given to every side without a prompt of its own")
    c.add_argument("--check", help="shell command run in the finished workspace (exit 0 passes). Without it, a run "
                   "counts as finished when its agent exits 0, and its workspace is kept for scoring elsewhere")
    c.add_argument("--side", action="append", required=True,
                   help="an agent and its arguments, e.g. 'claude --model haiku' (repeat for each side)")
    c.add_argument("--side-prompt", action="append", default=[], metavar="KEY=PROMPT",
                   help="a side's own prompt. Sides are a, b, c... in --side order, e.g. 'b=/b:ideate a todo app'")
    c.add_argument("--runs", type=int, default=10, help="fresh starts per side (default 10)")
    c.add_argument("--jobs", type=int, default=3, help="runs at the same time (default 3)")
    c.add_argument("--project", type=Path, default=Path.cwd())
    c.add_argument("--out", type=Path, help="run directory (default ~/.local/state/tare/calibrate/<project>-<time>)")
    c.add_argument("--allow-dirty", action="store_true", help="run even if a reading is not tare: 0.00")
    c.add_argument("--keep", action="store_true", help="keep every run's finished workspace (e.g. for judge-noise)")
    for parser in (k, w, c):
        parser.add_argument("--port", type=int, default=8777, help="dashboard port on localhost (default 8777)")
    sub.add_parser("watch", help="the live dashboard of one or more run directories (tare watch DIR...)")
    sub.add_parser("judge", help="score a page by a rubric, in a room without agent or model names so the judge cannot tell who "
                       "built it (usable as --check)")
    sub.add_parser("judge-noise", help="score the same pages repeatedly, to see how far the judge's scores vary")
    sub.add_parser("rerun", help="repeat a run from its recipe (tare rerun DIR)")
    args = ap.parse_args(argv)
    if args.command == "swap":
        names = [args.a, args.b]
    elif args.command == "calibrate":
        sides = [shlex.split(side) for side in args.side]
        unknown = [side[0] for side in sides if side[0] not in AGENTS]
        if unknown:
            ap.error(f"unknown agent: {', '.join(unknown)} (known: {', '.join(sorted(AGENTS))})")
        names = [side[0] for side in sides]
        keys = [chr(97 + i) for i in range(len(sides))]
        prompts = dict(item.split("=", 1) for item in args.side_prompt if "=" in item)
        bad = [item for item in args.side_prompt if "=" not in item or item.split("=", 1)[0] not in keys]
        if bad:
            ap.error(f"--side-prompt wants KEY=PROMPT with KEY one of {', '.join(keys)}: {', '.join(bad)}")
        if not args.prompt and len(prompts) < len(keys):
            ap.error("give a prompt, or a --side-prompt for every side")
    else:
        names = [args.agent if args.command in ("probe", "cliff") else args.command]
    project = args.project.resolve()
    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, _exit_on)

    try:
        reals = {name: AGENTS[name].discover() for name in dict.fromkeys(names)}
        journal = Journal(None)
        if args.command in ("cliff", "swap", "calibrate"):
            out = args.out or (Path.home() / ".local/state/tare" / args.command
                               / f"{project.name}-{time.strftime('%Y%m%d-%H%M%S')}")
            out.mkdir(parents=True, exist_ok=False)
            journal = Journal(out)
            if args.command == "cliff":
                agents = {"a": (AGENTS[args.agent], reals[args.agent], passthrough)}
                params = {"tails": args.tails, "budget": args.budget, "jobs": args.jobs, "gap_below": args.gap_below}
            elif args.command == "calibrate":
                agents = {chr(97 + i): (AGENTS[side[0]], reals[side[0]], side[1:]) for i, side in enumerate(sides)}
                params = {"runs": args.runs, "jobs": args.jobs, **({"prompts": prompts} if prompts else {})}
            else:
                agents = {"a": (AGENTS[args.a], reals[args.a], shlex.split(args.a_args)),
                          "b": (AGENTS[args.b], reals[args.b], shlex.split(args.b_args))}
                params = {"cuts": args.cuts, "tails": args.tails, "jobs": args.jobs, "handoff": args.handoff}
            recipe.write(out, original_argv, args.command, project, args.prompt, args.check, agents, params)
            print(f"tare {args.command}: run directory {out}", file=sys.stderr)
            print(f"tare {args.command}: live dashboard {_serve(out, args.port)}", file=sys.stderr)
        for name in dict.fromkeys(names):
            agent = AGENTS[name]
            reading = probe(agent, reals[name], project)
            print(render(reading, project), file=sys.stderr)
            journal("probe", agent=name, zero=reading.zero, text=render(reading, project))
            if args.command == "probe":
                return 0 if reading.zero else 1
            if not reading.zero:
                if not args.allow_dirty:
                    print("tare: not starting, because the room is not proven clean. Fix what the reading names, "
                          "or pass --allow-dirty.", file=sys.stderr)
                    return 1
                print(f"tare: --allow-dirty given, running {name} in a room whose reading is not tare: 0.00",
                      file=sys.stderr)
        agent, real = AGENTS[names[0]], reals[names[0]]
        if args.command == "cliff":
            print(cliff(agent, real, project, args.prompt, args.check, out, tails=args.tails, budget=args.budget,
                        jobs=args.jobs, claude_args=passthrough, journal=journal, gap_below=args.gap_below), end="")
            print(f"tare cliff: see it again with  tare watch {out}", file=sys.stderr)
            return 0
        if args.command == "calibrate":
            runs = [calibration.Side(key, agent_, real_, list(extra), prompts.get(key))
                    for key, (agent_, real_, extra) in agents.items()]
            print(calibration.calibrate(runs, project, args.prompt, args.check, out, runs=args.runs, jobs=args.jobs,
                                        journal=journal, keep=args.keep), end="")
            print(f"tare calibrate: see it again with  tare watch {out}", file=sys.stderr)
            return 0
        if args.command == "swap":
            a = Side("a", AGENTS[args.a], reals[args.a], shlex.split(args.a_args), out / "a")
            b = Side("b", AGENTS[args.b], reals[args.b], shlex.split(args.b_args), out / "b")
            cuts = [float(c) for c in args.cuts.split(",")]
            print(swap(a, b, project, args.prompt, args.check, out, cuts=cuts, tails=args.tails, jobs=args.jobs,
                       workspace_only=args.handoff == "workspace", journal=journal), end="")
            print(f"tare swap: see it again with  tare watch {out}", file=sys.stderr)
            return 0
        flags = agent.room_flags + (agent.yolo if args.yolo else [])
        with room_home(agent, real) as home:
            return _run_attached(bwrap(agent, real, home, project, [agent.name, *flags, *passthrough]))
    except TareError as err:
        print(f"tare: {err}", file=sys.stderr)
        return 2


def _watch(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="tare watch", description="the live dashboard of a run, or of several runs on one page")
    ap.add_argument("dirs", type=Path, nargs="+")
    ap.add_argument("--port", type=int, default=8777)
    args = ap.parse_args(argv)
    missing = [str(d) for d in args.dirs if not (d / "journal.jsonl").exists()]
    if missing:
        print(f"tare watch: not a tare run directory (no journal.jsonl): {', '.join(missing)}", file=sys.stderr)
        return 2
    dirs = [d.resolve() for d in args.dirs]
    print(f"tare watch: {_serve(dirs[0] if len(dirs) == 1 else dirs, args.port)}  (Ctrl-C to stop)", file=sys.stderr)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    return 0


def _judge(command: str, argv: list[str]) -> int:
    from . import judge as judging
    ap = argparse.ArgumentParser(prog=f"tare {command}")
    ap.add_argument("dirs", type=Path, nargs="*" if command == "judge" else "+", default=[Path.cwd()])
    ap.add_argument("--rubric", type=Path, required=True)
    ap.add_argument("--threshold", type=float, required=command == "judge")
    ap.add_argument("--times", type=int, default=10, help="scores per page (judge-noise, default 10)")
    ap.add_argument("--page", default="index.html", help="the page to render (default index.html)")
    ap.add_argument("--judge", default="claude --model sonnet", help="the judge agent and its arguments")
    args = ap.parse_args(argv)
    name, *extra = shlex.split(args.judge)
    try:
        if command == "judge":
            score, reason = judging.judge(args.dirs[0].resolve(), args.rubric.resolve(), args.page, name, extra)
            print(f"score {score} (threshold {args.threshold:g}): {reason}")
            return 0 if score >= args.threshold else 1
        text, clear = judging.noise([d.resolve() for d in args.dirs], args.rubric.resolve(), args.times,
                                    args.threshold, args.page, name, extra)
        print(text, end="")
        return 0 if clear else 1
    except (RuntimeError, TareError) as err:
        print(f"tare {command}: {err}")
        return 2


def _rerun(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="tare rerun", description="repeat a Calibrate, Cliff or Swap run from its recipe")
    ap.add_argument("dir", type=Path)
    ap.add_argument("--out", type=Path, help="run directory for the repeat (default: a new one)")
    args = ap.parse_args(argv)
    try:
        r = recipe.read(args.dir)
    except OSError:
        print(f"tare rerun: no recipe.json in {args.dir}", file=sys.stderr)
        return 2
    reals = {}
    for agent in r["agents"].values():
        try:
            reals[agent["name"]] = AGENTS[agent["name"]].discover()
        except TareError:
            pass
    for note in recipe.drift(r, reals):
        print(f"tare rerun: note: {note}", file=sys.stderr)
    spent = args.dir / "usage.json"
    if spent.exists():
        before = usages.Usage.from_dict(json.loads(spent.read_text()).get("total"))
        print(f"tare rerun: the run being repeated used {usages.describe(before)}", file=sys.stderr)
    command = recipe.with_out(r["argv"], args.out) if args.out else r["argv"]
    print(f"tare rerun: tare {shlex.join(command)}", file=sys.stderr)
    return main(command)


if __name__ == "__main__":
    sys.exit(main())

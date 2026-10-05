"""Swap: the room or the model (epic Swap).

Two agents, a and b, each run the task once in a room, with a capsule per step. At each cut,
a fraction of each run, both rooms are crossed with both agents: every agent continues
every room, by the same rendered handoff, so diagonal and off-diagonal cells read the
same kind of input. The state effect is how much better the tails do in room a than in
room b, averaged over the agents; the model effect is how much better agent a does than
agent b, averaged over the rooms. Where an agent can resume its own session natively, a
native cell on its own room prices the handoff itself (foreignness). At cut 0 both rooms
are the untouched project, so the state effect there must be zero: the null check.
"""
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from . import capsule as caps
from .cliff import wilson
from .journal import Journal


@dataclass
class Side:
    key: str  # "a" or "b"
    agent: object
    real: object
    args: list[str]
    out: Path
    steps: list = field(default_factory=list)
    events: list = field(default_factory=list)
    original: str = ""


def newcombe(x1: int, n1: int, x2: int, n2: int) -> tuple[float, float, float]:
    """Difference of two pass rates with a 95 % interval (Newcombe's hybrid score method)."""
    p1, p2 = x1 / n1, x2 / n2
    l1, u1 = wilson(x1, n1)
    l2, u2 = wilson(x2, n2)
    d = p1 - p2
    return d, d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2), d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)


def mean_effect(differences: list[tuple[float, float, float]]) -> tuple[float, float, float]:
    """Mean of independent differences; interval half-widths combine in quadrature."""
    k = len(differences)
    e = sum(d for d, _, _ in differences) / k
    down = math.sqrt(sum((d - lo) ** 2 for d, lo, _ in differences)) / k
    up = math.sqrt(sum((hi - d) ** 2 for d, _, hi in differences)) / k
    return e, e - down, e + up


@dataclass
class Cut:
    fraction: float
    steps: dict[str, int]  # side -> step of its run
    cells: dict[tuple[str, str], list[bool]] = field(default_factory=dict)  # (room, agent) -> passes
    native: dict[str, list[bool]] = field(default_factory=dict)  # side -> passes of its own native resume

    def count(self, room: str, agent: str) -> tuple[int, int]:
        r = self.cells[(room, agent)]
        return sum(r), len(r)

    def state(self) -> tuple[float, float, float]:
        return mean_effect([newcombe(*self.count("a", m), *self.count("b", m)) for m in "ab"])

    def model(self) -> tuple[float, float, float]:
        return mean_effect([newcombe(*self.count(r, "a"), *self.count(r, "b")) for r in "ab"])

    def foreignness(self, side: str) -> tuple[float, float, float] | None:
        if side not in self.native:
            return None
        native = self.native[side]
        return newcombe(sum(native), len(native), *self.count(side, side))


def swap(a: Side, b: Side, project: Path, prompt: str, check: str, out: Path, *, cuts: list[float],
         tails: int = 3, jobs: int = 3, workspace_only: bool = False, env: dict[str, str] | None = None,
         journal: Journal | None = None) -> str:
    sides = {"a": a, "b": b}
    journal = journal or Journal(None)
    journal("start", kind="swap", task=prompt, check=check, project=str(project), tails=tails, cuts=cuts,
            sides={s.key: {"agent": s.agent.name, "args": s.args, "dir": s.out.name} for s in (a, b)})
    journal("phase", phase="recording")
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda s: caps.record(s.agent, s.real, project, s.out, prompt, s.args, env), (a, b)))
    for side in (a, b):
        passed, detail = caps.run_check(check, side.out / "original" / "work")
        side.steps = caps.capsules(side.out, side.agent)
        side.events = side.agent.trail(caps.session_lines(side.out)).events
        side.original = f"{'passed' if passed else 'failed'} ({detail}) after {len(side.steps) - 1} steps"
        journal("original", side=side.key, passed=passed, detail=detail, steps=[s.tool for s in side.steps])

    plan = [Cut(f, {k: round(f * (len(s.steps) - 1)) for k, s in sides.items()}) for f in cuts]
    journal("plan", cuts=[{"fraction": c.fraction, "steps": c.steps} for c in plan])
    journal("phase", phase="tails")
    jobs_list = []
    for i, cut in enumerate(plan):
        for room in "ab":
            capsule = sides[room].steps[cut.steps[room]]
            for agent in "ab":
                cut.cells[(room, agent)] = []
                for n in range(tails):
                    jobs_list.append(("cell", i, room, agent, n, capsule))
            if sides[room].agent.native_resume:
                cut.native[room] = []
                for n in range(tails):
                    jobs_list.append(("native", i, room, room, n, capsule))

    def run(job):
        kind, i, room, agent, n, capsule = job
        name = f"cut{i}/{kind}-room-{room}-agent-{agent}-{n}"
        tail_dir = out / "swap" / name
        journal("tail", id=name, status="running", cut=i, room=room, agent=agent, kind=kind,
                agent_name=sides[agent].agent.name, dir=f"swap/{name}")
        if kind == "native":
            s = sides[room]
            tail = caps.run_tail(s.agent, s.real, s.out, capsule, prompt, s.args, check, n, env, tail_dir=tail_dir)
        else:
            s = sides[agent]
            tail = caps.run_handoff(s.agent, s.real, tail_dir, capsule, sides[room].events, prompt, s.args, check,
                                    env, workspace_only)
        journal("tail", id=name, status="passed" if tail.passed else "failed", detail=tail.detail)
        return job, tail.passed

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for (kind, i, room, agent, _, _), passed in pool.map(run, jobs_list):
            (plan[i].native[room] if kind == "native" else plan[i].cells[(room, agent)]).append(passed)

    text = "\n".join(report(sides, plan, prompt, check, project, len(jobs_list), workspace_only)) + "\n"
    (out / "report.txt").write_text(text)
    journal("report", text=text)
    journal("phase", phase="done")
    return text


def _leader(state: tuple[float, float, float], model: tuple[float, float, float]) -> str:
    """Which explains more of the gap at a cut: the room, the model, both alike, or neither (both near zero)."""
    if abs(state[0]) < 0.1 and abs(model[0]) < 0.1:
        return "neither"
    if abs(abs(state[0]) - abs(model[0])) < 0.1:
        return "tie"
    return "room" if abs(state[0]) > abs(model[0]) else "model"


def _sign(effect: tuple[float, float, float]) -> str:
    e, lo, hi = effect
    return f"{e:+.2f} [{lo:+.2f}, {hi:+.2f}]"


def report(sides: dict[str, Side], plan: list[Cut], prompt: str, check: str, project: Path, spent: int,
           workspace_only: bool) -> list[str]:
    def who(s: Side) -> str:
        return f"{s.agent.name}{' ' + ' '.join(s.args) if s.args else ''}"

    lines = [f"tare swap · a: {who(sides['a'])} · b: {who(sides['b'])} · {project}",
             f"  task      {prompt}", f"  check     {check}",
             f"  run a     {sides['a'].original}", f"  run b     {sides['b'].original}",
             f"  handoff   {'workspace only' if workspace_only else 'workspace and the rendered trail'}"]
    dominant, deciding = [], []
    for cut in plan:
        lines += ["", f"  cut {cut.fraction:.2f}: room a at step {cut.steps['a']}, room b at step {cut.steps['b']}",
                  "                agent a          agent b"]
        for room in "ab":
            row = []
            for agent in "ab":
                x, n = cut.count(room, agent)
                lo, hi = wilson(x, n)
                row.append(f"{x}/{n} {lo:.2f}-{hi:.2f}")
            lines.append(f"    room {room}      {row[0]:<17}{row[1]}")
        state, model = cut.state(), cut.model()
        lines.append(f"    state effect  {_sign(state)}  (room a better than room b)")
        lines.append(f"    model effect  {_sign(model)}  (agent a better than agent b)")
        for side in "ab":
            cost = cut.foreignness(side)
            if cost:
                native = cut.native[side]
                lines.append(f"    foreignness {side} {_sign(cost)}  (native resume {sum(native)}/{len(native)} "
                             "against the handoff on its own room)")
        dominant.append(_leader(state, model))
        deciding.append(state if dominant[-1] in ("room", "tie") else model)
    lines.append("")
    first = plan[0]
    if first.fraction == 0:
        _, lo, hi = first.state()
        lines.append("  null check   " + ("passed: no state effect at cut 0, where both rooms are the untouched project"
                                          if lo <= 0 <= hi else
                                          f"FAILED: a state effect at cut 0 ({_sign(first.state())}), where both rooms "
                                          "are the same; the effects above are not to be trusted"))
    shown = [i for i, d in enumerate(dominant) if d != "neither"]
    late = next((i for i, d in enumerate(dominant) if d in ("room", "tie") and "model" in dominant[:i]), None)
    if late is not None and dominant[late] == "tie" and "room" not in dominant:
        verdict = (f"the model explains more than the room until cut {plan[late - 1].fraction:.2f}; from cut "
                   f"{plan[late].fraction:.2f} on, room and model weigh alike")
    elif "room" in dominant and "model" in dominant[:dominant.index("room")]:
        at = dominant.index("room")
        before = max(i for i in range(at) if dominant[i] == "model")
        verdict = (f"blame passes from the model to the room between cut {plan[before].fraction:.2f} "
                   f"and cut {plan[at].fraction:.2f}")
    elif not shown:
        verdict = "neither the room nor the model makes a difference at any cut"
    elif {dominant[i] for i in shown} == {"model"}:
        verdict = "the model explains more than the room " + ("at every cut" if len(shown) == len(plan)
                                                               else "wherever there is an effect")
    elif {dominant[i] for i in shown} == {"room"}:
        verdict = "the room explains more than the model " + ("at every cut" if len(shown) == len(plan)
                                                               else "wherever there is an effect")
    else:
        verdict = "no clear transfer: " + ", ".join(f"{c.fraction:.2f} {d}" for c, d in zip(plan, dominant))
    if any(deciding[i][1] <= 0 <= deciding[i][2] for i in shown):
        verdict += "; some deciding intervals still include zero, more tails would firm this up"
    lines.append(f"  verdict      {verdict}")
    lines.append(f"  tails        {spent}")
    return lines

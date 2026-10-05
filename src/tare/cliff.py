"""Cliff: where did a failed run become lost (epic Cliff).

The original run fails its check. Tails resumed from each capsule show how often the run
could still have passed from that point. The baseline is a fresh start (step 0). A step
is high when its tails pass at least half as often as the baseline, low otherwise.
Bisection narrows the gap between the last high and the first low step; then more tails
go to that pair until their Wilson intervals separate or the budget runs out. The result
is a range, not a single step, unless the evidence says more.
"""
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from . import capsule as caps
from . import usage as usages
from .journal import Journal

Z = 1.96  # 95 % intervals


def wilson(passes: int, n: int) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = passes / n
    denominator = 1 + Z * Z / n
    centre = (p + Z * Z / (2 * n)) / denominator
    half = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


@dataclass
class Search:
    results: dict[int, list[bool]] = field(default_factory=dict)
    verdict: str = ""
    cliff: tuple[int, int] | None = None  # (last high step, first low step)
    separated: bool = False
    exhausted: bool = False
    rebounds: list[int] = field(default_factory=list)  # high steps after the first low one
    spent: int = 0

    def rate(self, step: int) -> float:
        return sum(self.results[step]) / len(self.results[step])

    def interval(self, step: int) -> tuple[float, float]:
        return wilson(sum(self.results[step]), len(self.results[step]))


def search(probe, last: int, tails: int, budget: int, gap_below: float = 0.2) -> Search:
    """probe(step, n) runs n tails from a capsule and returns whether each passed."""
    s = Search()

    def run(step: int, n: int) -> bool:
        n = min(n, budget - s.spent)
        if n <= 0:
            s.exhausted = True
            return False
        s.results.setdefault(step, []).extend(probe(step, n))
        s.spent += n
        return True

    run(0, tails)
    # 0/3 still allows a rate of 0.56: sample the baseline until a gap is clear, or it passes once
    while s.rate(0) == 0 and s.interval(0)[1] >= gap_below and run(0, tails):
        pass
    if s.rate(0) == 0:
        n, hi = len(s.results[0]), s.interval(0)[1]
        clear = hi < gap_below
        s.verdict = (f"A fresh start fails too: {n} of {n} failed, so the upper end of the baseline's 95% interval is {hi:.2f}. The task "
                     "is too hard for the model (a model gap), so there is no cliff to find." if clear else
                     f"No fresh start passed in {n} tails, so the upper end of the baseline's 95% interval is {hi:.2f}. The budget ran "
                     "out before a model gap was clear.")
        return s
    run(last, tails)
    unlucky = ("Continued from its last step, the run still passes at least half as often as a fresh start. "
               "The original run was unlucky, not lost.")

    while True:
        tau = s.rate(0) / 2
        probed = sorted(s.results)
        lows = [step for step in probed if step > 0 and s.rate(step) < tau]
        if not lows:
            s.cliff, s.verdict = None, unlucky
            return s
        low = min(lows)
        high = max(step for step in probed if step < low and s.rate(step) >= tau)
        s.cliff = (high, low)
        if low - high > 1:
            if not run((high + low) // 2, tails):
                break
            continue
        if s.interval(high)[0] > s.interval(low)[1]:
            s.separated = True
            break
        if not (run(high, tails) and run(low, tails)):
            break
    s.rebounds = [step for step in sorted(s.results) if step > s.cliff[1] and s.rate(step) >= s.rate(0) / 2]

    high, low = s.cliff
    if low - high > 1:
        s.verdict = f"Lost somewhere between step {high} and step {low}. The budget ran out before the range narrowed."
    elif s.separated:
        s.verdict = f"The run became lost at step {low}."
    else:
        s.verdict = (f"Most likely lost at step {low}. The intervals of steps {high} and {low} still overlap, and the "
                     "budget ran out.")
    return s


def cliff(agent, real, project: Path, prompt: str, check: str, out: Path, *, tails: int = 3, budget: int = 30,
          jobs: int = 3, claude_args: list[str] | None = None, env: dict[str, str] | None = None,
          journal: Journal | None = None, gap_below: float = 0.2) -> str:
    """The whole move: original run, capsules, baseline, search, report. Returns the report."""
    claude_args = claude_args or []
    journal = journal or Journal(None)
    journal("start", kind="cliff", task=prompt, check=check, project=str(project), tails=tails, budget=budget,
            sides={"a": {"agent": agent.name, "args": claude_args, "dir": ".", "billing": usages.billing(agent, real)}})
    journal("phase", phase="original run")
    caps.record(agent, real, project, out, prompt, claude_args, env)
    passed, detail, spent = caps.check_original(agent, out, check)
    header = [f"tare cliff · {agent.name} · {project}", f"  task      {prompt}", f"  check     {check}"]
    steps = caps.capsules(out, agent)
    journal("original", side="a", passed=passed, detail=detail, steps=[s.tool for s in steps], **spent)
    if passed:
        return _write(out, header + [f"  original  passed ({detail}): there is no cliff to find"], journal)
    header.append(f"  original  failed ({detail}) after {len(steps) - 1} steps")
    if len(steps) == 1:
        return _write(out, header + ["  The run made no tool calls, so there is no step to continue from."], journal)
    journal("phase", phase="tails")

    counts: dict[int, int] = {}
    events = agent.trail(caps.session_lines(out)).events

    def tail(step: int, i: int) -> caps.Tail:
        native = step == 0 or agent.native_resume
        name = f"{step:04d}-{i}"
        journal("tail", id=name, status="running", step=step, room="a", agent="a", agent_name=agent.name,
                kind="native" if native else "handoff", dir=f"tails/{name}")
        if native:
            result = caps.run_tail(agent, real, out, steps[step], prompt, claude_args, check, i, env)
        else:
            result = caps.run_handoff(agent, real, out / "tails" / name, steps[step], events, prompt,
                                      claude_args, check, env)
        journal("tail", id=name, status="passed" if result.passed else "failed", detail=result.detail,
                usage=result.usage, check_usage=result.check_usage)
        return result

    def probe(step: int, n: int) -> list[bool]:
        start = counts.get(step, 0)
        counts[step] = start + n
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            return [t.passed for t in pool.map(lambda i: tail(step, i), range(start, start + n))]

    s = search(probe, len(steps) - 1, tails, budget, gap_below)
    return _write(out, header + report(s, steps, budget), journal)


def report(s: Search, steps: list, budget: int) -> list[str]:
    lines = ["", "  step  what the step did                                      tails  pass  rate  95% interval"]
    for step in sorted(s.results):
        lo, hi = s.interval(step)
        marker = " <" if s.cliff and step == s.cliff[1] else ""
        lines.append(f"  {step:>4}  {steps[step].tool[:52]:<52}  {len(s.results[step]):>5}  {sum(s.results[step]):>4}"
                     f"  {s.rate(step):.2f}  {lo:.2f}-{hi:.2f}{marker}")
    lines += ["", f"  verdict   {s.verdict}"]
    if s.cliff and s.cliff[1] - s.cliff[0] == 1:
        step = steps[s.cliff[1]]
        changed = caps.changed_files(steps[s.cliff[0]].archive, step.archive)
        lines.append(f"  at step {step.step}: {step.tool}")
        lines.append(f"  changed   {', '.join(changed[:10]) or 'no files (the conversation changed, not the workspace)'}")
    if s.cliff:
        lines.append("  monotone  " + ("yes: no step after the cliff passes again" if not s.rebounds else
                                       f"no: steps {', '.join(map(str, s.rebounds))} pass again after the cliff"))
    lines.append(f"  tails     {s.spent} of a budget of {budget}")
    return lines


def _write(out: Path, lines: list[str], journal: Journal) -> str:
    text = "\n".join(lines + usages.report(out)) + "\n"
    (out / "report.txt").write_text(text)
    journal("report", text=text)
    journal("phase", phase="done")
    return text

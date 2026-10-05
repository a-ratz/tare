"""Calibrate: an agent's pass rate on a task, before Cliff or Swap spend tails on it (epic Calibrate).

Each side (an agent with its arguments, e.g. `claude --model haiku`) gets N fresh starts of
the task in rooms, scored by the check. The report gives each rate with its interval, so a
task can be chosen where one side mostly fails and the other mostly passes.
"""
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from . import capsule as caps
from .cliff import wilson
from .journal import Journal


@dataclass
class Side:
    key: str
    agent: object
    real: object
    args: list[str]
    results: list[bool] = field(default_factory=list)
    scores: list[int] = field(default_factory=list)  # judge scores, where the check is a judge

    def label(self) -> str:
        return " ".join([self.agent.name, *self.args])


def calibrate(sides: list[Side], project: Path, prompt: str, check: str, out: Path, *, runs: int = 10, jobs: int = 3,
              env: dict[str, str] | None = None, journal: Journal | None = None, keep: bool = False) -> str:
    journal = journal or Journal(None)
    journal("start", kind="calibrate", task=prompt, check=check, project=str(project), tails=runs,
            sides={s.key: {"agent": s.agent.name, "args": s.args, "dir": "."} for s in sides})
    work = out / "project"
    shutil.copytree(project, work, symlinks=True)
    caps.archive(work, out / "start.tar")
    shutil.rmtree(work)
    start = caps.Capsule(0, None, out / "start.tar", 0, 0, "start")
    journal("phase", phase="tails")

    def run(job: tuple[Side, int]) -> tuple[Side, caps.Tail]:
        side, i = job
        name = f"{side.key}-{i}"
        journal("tail", id=name, status="running", side=side.key, agent=side.key, agent_name=side.agent.name,
                kind="fresh", dir=f"calibrate/{name}")
        tail = caps.run_tail(side.agent, side.real, out, start, prompt, side.args, check, i, env,
                             tail_dir=out / "calibrate" / name, keep=keep)
        journal("tail", id=name, status="passed" if tail.passed else "failed", detail=tail.detail)
        return side, tail

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for side, tail in pool.map(run, [(s, i) for i in range(runs) for s in sides]):
            side.results.append(tail.passed)
            if score := re.search(r"score (\d+)", tail.detail):
                side.scores.append(int(score.group(1)))

    width = max(len(s.label()) for s in sides) + 2
    lines = [f"tare calibrate · {project}", f"  task      {prompt}", f"  check     {check}", "",
             f"  side  {'agent':<{width}}pass  rate  95% interval"]
    for s in sides:
        x, n = sum(s.results), len(s.results)
        lo, hi = wilson(x, n)
        lines.append(f"  {s.key:<4}  {s.label():<{width}}{x:>2}/{n:<2} {x / n:.2f}  {lo:.2f}-{hi:.2f}"
                     + (f"   scores {' '.join(map(str, sorted(s.scores)))}" if s.scores else ""))
    text = "\n".join(lines) + "\n"
    (out / "report.txt").write_text(text)
    journal("report", text=text)
    journal("phase", phase="done")
    return text

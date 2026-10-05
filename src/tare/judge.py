"""Judge: a check for work that tests cannot settle, such as the quality of a page (epic Judge).

The finished page is rendered headless in a room of its own (no home directory, the
workspace read-only) and photographed. A judge agent then gets the screenshot, the source
and the rubric in a fresh tare room, without any agent or model names, and answers with a
score. The check passes at or above a threshold. Before a threshold is used, `noise` scores
the same pages repeatedly: a threshold inside a page's spread would measure the judge's
dice, not the agent.
"""
import json
import re
import shutil
import statistics
import subprocess
import tempfile
from pathlib import Path

from . import room as rooms
from .agents import AGENTS, events, strings

VIEWPORT = "1280,900"
PROMPT = ("You are a strict, careful judge. Read rubric.md. Look at page.png, a screenshot of the page, and at the "
          "source in the source/ directory. Score the page from 0 to 100 exactly as the rubric says. Reply with "
          'nothing but one line of JSON: {"score": <0-100>, "reason": "<one sentence>"}')


def render(work: Path, page: str, target: Path, wait_ms: int = 2000):
    """Screenshot of work/page, rendered headless in a room: the workspace read-only, no home directory."""
    target.parent.mkdir(parents=True, exist_ok=True)
    shot = Path(tempfile.mkdtemp(prefix="tare-render-"))
    try:
        argv = ["bwrap", "--ro-bind", "/usr", "/usr", "--ro-bind", "/etc", "/etc", "--ro-bind", "/opt", "/opt",
                "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
                "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--tmpfs", "/home",
                "--ro-bind", str(work), "/work", "--bind", str(shot), "/shot",
                "--unshare-user", "--unshare-pid", "--unshare-ipc", "--unshare-uts", "--die-with-parent",
                "--clearenv", "--setenv", "HOME", "/tmp", "--setenv", "PATH", "/usr/bin:/bin", "--",
                "google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                f"--window-size={VIEWPORT}", f"--virtual-time-budget={wait_ms}", "--screenshot=/shot/page.png",
                f"file:///work/{page}"]
        subprocess.run(argv, capture_output=True, timeout=120, stdin=subprocess.DEVNULL)
        if not (shot / "page.png").exists():
            raise RuntimeError(f"the page {page} did not render")
        shutil.copyfile(shot / "page.png", target)
    finally:
        shutil.rmtree(shot, ignore_errors=True)


def _score(stdout: str) -> tuple[int, str]:
    """The last {"score": ...} the judge wrote, in any of its event stream's strings or in plain text."""
    texts = [s for e in events(stdout) for s in strings(e)] or [stdout]
    for text in reversed(texts):
        for match in reversed(list(re.finditer(r'\{[^{}]*"score"\s*:\s*\d+[^{}]*\}', text))):
            try:
                data = json.loads(match.group(0))
                return int(data["score"]), str(data.get("reason", ""))
            except (ValueError, KeyError):
                continue
    raise RuntimeError("the judge gave no score")


def judge(work: Path, rubric: Path, page: str = "index.html", agent_name: str = "claude",
          agent_args: list[str] | None = None, timeout: float = 600) -> tuple[int, str]:
    """Score the page in work/ by the rubric; the judge agent runs in a fresh, blind room."""
    agent = AGENTS[agent_name]
    real = agent.discover()
    with tempfile.TemporaryDirectory(prefix="tare-judge-") as tmp:
        bench = Path(tmp)
        render(work, page, bench / "page.png")
        shutil.copyfile(rubric, bench / "rubric.md")
        # the source the agent wrote, without anything that names an agent or its setup
        shutil.copytree(work, bench / "source", ignore=shutil.ignore_patterns(
            ".git", ".claude", ".codex", ".pi", "AGENTS.md", "CLAUDE.md", "node_modules"))
        with rooms.room_home(agent, real) as home:
            argv = rooms.bwrap(agent, real, home, bench, [agent.name, *agent.room_flags,
                                                         *agent.run_args(PROMPT, agent_args or [])])
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    return _score(proc.stdout)


def noise(pages: list[Path], rubric: Path, times: int, threshold: float | None, page: str = "index.html",
          agent_name: str = "claude", agent_args: list[str] | None = None) -> tuple[str, bool]:
    """Score each page `times` times. Returns the report and whether the threshold sits outside every spread."""
    lines = [f"tare judge-noise · {agent_name} {' '.join(agent_args or [])}".rstrip(), f"  rubric    {rubric}",
             "", "  page                              scores                         mean   sd   min-max"]
    clear = True
    for p in pages:
        scores = [judge(p, rubric, page, agent_name, agent_args)[0] for _ in range(times)]
        mean, sd = statistics.mean(scores), statistics.pstdev(scores)
        inside = threshold is not None and min(scores) <= threshold <= max(scores)
        clear = clear and not inside
        lines.append(f"  {str(p)[-32:]:<32}  {' '.join(f'{x:>3}' for x in scores):<30} {mean:5.1f} {sd:4.1f}  "
                     f"{min(scores)}-{max(scores)}" + ("  <- threshold inside this page's range" if inside else ""))
    if threshold is not None:
        lines += ["", f"  threshold {threshold}: " + ("outside every page's range of scores" if clear else
                                                     "INSIDE a page's range of scores. There, chance decides pass or "
                                                     "fail.")]
    return "\n".join(lines) + "\n", clear

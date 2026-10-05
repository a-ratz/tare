"""Dirty-twin test for Pi (see PLAN.md).

usage:
  uv run experiments/dirty-twin-pi/run.py run r0|t0|t1|t1b   # one condition
  uv run experiments/dirty-twin-pi/run.py check              # score every run against the markers

The fake is reached through a provider of its own ("tare", api anthropic-messages): Pi
has no environment variable for a base URL. T0 runs on a copy of the user's agent
directory with that provider added; the real directory is never written.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from tare.agents import Pi, strings
from tare.fake import Fake
from tare.probe import REACH_SCRIPT, SECRET_PATHS
from tare.room import bwrap, room_home

HERE = Path(__file__).resolve().parent
WORK = HERE / "runs" / "work"
PI = Pi()
FLAGS = ["--no-extensions", "--no-skills", "--no-context-files"]  # CONCEPT.md, adapters table


def fake_provider(models: Path, url: str):
    data = json.loads(models.read_text()) if models.exists() else {"providers": {}}
    data.setdefault("providers", {})["tare"] = {"api": "anthropic-messages", "apiKey": "tare", "baseUrl": url,
                                                "models": [{"id": "fake", "name": "fake"}]}
    models.write_text(json.dumps(data))


def save(out: Path, proc, bodies):
    (out / "stdout.jsonl").write_text(proc.stdout)
    (out / "stderr.log").write_text(proc.stderr)
    (out / "exit").write_text(str(proc.returncode))
    (out / "bodies.json").write_text(json.dumps(bodies, ensure_ascii=False))
    print(f"exit {proc.returncode}, {len(bodies)} bodies")


def run(condition: str):
    out = HERE / "runs" / condition
    out.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "AGENTS.md").write_text("Project rule: every answer ends with the word tare.\n")
    real = PI.discover()
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    base = ["-p", "--mode", "json", "--no-session"]
    if condition == "r0":
        proc = subprocess.run([str(real.binary), *base, "say ok"], cwd=WORK, env=env, capture_output=True,
                              text=True, timeout=600, stdin=subprocess.DEVNULL)
        return save(out, proc, [])
    with Fake() as fake:
        args = [*base, "--provider", "tare", "--model", "fake", "say ok"]
        if condition == "t0":
            with tempfile.TemporaryDirectory(prefix="tare-pi-twin-") as copy:
                agent_dir = Path(copy) / "agent"
                shutil.copytree(real.config, agent_dir, symlinks=True, ignore=shutil.ignore_patterns("sessions"))
                fake_provider(agent_dir / "models.json", fake.url)
                proc = subprocess.run([str(real.binary), *args], cwd=WORK, env=env | {"PI_CODING_AGENT_DIR": str(agent_dir)},
                                      capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL)
        else:
            flags = FLAGS if condition == "t1" else []
            with room_home(PI, real) as home:
                fake_provider(home / ".pi" / "agent" / "models.json", fake.url)
                proc = subprocess.run(bwrap(PI, real, home, WORK, ["pi", *flags, *args]), env=env,
                                      capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL)
                targets = [str(real.home), str(real.config), *(str(real.home / p) for p in SECRET_PATHS)]
                reach = subprocess.run(bwrap(PI, real, home, WORK, ["/bin/sh", "-c", REACH_SCRIPT, "reach", *targets]),
                                       capture_output=True, text=True, timeout=60)
                (out / "reach.txt").write_text(reach.stdout)
        save(out, proc, fake.requests)


def text_of(condition: str) -> tuple[str, set[str]]:
    out = HERE / "runs" / condition
    if condition == "r0":
        events = [json.loads(line) for line in (out / "stdout.jsonl").read_text().splitlines() if line.startswith("{")]
        return "\n".join(strings(events)), set()
    bodies = [b for b in json.loads((out / "bodies.json").read_text()) if b.get("tools")]
    if not bodies:
        return "", set()
    main = bodies[0]
    return "\n".join(strings({k: main.get(k) for k in ("system", "messages", "tools")})), {t["name"] for t in main["tools"]}


def check():
    markers = json.loads((HERE / "markers.local.json").read_text())
    conditions = [c for c in ("r0", "t0", "t1", "t1b") if (HERE / "runs" / c / "exit").exists()]
    tools = {}
    for c in conditions:
        text, tools[c] = text_of(c)
        print(f"== {c} (exit {(HERE / 'runs' / c / 'exit').read_text()}): {len(text)} chars, {len(tools[c])} tools")
        found = {k: (v in text or (k == "Q2" and any(v in name for name in tools[c]))) for k, v in markers.items()}
        print("   markers:", "  ".join(f"{k}={'YES' if v else 'no'}" for k, v in found.items()))
        reach = HERE / "runs" / c / "reach.txt"
        if reach.exists():
            print("   reach:", " ".join(reach.read_text().split()))
    if "t0" in tools and "t1b" in tools:
        print("tools in t0 but not t1b:", sorted(tools["t0"] - tools["t1b"]))


if __name__ == "__main__":
    run(sys.argv[2]) if sys.argv[1] == "run" else check()

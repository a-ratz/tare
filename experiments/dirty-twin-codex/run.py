"""Dirty-twin test for Codex (see PLAN.md).

usage:
  uv run experiments/dirty-twin-codex/run.py run r0|t0|t1|t1b   # one condition
  uv run experiments/dirty-twin-codex/run.py check              # score every run against the markers

Runs land in runs/<condition>/ (not committed): request bodies the fake received, the
CLI's stdout and stderr, its exit code.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from tare.agents import Codex, strings
from tare.fake import Fake
from tare.probe import REACH_SCRIPT, SECRET_PATHS
from tare.room import bwrap, room_home

HERE = Path(__file__).resolve().parent
WORK = HERE / "runs" / "work"
CODEX = Codex()


def save(out: Path, proc, bodies, other):
    (out / "stdout.jsonl").write_text(proc.stdout)
    (out / "stderr.log").write_text(proc.stderr)
    (out / "exit").write_text(str(proc.returncode))
    (out / "bodies.json").write_text(json.dumps(bodies, ensure_ascii=False))
    (out / "other_paths.json").write_text(json.dumps(other))
    print(f"exit {proc.returncode}, {len(bodies)} bodies, other paths {sorted(set(other))}")


def run(condition: str):
    out = HERE / "runs" / condition
    out.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    real = CODEX.discover()
    # start like a plain terminal: drop what a parent Claude Code session exports
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    if condition == "r0":
        proc = subprocess.run([str(real.binary), "debug", "prompt-input", "say ok"], cwd=WORK, env=env,
                              capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
        return save(out, proc, [], [])
    with Fake() as fake:
        args, extra = CODEX.probe(fake.url)
        if condition == "t0":
            proc = subprocess.run([str(real.binary), *args], cwd=WORK, env=env | extra,
                                  capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
        else:
            flags = CODEX.room_flags if condition == "t1" else []
            with room_home(CODEX, real) as home:
                proc = subprocess.run(bwrap(CODEX, real, home, WORK, ["codex", *flags, *args], extra), env=env,
                                      capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
                targets = [str(real.home), str(real.config), *(str(real.home / p) for p in SECRET_PATHS)]
                reach = subprocess.run(bwrap(CODEX, real, home, WORK, ["/bin/sh", "-c", REACH_SCRIPT, "reach", *targets]),
                                       capture_output=True, text=True, timeout=60)
                (out / "reach.txt").write_text(reach.stdout)
        save(out, proc, fake.requests, fake.other_paths)


def text_of(condition: str) -> tuple[str, set[str], str]:
    out = HERE / "runs" / condition
    if condition == "r0":
        rendered = (out / "stdout.jsonl").read_text()
        return "\n".join(strings(json.loads(rendered))), set(), ""
    bodies = json.loads((out / "bodies.json").read_text())
    capture = CODEX.capture("", bodies)
    return (capture.text, capture.tools, bodies[0].get("model", "?")) if capture else ("", set(), "?")


def check():
    markers = json.loads((HERE / "markers.local.json").read_text())
    conditions = [c for c in ("r0", "t0", "t1", "t1b") if (HERE / "runs" / c / "exit").exists()]
    texts = {c: text_of(c) for c in conditions}
    for c in conditions:
        text, tools, model = texts[c]
        rc = (HERE / "runs" / c / "exit").read_text()
        print(f"== {c} (exit {rc}): {len(text)} chars, {len(tools)} tools, model={model}")
        print("   markers:", "  ".join(f"{k}={'YES' if v in text else 'no'}" for k, v in markers.items()))
        reach = HERE / "runs" / c / "reach.txt"
        if reach.exists():
            for line in reach.read_text().splitlines():
                print("   " + line)
    if "t1" in texts and "t1b" in texts:
        listing = lambda t: {l for l in t.splitlines() if l.startswith("- ")}
        extra = sorted(listing(texts["t1b"][0]) - listing(texts["t1"][0]))
        print(f"\nlisting lines in t1b but not t1 (what --disable remote_plugin removes): {len(extra)}")
        for line in extra[:20]:
            print("   " + line[:100])


if __name__ == "__main__":
    if sys.argv[1] == "run":
        run(sys.argv[2])
    else:
        check()

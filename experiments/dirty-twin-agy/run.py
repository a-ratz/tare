"""Dirty-twin test for the Antigravity CLI (see PLAN.md).

usage:
  uv run experiments/dirty-twin-agy/run.py markers         # write markers.local.json, print digests only
  uv run experiments/dirty-twin-agy/run.py run t0|t1|t2    # one condition
  uv run experiments/dirty-twin-agy/run.py check           # score every run against the markers

The fake is reached through CLOUD_CODE_URL. The twins (T0, T2) see the real setup through an
overlay over ~/.gemini whose writes die with the run; T2 plants markers into that overlay
only. The work directory sits directly under the home directory, outside any repository,
and is removed after each run.
"""
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from tare.agents import Antigravity
from tare.fake import Fake
from tare.probe import REACH_SCRIPT, SECRET_PATHS, instruction_lines
from tare.room import bwrap, room_home

HERE = Path(__file__).resolve().parent
AGY = Antigravity()
GEMINI = Path.home() / ".gemini"
PROJECT_RULE = "Project rule: every answer ends with the word tare."
PLANTED = {
    "Q6": ("tare marker Q6: a global rule in the Gemini CLI place", GEMINI / "GEMINI.md"),
    "Q7": ("tare marker Q7: a global rule in the Antigravity config", GEMINI / "config" / "rules" / "tare-q7.md"),
}
SKILL = GEMINI / "config" / "skills" / "tare-q8-skill" / "SKILL.md"
SKILL_TEXT = "---\nname: tare-q8-skill\ndescription: tare marker Q8, a global skill\n---\nNothing to do.\n"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def _payload(token: str) -> dict:
    part = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


def markers():
    real = AGY.discover()
    payload = _payload(json.loads((real.config / AGY.credentials).read_text())["id_token"])
    found = {
        "Q1": instruction_lines(Path.home() / "AGENTS.md")[0],
        # the most distinctive (longest) skill name of each place
        "Q2": max((p.name for p in (Path.home() / ".agents" / "skills").iterdir()), key=len),
        "Q3": max((p.name for p in (GEMINI / "skills").iterdir()), key=len),
        "Q4": f"{Path.home()}/",
        "Q5": PROJECT_RULE,
        "Q6": PLANTED["Q6"][0], "Q7": PLANTED["Q7"][0], "Q8": "tare-q8-skill",
        "Q9": payload["email"], "Q10": payload["name"],
    }
    (HERE / "markers.local.json").write_text(json.dumps(found))
    for key, value in found.items():
        print(key, digest(value))


def manifest() -> str:
    """Paths, sizes and mtimes under ~/.gemini: unchanged if the twin wrote nothing there."""
    h = hashlib.sha256()
    for path in sorted(GEMINI.rglob("*")):
        st = path.lstat()
        h.update(f"{path.relative_to(GEMINI)}\0{st.st_size}\0{st.st_mtime_ns}\n".encode())
    return h.hexdigest()


def plant() -> str:
    lines = [f"mkdir -p '{PLANTED['Q7'][1].parent}' '{SKILL.parent}'"]
    lines += [f"printf '%s\\n' '{text}' >> '{path}'" for text, path in PLANTED.values()]
    lines.append(f"printf '%s' '{SKILL_TEXT}' > '{SKILL}'")
    return " && ".join(lines)


def save(out: Path, proc, bodies):
    (out / "stdout.jsonl").write_text(proc.stdout)
    (out / "stderr.log").write_text(proc.stderr)
    (out / "exit").write_text(str(proc.returncode))
    (out / "bodies.json").write_text(json.dumps(bodies, ensure_ascii=False))
    print(f"exit {proc.returncode}, {len(bodies)} model requests")


def run(condition: str):
    out = HERE / "runs" / condition
    out.mkdir(parents=True, exist_ok=True)
    real = AGY.discover()
    work = Path(tempfile.mkdtemp(prefix=".tare-agy-twin-work-", dir=Path.home()))
    try:
        (work / "AGENTS.md").write_text(PROJECT_RULE + "\n")
        with Fake() as fake:
            args, env = AGY.probe(fake.url)
            if condition in ("t0", "t2"):
                before = manifest()
                with AGY.twin(real, fake.url) as extra:
                    twin_env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")} | env | extra
                    argv = AGY.twin_argv([str(real.binary), *args], twin_env, plant() if condition == "t2" else "")
                    proc = subprocess.run(argv, cwd=work, env=twin_env, capture_output=True, text=True, timeout=300,
                                          stdin=subprocess.DEVNULL)
                after = manifest()
                (out / "manifest.txt").write_text(f"before {before}\nafter  {after}\n")
                print("~/.gemini", "unchanged" if before == after else "CHANGED")
            else:
                with room_home(AGY, real) as home:
                    proc = subprocess.run(bwrap(AGY, real, home, work, ["agy", *args], env), capture_output=True,
                                          text=True, timeout=300, stdin=subprocess.DEVNULL)
                    targets = [str(real.home), str(real.config), *(str(real.home / p) for p in SECRET_PATHS)]
                    reach = subprocess.run(bwrap(AGY, real, home, work, ["/bin/sh", "-c", REACH_SCRIPT, "reach", *targets]),
                                           capture_output=True, text=True, timeout=60)
                    (out / "reach.txt").write_text(reach.stdout)
            save(out, proc, fake.requests)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def check():
    found_markers = json.loads((HERE / "markers.local.json").read_text())
    for c in ("t0", "t1", "t2"):
        out = HERE / "runs" / c
        if not (out / "exit").exists():
            continue
        capture = AGY.capture((out / "stdout.jsonl").read_text(), json.loads((out / "bodies.json").read_text()))
        text = capture.text if capture else ""
        print(f"== {c} (exit {(out / 'exit').read_text()}): {len(text)} chars, {len(capture.tools) if capture else 0} tools")
        print("   markers:", "  ".join(f"{k}={'YES' if v in text else 'no'}" for k, v in found_markers.items()))
        for name in ("manifest.txt", "reach.txt"):
            if (out / name).exists():
                print(f"   {name[:-4]}:", " ".join((out / name).read_text().split()))


if __name__ == "__main__":
    {"markers": markers, "check": check}.get(sys.argv[1], lambda: run(sys.argv[2]))()
